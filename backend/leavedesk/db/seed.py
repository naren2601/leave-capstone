"""Demo data for one tenant: leave types, people and this year's balances.

Run it after the migrations, from the backend folder:

    alembic upgrade head
    python -m leavedesk.db.seed

Seeding is safe to repeat: a tenant that already exists is left as it is.
"""

import os
from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from leavedesk.db import models as db
from leavedesk.domain.models import Employee, Manager
from leavedesk.domain.policies import default_policies

DEFAULT_TENANT = "LeaveDesk Demo"

# Earliest start, in days from today, for each leave type (matches policies.py):
# annual needs 3 days' notice, sick can be backdated a week, casual from today.
START_OFFSETS = {"ANNUAL": 3, "SICK": -7, "CASUAL": 0}
MAX_DAYS_PER_REQUEST = {"CASUAL": Decimal("2")}
NAMES = {"ANNUAL": "Annual leave", "SICK": "Sick leave", "CASUAL": "Casual leave"}


def find_tenant(session: Session, name: str) -> int:
    tenant_id = session.scalar(select(db.Tenant.id).where(db.Tenant.name == name))
    if tenant_id is None:
        raise RuntimeError(f"tenant {name!r} does not exist; run python -m leavedesk.db.seed")
    return tenant_id


def seed_tenant(session: Session, name: str, people: list[Employee], year: int) -> int:
    """Create the tenant if it is missing, and return its id."""
    existing = session.scalar(select(db.Tenant.id).where(db.Tenant.name == name))
    if existing is not None:
        return existing

    tenant = db.Tenant(name=name)
    session.add(tenant)
    session.flush()

    leave_types = []
    for leave_type, policy in default_policies().items():
        code = leave_type.value
        row = db.LeaveType(
            tenant_id=tenant.id,
            code=code,
            name=NAMES[code],
            days_per_year=Decimal(str(policy.days_per_year)),
            min_start_offset_days=START_OFFSETS[code],
            max_days_per_request=MAX_DAYS_PER_REQUEST.get(code),
        )
        session.add(row)
        leave_types.append(row)

    # Managers first, so employees can point at them.
    rows_by_code: dict[str, db.Employee] = {}
    for person in sorted(people, key=lambda p: p.manager_id is not None):
        row = db.Employee(
            tenant_id=tenant.id,
            code=person.id,
            name=person.name,
            email=person.email,
            is_manager=isinstance(person, Manager),
            manager_id=rows_by_code[person.manager_id].id if person.manager_id else None,
        )
        session.add(row)
        session.flush()
        rows_by_code[person.id] = row

    # This year's balances, each opened with an ENTITLEMENT ledger row.
    for employee in rows_by_code.values():
        for leave_type in leave_types:
            session.add(
                db.LeaveBalance(
                    tenant_id=tenant.id,
                    employee_id=employee.id,
                    leave_type_id=leave_type.id,
                    year=year,
                    entitled=leave_type.days_per_year,
                )
            )
            session.flush()
            session.add(
                db.LeaveLedger(
                    tenant_id=tenant.id,
                    employee_id=employee.id,
                    leave_type_id=leave_type.id,
                    year=year,
                    movement="ENTITLEMENT",
                    entitled_delta=leave_type.days_per_year,
                )
            )
    session.flush()
    return tenant.id


def seed_users(session: Session, tenant_id: int, password_hash: str) -> int:
    """Give every employee of the tenant without a login one, with this password hash.

    Existing logins (and their lockout counters) are left alone. Returns how many were added.
    """
    missing = session.scalars(
        select(db.Employee.id).where(
            db.Employee.tenant_id == tenant_id,
            ~select(db.User.employee_id)
            .where(db.User.tenant_id == tenant_id, db.User.employee_id == db.Employee.id)
            .exists(),
        )
    ).all()
    session.add_all(
        db.User(tenant_id=tenant_id, employee_id=employee_id, password_hash=password_hash)
        for employee_id in missing
    )
    session.flush()
    return len(missing)


def main() -> None:
    from leavedesk.api.state import SEED_PEOPLE

    url = os.environ.get("LEAVEDESK_DATABASE_URL")
    if not url:
        raise SystemExit("Set LEAVEDESK_DATABASE_URL first (see .env.example).")
    tenant = os.environ.get("LEAVEDESK_TENANT_NAME", DEFAULT_TENANT)
    engine = create_engine(url)
    password = os.environ.get("LEAVEDESK_SEED_PASSWORD")
    with Session(engine) as session, session.begin():
        tenant_id = seed_tenant(session, tenant, SEED_PEOPLE, date.today().year)
        if password:
            from leavedesk.api.auth import hash_password

            seed_users(session, tenant_id, hash_password(password))
    engine.dispose()
    print(f"Tenant {tenant!r} is ready (id {tenant_id}).")


if __name__ == "__main__":
    main()
