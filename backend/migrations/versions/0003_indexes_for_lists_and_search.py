"""Indexes for lists and search, measured with 100,000 requests (see PERF.md).

- ix_leave_requests_history (tenant_id, employee_id, start_date, id) replaces the
  plain (tenant_id, employee_id) index: same foreign-key job, and also sorted.
- ix_leave_requests_pending: the same columns, PENDING rows only (the approval queue).
- ix_employees_name_trgm: a trigram index, so ILIKE '%text%' does not read every employee.

CREATE INDEX CONCURRENTLY builds an index without blocking writes to the table,
which matters on a live system. It cannot run inside a transaction, hence the
autocommit blocks.

Revision ID: 0003
Revises: 0002
"""

from collections.abc import Iterator, Sequence
from contextlib import contextmanager

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

KEY = ["tenant_id", "employee_id", "start_date", "id"]


@contextmanager
def outside_a_transaction() -> Iterator[None]:
    """Run statements in autocommit mode, as CONCURRENTLY requires.

    With pg8000, Alembic's autocommit block still leaves a transaction open: it reads
    the isolation level first, and pg8000 starts a transaction for that read. COMMIT
    ends it. With psycopg there is none, and PostgreSQL only logs a warning.
    """
    with op.get_context().autocommit_block():
        op.execute("COMMIT")
        yield


def upgrade() -> None:
    # pg_trgm is a "trusted" extension: the table owner may add it without a superuser.
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    with outside_a_transaction():
        op.create_index(
            "ix_leave_requests_history",
            "leave_requests",
            KEY,
            postgresql_concurrently=True,
            if_not_exists=True,
        )
        op.create_index(
            "ix_leave_requests_pending",
            "leave_requests",
            KEY,
            postgresql_where="status = 'PENDING'",
            postgresql_concurrently=True,
            if_not_exists=True,
        )
        op.create_index(
            "ix_employees_name_trgm",
            "employees",
            ["name"],
            postgresql_using="gin",
            postgresql_ops={"name": "gin_trgm_ops"},
            postgresql_concurrently=True,
            if_not_exists=True,
        )
        # Only after its replacement exists, so the foreign key is never unindexed.
        op.drop_index(
            "ix_leave_requests_tenant_id_employee_id",
            table_name="leave_requests",
            postgresql_concurrently=True,
            if_exists=True,
        )


def downgrade() -> None:
    with outside_a_transaction():
        op.create_index(
            "ix_leave_requests_tenant_id_employee_id",
            "leave_requests",
            ["tenant_id", "employee_id"],
            postgresql_concurrently=True,
            if_not_exists=True,
        )
        for name, table in (
            ("ix_employees_name_trgm", "employees"),
            ("ix_leave_requests_pending", "leave_requests"),
            ("ix_leave_requests_history", "leave_requests"),
        ):
            op.drop_index(name, table_name=table, postgresql_concurrently=True, if_exists=True)
    # pg_trgm stays: other objects may use it, and keeping it is harmless.
