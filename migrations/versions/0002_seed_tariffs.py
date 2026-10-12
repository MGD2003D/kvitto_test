"""seed tariffs

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

tariffs = sa.table(
    "tariffs",
    sa.column("id", sa.Integer),
    sa.column("title", sa.String),
    sa.column("price", sa.Integer),
)


def upgrade() -> None:
    op.bulk_insert(
        tariffs,
        [
            {"id": 1, "title": "basic", "price": 990000},
            {"id": 2, "title": "standard", "price": 1990000},
            {"id": 3, "title": "premium", "price": 2990000},
        ],
    )
    # Explicit ids do not advance the PostgreSQL sequence; move it past them.
    if op.get_bind().dialect.name == "postgresql":
        op.execute("SELECT setval(pg_get_serial_sequence('tariffs', 'id'), 3)")


def downgrade() -> None:
    op.execute(tariffs.delete().where(tariffs.c.id.in_([1, 2, 3])))
