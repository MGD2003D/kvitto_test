"""Race on status change: two webhooks read the same status, only one may apply.

Runs against SQLite: the losing UPDATE matches no row because its WHERE includes
the status it read.
"""

from uuid import UUID

import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.constants import PaymentStatus
from app.models import Payment
from app.repositories.payment_repo import PaymentRepo
from app.repositories.tariff_repo import TariffRepo
from app.services.exceptions import InvalidTransition
from app.services.payment_service import PaymentService
from tests.conftest import DbProbe
from tests.integration.test_idempotency_race import payment_fields


class RacingPaymentRepo(PaymentRepo):
    """Commits a concurrent `failed` right after the service reads the payment."""

    async def get(self, payment_id: UUID) -> Payment | None:
        payment = await super().get(payment_id)
        await self._session.execute(
            update(Payment)
            .where(Payment.id == payment_id)
            .values(status=PaymentStatus.FAILED.value)
            .execution_options(synchronize_session=False)
        )
        return payment


async def test_concurrent_transition_is_rejected(
    session_factory: async_sessionmaker[AsyncSession], db: DbProbe
) -> None:
    async with session_factory() as session:
        payment = await PaymentRepo(session).add(**payment_fields(None))
        await session.commit()
    assert payment is not None

    async with session_factory() as session:
        service = PaymentService(RacingPaymentRepo(session), TariffRepo(session))
        with pytest.raises(InvalidTransition):
            await service.change_status(payment.id, PaymentStatus.SUCCEEDED)
        await session.commit()  # persist the "concurrent" write to check it survived

    assert (await db.get_payment(payment.id)).status == "failed"


async def test_update_status_applies_only_from_expected_status(
    session_factory: async_sessionmaker[AsyncSession], db: DbProbe
) -> None:
    async with session_factory() as session:
        payment = await PaymentRepo(session).add(**payment_fields(None))
        await session.commit()
    assert payment is not None

    async with session_factory() as session:
        repo = PaymentRepo(session)
        assert await repo.update_status(payment.id, "pending", "succeeded") is True
        assert await repo.update_status(payment.id, "pending", "failed") is False
        await session.commit()

    assert (await db.get_payment(payment.id)).status == "succeeded"
