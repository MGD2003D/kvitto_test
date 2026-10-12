import hashlib
import hmac

import pytest

from app.services.exceptions import InvalidSignature
from app.services.webhook_service import sign, verify_signature

SECRET = "secret"
BODY = b'{"payment_id": "00000000-0000-0000-0000-000000000000", "status": "succeeded"}'


def test_sign_is_hex_hmac_sha256() -> None:
    assert sign(BODY, SECRET) == hmac.new(SECRET.encode(), BODY, hashlib.sha256).hexdigest()


def test_valid_signature() -> None:
    verify_signature(BODY, sign(BODY, SECRET), SECRET)


def test_valid_signature_uppercase_hex() -> None:
    verify_signature(BODY, sign(BODY, SECRET).upper(), SECRET)


@pytest.mark.parametrize(
    "signature",
    [None, "", "deadbeef", sign(BODY, "other-secret"), sign(BODY + b" ", SECRET), "подпись"],
)
def test_invalid_signature(signature: str | None) -> None:
    with pytest.raises(InvalidSignature):
        verify_signature(BODY, signature, SECRET)
