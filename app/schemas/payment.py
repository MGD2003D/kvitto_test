from typing import Annotated, Self
from uuid import UUID

from fastapi.openapi.models import Example
from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.core.constants import (
    MAX_DB_INT,
    PROMO_CODES,
    InstallmentMonths,
    PaymentMethod,
    PaymentStatus,
)

# Stripped before the length check; fits payments.idempotency_key String(255).
IdempotencyKey = Annotated[str, StringConstraints(strip_whitespace=True, max_length=255)]


# Named Swagger examples for POST /payments; each must pass PaymentCreate validation.
PAYMENT_CREATE_EXAMPLES: dict[str, Example] = {
    "card": {
        "summary": "Card, no promo code",
        "value": {"tariff_id": 2, "email": "student@example.com", "method": "card"},
    },
    "sbp_promo": {
        "summary": "SBP with promo code kvitto10 (case-insensitive)",
        "value": {
            "tariff_id": 2,
            "email": "student@example.com",
            "method": "sbp",
            "promo_code": "kvitto10",
        },
    },
    "installment": {
        "summary": "Installment for 3 months",
        "value": {
            "tariff_id": 2,
            "email": "student@example.com",
            "method": "installment",
            "installment_months": 3,
        },
    },
}


class PaymentCreate(BaseModel):
    tariff_id: int = Field(ge=1, le=MAX_DB_INT)
    email: EmailStr
    method: PaymentMethod
    installment_months: InstallmentMonths | None = None
    promo_code: str | None = None

    @field_validator("promo_code")
    @classmethod
    def normalize_promo_code(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        code = value.strip().upper()
        if code not in PROMO_CODES:
            raise ValueError("unknown promo code")
        return code

    @model_validator(mode="after")
    def check_installment(self) -> Self:
        if self.method == PaymentMethod.INSTALLMENT:
            if self.installment_months is None:
                raise ValueError("installment_months is required for installment")
        elif self.installment_months is not None:
            raise ValueError("installment_months is allowed only for installment")
        return self


class PaymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    status: PaymentStatus
    tariff_id: int
    amount: int
    discount: int
    method: PaymentMethod
    installment_months: int | None
    schedule: list[int] | None
    email: str
    created_at: AwareDatetime
