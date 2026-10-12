"""Race on Idempotency-Key: the unique constraint wins and the existing payment is returned.

Runs against SQLite with the SAVEPOINT workaround from conftest.py.
"""

from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.constants import PaymentMethod
from app.models import Payment
from app.repositories.payment_repo import PaymentRepo
from app.repositories.tariff_repo import TariffRepo
from app.services.payment_service import NewPayment, PaymentService


def payment_fields(key: str | None) -> dict[str, Any]:
    return {
        "tariff_id": 1,
        "email": "a@example.com",
        "method": "card",
        "status": "pending",
        "amount": 990000,
        "discount": 0,
        "installment_months": None,
        "schedule": None,
        "idempotency_key": key,
    }


class RacingPaymentRepo(PaymentRepo):
    """Pretends the first key lookup happened before a concurrent insert committed."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self._lookups = 0

    async def get_by_idempotency_key(self, key: str) -> Payment | None:
        self._lookups += 1
        if self._lookups == 1:
            return None
        return await super().get_by_idempotency_key(key)


async def count_payments(session: AsyncSession) -> int:
    return await session.scalar(select(func.count()).select_from(Payment)) or 0


async def test_duplicate_key_insert_keeps_outer_transaction(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        first = await PaymentRepo(session).add(**payment_fields("race-key"))
        await session.commit()
    assert first is not None

    async with session_factory() as session:
        repo = PaymentRepo(session)
        duplicate = await repo.add(**payment_fields("race-key"))
        # The outer transaction must survive the rolled-back savepoint.
        other = await repo.add(**payment_fields("other-key"))
        await session.commit()

    assert duplicate is None
    assert other is not None
    async with session_factory() as session:
        keys = await session.scalars(select(Payment.idempotency_key))
        assert sorted(keys.all()) == ["other-key", "race-key"]


async def test_other_integrity_error_is_not_a_key_repeat(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    # A key is set, but the insert fails on NOT NULL: that must surface, not read as a repeat.
    async with session_factory() as session:
        with pytest.raises(IntegrityError):
            await PaymentRepo(session).add(**{**payment_fields("fresh-key"), "email": None})
        await session.rollback()

    async with session_factory() as session:
        assert await count_payments(session) == 0


async def test_outer_rollback_discards_savepoint_insert(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    # get_db rolls back on exception: an insert made inside a savepoint must not survive it.
    async with session_factory() as session:
        assert await PaymentRepo(session).add(**payment_fields("rolled-back")) is not None
        await session.rollback()

    async with session_factory() as session:
        assert await count_payments(session) == 0


async def test_service_returns_existing_payment_on_race(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        first = await PaymentRepo(session).add(**payment_fields("race-key"))
        await session.commit()
    assert first is not None

    data = NewPayment(tariff_id=2, email="b@example.com", method=PaymentMethod.SBP)
    async with session_factory() as session:
        service = PaymentService(RacingPaymentRepo(session), TariffRepo(session))
        payment, created = await service.create(data, "race-key")
        await session.commit()

    assert created is False
    assert payment.id == first.id
    assert payment.tariff_id == 1
    async with session_factory() as session:
        assert await count_payments(session) == 1
