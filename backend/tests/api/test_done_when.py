"""Day 3 "done when": the whole system keeps its promises under failure and load.

PostgreSQL only. The checklist mapping each Day 3 requirement to its tests is in
SCHEMA.md, section 9.
"""

import threading

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from leavedesk.db.notifications import PostgresInbox
from tests.postgres import requires_postgres

pytestmark = [requires_postgres, pytest.mark.parametrize("backend", ["postgres"], indirect=True)]

BODY = {
    "leave_type": "ANNUAL",
    "start_date": "2026-11-16",
    "end_date": "2026-11-18",
    "reason": "Family trip",
}


COUNTS = {
    "requests": "SELECT count(*) FROM leave_requests WHERE tenant_id = :t",
    "reserve_rows": "SELECT count(*) FROM leave_ledger WHERE tenant_id = :t"
    " AND movement = 'RESERVE'",
    "notifications": "SELECT count(*) FROM notifications WHERE tenant_id = :t",
    "outbox": "SELECT count(*) FROM notification_outbox WHERE tenant_id = :t",
    "idempotency_keys": "SELECT count(*) FROM idempotency_keys WHERE tenant_id = :t",
    "pending_days": "SELECT coalesce(sum(pending), 0) FROM leave_balances WHERE tenant_id = :t",
}


def counts(state) -> dict[str, int]:
    """How many rows of each kind this test's tenant has."""
    with state.session_factory() as session:
        return {
            name: session.execute(text(sql), {"t": state.tenant_id}).scalar()
            for name, sql in COUNTS.items()
        }


def test_a_failure_at_the_last_moment_undoes_everything(app, state, auth, monkeypatch):
    """The request, its ledger row, the balance, the notifications, the outbox and
    the idempotency key are one transaction: a crash after all of them were written
    leaves no trace of any of them."""
    save = PostgresInbox.save

    def save_then_crash(self, notifications):
        save(self, notifications)  # everything is written by now...
        raise RuntimeError("the server crashed before COMMIT")  # ...and then this

    monkeypatch.setattr(PostgresInbox, "save", save_then_crash)
    client = TestClient(app, raise_server_exceptions=False)
    headers = auth("e1") | {"Idempotency-Key": "crash-test"}

    crashed = client.post("/leave-requests", json=BODY, headers=headers)

    assert crashed.status_code == 500
    assert counts(state) == {
        "requests": 0,
        "reserve_rows": 0,
        "notifications": 0,
        "outbox": 0,
        "idempotency_keys": 0,
        "pending_days": 0,
    }

    # Once the fault is gone, the client's retry with the same key works normally.
    monkeypatch.setattr(PostgresInbox, "save", save)
    retry = client.post("/leave-requests", json=BODY, headers=headers)
    assert retry.status_code == 201
    assert counts(state)["requests"] == 1


def test_many_people_at_once_never_break_a_rule(app, state, auth):
    """12 applications at the same moment, then 9 decisions at the same moment.

    Afterwards every rule must still hold: one active request per person for the
    same dates, each request decided once, and every balance equal to its ledger.
    """
    people = ["e1", "e2", "e3"]
    applied = run_together(
        [
            lambda c, p=p: c.post("/leave-requests", json=BODY, headers=auth(p))
            for p in people
            for _ in range(4)
        ],
        app,
    )
    created = [r.json() for r in applied if r.status_code == 201]

    assert sorted(r.status_code for r in applied) == [201] * 3 + [409] * 9
    assert sorted(r["employee_id"] for r in created) == people

    ids = {r["employee_id"]: r["id"] for r in created}
    manager = {"e1": "m1", "e2": "m1", "e3": "m2"}

    def approve(c, p):
        return c.post(f"/leave-requests/{ids[p]}/approve", headers=auth(manager[p]))

    def reject(c, p):
        reason = {"reason": "Team is short that week"}
        return c.post(f"/leave-requests/{ids[p]}/reject", json=reason, headers=auth(manager[p]))

    def cancel(c, p):
        return c.delete(f"/leave-requests/{ids[p]}", headers=auth(p))

    decided = run_together(
        [lambda c, p=p, act=act: act(c, p) for p in people for act in (approve, reject, cancel)],
        app,
    )

    # Exactly one decision per request wins; the others see it is no longer pending.
    assert sorted(r.status_code for r in decided) == [200] * 3 + [409] * 6
    assert_every_balance_matches_its_ledger_and_requests(state)


def run_together(calls, app):
    start = threading.Barrier(len(calls))
    results = [None] * len(calls)

    def run(index, call):
        client = TestClient(app)
        start.wait()
        results[index] = call(client)

    threads = [threading.Thread(target=run, args=(i, c)) for i, c in enumerate(calls)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    return results


def assert_every_balance_matches_its_ledger_and_requests(state):
    """The ledger is the truth: each balance equals the sum of its movements, and
    pending and used days equal the days of PENDING and APPROVED requests."""
    with state.session_factory() as session:
        mismatches = session.execute(
            text(
                """
                SELECT b.employee_id, b.leave_type_id,
                       b.entitled, b.used, b.pending,
                       l.entitled AS l_entitled, l.used AS l_used, l.pending AS l_pending,
                       coalesce(r.used, 0) AS r_used, coalesce(r.pending, 0) AS r_pending
                FROM leave_balances b
                JOIN LATERAL (
                    SELECT sum(entitled_delta) AS entitled, sum(used_delta) AS used,
                           sum(pending_delta) AS pending
                    FROM leave_ledger x
                    WHERE (x.tenant_id, x.employee_id, x.leave_type_id, x.year)
                        = (b.tenant_id, b.employee_id, b.leave_type_id, b.year)
                ) l ON true
                LEFT JOIN LATERAL (
                    SELECT sum(days) FILTER (WHERE status = 'APPROVED') AS used,
                           sum(days) FILTER (WHERE status = 'PENDING') AS pending
                    FROM leave_requests q
                    WHERE (q.tenant_id, q.employee_id, q.leave_type_id)
                        = (b.tenant_id, b.employee_id, b.leave_type_id)
                ) r ON true
                WHERE b.tenant_id = :t
                  AND (b.entitled, b.used, b.pending) IS DISTINCT FROM
                      (l.entitled, l.used, l.pending)
                   OR (b.tenant_id = :t
                       AND (b.used, b.pending) IS DISTINCT FROM
                           (coalesce(r.used, 0), coalesce(r.pending, 0)))
                """
            ),
            {"t": state.tenant_id},
        ).all()
        balances = session.execute(
            text("SELECT count(*) FROM leave_balances WHERE tenant_id = :t"),
            {"t": state.tenant_id},
        ).scalar()

    assert balances == 15  # 5 people x 3 leave types
    assert mismatches == []
