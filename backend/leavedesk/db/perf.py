"""Performance check (Day 3, step 6): load 100,000 leave requests, then EXPLAIN.

From the backend folder, against a database you can throw away:

    python -m leavedesk.db.perf seed       # once: 10,000 employees, 100,000 requests
    python -m leavedesk.db.perf explain    # plans and timings of the API's queries

Uses LEAVEDESK_MIGRATION_DATABASE_URL (or LEAVEDESK_DATABASE_URL). The data goes into
its own tenant, "Perf", so it never mixes with the demo data. The queries explained
are built by the same repository code the API uses, so the plans are the real ones.
"""

import os
import sys
import time
from datetime import date

from sqlalchemy import Select, create_engine, func, select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from leavedesk.db import models as db
from leavedesk.db.repository import PostgresLeaveRepository, manager_id_of
from leavedesk.domain.models import LeaveStatus

TENANT = "Perf"
MANAGERS = 100
REPORTS_PER_MANAGER = 99  # 100 x (1 + 99) = 10,000 employees
REQUESTS_PER_EMPLOYEE = 10  # 10,000 x 10 = 100,000 requests
YEAR = 2026

# One INSERT ... SELECT per table: generate_series builds every row inside PostgreSQL,
# which takes seconds instead of the minutes 100,000 single INSERTs would take.
# mod(a, b) rather than a % b: the pg8000 driver reads % as a parameter marker.
# Numbers are CAST because pg8000 sends parameters without a type.
SEED_SQL = [
    "INSERT INTO tenants (name) VALUES (:tenant)",
    """
    INSERT INTO leave_types (tenant_id, code, name, days_per_year, min_start_offset_days)
    SELECT t.id, v.code, v.name, v.days, v.offset_days
    FROM tenants t,
         (VALUES ('ANNUAL', 'Annual leave', 18, 3), ('SICK', 'Sick leave', 12, -7),
                 ('CASUAL', 'Casual leave', 6, 0)) AS v(code, name, days, offset_days)
    WHERE t.name = :tenant
    """,
    # Managers m1..m100, then employees e1..e9900, each reporting to one manager.
    """
    INSERT INTO employees (tenant_id, code, name, email, is_manager)
    SELECT t.id, 'm' || g, 'Manager ' || g, 'm' || g || '@perf.leavedesk.dev', true
    FROM tenants t, generate_series(1, CAST(:managers AS integer)) g
    WHERE t.name = :tenant
    """,
    """
    INSERT INTO employees (tenant_id, code, name, email, manager_id)
    SELECT t.id, 'e' || g,
           (ARRAY['Asha','Kiran','Sam','Ravi','Meena','Arjun','Divya','Farah','Gopal',
                  'Hema'])[1 + mod(g, 10)] || ' ' || (ARRAY['Rao','Das','Joseph','Kumar','Iyer',
                  'Nair','Shah','Khan','Menon','Pillai'])[1 + mod(g / 10, 10)] || ' ' || g,
           'e' || g || '@perf.leavedesk.dev', m.id
    FROM tenants t
    CROSS JOIN generate_series(1, CAST(:managers AS integer) * CAST(:reports AS integer)) g
    JOIN employees m ON m.tenant_id = t.id
     AND m.code = 'm' || (1 + (g - 1) / CAST(:reports AS integer))
    WHERE t.name = :tenant
    """,
    # 10 requests per employee, two weeks apart, so none overlap. About 10% PENDING,
    # 70% APPROVED, 15% REJECTED, 5% CANCELLED, like a real year.
    """
    INSERT INTO leave_requests
        (id, tenant_id, employee_id, leave_type_id, start_date, end_date, reason, status, days)
    SELECT gen_random_uuid(), e.tenant_id, e.id, lt.id,
           date '2026-01-05' + (n * 14 + mod(e.id, 5))::int,
           date '2026-01-05' + (n * 14 + mod(e.id, 5) + mod(e.id + n, 3))::int,
           'Generated for the performance check',
           CASE WHEN mod(e.id + n, 20) IN (0, 1) THEN 'PENDING'
                WHEN mod(e.id + n, 20) IN (2, 3, 4) THEN 'REJECTED'
                WHEN mod(e.id + n, 20) = 5 THEN 'CANCELLED'
                ELSE 'APPROVED' END,
           1 + mod(e.id + n, 3)
    FROM employees e
    JOIN tenants t ON t.id = e.tenant_id AND t.name = :tenant
    CROSS JOIN generate_series(0, CAST(:per_employee AS integer) - 1) n
    JOIN leave_types lt ON lt.tenant_id = e.tenant_id
     AND lt.code = (ARRAY['ANNUAL', 'SICK', 'CASUAL'])[1 + mod(e.id + n, 3)]
    """,
    # Fresh statistics, so the planner knows how big the tables now are.
    "ANALYZE employees",
    "ANALYZE leave_requests",
]


def seed(
    session: Session,
    tenant: str = TENANT,
    managers: int = MANAGERS,
    reports: int = REPORTS_PER_MANAGER,
    per_employee: int = REQUESTS_PER_EMPLOYEE,
) -> None:
    """Load the generated company. Tests call it with smaller numbers."""
    if session.scalar(select(db.Tenant.id).where(db.Tenant.name == tenant)) is not None:
        print(f"The {tenant} tenant already exists; nothing to do.")
        return
    params = {
        "tenant": tenant,
        "managers": managers,
        "reports": reports,
        "per_employee": per_employee,
    }
    started = time.perf_counter()
    for sql in SEED_SQL:
        session.execute(text(sql), params)
    count = session.scalar(select(func.count()).select_from(db.LeaveRequest))
    print(f"Seeded in {time.perf_counter() - started:.1f} s; leave_requests now has {count} rows.")


def queries(session: Session) -> dict[str, Select]:
    """The API's hottest queries, built by the repository itself."""
    tenant_id = session.scalar(select(db.Tenant.id).where(db.Tenant.name == TENANT))
    repo = PostgresLeaveRepository(session, tenant_id, YEAR)
    team = {e.id for e in repo.direct_reports("m42")}
    pending = repo.request_list_query(team, LeaveStatus.PENDING)
    history = repo.request_list_query(team, None)
    # The last row of the page before page 40, for the keyset version of page 40.
    page_39_last = session.execute(
        repo.request_page_query(history, False, 1, offset=779).with_only_columns(
            db.LeaveRequest.start_date, db.LeaveRequest.id
        )
    ).one()
    return {
        "1. Manager m42's pending queue (first page)": repo.request_page_query(
            pending, descending=False, limit=21
        ),
        "2. One employee's history (newest first)": repo.request_page_query(
            repo.request_list_query({"e4100"}, None), descending=True, limit=21
        ),
        "3a. Team history, page 40 with OFFSET 780": repo.request_page_query(
            history, descending=False, limit=21, offset=780
        ),
        "3b. Team history, page 40 with a keyset cursor": repo.request_page_query(
            history,
            descending=False,
            limit=21,
            after=(page_39_last.start_date, str(page_39_last.id)),
        ),
        "4. Find a manager's direct reports": select(db.Employee).where(
            db.Employee.tenant_id == tenant_id,
            db.Employee.manager_id == manager_id_of(tenant_id, "m42"),
        ),
        "5. Search employees by name: ?q=meena kh": select(db.Employee)
        .where(db.Employee.tenant_id == tenant_id, db.Employee.name.ilike("%meena kh%"))
        .order_by(db.Employee.name)
        .limit(20),
    }


def explain(session: Session) -> None:
    for title, query in queries(session).items():
        sql = str(
            query.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
        )
        # The values inside are this file's own constants, never user input.
        # Sent straight to the driver, which turns the compiled %% back into %.
        explained = "EXPLAIN (ANALYZE, BUFFERS) " + sql
        plan = session.connection().exec_driver_sql(explained).scalars().all()
        print(f"\n## {title}\n")
        print("\n".join(plan))


def main() -> None:
    url = os.environ.get("LEAVEDESK_MIGRATION_DATABASE_URL") or os.environ.get(
        "LEAVEDESK_DATABASE_URL"
    )
    if not url or len(sys.argv) != 2 or sys.argv[1] not in ("seed", "explain"):
        raise SystemExit("usage: python -m leavedesk.db.perf seed|explain  (set the URL first)")
    engine = create_engine(url)
    with Session(engine) as session, session.begin():
        seed(session) if sys.argv[1] == "seed" else explain(session)
    engine.dispose()


if __name__ == "__main__":
    print(f"LeaveDesk performance check, {date.today()}")
    main()
