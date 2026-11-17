"""Day 3, Part C: safe changes. Versions, If-Match, Idempotency-Key and concurrency.

Most tests run on both backends. The concurrency tests need real transactions and
row locks, so they run on PostgreSQL only.
"""

import threading

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from leavedesk.db import models as db
from tests.api.conftest import error_code
from tests.postgres import requires_postgres

BODY = {
    "leave_type": "ANNUAL",
    "start_date": "2026-11-16",
    "end_date": "2026-11-18",
    "reason": "Family trip",
}


def approve(client, auth, request_id, **headers):
    return client.post(f"/leave-requests/{request_id}/approve", headers=auth("m1") | headers)


# Versions and If-Match (optimistic locking)


def test_every_change_gets_a_new_version(client, auth):
    created = client.post("/leave-requests", json=BODY, headers=auth("e1"))
    request_id = created.json()["id"]

    approved = approve(client, auth, request_id)
    fetched = client.get(f"/leave-requests/{request_id}", headers=auth("e1"))

    assert created.json()["version"] == 1
    assert created.headers["etag"] == '"1"'
    assert approved.json()["version"] == 2
    assert fetched.headers["etag"] == '"2"'


@pytest.mark.parametrize("if_match", ["1", '"1"', 'W/"1"'])
def test_matching_version_is_accepted(client, auth, if_match):
    request_id = client.post("/leave-requests", json=BODY, headers=auth("e1")).json()["id"]

    response = approve(client, auth, request_id, **{"If-Match": if_match})

    assert response.status_code == 200


def test_stale_version_is_rejected_with_409(client, auth):
    request_id = client.post("/leave-requests", json=BODY, headers=auth("e1")).json()["id"]
    approve(client, auth, request_id)  # version 1 -> 2

    stale = client.post(
        f"/leave-requests/{request_id}/reject",
        json={"reason": "Too late"},
        headers=auth("m1") | {"If-Match": "1"},
    )

    assert stale.status_code == 409
    assert error_code(stale) == "VERSION_CONFLICT"
    status = client.get(f"/leave-requests/{request_id}", headers=auth("e1")).json()["status"]
    assert status == "APPROVED"


def test_stale_cancel_is_rejected_with_409(client, auth):
    request_id = client.post("/leave-requests", json=BODY, headers=auth("e1")).json()["id"]

    response = client.delete(
        f"/leave-requests/{request_id}", headers=auth("e1") | {"If-Match": "7"}
    )

    assert response.status_code == 409
    assert error_code(response) == "VERSION_CONFLICT"


def test_if_match_must_be_a_number(client, auth):
    request_id = client.post("/leave-requests", json=BODY, headers=auth("e1")).json()["id"]

    response = approve(client, auth, request_id, **{"If-Match": "latest"})

    assert response.status_code == 422


def test_without_if_match_changes_still_work(client, auth):
    request_id = client.post("/leave-requests", json=BODY, headers=auth("e1")).json()["id"]

    assert approve(client, auth, request_id).status_code == 200


# Idempotency-Key


def test_retry_with_the_same_key_returns_the_first_result(client, auth, notifier):
    headers = auth("e1") | {"Idempotency-Key": "apply-123"}

    first = client.post("/leave-requests", json=BODY, headers=headers)
    retry = client.post("/leave-requests", json=BODY, headers=headers)

    assert first.status_code == retry.status_code == 201
    assert retry.json() == first.json()
    assert retry.headers["idempotent-replayed"] == "true"
    assert client.get("/leave-requests", headers=auth("e1")).json()["total"] == 1
    assert len(notifier.sent) == 2  # employee and manager, once only
    balance = client.get("/employees/e1/balance", headers=auth("e1")).json()
    assert next(b for b in balance if b["leave_type"] == "ANNUAL")["pending"] == 3


def test_same_key_with_a_different_request_is_refused(client, auth):
    headers = auth("e1") | {"Idempotency-Key": "apply-123"}
    client.post("/leave-requests", json=BODY, headers=headers)

    response = client.post(
        "/leave-requests", json=BODY | {"reason": "Something else"}, headers=headers
    )

    assert response.status_code == 422


def test_keys_belong_to_one_employee(client, auth):
    key = {"Idempotency-Key": "same-key"}

    asha = client.post("/leave-requests", json=BODY, headers=auth("e1") | key)
    kiran = client.post("/leave-requests", json=BODY, headers=auth("e2") | key)

    assert asha.status_code == kiran.status_code == 201
    assert asha.json()["id"] != kiran.json()["id"]


def test_a_failed_request_does_not_use_up_its_key(client, auth):
    headers = auth("e1") | {"Idempotency-Key": "try-again"}
    bad = client.post("/leave-requests", json=BODY | {"end_date": "2026-11-10"}, headers=headers)

    good = client.post("/leave-requests", json=BODY, headers=headers)

    assert bad.status_code == 422
    assert good.status_code == 201


def test_empty_key_is_rejected(client, auth):
    response = client.post(
        "/leave-requests", json=BODY, headers=auth("e1") | {"Idempotency-Key": ""}
    )

    assert response.status_code == 422


# Concurrency: real transactions at the same moment (PostgreSQL only)


def at_the_same_time(app, *calls):
    """Run each call(client) in its own thread, all starting together."""
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
        thread.join(timeout=30)
    return results


def ledger_count(state, movement):
    with state.session_factory() as session:
        return session.scalar(
            select(func.count()).where(
                db.LeaveLedger.tenant_id == state.tenant_id, db.LeaveLedger.movement == movement
            )
        )


@requires_postgres
@pytest.mark.parametrize("backend", ["postgres"], indirect=True)
def test_two_approvals_at_once_deduct_the_days_once(app, client, auth, state):
    request_id = client.post("/leave-requests", json=BODY, headers=auth("e1")).json()["id"]

    def approve_it(c):
        return approve(c, auth, request_id)

    results = at_the_same_time(app, approve_it, approve_it)

    assert sorted(r.status_code for r in results) == [200, 409]
    balance = client.get("/employees/e1/balance", headers=auth("e1")).json()
    annual = next(b for b in balance if b["leave_type"] == "ANNUAL")
    assert (annual["used"], annual["pending"], annual["available"]) == (3, 0, 15)
    assert ledger_count(state, "CONSUME") == 1


@requires_postgres
@pytest.mark.parametrize("backend", ["postgres"], indirect=True)
def test_two_overlapping_requests_at_once_only_one_is_saved(app, client, auth, state):
    def apply_it(c):
        return c.post("/leave-requests", json=BODY, headers=auth("e1"))

    results = at_the_same_time(app, apply_it, apply_it)

    assert sorted(r.status_code for r in results) == [201, 409]
    assert client.get("/leave-requests", headers=auth("e1")).json()["total"] == 1
    assert ledger_count(state, "RESERVE") == 1


@requires_postgres
@pytest.mark.parametrize("backend", ["postgres"], indirect=True)
def test_the_same_retry_at_once_creates_one_request(app, client, auth):
    def apply_it(c):
        return c.post("/leave-requests", json=BODY, headers=auth("e1") | {"Idempotency-Key": "k1"})

    results = at_the_same_time(app, apply_it, apply_it, apply_it)

    assert [r.status_code for r in results] == [201, 201, 201]
    assert len({r.json()["id"] for r in results}) == 1
    assert client.get("/leave-requests", headers=auth("e1")).json()["total"] == 1
