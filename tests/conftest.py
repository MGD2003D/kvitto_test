from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from app.core.config import Settings, get_settings
from app.core.database import get_sessionmaker
from app.main import app
from app.models import Base, Payment, Tariff

WEBHOOK_SECRET = "test-secret"

TARIFFS = [
    {"id": 1, "title": "basic", "price": 990000},
    {"id": 2, "title": "standard", "price": 1990000},
    {"id": 3, "title": "premium", "price": 2990000},
]


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    # pysqlite/aiosqlite manage transactions themselves and break SAVEPOINT
    # (begin_nested). Workaround from the SQLAlchemy SQLite dialect docs:
    # disable the driver's implicit BEGIN and emit it ourselves.
    @event.listens_for(engine.sync_engine, "connect")
    def _connect(dbapi_connection: Any, _: Any) -> None:
        dbapi_connection.isolation_level = None

    @event.listens_for(engine.sync_engine, "begin")
    def _begin(connection: Any) -> None:
        connection.exec_driver_sql("BEGIN")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(Tariff.__table__.insert(), TARIFFS)
    yield engine
    await engine.dispose()


@pytest.fixture
def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


class DbProbe:
    """Reads and tweaks database state from tests.

    Every call uses its own short session: StaticPool shares one SQLite connection,
    so a session left open with a transaction would block the app's next BEGIN.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def count_payments(self) -> int:
        async with self._session_factory() as session:
            return await session.scalar(select(func.count()).select_from(Payment)) or 0

    async def get_payment(self, payment_id: str | UUID) -> Payment:
        async with self._session_factory() as session:
            payment = await session.get(Payment, UUID(str(payment_id)))
        assert payment is not None
        return payment

    async def set_status(self, payment_id: str | UUID, status: str) -> None:
        async with self._session_factory() as session:
            payment = await session.get(Payment, UUID(str(payment_id)))
            assert payment is not None
            payment.status = status
            await session.commit()


@pytest.fixture
def db(session_factory: async_sessionmaker[AsyncSession]) -> DbProbe:
    return DbProbe(session_factory)


@pytest.fixture
async def client(session_factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncClient]:
    settings = Settings(
        database_url="sqlite+aiosqlite://", webhook_secret=SecretStr(WEBHOOK_SECRET)
    )
    # The real get_db runs; only its sessionmaker points at the test engine.
    app.dependency_overrides[get_sessionmaker] = lambda: session_factory
    app.dependency_overrides[get_settings] = lambda: settings
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()
