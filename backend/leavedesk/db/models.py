"""SQLAlchemy 2 models for LeaveDesk. See SCHEMA.md for the reasons behind each choice.

Relationships are view-only and use lazy="raise": related rows must be loaded
explicitly (for example with selectinload), so an accidental N+1 query fails
loudly instead of quietly running one query per row.

Rules that apply to every table:
- Every business table has tenant_id, and foreign keys between business tables
  include tenant_id, so a row can never point at another tenant's row.
- Every foreign key has an index whose leading columns match it.
- Days are numeric(5,1) and timestamps are timestamptz.

Schema changes are made only through Alembic revisions in migrations/versions/.
tests/db/test_schema.py checks that the migrations and these models match.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Index,
    Integer,
    MetaData,
    Numeric,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSRANGE, UUID, ExcludeConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from leavedesk.db.ids import uuid7

# Predictable constraint names, so migrations and error handling can refer to them.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

DAYS = Numeric(5, 1)

LEAVE_STATUSES = ("PENDING", "APPROVED", "REJECTED", "CANCELLED")
ACTIVE_STATUSES = ("PENDING", "APPROVED")
DAY_PARTS = ("FULL", "AM", "PM")
NOTIFICATION_EVENTS = ("SUBMITTED", "APPROVED", "REJECTED", "CANCELLED")
LEDGER_MOVEMENTS = ("ENTITLEMENT", "RESERVE", "RELEASE", "CONSUME", "RESTORE")


def _in(column: str, values: tuple[str, ...]) -> str:
    quoted = ", ".join(f"'{value}'" for value in values)
    return f"{column} IN ({quoted})"


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map = {
        datetime: DateTime(timezone=True),
        Decimal: DAYS,
        dict[str, Any]: JSONB,
    }


def created_at() -> Mapped[datetime]:
    return mapped_column(server_default=func.now())


def tenant_id_column() -> Mapped[int]:
    return mapped_column(BigInteger, ForeignKey("tenants.id"))


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    name: Mapped[str] = mapped_column(Text, unique=True)
    created_at: Mapped[datetime] = created_at()

    __table_args__ = (CheckConstraint("btrim(name) <> ''", name="name_not_blank"),)


class Department(Base):
    __tablename__ = "departments"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    tenant_id: Mapped[int] = tenant_id_column()
    name: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at()

    __table_args__ = (
        UniqueConstraint("tenant_id", "name"),
        UniqueConstraint("tenant_id", "id"),  # target for tenant-safe foreign keys
        CheckConstraint("btrim(name) <> ''", name="name_not_blank"),
    )


class Employee(Base):
    __tablename__ = "employees"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    tenant_id: Mapped[int] = tenant_id_column()
    code: Mapped[str] = mapped_column(Text)  # the id the API uses, such as "e1"
    name: Mapped[str] = mapped_column(Text)
    email: Mapped[str] = mapped_column(Text)
    is_manager: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    department_id: Mapped[int | None] = mapped_column(BigInteger)
    manager_id: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("tenant_id", "code"),
        UniqueConstraint("tenant_id", "id"),
        # Email is unique per tenant, ignoring case.
        Index(
            "uq_employees_tenant_id_lower_email",
            "tenant_id",
            func.lower(text("email")),
            unique=True,
        ),
        ForeignKeyConstraint(
            ["tenant_id", "manager_id"],
            ["employees.tenant_id", "employees.id"],
            name="fk_employees_tenant_id_manager_id_employees",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "department_id"],
            ["departments.tenant_id", "departments.id"],
            name="fk_employees_tenant_id_department_id_departments",
        ),
        Index("ix_employees_tenant_id_manager_id", "tenant_id", "manager_id"),
        Index("ix_employees_tenant_id_department_id", "tenant_id", "department_id"),
        CheckConstraint("manager_id <> id", name="not_own_manager"),
        CheckConstraint("btrim(code) <> ''", name="code_not_blank"),
        CheckConstraint("btrim(name) <> ''", name="name_not_blank"),
        CheckConstraint(r"email ~ '^[^@\s]+@[^@\s]+\.[^@\s]+$'", name="email_format"),
    )

    manager: Mapped["Employee | None"] = relationship(
        primaryjoin="and_(Employee.manager_id == remote(Employee.id),"
        " Employee.tenant_id == remote(Employee.tenant_id))",
        foreign_keys="[Employee.manager_id, Employee.tenant_id]",
        viewonly=True,
        lazy="raise",
    )


class User(Base):
    """Login details. One per employee; the email is the employee's email."""

    __tablename__ = "users"

    employee_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = tenant_id_column()
    password_hash: Mapped[str] = mapped_column(Text)
    failed_login_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    locked_until: Mapped[datetime | None]
    last_login_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = created_at()

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "employee_id"],
            ["employees.tenant_id", "employees.id"],
            ondelete="CASCADE",
            name="fk_users_tenant_id_employee_id_employees",
        ),
        Index("ix_users_tenant_id_employee_id", "tenant_id", "employee_id"),
        CheckConstraint("failed_login_count >= 0", name="failed_login_count_not_negative"),
        CheckConstraint("password_hash LIKE '$argon2id$%'", name="argon2id_hash"),
    )


class LeaveType(Base):
    """A lookup table, because each type carries its own rules."""

    __tablename__ = "leave_types"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    tenant_id: Mapped[int] = tenant_id_column()
    code: Mapped[str] = mapped_column(Text)  # ANNUAL, SICK, CASUAL
    name: Mapped[str] = mapped_column(Text)
    days_per_year: Mapped[Decimal]
    # Earliest allowed start, in days from today: 3 means three days' notice,
    # -7 means it can be backdated by a week.
    min_start_offset_days: Mapped[int] = mapped_column(Integer)
    max_days_per_request: Mapped[Decimal | None]

    __table_args__ = (
        UniqueConstraint("tenant_id", "code"),
        UniqueConstraint("tenant_id", "id"),
        CheckConstraint("code ~ '^[A-Z_]+$'", name="code_format"),
        CheckConstraint("days_per_year >= 0", name="days_per_year_not_negative"),
        CheckConstraint(
            "max_days_per_request IS NULL OR max_days_per_request > 0",
            name="max_days_per_request_positive",
        ),
    )


# The time a request covers, with half-day precision, so an AM and a PM
# half-day on the same date do not overlap. NULL when the dates are reversed,
# so the clearer dates_in_order CHECK reports that case.
PERIOD_SQL = (
    "CASE "
    "WHEN end_date < start_date THEN NULL "
    "WHEN day_part = 'AM' "
    "THEN tsrange(start_date + time '00:00', start_date + time '12:00', '[)') "
    "WHEN day_part = 'PM' "
    "THEN tsrange(start_date + time '12:00', start_date + 1 + time '00:00', '[)') "
    "ELSE tsrange(start_date + time '00:00', end_date + 1 + time '00:00', '[)') END"
)


class LeaveRequest(Base):
    __tablename__ = "leave_requests"

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid7)
    tenant_id: Mapped[int] = tenant_id_column()
    employee_id: Mapped[int] = mapped_column(BigInteger)
    leave_type_id: Mapped[int] = mapped_column(BigInteger)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    day_part: Mapped[str] = mapped_column(Text, server_default=text("'FULL'"))
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default=text("'PENDING'"))
    days: Mapped[Decimal]
    decision_note: Mapped[str | None] = mapped_column(Text)
    decided_by_id: Mapped[int | None] = mapped_column(BigInteger)
    decided_at: Mapped[datetime | None]
    version: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    # Nullable on purpose: NULL for reversed dates (see PERIOD_SQL).
    period: Mapped[Any | None] = mapped_column(TSRANGE, Computed(PERIOD_SQL, persisted=True))
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        ForeignKeyConstraint(
            ["tenant_id", "employee_id"],
            ["employees.tenant_id", "employees.id"],
            name="fk_leave_requests_tenant_id_employee_id_employees",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "leave_type_id"],
            ["leave_types.tenant_id", "leave_types.id"],
            name="fk_leave_requests_tenant_id_leave_type_id_leave_types",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "decided_by_id"],
            ["employees.tenant_id", "employees.id"],
            name="fk_leave_requests_tenant_id_decided_by_id_employees",
        ),
        Index("ix_leave_requests_tenant_id_employee_id", "tenant_id", "employee_id"),
        Index("ix_leave_requests_tenant_id_leave_type_id", "tenant_id", "leave_type_id"),
        Index(
            "ix_leave_requests_tenant_id_decided_by_id",
            "tenant_id",
            "decided_by_id",
            postgresql_where=text("decided_by_id IS NOT NULL"),
        ),
        CheckConstraint("end_date >= start_date", name="dates_in_order"),
        CheckConstraint("day_part = 'FULL' OR start_date = end_date", name="half_day_single_date"),
        CheckConstraint(_in("day_part", DAY_PARTS), name="day_part_valid"),
        CheckConstraint(_in("status", LEAVE_STATUSES), name="status_valid"),
        CheckConstraint("days > 0", name="days_positive"),
        CheckConstraint("char_length(btrim(reason)) BETWEEN 5 AND 500", name="reason_length"),
        CheckConstraint("version > 0", name="version_positive"),
        # No overlapping PENDING or APPROVED leave for the same employee.
        # Needs the btree_gist extension so tenant_id and employee_id can use =.
        ExcludeConstraint(
            ("tenant_id", "="),
            ("employee_id", "="),
            ("period", "&&"),
            name="no_overlapping_leave",
            using="gist",
            where=text(_in("status", ACTIVE_STATUSES)),
        ),
    )

    employee: Mapped[Employee] = relationship(
        primaryjoin="and_(LeaveRequest.employee_id == Employee.id,"
        " LeaveRequest.tenant_id == Employee.tenant_id)",
        foreign_keys="[LeaveRequest.employee_id, LeaveRequest.tenant_id]",
        viewonly=True,
        lazy="raise",
    )
    leave_type: Mapped[LeaveType] = relationship(
        primaryjoin="and_(LeaveRequest.leave_type_id == LeaveType.id,"
        " LeaveRequest.tenant_id == LeaveType.tenant_id)",
        foreign_keys="[LeaveRequest.leave_type_id, LeaveRequest.tenant_id]",
        viewonly=True,
        lazy="raise",
    )

    # Optimistic locking: every UPDATE checks and increments version.
    __mapper_args__ = {"version_id_col": version}


class LeaveBalance(Base):
    """Running totals of the ledger, one row per employee, leave type and year.

    This is the row approvals lock with SELECT ... FOR UPDATE, and its CHECK
    makes overspending impossible, even with concurrent approvals.
    """

    __tablename__ = "leave_balances"

    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenants.id"), primary_key=True)
    employee_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    leave_type_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    year: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    entitled: Mapped[Decimal] = mapped_column(DAYS, server_default=text("0"))
    used: Mapped[Decimal] = mapped_column(DAYS, server_default=text("0"))
    pending: Mapped[Decimal] = mapped_column(DAYS, server_default=text("0"))
    version: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "employee_id"],
            ["employees.tenant_id", "employees.id"],
            name="fk_leave_balances_tenant_id_employee_id_employees",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "leave_type_id"],
            ["leave_types.tenant_id", "leave_types.id"],
            name="fk_leave_balances_tenant_id_leave_type_id_leave_types",
        ),
        Index("ix_leave_balances_tenant_id_leave_type_id", "tenant_id", "leave_type_id"),
        CheckConstraint("entitled >= 0", name="entitled_not_negative"),
        CheckConstraint("used >= 0 AND pending >= 0", name="used_pending_not_negative"),
        CheckConstraint("used + pending <= entitled", name="no_overspend"),
        CheckConstraint("year BETWEEN 2000 AND 2100", name="year_range"),
        CheckConstraint("version > 0", name="version_positive"),
    )

    __mapper_args__ = {"version_id_col": version}


class LeaveLedger(Base):
    """Append-only: a trigger rejects UPDATE, DELETE and TRUNCATE."""

    __tablename__ = "leave_ledger"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    tenant_id: Mapped[int] = tenant_id_column()
    employee_id: Mapped[int] = mapped_column(BigInteger)
    leave_type_id: Mapped[int] = mapped_column(BigInteger)
    year: Mapped[int] = mapped_column(SmallInteger)
    leave_request_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    movement: Mapped[str] = mapped_column(Text)
    entitled_delta: Mapped[Decimal] = mapped_column(DAYS, server_default=text("0"))
    pending_delta: Mapped[Decimal] = mapped_column(DAYS, server_default=text("0"))
    used_delta: Mapped[Decimal] = mapped_column(DAYS, server_default=text("0"))
    created_by_id: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = created_at()

    __table_args__ = (
        # Every movement belongs to an existing balance row.
        ForeignKeyConstraint(
            ["tenant_id", "employee_id", "leave_type_id", "year"],
            [
                "leave_balances.tenant_id",
                "leave_balances.employee_id",
                "leave_balances.leave_type_id",
                "leave_balances.year",
            ],
            name="fk_leave_ledger_balance_leave_balances",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "leave_request_id"],
            ["leave_requests.tenant_id", "leave_requests.id"],
            name="fk_leave_ledger_tenant_id_leave_request_id_leave_requests",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "created_by_id"],
            ["employees.tenant_id", "employees.id"],
            name="fk_leave_ledger_tenant_id_created_by_id_employees",
        ),
        Index(
            "ix_leave_ledger_balance",
            "tenant_id",
            "employee_id",
            "leave_type_id",
            "year",
        ),
        Index(
            "ix_leave_ledger_tenant_id_leave_request_id",
            "tenant_id",
            "leave_request_id",
            postgresql_where=text("leave_request_id IS NOT NULL"),
        ),
        Index(
            "ix_leave_ledger_tenant_id_created_by_id",
            "tenant_id",
            "created_by_id",
            postgresql_where=text("created_by_id IS NOT NULL"),
        ),
        CheckConstraint(_in("movement", LEDGER_MOVEMENTS), name="movement_valid"),
        # Each kind of movement may only change the columns it is meant to.
        CheckConstraint(
            "(movement = 'ENTITLEMENT' AND pending_delta = 0 AND used_delta = 0)"
            " OR (movement = 'RESERVE' AND entitled_delta = 0 AND pending_delta > 0"
            " AND used_delta = 0)"
            " OR (movement = 'RELEASE' AND entitled_delta = 0 AND pending_delta < 0"
            " AND used_delta = 0)"
            " OR (movement = 'CONSUME' AND entitled_delta = 0 AND pending_delta < 0"
            " AND used_delta = -pending_delta)"
            " OR (movement = 'RESTORE' AND entitled_delta = 0 AND pending_delta = 0"
            " AND used_delta < 0)",
            name="movement_shape",
        ),
        CheckConstraint(
            "movement = 'ENTITLEMENT' OR leave_request_id IS NOT NULL",
            name="request_movements_have_request",
        ),
    )


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid7)
    tenant_id: Mapped[int] = tenant_id_column()
    recipient_id: Mapped[int] = mapped_column(BigInteger)
    event: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(server_default=text("'{}'::jsonb"))
    read_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = created_at()

    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        ForeignKeyConstraint(
            ["tenant_id", "recipient_id"],
            ["employees.tenant_id", "employees.id"],
            name="fk_notifications_tenant_id_recipient_id_employees",
        ),
        # Lists a recipient's notifications, newest first (also the FK index).
        Index(
            "ix_notifications_recipient_created_at",
            "tenant_id",
            "recipient_id",
            text("created_at DESC"),
        ),
        # Small and fast for the unread count: only unread rows are indexed.
        Index(
            "ix_notifications_recipient_unread",
            "tenant_id",
            "recipient_id",
            text("created_at DESC"),
            postgresql_where=text("read_at IS NULL"),
        ),
        CheckConstraint(_in("event", NOTIFICATION_EVENTS), name="event_valid"),
        CheckConstraint("jsonb_typeof(payload) = 'object'", name="payload_is_object"),
    )


class NotificationOutbox(Base):
    """Deliveries waiting to be sent. Written in the same transaction as the change."""

    __tablename__ = "notification_outbox"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    tenant_id: Mapped[int] = tenant_id_column()
    notification_id: Mapped[uuid.UUID] = mapped_column(UUID)
    channel: Mapped[str] = mapped_column(Text, server_default=text("'email'"))
    status: Mapped[str] = mapped_column(Text, server_default=text("'PENDING'"))
    attempts: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    available_at: Mapped[datetime] = mapped_column(server_default=func.now())
    claimed_at: Mapped[datetime | None]
    sent_at: Mapped[datetime | None]
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at()

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "notification_id"],
            ["notifications.tenant_id", "notifications.id"],
            name="fk_notification_outbox_tenant_id_notification_id_notifications",
        ),
        Index("ix_notification_outbox_tenant_id_notification_id", "tenant_id", "notification_id"),
        # What the worker reads: the oldest pending rows that are due.
        Index(
            "ix_notification_outbox_pending",
            "available_at",
            "id",
            postgresql_where=text("status = 'PENDING'"),
        ),
        CheckConstraint("channel IN ('email')", name="channel_valid"),
        CheckConstraint("status IN ('PENDING', 'SENT', 'FAILED')", name="status_valid"),
        CheckConstraint("attempts >= 0", name="attempts_not_negative"),
    )


class AuditLog(Base):
    """Append-only, like the ledger. Free text such as leave reasons is never stored."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    tenant_id: Mapped[int] = tenant_id_column()
    actor_id: Mapped[int | None] = mapped_column(BigInteger)
    action: Mapped[str] = mapped_column(Text)
    entity: Mapped[str] = mapped_column(Text)
    entity_id: Mapped[str] = mapped_column(Text)
    request_id: Mapped[str | None] = mapped_column(Text)
    details: Mapped[dict[str, Any]] = mapped_column(server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = created_at()

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "actor_id"],
            ["employees.tenant_id", "employees.id"],
            name="fk_audit_log_tenant_id_actor_id_employees",
        ),
        Index("ix_audit_log_tenant_id_actor_id", "tenant_id", "actor_id"),
        Index("ix_audit_log_tenant_id_created_at", "tenant_id", text("created_at DESC")),
    )


class IdempotencyKey(Base):
    """The first result for each Idempotency-Key, so a retried POST is not duplicated."""

    __tablename__ = "idempotency_keys"

    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenants.id"), primary_key=True)
    employee_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    key: Mapped[str] = mapped_column(Text, primary_key=True)
    leave_request_id: Mapped[uuid.UUID] = mapped_column(UUID)
    created_at: Mapped[datetime] = created_at()

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "employee_id"],
            ["employees.tenant_id", "employees.id"],
            name="fk_idempotency_keys_tenant_id_employee_id_employees",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "leave_request_id"],
            ["leave_requests.tenant_id", "leave_requests.id"],
            name="fk_idempotency_keys_tenant_id_leave_request_id_leave_requests",
        ),
        Index("ix_idempotency_keys_tenant_id_leave_request_id", "tenant_id", "leave_request_id"),
        CheckConstraint("char_length(key) BETWEEN 1 AND 200", name="key_length"),
    )
