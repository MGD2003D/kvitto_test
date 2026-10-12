import pytest
from pydantic import ValidationError

from app.core.config import DatabaseSettings, Settings


def test_database_settings_do_not_need_webhook_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    # Alembic uses DatabaseSettings: migrations must run without app secrets.
    monkeypatch.delenv("WEBHOOK_SECRET", raising=False)
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite://")

    settings = DatabaseSettings(_env_file=None)

    assert settings.database_url == "sqlite+aiosqlite://"


def test_settings_require_webhook_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WEBHOOK_SECRET", raising=False)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


@pytest.mark.parametrize("secret", ["", "   "])
def test_settings_reject_blank_webhook_secret(secret: str) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, webhook_secret=secret)


def test_settings_accept_webhook_secret() -> None:
    settings = Settings(_env_file=None, webhook_secret="s3cret")

    assert settings.webhook_secret.get_secret_value() == "s3cret"
