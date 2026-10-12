from fastapi import APIRouter

from app.api.dependencies import TariffServiceDep
from app.schemas.tariff import TariffOut

router = APIRouter(prefix="/tariffs", tags=["tariffs"])


@router.get("", response_model=list[TariffOut])
async def list_tariffs(service: TariffServiceDep) -> list[TariffOut]:
    tariffs = await service.list_tariffs()
    return [TariffOut.model_validate(t) for t in tariffs]
