from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tariff import Tariff


class TariffRepo:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_all(self) -> Sequence[Tariff]:
        result = await self._session.scalars(select(Tariff).order_by(Tariff.id))
        return result.all()

    async def get(self, tariff_id: int) -> Tariff | None:
        return await self._session.get(Tariff, tariff_id)
