import json
from typing import Annotated, Any

from fastapi import APIRouter, Header, Request
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError

from app.api.dependencies import PaymentServiceDep, SettingsDep
from app.schemas.webhook import BANK_WEBHOOK_EXAMPLE, BankWebhookIn, WebhookResult
from app.services.webhook_service import verify_signature

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

# The body schema is inlined via openapi_extra, so its refs must point into the
# document's components (where FastAPI already puts PaymentStatus), not at local $defs.
_BANK_WEBHOOK_SCHEMA = BankWebhookIn.model_json_schema(ref_template="#/components/schemas/{model}")
_BANK_WEBHOOK_SCHEMA.pop("$defs", None)


def _json_invalid(pos: int, reason: str, doc: Any) -> RequestValidationError:
    # The exact error FastAPI itself returns for a body it cannot decode.
    error = {
        "type": "json_invalid",
        "loc": ("body", pos),
        "msg": "JSON decode error",
        "input": {},
        "ctx": {"error": reason},
    }
    return RequestValidationError([error], body=doc)


def parse_event(raw: bytes) -> BankWebhookIn:
    """Decode and validate the body the way FastAPI does for a declared body parameter."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise _json_invalid(exc.pos, exc.msg, exc.doc) from exc
    except UnicodeDecodeError as exc:
        raise _json_invalid(exc.start, exc.reason, raw) from exc
    try:
        return BankWebhookIn.model_validate(data)
    except ValidationError as exc:
        errors = [
            {**error, "loc": ("body", *error["loc"])} for error in exc.errors(include_url=False)
        ]
        raise RequestValidationError(errors, body=data) from exc


# The body is read raw rather than declared as a parameter: the signature must be
# checked against the exact bytes, and before FastAPI would reject a malformed body.
@router.post(
    "/bank",
    response_model=WebhookResult,
    description=(
        "Bank notification about a payment status change.\n\n"
        "`X-Signature` is the hex HMAC-SHA256 of the raw request body, keyed with "
        "`WEBHOOK_SECRET`. The signature covers the exact bytes sent, so sign the body "
        "as it goes over the wire:\n\n"
        "```sh\n"
        'SIG=$(printf \'%s\' "$BODY" | openssl dgst -sha256 -hmac "$WEBHOOK_SECRET" '
        "| awk '{print $NF}')\n"
        "```\n\n"
        "Checks, in order: signature (401), body (422), payment exists (404), "
        "transition allowed (409)."
    ),
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": _BANK_WEBHOOK_SCHEMA,
                    "example": BANK_WEBHOOK_EXAMPLE,
                }
            },
        }
    },
)
async def bank_webhook(
    request: Request,
    service: PaymentServiceDep,
    settings: SettingsDep,
    x_signature: Annotated[
        str | None,
        Header(description="Hex HMAC-SHA256 of the raw request body, keyed with WEBHOOK_SECRET"),
    ] = None,
) -> WebhookResult:
    raw = await request.body()
    verify_signature(raw, x_signature, settings.webhook_secret.get_secret_value())
    event = parse_event(raw)
    await service.change_status(event.payment_id, event.status)
    return WebhookResult()
