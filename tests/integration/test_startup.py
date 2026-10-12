from collections.abc import Iterator
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import get_settings
from app.main import app, lifespan


@pytest.fixture
def no_settings_cache() -> Iterator[None]:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.mark.usefixtures("no_settings_cache")
async def test_startup_fails_without_webhook_secret(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("WEBHOOK_SECRET", raising=False)
    monkeypatch.chdir(tmp_path)  # no .env to fall back on

    with pytest.raises(ValidationError, match="webhook_secret"):
        async with lifespan(app):
            pass


@pytest.mark.usefixtures("no_settings_cache")
async def test_startup_succeeds_with_webhook_secret(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("WEBHOOK_SECRET", "s3cret")
    monkeypatch.chdir(tmp_path)

    async with lifespan(app):
        assert get_settings().webhook_secret.get_secret_value() == "s3cret"
