from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from app.api import payments, tariffs, webhooks
from app.core.config import get_settings
from app.core.database import get_engine
from app.services.exceptions import (
    InvalidSignature,
    InvalidTransition,
    PaymentNotFound,
    TariffNotFound,
)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    # Fail at startup, not on the first request, if required settings are missing.
    get_settings()
    yield
    if get_engine.cache_info().currsize:
        await get_engine().dispose()


app = FastAPI(title="Kvitto Payments API", lifespan=lifespan)
app.include_router(tariffs.router)
app.include_router(payments.router)
app.include_router(webhooks.router)


@app.exception_handler(TariffNotFound)
async def tariff_not_found(_: Request, __: TariffNotFound) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND, content={"detail": "Tariff not found"}
    )


@app.exception_handler(PaymentNotFound)
async def payment_not_found(_: Request, __: PaymentNotFound) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND, content={"detail": "Payment not found"}
    )


@app.exception_handler(InvalidSignature)
async def invalid_signature(_: Request, __: InvalidSignature) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_401_UNAUTHORIZED, content={"detail": "Invalid signature"}
    )


@app.exception_handler(InvalidTransition)
async def invalid_transition(_: Request, __: InvalidTransition) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT, content={"error": "invalid_transition"}
    )
