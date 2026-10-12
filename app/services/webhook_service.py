import hashlib
import hmac

from app.services.exceptions import InvalidSignature


def sign(body: bytes, secret: str) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def verify_signature(body: bytes, signature: str | None, secret: str) -> None:
    """Raise InvalidSignature unless `signature` is the hex HMAC-SHA256 of the raw body."""
    if not signature:
        raise InvalidSignature
    # Compare bytes: compare_digest raises TypeError on non-ASCII str.
    expected = sign(body, secret).encode()
    if not hmac.compare_digest(expected, signature.strip().lower().encode()):
        raise InvalidSignature
