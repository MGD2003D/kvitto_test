from collections.abc import Sequence
from typing import Protocol


class TariffRecord(Protocol):
    @property
    def id(self) -> int: ...

    @property
    def title(self) -> str: ...

    @property
    def price(self) -> int: ...


class TariffRepository(Protocol):
    async def list_all(self) -> Sequence[TariffRecord]: ...

    async def get(self, tariff_id: int) -> TariffRecord | None: ...


class TariffService:
    def __init__(self, tariffs: TariffRepository) -> None:
        self._tariffs = tariffs

    async def list_tariffs(self) -> Sequence[TariffRecord]:
        return await self._tariffs.list_all()
