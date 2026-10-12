from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient

from tests.conftest import DbProbe


def payload(**overrides: Any) -> dict[str, Any]:
    return {"tariff_id": 2, "email": "student@example.com", "method": "card", **overrides}


async def create(client: AsyncClient, **overrides: Any) -> dict[str, Any]:
    response = await client.post("/payments", json=payload(**overrides))
    assert response.status_code == 201, response.text
    return response.json()


# --- POST /payments ---


async def test_create_card_payment(client: AsyncClient, db: DbProbe) -> None:
    response = await client.post("/payments", json=payload())

    assert response.status_code == 201
    body = response.json()
    assert UUID(body["id"]).version == 4
    assert body == {
        "id": body["id"],
        "status": "pending",
        "tariff_id": 2,
        "amount": 1990000,
        "discount": 0,
        "method": "card",
        "installment_months": None,
        "schedule": None,
        "email": "student@example.com",
        "created_at": body["created_at"],
    }
    created_at = datetime.fromisoformat(body["created_at"])
    assert created_at.utcoffset() == timedelta(0)

    stored = await db.get_payment(body["id"])
    assert (stored.amount, stored.status) == (1990000, "pending")


@pytest.mark.parametrize("promo_code", ["KVITTO10", "kvitto10", "  Kvitto10 "])
async def test_create_with_promo(client: AsyncClient, promo_code: str) -> None:
    body = await create(client, promo_code=promo_code)

    assert (body["amount"], body["discount"]) == (1791000, 199000)


@pytest.mark.parametrize("promo_code", [None, "", "   "])
async def test_create_with_empty_promo_means_no_discount(
    client: AsyncClient, promo_code: str | None
) -> None:
    body = await create(client, promo_code=promo_code)

    assert (body["amount"], body["discount"]) == (1990000, 0)


async def test_create_with_unknown_promo(client: AsyncClient, db: DbProbe) -> None:
    response = await client.post("/payments", json=payload(promo_code="FREE100"))

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "promo_code"]
    assert await db.count_payments() == 0


@pytest.mark.parametrize("months", [3, 6, 12])
@pytest.mark.parametrize(("promo_code", "amount"), [(None, 1990000), ("KVITTO10", 1791000)])
async def test_installment_schedule_sums_to_amount(
    client: AsyncClient, months: int, promo_code: str | None, amount: int
) -> None:
    body = await create(
        client, method="installment", installment_months=months, promo_code=promo_code
    )

    assert body["amount"] == amount
    assert body["installment_months"] == months
    assert len(body["schedule"]) == months
    assert sum(body["schedule"]) == amount


async def test_installment_example_from_spec(client: AsyncClient) -> None:
    body = await create(client, method="installment", installment_months=3)

    assert body["schedule"] == [663334, 663333, 663333]


@pytest.mark.parametrize("months", [None, 1, 24])
async def test_installment_requires_valid_months(
    client: AsyncClient, db: DbProbe, months: int | None
) -> None:
    response = await client.post(
        "/payments", json=payload(method="installment", installment_months=months)
    )

    assert response.status_code == 422
    assert await db.count_payments() == 0


@pytest.mark.parametrize("method", ["card", "sbp"])
async def test_non_installment_rejects_months(
    client: AsyncClient, db: DbProbe, method: str
) -> None:
    response = await client.post("/payments", json=payload(method=method, installment_months=3))

    assert response.status_code == 422
    assert await db.count_payments() == 0


@pytest.mark.parametrize("method", ["card", "sbp"])
async def test_non_installment_accepts_null_months(client: AsyncClient, method: str) -> None:
    body = await create(client, method=method, installment_months=None)

    assert body["method"] == method
    assert body["installment_months"] is None
    assert body["schedule"] is None


@pytest.mark.parametrize(
    "overrides",
    [{"method": "cash"}, {"email": "not-an-email"}, {"tariff_id": "abc"}],
)
async def test_create_validation_errors(client: AsyncClient, overrides: dict[str, Any]) -> None:
    response = await client.post("/payments", json=payload(**overrides))

    assert response.status_code == 422


async def test_create_unknown_tariff(client: AsyncClient, db: DbProbe) -> None:
    response = await client.post("/payments", json=payload(tariff_id=99))

    assert response.status_code == 404
    assert response.json() == {"detail": "Tariff not found"}
    assert await db.count_payments() == 0


@pytest.mark.parametrize("tariff_id", [0, -1, 2**31, 2**63])
async def test_create_tariff_id_out_of_range(
    client: AsyncClient, db: DbProbe, tariff_id: int
) -> None:
    response = await client.post("/payments", json=payload(tariff_id=tariff_id))

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "tariff_id"]
    assert await db.count_payments() == 0


async def test_create_max_tariff_id_is_not_found(client: AsyncClient) -> None:
    response = await client.post("/payments", json=payload(tariff_id=2**31 - 1))

    assert response.status_code == 404
    assert response.json() == {"detail": "Tariff not found"}


# --- Idempotency-Key ---


async def test_idempotency_key_returns_same_payment(client: AsyncClient, db: DbProbe) -> None:
    headers = {"Idempotency-Key": "order-42"}

    first = await client.post("/payments", json=payload(), headers=headers)
    second = await client.post("/payments", json=payload(), headers=headers)

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json() == first.json()
    assert await db.count_payments() == 1


async def test_idempotency_key_ignores_different_body(client: AsyncClient, db: DbProbe) -> None:
    headers = {"Idempotency-Key": "order-43"}

    first = await client.post("/payments", json=payload(), headers=headers)
    second = await client.post("/payments", json=payload(tariff_id=3), headers=headers)

    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["tariff_id"] == 2
    assert await db.count_payments() == 1


async def test_different_idempotency_keys_create_two_payments(
    client: AsyncClient, db: DbProbe
) -> None:
    first = await client.post("/payments", json=payload(), headers={"Idempotency-Key": "a"})
    second = await client.post("/payments", json=payload(), headers={"Idempotency-Key": "b"})

    assert (first.status_code, second.status_code) == (201, 201)
    assert first.json()["id"] != second.json()["id"]
    assert await db.count_payments() == 2


async def test_blank_idempotency_key_is_ignored(client: AsyncClient, db: DbProbe) -> None:
    headers = {"Idempotency-Key": "   "}

    first = await client.post("/payments", json=payload(), headers=headers)
    second = await client.post("/payments", json=payload(tariff_id=3), headers=headers)

    assert (first.status_code, second.status_code) == (201, 201)
    assert second.json()["id"] != first.json()["id"]
    assert second.json()["tariff_id"] == 3
    assert await db.count_payments() == 2
    assert (await db.get_payment(first.json()["id"])).idempotency_key is None


async def test_idempotency_key_is_trimmed(client: AsyncClient, db: DbProbe) -> None:
    padded = {"Idempotency-Key": " order-44 "}
    first = await client.post("/payments", json=payload(), headers=padded)
    second = await client.post("/payments", json=payload(), headers={"Idempotency-Key": "order-44"})

    assert (first.status_code, second.status_code) == (201, 200)
    assert second.json()["id"] == first.json()["id"]
    assert (await db.get_payment(first.json()["id"])).idempotency_key == "order-44"
    assert await db.count_payments() == 1


async def test_idempotency_key_length_is_checked_after_trim(
    client: AsyncClient, db: DbProbe
) -> None:
    key = "k" * 255

    response = await client.post(
        "/payments", json=payload(), headers={"Idempotency-Key": f"  {key}     "}
    )

    assert response.status_code == 201
    assert (await db.get_payment(response.json()["id"])).idempotency_key == key


async def test_too_long_idempotency_key(client: AsyncClient, db: DbProbe) -> None:
    response = await client.post(
        "/payments", json=payload(), headers={"Idempotency-Key": "k" * 256}
    )

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["header", "idempotency-key"]
    assert await db.count_payments() == 0


async def test_long_blank_idempotency_key_is_ignored(client: AsyncClient, db: DbProbe) -> None:
    response = await client.post(
        "/payments", json=payload(), headers={"Idempotency-Key": " " * 300}
    )

    assert response.status_code == 201
    assert (await db.get_payment(response.json()["id"])).idempotency_key is None


async def test_without_idempotency_key_creates_two_payments(
    client: AsyncClient, db: DbProbe
) -> None:
    await create(client)
    await create(client)

    assert await db.count_payments() == 2


# --- GET /payments/{id} ---


async def test_get_payment(client: AsyncClient) -> None:
    created = await create(client, method="installment", installment_months=6)

    response = await client.get(f"/payments/{created['id']}")

    assert response.status_code == 200
    assert response.json() == created


async def test_get_missing_payment(client: AsyncClient) -> None:
    response = await client.get(f"/payments/{uuid4()}")

    assert response.status_code == 404
    assert response.json() == {"detail": "Payment not found"}


async def test_get_payment_with_invalid_id(client: AsyncClient) -> None:
    response = await client.get("/payments/123")

    assert response.status_code == 422


# --- GET /payments ---


@pytest.fixture
async def three_payments(client: AsyncClient, db: DbProbe) -> list[dict[str, Any]]:
    a = await create(client, email="a@example.com")
    b = await create(client, email="a@example.com")
    c = await create(client, email="c@example.com")
    await db.set_status(b["id"], "succeeded")
    return [a, b, c]


def ids(response_json: list[dict[str, Any]]) -> set[str]:
    return {p["id"] for p in response_json}


async def test_list_all(client: AsyncClient, three_payments: list[dict[str, Any]]) -> None:
    response = await client.get("/payments")

    assert response.status_code == 200
    assert ids(response.json()) == ids(three_payments)


async def test_list_newest_first(client: AsyncClient, three_payments: list[dict[str, Any]]) -> None:
    body = (await client.get("/payments")).json()

    created = [p["created_at"] for p in body]
    assert created == sorted(created, reverse=True)


async def test_filter_by_email(client: AsyncClient, three_payments: list[dict[str, Any]]) -> None:
    a, b, _ = three_payments

    response = await client.get("/payments", params={"email": "a@example.com"})

    assert ids(response.json()) == {a["id"], b["id"]}


async def test_filter_by_status(client: AsyncClient, three_payments: list[dict[str, Any]]) -> None:
    a, b, c = three_payments

    pending = await client.get("/payments", params={"status": "pending"})
    succeeded = await client.get("/payments", params={"status": "succeeded"})

    assert ids(pending.json()) == {a["id"], c["id"]}
    assert ids(succeeded.json()) == {b["id"]}
    assert succeeded.json()[0]["status"] == "succeeded"


async def test_filter_by_email_and_status(
    client: AsyncClient, three_payments: list[dict[str, Any]]
) -> None:
    a, _, _ = three_payments

    response = await client.get("/payments", params={"email": "a@example.com", "status": "pending"})

    assert ids(response.json()) == {a["id"]}


async def test_filter_no_matches(client: AsyncClient, three_payments: list[dict[str, Any]]) -> None:
    response = await client.get("/payments", params={"email": "c@example.com", "status": "failed"})

    assert response.status_code == 200
    assert response.json() == []


async def test_filter_unknown_status(client: AsyncClient) -> None:
    response = await client.get("/payments", params={"status": "paid"})

    assert response.status_code == 422


async def test_pagination(client: AsyncClient, three_payments: list[dict[str, Any]]) -> None:
    full = (await client.get("/payments")).json()

    page1 = (await client.get("/payments", params={"limit": 2, "offset": 0})).json()
    page2 = (await client.get("/payments", params={"limit": 2, "offset": 2})).json()

    assert page1 == full[:2]
    assert page2 == full[2:]


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 101}, {"offset": -1}])
async def test_pagination_bounds(client: AsyncClient, params: dict[str, int]) -> None:
    response = await client.get("/payments", params=params)

    assert response.status_code == 422
