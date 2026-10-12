from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.payment import Payment


class PaymentRepo:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, payment_id: UUID) -> Payment | None:
        return await self._session.get(Payment, payment_id)

    async def get_by_idempotency_key(self, key: str) -> Payment | None:
        return await self._session.scalar(select(Payment).where(Payment.idempotency_key == key))

    async def list(
        self, *, email: str | None, status: str | None, limit: int, offset: int
    ) -> Sequence[Payment]:
        query = select(Payment)
        if email is not None:
            query = query.where(Payment.email == email)
        if status is not None:
            query = query.where(Payment.status == status)
        query = query.order_by(Payment.created_at.desc(), Payment.id.desc())
        result = await self._session.scalars(query.limit(limit).offset(offset))
        return result.all()

    async def add(self, **fields: Any) -> Payment | None:
        """Insert a payment; return None if its idempotency key is already taken.

        Other integrity errors are re-raised, even when a key was given.

        The insert runs in a SAVEPOINT so a unique violation rolls back only this
        statement and the outer request transaction stays usable.
        """
        payment = Payment(**fields)
        try:
            async with self._session.begin_nested():
                self._session.add(payment)
                await self._session.flush()
        except IntegrityError:
            # Only a taken key is a repeat; any other violation is a real error.
            key = fields.get("idempotency_key")
            if key is None or await self.get_by_idempotency_key(key) is None:
                raise
            return None
        return payment

    async def update_status(self, payment_id: UUID, current: str, new: str) -> bool:
        """Set `new` only if the status is still `current`; return False otherwise.

        The status check is part of the UPDATE itself, so of two concurrent
        transitions from the same status only one matches a row.
        """
        result = await self._session.execute(
            update(Payment)
            .where(Payment.id == payment_id, Payment.status == current)
            .values(status=new)
        )
        return result.rowcount == 1
