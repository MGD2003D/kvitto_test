from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel

from app.core.constants import PaymentStatus

# Swagger example for POST /webhooks/bank.
BANK_WEBHOOK_EXAMPLE: dict[str, Any] = {
    "payment_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    "status": "succeeded",
}


class BankWebhookIn(BaseModel):
    payment_id: UUID
    status: PaymentStatus


class WebhookResult(BaseModel):
    result: Literal["ok"] = "ok"
