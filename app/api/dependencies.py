from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.repositories.payment_repo import PaymentRepo
from app.repositories.tariff_repo import TariffRepo
from app.services.payment_service import PaymentService
from app.services.tariff_service import TariffService

# scope="function": commit/rollback runs before the response is sent, so the client
# never gets a success response for a transaction that then fails to commit.
DbSession = Annotated[AsyncSession, Depends(get_db, scope="function")]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_tariff_service(session: DbSession) -> TariffService:
    return TariffService(TariffRepo(session))


def get_payment_service(session: DbSession) -> PaymentService:
    return PaymentService(PaymentRepo(session), TariffRepo(session))


TariffServiceDep = Annotated[TariffService, Depends(get_tariff_service)]
PaymentServiceDep = Annotated[PaymentService, Depends(get_payment_service)]
