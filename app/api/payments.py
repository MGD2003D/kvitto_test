from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, Header, Query, Response, status
from pydantic import EmailStr

from app.api.dependencies import PaymentServiceDep
from app.core.constants import PaymentStatus
from app.schemas.payment import (
    PAYMENT_CREATE_EXAMPLES,
    IdempotencyKey,
    PaymentCreate,
    PaymentOut,
)
from app.services.payment_service import NewPayment

router = APIRouter(prefix="/payments", tags=["payments"])

STATUS_FILTER_DESCRIPTION = "Payment status, one of: " + ", ".join(s.value for s in PaymentStatus)


@router.post(
    "",
    response_model=PaymentOut,
    status_code=status.HTTP_201_CREATED,
    responses={200: {"model": PaymentOut, "description": "Existing payment for Idempotency-Key"}},
)
async def create_payment(
    body: Annotated[PaymentCreate, Body(openapi_examples=PAYMENT_CREATE_EXAMPLES)],
    response: Response,
    service: PaymentServiceDep,
    idempotency_key: Annotated[IdempotencyKey | None, Header()] = None,
) -> PaymentOut:
    # A blank key (already stripped) means no key.
    key = idempotency_key or None
    payment, created = await service.create(NewPayment(**body.model_dump()), key)
    if not created:
        response.status_code = status.HTTP_200_OK
    return PaymentOut.model_validate(payment)


@router.get("/{payment_id}", response_model=PaymentOut)
async def get_payment(payment_id: UUID, service: PaymentServiceDep) -> PaymentOut:
    return PaymentOut.model_validate(await service.get(payment_id))


@router.get("", response_model=list[PaymentOut])
async def list_payments(
    service: PaymentServiceDep,
    email: EmailStr | None = None,
    status: Annotated[PaymentStatus | None, Query(description=STATUS_FILTER_DESCRIPTION)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[PaymentOut]:
    payments = await service.list(email=email, status=status, limit=limit, offset=offset)
    return [PaymentOut.model_validate(p) for p in payments]
