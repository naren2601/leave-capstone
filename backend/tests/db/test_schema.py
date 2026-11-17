"""The schema does what SCHEMA.md promises, checked against a real PostgreSQL."""

from datetime import date
from decimal import Decimal

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text

from leavedesk.db.models import (
    AuditLog,
    Base,
    Employee,
    LeaveBalance,
    LeaveLedger,
    Tenant,
    User,
)
from tests.postgres import alembic_config, requires_postgres, temporary_database

pytestmark = requires_postgres

MONDAY = date(2026, 11, 16)
TUESDAY = date(2026, 11, 17)
WEDNESDAY = date(2026, 11, 18)


# The migrations


def test_migrations_upgrade_downgrade_and_upgrade_again():
    with temporary_database() as url:
        config = alembic_config(url)
        command.upgrade(config, "head")
        command.downgrade(config, "base")
        engine = create_engine(url)
        assert inspect(engine).get_table_names() == ["alembic_version"]
        engine.dispose()
        command.upgrade(config, "head")


def test_models_and_migrations_match(engine):
    """Like `alembic check`: autogenerate would find nothing to change."""
    with engine.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        assert compare_metadata(context, Base.metadata) == []


def test_every_business_table_has_a_tenant_id(engine):
    tables = set(inspect(engine).get_table_names()) - {"alembic_version", "tenants"}

    for table in tables:
        column = next(c for c in inspect(engine).get_columns(table) if c["name"] == "tenant_id")
        assert column["nullable"] is False, table


def test_every_foreign_key_has_an_index(engine):
    """PostgreSQL does not index foreign keys automatically. We must."""
    missing = engine.connect().execute(
        text("""
            SELECT c.conrelid::regclass::text AS table_name, c.conname
            FROM pg_constraint c
            WHERE c.contype = 'f'
              AND c.connamespace = 'public'::regnamespace
              AND NOT EXISTS (
                  SELECT 1 FROM pg_index i
                  WHERE i.indrelid = c.conrelid
                    AND (i.indkey::int2[])[0:array_length(c.conkey, 1) - 1]
                        @> c.conkey
                    AND (i.indkey::int2[])[0:array_length(c.conkey, 1) - 1]
                        <@ c.conkey
              )
        """)
    )
    assert missing.all() == []


def test_audit_columns_are_timestamptz_and_days_are_numeric(engine):
    rows = (
        engine.connect()
        .execute(
            text("""
            SELECT table_name, column_name, data_type, numeric_precision, numeric_scale
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND (column_name LIKE '%\\_at' OR column_name IN
                   ('days', 'entitled', 'used', 'pending', 'days_per_year',
                    'max_days_per_request', 'entitled_delta', 'pending_delta', 'used_delta'))
        """)
        )
        .all()
    )

    assert rows
    for table, column, data_type, precision, scale in rows:
        if column.endswith("_at"):
            assert data_type == "timestamp with time zone", f"{table}.{column}"
        else:
            assert (data_type, precision, scale) == ("numeric", 5, 1), f"{table}.{column}"


# Leave requests


def test_valid_request_gets_a_uuid7_id_and_defaults(make_request):
    request = make_request(MONDAY, WEDNESDAY, days=Decimal("3"))

    assert request.id.version == 7
    assert request.status == "PENDING"
    assert request.day_part == "FULL"
    assert request.version == 1


def test_overlapping_active_leave_is_rejected(make_request, rejected):
    make_request(MONDAY, WEDNESDAY)

    with rejected("no_overlapping_leave"):
        make_request(TUESDAY, date(2026, 11, 20))


def test_approved_leave_also_blocks_overlaps(make_request, rejected):
    make_request(MONDAY, status="APPROVED")

    with rejected("no_overlapping_leave"):
        make_request(MONDAY)


def test_am_and_pm_on_the_same_date_do_not_overlap(make_request):
    make_request(MONDAY, day_part="AM", days=Decimal("0.5"))

    make_request(MONDAY, day_part="PM", days=Decimal("0.5"))


def test_same_half_day_twice_is_rejected(make_request, rejected):
    make_request(MONDAY, day_part="AM", days=Decimal("0.5"))

    with rejected("no_overlapping_leave"):
        make_request(MONDAY, day_part="AM", days=Decimal("0.5"))


def test_full_day_over_a_half_day_is_rejected(make_request, rejected):
    make_request(MONDAY, day_part="PM", days=Decimal("0.5"))

    with rejected("no_overlapping_leave"):
        make_request(MONDAY)


def test_rejected_and_cancelled_dates_can_be_reused(make_request):
    make_request(MONDAY, status="REJECTED")
    make_request(MONDAY, status="CANCELLED")

    make_request(MONDAY)


def test_other_employees_are_not_blocked(make_request, org):
    make_request(MONDAY)

    make_request(MONDAY, employee_id=org["kiran"].id)


def test_end_before_start_is_rejected_by_name(make_request, rejected):
    with rejected("ck_leave_requests_dates_in_order"):
        make_request(WEDNESDAY, MONDAY)


def test_half_day_over_two_dates_is_rejected(make_request, rejected):
    with rejected("ck_leave_requests_half_day_single_date"):
        make_request(MONDAY, TUESDAY, day_part="AM")


def test_field_rules(make_request, rejected):
    with rejected("ck_leave_requests_reason_length"):
        make_request(MONDAY, reason="   abc   ")
    with rejected("ck_leave_requests_status_valid"):
        make_request(MONDAY, status="ON_HOLD")
    with rejected("ck_leave_requests_day_part_valid"):
        make_request(MONDAY, day_part="EVENING")
    with rejected("ck_leave_requests_days_positive"):
        make_request(MONDAY, days=Decimal("0"))


def test_days_keep_exact_halves(make_request):
    request = make_request(MONDAY, day_part="AM", days=Decimal("0.5"))

    assert request.days == Decimal("0.5")


# Balances and the ledger


def test_balance_cannot_be_overspent(session, org, rejected):
    balance = session.get(LeaveBalance, (org["tenant"].id, org["asha"].id, org["annual"].id, 2026))

    with rejected("ck_leave_balances_no_overspend"):
        balance.pending = Decimal("10")
        balance.used = Decimal("9")


def _ledger(org, **values) -> LeaveLedger:
    defaults = {
        "tenant_id": org["tenant"].id,
        "employee_id": org["asha"].id,
        "leave_type_id": org["annual"].id,
        "year": 2026,
    }
    return LeaveLedger(**(defaults | values))


def test_ledger_rows_cannot_be_changed_or_deleted(session, org, rejected):
    row = _ledger(org, movement="ENTITLEMENT", entitled_delta=Decimal("18"))
    session.add(row)
    session.flush()

    with rejected("append-only"):
        session.execute(
            text("UPDATE leave_ledger SET entitled_delta = 99 WHERE id = :id"), {"id": row.id}
        )
    with rejected("append-only"):
        session.execute(text("DELETE FROM leave_ledger WHERE id = :id"), {"id": row.id})
    with rejected("append-only"):
        session.execute(text("TRUNCATE leave_ledger CASCADE"))


def test_audit_log_is_append_only(session, org, rejected):
    entry = AuditLog(
        tenant_id=org["tenant"].id, action="approve", entity="leave_request", entity_id="x"
    )
    session.add(entry)
    session.flush()

    with rejected("append-only"):
        session.execute(text("DELETE FROM audit_log WHERE id = :id"), {"id": entry.id})


def test_ledger_movements_have_the_right_shape(session, org, make_request, rejected):
    request = make_request(MONDAY)

    # A reservation that also changes used days is not a reservation.
    with rejected("ck_leave_ledger_movement_shape"):
        session.add(
            _ledger(
                org,
                movement="RESERVE",
                leave_request_id=request.id,
                pending_delta=Decimal("1"),
                used_delta=Decimal("1"),
            )
        )
    # Request movements must say which request they belong to.
    with rejected("ck_leave_ledger_request_movements_have_request"):
        session.add(_ledger(org, movement="RESERVE", pending_delta=Decimal("1")))

    session.add(
        _ledger(org, movement="RESERVE", leave_request_id=request.id, pending_delta=Decimal("1"))
    )
    session.flush()


def test_ledger_rows_need_an_existing_balance(session, org, rejected):
    with rejected("fk_leave_ledger_balance_leave_balances"):
        session.add(_ledger(org, movement="ENTITLEMENT", entitled_delta=Decimal("6"), year=2030))


# Employees, users and tenants


def test_email_is_unique_per_tenant_ignoring_case(session, org, rejected):
    with rejected("uq_employees_tenant_id_lower_email"):
        session.add(
            Employee(tenant_id=org["tenant"].id, code="e9", name="Copy", email="ASHA@acme.dev")
        )

    other = Tenant(name="Other company")
    session.add(other)
    session.flush()
    session.add(Employee(tenant_id=other.id, code="e1", name="Asha", email="asha@acme.dev"))
    session.flush()


def test_manager_must_be_in_the_same_tenant(session, org, rejected):
    other = Tenant(name="Rival company")
    session.add(other)
    session.flush()

    with rejected("fk_employees_tenant_id_manager_id_employees"):
        session.add(
            Employee(
                tenant_id=other.id,
                code="x1",
                name="Spy",
                email="spy@rival.dev",
                manager_id=org["ravi"].id,
            )
        )


def test_employee_cannot_manage_themselves(session, org, rejected):
    with rejected("ck_employees_not_own_manager"):
        org["ravi"].manager_id = org["ravi"].id


def test_email_format_is_checked(session, org, rejected):
    with rejected("ck_employees_email_format"):
        session.add(Employee(tenant_id=org["tenant"].id, code="e8", name="Bad", email="nope"))


def test_users_store_only_argon2id_hashes(session, org, rejected):
    with rejected("ck_users_argon2id_hash"):
        session.add(
            User(employee_id=org["asha"].id, tenant_id=org["tenant"].id, password_hash="secret1")
        )

    session.add(
        User(
            employee_id=org["asha"].id,
            tenant_id=org["tenant"].id,
            password_hash="$argon2id$v=19$m=65536,t=3,p=4$c2FsdA$aGFzaA",
        )
    )
    session.flush()
