from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

from app.core.constants import PROMO_CODES, PaymentMethod, PaymentStatus
from app.services.exceptions import (
    InvalidTransition,
    PaymentNotFound,
    TariffNotFound,
    UnknownPromoCode,
)
from app.services.tariff_service import TariffRepository

ALLOWED_TRANSITIONS: dict[PaymentStatus, frozenset[PaymentStatus]] = {
    PaymentStatus.PENDING: frozenset({PaymentStatus.SUCCEEDED, PaymentStatus.FAILED}),
    PaymentStatus.SUCCEEDED: frozenset({PaymentStatus.REFUNDED}),
}


class PaymentRepository(Protocol):
    async def get(self, payment_id: UUID) -> Any: ...

    async def get_by_idempotency_key(self, key: str) -> Any: ...

    async def list(
        self, *, email: str | None, status: str | None, limit: int, offset: int
    ) -> Sequence[Any]: ...

    async def add(self, **fields: Any) -> Any:
        """Insert a payment; return None if `idempotency_key` is already taken."""
        ...

    async def update_status(self, payment_id: UUID, current: str, new: str) -> bool:
        """Set `new` only if the status is still `current`; return False otherwise."""
        ...


@dataclass(frozen=True, slots=True)
class NewPayment:
    tariff_id: int
    email: str
    method: PaymentMethod
    installment_months: int | None = None
    promo_code: str | None = None


def calculate_amount(price: int, promo_code: str | None) -> tuple[int, int]:
    """Return (amount, discount) in kopecks. `promo_code` must already be normalized."""
    if not promo_code:
        return price, 0
    if promo_code not in PROMO_CODES:
        raise UnknownPromoCode(promo_code)
    percent = PROMO_CODES[promo_code]
    discount = price * percent // 100
    return price - discount, discount


def build_schedule(amount: int, months: int) -> list[int]:
    """Split `amount` into `months` payments; extra kopecks go to the first ones."""
    base, rest = divmod(amount, months)
    return [base + 1 if i < rest else base for i in range(months)]


def can_transition(current: str, new: str) -> bool:
    return PaymentStatus(new) in ALLOWED_TRANSITIONS.get(PaymentStatus(current), frozenset())


class PaymentService:
    def __init__(self, payments: PaymentRepository, tariffs: TariffRepository) -> None:
        self._payments = payments
        self._tariffs = tariffs

    async def create(self, data: NewPayment, idempotency_key: str | None) -> tuple[Any, bool]:
        """Return (payment, created). `created` is False for an idempotent repeat."""
        if idempotency_key is not None:
            existing = await self._payments.get_by_idempotency_key(idempotency_key)
            if existing is not None:
                return existing, False

        tariff = await self._tariffs.get(data.tariff_id)
        if tariff is None:
            raise TariffNotFound(data.tariff_id)

        amount, discount = calculate_amount(tariff.price, data.promo_code)
        is_installment = data.method == PaymentMethod.INSTALLMENT
        months = data.installment_months if is_installment else None
        schedule = build_schedule(amount, months) if months else None

        payment = await self._payments.add(
            tariff_id=tariff.id,
            email=data.email,
            method=data.method.value,
            status=PaymentStatus.PENDING.value,
            amount=amount,
            discount=discount,
            installment_months=months,
            schedule=schedule,
            idempotency_key=idempotency_key,
        )
        if payment is not None:
            return payment, True

        # Lost a race: a concurrent request with the same key was inserted first.
        existing = await self._payments.get_by_idempotency_key(idempotency_key or "")
        if existing is None:
            raise RuntimeError("idempotency key conflict, but no payment found")
        return existing, False

    async def get(self, payment_id: UUID) -> Any:
        payment = await self._payments.get(payment_id)
        if payment is None:
            raise PaymentNotFound(payment_id)
        return payment

    async def list(
        self, *, email: str | None, status: PaymentStatus | None, limit: int, offset: int
    ) -> Sequence[Any]:
        return await self._payments.list(
            email=email,
            status=status.value if status else None,
            limit=limit,
            offset=offset,
        )

    async def change_status(self, payment_id: UUID, status: PaymentStatus) -> None:
        payment = await self.get(payment_id)
        if not can_transition(payment.status, status):
            raise InvalidTransition(payment.status, status)
        # A concurrent webhook may have changed the status since we read it.
        if not await self._payments.update_status(payment_id, payment.status, status.value):
            raise InvalidTransition(payment.status, status)
