"""The real get_db is the transactional boundary: commit on success, rollback on error."""

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.database import get_db, get_sessionmaker
from app.main import app
from app.repositories.payment_repo import PaymentRepo
from tests.conftest import DbProbe
from tests.integration.test_idempotency_race import payment_fields


class FailingCommitSession(AsyncSession):
    async def commit(self) -> None:
        raise RuntimeError("commit failed")


@pytest.fixture
async def failing_commit_client(
    client: AsyncClient, engine: AsyncEngine
) -> AsyncIterator[AsyncClient]:
    # `client` sets up the overrides; this one swaps in sessions whose commit fails
    # and returns server errors as responses instead of raising them in the test.
    failing = async_sessionmaker(engine, class_=FailingCommitSession, expire_on_commit=False)
    app.dependency_overrides[get_sessionmaker] = lambda: failing
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as failing_client:
        yield failing_client


async def test_failed_commit_is_500_not_201(
    failing_commit_client: AsyncClient, db: DbProbe
) -> None:
    # get_db runs with scope="function": the commit happens before the response is sent,
    # so a failed commit turns into a 500 instead of a 201 for a payment that does not exist.
    response = await failing_commit_client.post(
        "/payments", json={"tariff_id": 1, "email": "a@example.com", "method": "card"}
    )

    assert response.status_code == 500
    assert await db.count_payments() == 0


async def test_get_db_commits_on_success(
    session_factory: async_sessionmaker[AsyncSession], db: DbProbe
) -> None:
    sessions = get_db(session_factory)
    session = await anext(sessions)
    await PaymentRepo(session).add(**payment_fields(None))

    with pytest.raises(StopAsyncIteration):
        await anext(sessions)

    assert await db.count_payments() == 1


async def test_get_db_rolls_back_on_error(
    session_factory: async_sessionmaker[AsyncSession], db: DbProbe
) -> None:
    sessions = get_db(session_factory)
    session = await anext(sessions)
    await PaymentRepo(session).add(**payment_fields(None))

    with pytest.raises(RuntimeError):
        await sessions.athrow(RuntimeError("handler failed"))

    assert await db.count_payments() == 0
