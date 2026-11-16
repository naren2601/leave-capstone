"""Initial schema: every LeaveDesk table, constraint and index.

Generated with `alembic revision --autogenerate` from leavedesk/db/models.py,
then reviewed and extended by hand with what the ORM cannot express:
- the btree_gist extension, needed by the no_overlapping_leave EXCLUDE constraint;
- triggers that make leave_ledger and audit_log append-only.

Revision ID: 0001
Revises:
Create Date: 2026-11-16 09:09:31.685574
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


APPEND_ONLY_FUNCTION = """
CREATE FUNCTION reject_change_to_append_only_table() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION '% is append-only: % is not allowed', TG_TABLE_NAME, TG_OP
        USING ERRCODE = 'restrict_violation';
END;
$$
"""

APPEND_ONLY_TABLES = ("leave_ledger", "audit_log")


def upgrade() -> None:
    # Lets plain columns (tenant_id, employee_id) use = in the GiST EXCLUDE constraint.
    # A trusted extension, so the database owner can create it without superuser.
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")

    op.create_table(
        "tenants",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("btrim(name) <> ''", name=op.f("ck_tenants_name_not_blank")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tenants")),
        sa.UniqueConstraint("name", name=op.f("uq_tenants_name")),
    )
    op.create_table(
        "departments",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("btrim(name) <> ''", name=op.f("ck_departments_name_not_blank")),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_departments_tenant_id_tenants")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_departments")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_departments_tenant_id_id")),
        sa.UniqueConstraint("tenant_id", "name", name=op.f("uq_departments_tenant_id_name")),
    )
    op.create_table(
        "leave_types",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("days_per_year", sa.Numeric(precision=5, scale=1), nullable=False),
        sa.Column("min_start_offset_days", sa.Integer(), nullable=False),
        sa.Column("max_days_per_request", sa.Numeric(precision=5, scale=1), nullable=True),
        sa.CheckConstraint("code ~ '^[A-Z_]+$'", name=op.f("ck_leave_types_code_format")),
        sa.CheckConstraint(
            "days_per_year >= 0", name=op.f("ck_leave_types_days_per_year_not_negative")
        ),
        sa.CheckConstraint(
            "max_days_per_request IS NULL OR max_days_per_request > 0",
            name=op.f("ck_leave_types_max_days_per_request_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_leave_types_tenant_id_tenants")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_leave_types")),
        sa.UniqueConstraint("tenant_id", "code", name=op.f("uq_leave_types_tenant_id_code")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_leave_types_tenant_id_id")),
    )
    op.create_table(
        "employees",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("is_manager", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("department_id", sa.BigInteger(), nullable=True),
        sa.Column("manager_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("btrim(code) <> ''", name=op.f("ck_employees_code_not_blank")),
        sa.CheckConstraint("btrim(name) <> ''", name=op.f("ck_employees_name_not_blank")),
        sa.CheckConstraint(
            "email ~ '^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$'", name=op.f("ck_employees_email_format")
        ),
        sa.CheckConstraint("manager_id <> id", name=op.f("ck_employees_not_own_manager")),
        sa.ForeignKeyConstraint(
            ["tenant_id", "department_id"],
            ["departments.tenant_id", "departments.id"],
            name="fk_employees_tenant_id_department_id_departments",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "manager_id"],
            ["employees.tenant_id", "employees.id"],
            name="fk_employees_tenant_id_manager_id_employees",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_employees_tenant_id_tenants")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_employees")),
        sa.UniqueConstraint("tenant_id", "code", name=op.f("uq_employees_tenant_id_code")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_employees_tenant_id_id")),
    )
    op.create_index(
        "ix_employees_tenant_id_department_id",
        "employees",
        ["tenant_id", "department_id"],
        unique=False,
    )
    op.create_index(
        "ix_employees_tenant_id_manager_id", "employees", ["tenant_id", "manager_id"], unique=False
    )
    op.create_index(
        "uq_employees_tenant_id_lower_email",
        "employees",
        ["tenant_id", sa.literal_column("lower(email)")],
        unique=True,
    )
    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("actor_id", sa.BigInteger(), nullable=True),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("entity", sa.Text(), nullable=False),
        sa.Column("entity_id", sa.Text(), nullable=False),
        sa.Column("request_id", sa.Text(), nullable=True),
        sa.Column(
            "details",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "actor_id"],
            ["employees.tenant_id", "employees.id"],
            name="fk_audit_log_tenant_id_actor_id_employees",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_audit_log_tenant_id_tenants")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_log")),
    )
    op.create_index(
        "ix_audit_log_tenant_id_actor_id", "audit_log", ["tenant_id", "actor_id"], unique=False
    )
    op.create_index(
        "ix_audit_log_tenant_id_created_at",
        "audit_log",
        ["tenant_id", sa.literal_column("created_at DESC")],
        unique=False,
    )
    op.create_table(
        "leave_balances",
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("employee_id", sa.BigInteger(), nullable=False),
        sa.Column("leave_type_id", sa.BigInteger(), nullable=False),
        sa.Column("year", sa.SmallInteger(), nullable=False),
        sa.Column(
            "entitled",
            sa.Numeric(precision=5, scale=1),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "used", sa.Numeric(precision=5, scale=1), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "pending", sa.Numeric(precision=5, scale=1), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("entitled >= 0", name=op.f("ck_leave_balances_entitled_not_negative")),
        sa.CheckConstraint(
            "used + pending <= entitled", name=op.f("ck_leave_balances_no_overspend")
        ),
        sa.CheckConstraint(
            "used >= 0 AND pending >= 0", name=op.f("ck_leave_balances_used_pending_not_negative")
        ),
        sa.CheckConstraint("version > 0", name=op.f("ck_leave_balances_version_positive")),
        sa.CheckConstraint("year BETWEEN 2000 AND 2100", name=op.f("ck_leave_balances_year_range")),
        sa.ForeignKeyConstraint(
            ["tenant_id", "employee_id"],
            ["employees.tenant_id", "employees.id"],
            name="fk_leave_balances_tenant_id_employee_id_employees",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "leave_type_id"],
            ["leave_types.tenant_id", "leave_types.id"],
            name="fk_leave_balances_tenant_id_leave_type_id_leave_types",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_leave_balances_tenant_id_tenants")
        ),
        sa.PrimaryKeyConstraint(
            "tenant_id", "employee_id", "leave_type_id", "year", name=op.f("pk_leave_balances")
        ),
    )
    op.create_index(
        "ix_leave_balances_tenant_id_leave_type_id",
        "leave_balances",
        ["tenant_id", "leave_type_id"],
        unique=False,
    )
    op.create_table(
        "leave_requests",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("employee_id", sa.BigInteger(), nullable=False),
        sa.Column("leave_type_id", sa.BigInteger(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("day_part", sa.Text(), server_default=sa.text("'FULL'"), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'PENDING'"), nullable=False),
        sa.Column("days", sa.Numeric(precision=5, scale=1), nullable=False),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.Column("decided_by_id", sa.BigInteger(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column(
            "period",
            postgresql.TSRANGE(),
            sa.Computed(
                "CASE WHEN end_date < start_date THEN NULL WHEN day_part = 'AM' THEN tsrange(start_date + time '00:00', start_date + time '12:00', '[)') WHEN day_part = 'PM' THEN tsrange(start_date + time '12:00', start_date + 1 + time '00:00', '[)') ELSE tsrange(start_date + time '00:00', end_date + 1 + time '00:00', '[)') END",
                persisted=True,
            ),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        postgresql.ExcludeConstraint(
            (sa.column("tenant_id"), "="),
            (sa.column("employee_id"), "="),
            (sa.column("period"), "&&"),
            where=sa.text("status IN ('PENDING', 'APPROVED')"),
            using="gist",
            name="no_overlapping_leave",
        ),
        sa.CheckConstraint(
            "day_part = 'FULL' OR start_date = end_date",
            name=op.f("ck_leave_requests_half_day_single_date"),
        ),
        sa.CheckConstraint(
            "day_part IN ('FULL', 'AM', 'PM')", name=op.f("ck_leave_requests_day_part_valid")
        ),
        sa.CheckConstraint(
            "status IN ('PENDING', 'APPROVED', 'REJECTED', 'CANCELLED')",
            name=op.f("ck_leave_requests_status_valid"),
        ),
        sa.CheckConstraint(
            "char_length(btrim(reason)) BETWEEN 5 AND 500",
            name=op.f("ck_leave_requests_reason_length"),
        ),
        sa.CheckConstraint("days > 0", name=op.f("ck_leave_requests_days_positive")),
        sa.CheckConstraint("end_date >= start_date", name=op.f("ck_leave_requests_dates_in_order")),
        sa.CheckConstraint("version > 0", name=op.f("ck_leave_requests_version_positive")),
        sa.ForeignKeyConstraint(
            ["tenant_id", "decided_by_id"],
            ["employees.tenant_id", "employees.id"],
            name="fk_leave_requests_tenant_id_decided_by_id_employees",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "employee_id"],
            ["employees.tenant_id", "employees.id"],
            name="fk_leave_requests_tenant_id_employee_id_employees",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "leave_type_id"],
            ["leave_types.tenant_id", "leave_types.id"],
            name="fk_leave_requests_tenant_id_leave_type_id_leave_types",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_leave_requests_tenant_id_tenants")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_leave_requests")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_leave_requests_tenant_id_id")),
    )
    op.create_index(
        "ix_leave_requests_tenant_id_decided_by_id",
        "leave_requests",
        ["tenant_id", "decided_by_id"],
        unique=False,
        postgresql_where=sa.text("decided_by_id IS NOT NULL"),
    )
    op.create_index(
        "ix_leave_requests_tenant_id_employee_id",
        "leave_requests",
        ["tenant_id", "employee_id"],
        unique=False,
    )
    op.create_index(
        "ix_leave_requests_tenant_id_leave_type_id",
        "leave_requests",
        ["tenant_id", "leave_type_id"],
        unique=False,
    )
    op.create_table(
        "notifications",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("recipient_id", sa.BigInteger(), nullable=False),
        sa.Column("event", sa.Text(), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "event IN ('SUBMITTED', 'APPROVED', 'REJECTED', 'CANCELLED')",
            name=op.f("ck_notifications_event_valid"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(payload) = 'object'", name=op.f("ck_notifications_payload_is_object")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "recipient_id"],
            ["employees.tenant_id", "employees.id"],
            name="fk_notifications_tenant_id_recipient_id_employees",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_notifications_tenant_id_tenants")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notifications")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_notifications_tenant_id_id")),
    )
    op.create_index(
        "ix_notifications_recipient_created_at",
        "notifications",
        ["tenant_id", "recipient_id", sa.literal_column("created_at DESC")],
        unique=False,
    )
    op.create_index(
        "ix_notifications_recipient_unread",
        "notifications",
        ["tenant_id", "recipient_id", sa.literal_column("created_at DESC")],
        unique=False,
        postgresql_where=sa.text("read_at IS NULL"),
    )
    op.create_table(
        "users",
        sa.Column("employee_id", sa.BigInteger(), nullable=False),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("failed_login_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "password_hash LIKE '$argon2id$%%'", name=op.f("ck_users_argon2id_hash")
        ),
        sa.CheckConstraint(
            "failed_login_count >= 0", name=op.f("ck_users_failed_login_count_not_negative")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "employee_id"],
            ["employees.tenant_id", "employees.id"],
            name="fk_users_tenant_id_employee_id_employees",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_users_tenant_id_tenants")
        ),
        sa.PrimaryKeyConstraint("employee_id", name=op.f("pk_users")),
    )
    op.create_index(
        "ix_users_tenant_id_employee_id", "users", ["tenant_id", "employee_id"], unique=False
    )
    op.create_table(
        "idempotency_keys",
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("employee_id", sa.BigInteger(), nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("leave_request_id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "char_length(key) BETWEEN 1 AND 200", name=op.f("ck_idempotency_keys_key_length")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "employee_id"],
            ["employees.tenant_id", "employees.id"],
            name="fk_idempotency_keys_tenant_id_employee_id_employees",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "leave_request_id"],
            ["leave_requests.tenant_id", "leave_requests.id"],
            name="fk_idempotency_keys_tenant_id_leave_request_id_leave_requests",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_idempotency_keys_tenant_id_tenants")
        ),
        sa.PrimaryKeyConstraint(
            "tenant_id", "employee_id", "key", name=op.f("pk_idempotency_keys")
        ),
    )
    op.create_index(
        "ix_idempotency_keys_tenant_id_leave_request_id",
        "idempotency_keys",
        ["tenant_id", "leave_request_id"],
        unique=False,
    )
    op.create_table(
        "leave_ledger",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("employee_id", sa.BigInteger(), nullable=False),
        sa.Column("leave_type_id", sa.BigInteger(), nullable=False),
        sa.Column("year", sa.SmallInteger(), nullable=False),
        sa.Column("leave_request_id", sa.UUID(), nullable=True),
        sa.Column("movement", sa.Text(), nullable=False),
        sa.Column(
            "entitled_delta",
            sa.Numeric(precision=5, scale=1),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "pending_delta",
            sa.Numeric(precision=5, scale=1),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "used_delta",
            sa.Numeric(precision=5, scale=1),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("created_by_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(movement = 'ENTITLEMENT' AND pending_delta = 0 AND used_delta = 0) OR (movement = 'RESERVE' AND entitled_delta = 0 AND pending_delta > 0 AND used_delta = 0) OR (movement = 'RELEASE' AND entitled_delta = 0 AND pending_delta < 0 AND used_delta = 0) OR (movement = 'CONSUME' AND entitled_delta = 0 AND pending_delta < 0 AND used_delta = -pending_delta) OR (movement = 'RESTORE' AND entitled_delta = 0 AND pending_delta = 0 AND used_delta < 0)",
            name=op.f("ck_leave_ledger_movement_shape"),
        ),
        sa.CheckConstraint(
            "movement = 'ENTITLEMENT' OR leave_request_id IS NOT NULL",
            name=op.f("ck_leave_ledger_request_movements_have_request"),
        ),
        sa.CheckConstraint(
            "movement IN ('ENTITLEMENT', 'RESERVE', 'RELEASE', 'CONSUME', 'RESTORE')",
            name=op.f("ck_leave_ledger_movement_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "created_by_id"],
            ["employees.tenant_id", "employees.id"],
            name="fk_leave_ledger_tenant_id_created_by_id_employees",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "employee_id", "leave_type_id", "year"],
            [
                "leave_balances.tenant_id",
                "leave_balances.employee_id",
                "leave_balances.leave_type_id",
                "leave_balances.year",
            ],
            name="fk_leave_ledger_balance_leave_balances",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "leave_request_id"],
            ["leave_requests.tenant_id", "leave_requests.id"],
            name="fk_leave_ledger_tenant_id_leave_request_id_leave_requests",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_leave_ledger_tenant_id_tenants")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_leave_ledger")),
    )
    op.create_index(
        "ix_leave_ledger_balance",
        "leave_ledger",
        ["tenant_id", "employee_id", "leave_type_id", "year"],
        unique=False,
    )
    op.create_index(
        "ix_leave_ledger_tenant_id_created_by_id",
        "leave_ledger",
        ["tenant_id", "created_by_id"],
        unique=False,
        postgresql_where=sa.text("created_by_id IS NOT NULL"),
    )
    op.create_index(
        "ix_leave_ledger_tenant_id_leave_request_id",
        "leave_ledger",
        ["tenant_id", "leave_request_id"],
        unique=False,
        postgresql_where=sa.text("leave_request_id IS NOT NULL"),
    )
    op.create_table(
        "notification_outbox",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("notification_id", sa.UUID(), nullable=False),
        sa.Column("channel", sa.Text(), server_default=sa.text("'email'"), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'PENDING'"), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "channel IN ('email')", name=op.f("ck_notification_outbox_channel_valid")
        ),
        sa.CheckConstraint(
            "status IN ('PENDING', 'SENT', 'FAILED')",
            name=op.f("ck_notification_outbox_status_valid"),
        ),
        sa.CheckConstraint(
            "attempts >= 0", name=op.f("ck_notification_outbox_attempts_not_negative")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "notification_id"],
            ["notifications.tenant_id", "notifications.id"],
            name="fk_notification_outbox_tenant_id_notification_id_notifications",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_notification_outbox_tenant_id_tenants")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notification_outbox")),
    )
    op.create_index(
        "ix_notification_outbox_pending",
        "notification_outbox",
        ["available_at", "id"],
        unique=False,
        postgresql_where=sa.text("status = 'PENDING'"),
    )
    op.create_index(
        "ix_notification_outbox_tenant_id_notification_id",
        "notification_outbox",
        ["tenant_id", "notification_id"],
        unique=False,
    )

    # Rows in the ledger and audit log are history: they can be added, never changed.
    op.execute(APPEND_ONLY_FUNCTION)
    for table in APPEND_ONLY_TABLES:
        op.execute(
            f"CREATE TRIGGER {table}_no_update_or_delete BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION reject_change_to_append_only_table()"
        )
        op.execute(
            f"CREATE TRIGGER {table}_no_truncate BEFORE TRUNCATE ON {table} "
            "FOR EACH STATEMENT EXECUTE FUNCTION reject_change_to_append_only_table()"
        )


def downgrade() -> None:
    # Dropping the tables removes their triggers; then the function can go.
    op.drop_index(
        "ix_notification_outbox_tenant_id_notification_id", table_name="notification_outbox"
    )
    op.drop_index(
        "ix_notification_outbox_pending",
        table_name="notification_outbox",
        postgresql_where=sa.text("status = 'PENDING'"),
    )
    op.drop_table("notification_outbox")
    op.drop_index(
        "ix_leave_ledger_tenant_id_leave_request_id",
        table_name="leave_ledger",
        postgresql_where=sa.text("leave_request_id IS NOT NULL"),
    )
    op.drop_index(
        "ix_leave_ledger_tenant_id_created_by_id",
        table_name="leave_ledger",
        postgresql_where=sa.text("created_by_id IS NOT NULL"),
    )
    op.drop_index("ix_leave_ledger_balance", table_name="leave_ledger")
    op.drop_table("leave_ledger")
    op.drop_index("ix_idempotency_keys_tenant_id_leave_request_id", table_name="idempotency_keys")
    op.drop_table("idempotency_keys")
    op.drop_index("ix_users_tenant_id_employee_id", table_name="users")
    op.drop_table("users")
    op.drop_index(
        "ix_notifications_recipient_unread",
        table_name="notifications",
        postgresql_where=sa.text("read_at IS NULL"),
    )
    op.drop_index("ix_notifications_recipient_created_at", table_name="notifications")
    op.drop_table("notifications")
    op.drop_index("ix_leave_requests_tenant_id_leave_type_id", table_name="leave_requests")
    op.drop_index("ix_leave_requests_tenant_id_employee_id", table_name="leave_requests")
    op.drop_index(
        "ix_leave_requests_tenant_id_decided_by_id",
        table_name="leave_requests",
        postgresql_where=sa.text("decided_by_id IS NOT NULL"),
    )
    op.drop_table("leave_requests")
    op.drop_index("ix_leave_balances_tenant_id_leave_type_id", table_name="leave_balances")
    op.drop_table("leave_balances")
    op.drop_index("ix_audit_log_tenant_id_created_at", table_name="audit_log")
    op.drop_index("ix_audit_log_tenant_id_actor_id", table_name="audit_log")
    op.drop_table("audit_log")
    op.drop_index("uq_employees_tenant_id_lower_email", table_name="employees")
    op.drop_index("ix_employees_tenant_id_manager_id", table_name="employees")
    op.drop_index("ix_employees_tenant_id_department_id", table_name="employees")
    op.drop_table("employees")
    op.drop_table("leave_types")
    op.drop_table("departments")
    op.drop_table("tenants")
    op.execute("DROP FUNCTION IF EXISTS reject_change_to_append_only_table()")
    # btree_gist is left installed: other databases objects may rely on it.
