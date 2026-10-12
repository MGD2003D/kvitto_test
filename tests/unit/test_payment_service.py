from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.core.constants import PaymentMethod, PaymentStatus
from app.services.exceptions import (
    InvalidTransition,
    PaymentNotFound,
    TariffNotFound,
    UnknownPromoCode,
)
from app.services.payment_service import (
    NewPayment,
    PaymentService,
    build_schedule,
    calculate_amount,
    can_transition,
)


@dataclass
class FakeTariff:
    id: int
    title: str
    price: int


@dataclass
class FakePayment:
    tariff_id: int
    email: str
    method: str
    status: str
    amount: int
    discount: int
    installment_months: int | None
    schedule: list[int] | None
    idempotency_key: str | None
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class FakeTariffRepo:
    def __init__(self) -> None:
        self.items = {
            1: FakeTariff(1, "basic", 990000),
            2: FakeTariff(2, "standard", 1990000),
            3: FakeTariff(3, "premium", 2990000),
        }

    async def list_all(self) -> Sequence[FakeTariff]:
        return list(self.items.values())

    async def get(self, tariff_id: int) -> FakeTariff | None:
        return self.items.get(tariff_id)


class FakePaymentRepo:
    def __init__(self) -> None:
        self.items: dict[UUID, FakePayment] = {}

    async def get(self, payment_id: UUID) -> FakePayment | None:
        return self.items.get(payment_id)

    async def get_by_idempotency_key(self, key: str) -> FakePayment | None:
        return next((p for p in self.items.values() if p.idempotency_key == key), None)

    async def list(
        self, *, email: str | None, status: str | None, limit: int, offset: int
    ) -> Sequence[FakePayment]:
        return list(self.items.values())[offset : offset + limit]

    async def add(self, **fields: Any) -> FakePayment | None:
        payment = FakePayment(**fields)
        self.items[payment.id] = payment
        return payment

    async def update_status(self, payment_id: UUID, current: str, new: str) -> bool:
        payment = self.items.get(payment_id)
        if payment is None or payment.status != current:
            return False
        payment.status = new
        return True


@pytest.fixture
def payments() -> FakePaymentRepo:
    return FakePaymentRepo()


@pytest.fixture
def service(payments: FakePaymentRepo) -> PaymentService:
    return PaymentService(payments, FakeTariffRepo())


# --- calculate_amount ---


def test_amount_without_promo() -> None:
    assert calculate_amount(1990000, None) == (1990000, 0)


def test_amount_with_promo() -> None:
    assert calculate_amount(1990000, "KVITTO10") == (1791000, 199000)


@pytest.mark.parametrize("promo_code", ["BAD", "kvitto10"])
def test_amount_with_unknown_or_unnormalized_promo_raises(promo_code: str) -> None:
    # Normalization (strip + upper) is the schema's job; the service sees only final codes.
    with pytest.raises(UnknownPromoCode):
        calculate_amount(990000, promo_code)


def test_discount_rounds_down_to_whole_kopecks() -> None:
    amount, discount = calculate_amount(999, "KVITTO10")
    assert (amount, discount) == (900, 99)
    assert isinstance(amount, int) and isinstance(discount, int)


# --- build_schedule ---


def test_schedule_example_from_spec() -> None:
    assert build_schedule(1990000, 3) == [663334, 663333, 663333]


@pytest.mark.parametrize("months", [3, 6, 12])
@pytest.mark.parametrize("amount", [990000, 1990000, 2990000, 891000, 1791000, 2691000, 1000001])
def test_schedule_sums_to_amount(amount: int, months: int) -> None:
    schedule = build_schedule(amount, months)

    assert len(schedule) == months
    assert sum(schedule) == amount
    assert all(isinstance(x, int) for x in schedule)
    assert max(schedule) - min(schedule) <= 1
    assert schedule == sorted(schedule, reverse=True)  # extra kopecks go first


# --- can_transition ---


@pytest.mark.parametrize(
    ("current", "new"),
    [("pending", "succeeded"), ("pending", "failed"), ("succeeded", "refunded")],
)
def test_allowed_transitions(current: str, new: str) -> None:
    assert can_transition(current, new) is True


@pytest.mark.parametrize(
    ("current", "new"),
    [
        ("pending", "pending"),
        ("pending", "refunded"),
        ("succeeded", "succeeded"),
        ("succeeded", "pending"),
        ("succeeded", "failed"),
        ("failed", "failed"),
        ("failed", "succeeded"),
        ("failed", "pending"),
        ("refunded", "refunded"),
        ("refunded", "succeeded"),
        ("refunded", "pending"),
    ],
)
def test_forbidden_transitions(current: str, new: str) -> None:
    assert can_transition(current, new) is False


# --- PaymentService ---


async def test_create_card_payment(service: PaymentService) -> None:
    data = NewPayment(tariff_id=2, email="a@example.com", method=PaymentMethod.CARD)

    payment, created = await service.create(data, None)

    assert created is True
    assert payment.status == "pending"
    assert (payment.amount, payment.discount) == (1990000, 0)
    assert payment.schedule is None
    assert payment.installment_months is None


async def test_create_installment_with_promo(service: PaymentService) -> None:
    data = NewPayment(
        tariff_id=3,
        email="a@example.com",
        method=PaymentMethod.INSTALLMENT,
        installment_months=12,
        promo_code="KVITTO10",
    )

    payment, _ = await service.create(data, None)

    assert (payment.amount, payment.discount) == (2691000, 299000)
    assert payment.installment_months == 12
    assert sum(payment.schedule) == payment.amount


async def test_create_unknown_tariff(service: PaymentService) -> None:
    data = NewPayment(tariff_id=99, email="a@example.com", method=PaymentMethod.SBP)

    with pytest.raises(TariffNotFound):
        await service.create(data, None)


async def test_create_is_idempotent(service: PaymentService, payments: FakePaymentRepo) -> None:
    data = NewPayment(tariff_id=1, email="a@example.com", method=PaymentMethod.CARD)

    first, first_created = await service.create(data, "key-1")
    second, second_created = await service.create(data, "key-1")

    assert (first_created, second_created) == (True, False)
    assert second.id == first.id
    assert len(payments.items) == 1


async def test_change_status(service: PaymentService) -> None:
    data = NewPayment(tariff_id=1, email="a@example.com", method=PaymentMethod.CARD)
    payment, _ = await service.create(data, None)

    await service.change_status(payment.id, PaymentStatus.SUCCEEDED)

    assert payment.status == "succeeded"


async def test_change_status_invalid_transition_keeps_status(service: PaymentService) -> None:
    data = NewPayment(tariff_id=1, email="a@example.com", method=PaymentMethod.CARD)
    payment, _ = await service.create(data, None)

    with pytest.raises(InvalidTransition):
        await service.change_status(payment.id, PaymentStatus.REFUNDED)

    assert payment.status == "pending"


async def test_change_status_lost_race_raises_and_keeps_winner(
    service: PaymentService, payments: FakePaymentRepo
) -> None:
    data = NewPayment(tariff_id=1, email="a@example.com", method=PaymentMethod.CARD)
    payment, _ = await service.create(data, None)
    stale = FakePayment(**{**payment.__dict__, "status": "pending"})
    payment.status = "failed"  # a concurrent webhook committed first

    async def get_stale(payment_id: UUID) -> FakePayment:
        return stale

    payments.get = get_stale  # type: ignore[method-assign]

    with pytest.raises(InvalidTransition):
        await service.change_status(payment.id, PaymentStatus.SUCCEEDED)

    assert payment.status == "failed"


async def test_change_status_unknown_payment(service: PaymentService) -> None:
    with pytest.raises(PaymentNotFound):
        await service.change_status(uuid4(), PaymentStatus.SUCCEEDED)
