import json
from typing import Any
from uuid import uuid4

import pytest
from httpx import AsyncClient, Response

from app.services.webhook_service import sign
from tests.conftest import WEBHOOK_SECRET, DbProbe


async def send(client: AsyncClient, body: bytes, signature: str | None = "auto") -> Response:
    headers = {"Content-Type": "application/json"}
    if signature == "auto":
        signature = sign(body, WEBHOOK_SECRET)
    if signature is not None:
        headers["X-Signature"] = signature
    return await client.post("/webhooks/bank", content=body, headers=headers)


def event(payment_id: Any, status: str) -> bytes:
    return json.dumps({"payment_id": str(payment_id), "status": status}).encode()


@pytest.fixture
async def payment_id(client: AsyncClient) -> str:
    response = await client.post(
        "/payments", json={"tariff_id": 1, "email": "a@example.com", "method": "card"}
    )
    return response.json()["id"]


async def test_valid_signature_changes_status(
    client: AsyncClient, db: DbProbe, payment_id: str
) -> None:
    response = await send(client, event(payment_id, "succeeded"))

    assert response.status_code == 200
    assert response.json() == {"result": "ok"}
    assert (await db.get_payment(payment_id)).status == "succeeded"
    assert (await client.get(f"/payments/{payment_id}")).json()["status"] == "succeeded"


async def test_full_lifecycle_to_refunded(
    client: AsyncClient, db: DbProbe, payment_id: str
) -> None:
    assert (await send(client, event(payment_id, "succeeded"))).status_code == 200
    assert (await send(client, event(payment_id, "refunded"))).status_code == 200

    assert (await db.get_payment(payment_id)).status == "refunded"


@pytest.mark.parametrize(
    "signature",
    [None, "", "0" * 64, "not-hex", "auto-wrong-secret"],
    ids=["missing", "empty", "zeros", "garbage", "wrong-secret"],
)
async def test_bad_signature_is_rejected(
    client: AsyncClient, db: DbProbe, payment_id: str, signature: str | None
) -> None:
    body = event(payment_id, "succeeded")
    if signature == "auto-wrong-secret":
        signature = sign(body, "wrong-secret")

    response = await send(client, body, signature)

    assert response.status_code == 401
    assert (await db.get_payment(payment_id)).status == "pending"


async def test_signature_over_different_body_is_rejected(
    client: AsyncClient, db: DbProbe, payment_id: str
) -> None:
    signed = event(payment_id, "failed")
    sent = event(payment_id, "succeeded")

    response = await send(client, sent, sign(signed, WEBHOOK_SECRET))

    assert response.status_code == 401
    assert (await db.get_payment(payment_id)).status == "pending"


async def test_signature_checked_before_body_validation(client: AsyncClient) -> None:
    response = await send(client, b"{not json", signature=None)

    assert response.status_code == 401


@pytest.mark.parametrize(
    ("body", "loc"),
    [
        (b"{not json", ["body", 1]),
        (b'{"payment_id": "123", "status": "succeeded"}', ["body", "payment_id"]),
        (event(uuid4(), "paid"), ["body", "status"]),
        (b'{"status": "succeeded"}', ["body", "payment_id"]),
    ],
    ids=["broken-json", "non-uuid", "unknown-status", "missing-field"],
)
async def test_invalid_body_with_valid_signature(
    client: AsyncClient, body: bytes, loc: list[str]
) -> None:
    response = await send(client, body)

    assert response.status_code == 422
    # Same shape as FastAPI's own body validation errors.
    assert response.json()["detail"][0]["loc"] == loc


@pytest.mark.parametrize("body", [b"{not json", b'{"payment_id": '])
async def test_broken_json_error_matches_fastapi(client: AsyncClient, body: bytes) -> None:
    # POST /payments declares its body, so FastAPI itself builds that 422.
    reference = await client.post(
        "/payments", content=body, headers={"Content-Type": "application/json"}
    )

    response = await send(client, body)

    assert response.status_code == 422
    assert response.json() == reference.json()
    assert response.json()["detail"][0]["type"] == "json_invalid"


async def test_non_utf8_body_is_422(client: AsyncClient) -> None:
    # FastAPI answers 400 here; SPEC.md (webhook, step 2) wants 422 for a non-UTF-8 body.
    response = await send(client, b'{"status": "\xff"}')

    assert response.status_code == 422
    assert response.json()["detail"][0]["type"] == "json_invalid"
    assert response.json()["detail"][0]["loc"] == ["body", 12]


async def test_unknown_payment(client: AsyncClient) -> None:
    response = await send(client, event(uuid4(), "succeeded"))

    assert response.status_code == 404
    assert response.json() == {"detail": "Payment not found"}


@pytest.mark.parametrize(
    ("first", "second"),
    [("succeeded", "succeeded"), ("succeeded", "failed"), ("failed", "succeeded")],
)
async def test_invalid_transition(
    client: AsyncClient, db: DbProbe, payment_id: str, first: str, second: str
) -> None:
    assert (await send(client, event(payment_id, first))).status_code == 200

    response = await send(client, event(payment_id, second))

    assert response.status_code == 409
    assert response.json() == {"error": "invalid_transition"}
    assert (await client.get(f"/payments/{payment_id}")).json()["status"] == first
    assert (await db.get_payment(payment_id)).status == first


async def test_refund_from_pending_is_invalid(client: AsyncClient, payment_id: str) -> None:
    response = await send(client, event(payment_id, "refunded"))

    assert response.status_code == 409
    assert response.json() == {"error": "invalid_transition"}
    assert (await client.get(f"/payments/{payment_id}")).json()["status"] == "pending"
