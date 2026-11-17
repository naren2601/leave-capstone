"""Step 4 through the API, on PostgreSQL only.

The Day 2 notification tests already run on both backends. These check what only
a database gives: notifications survive a restart, a failed change sends nothing,
and the running server delivers to SSE streams from LISTEN.
"""

import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from leavedesk.api.main import create_app
from leavedesk.db import models as db
from tests.api.conftest import TODAY
from tests.postgres import requires_postgres

pytestmark = [requires_postgres, pytest.mark.parametrize("backend", ["postgres"], indirect=True)]


def outbox_statuses(state) -> list[str]:
    with state.session_factory() as session:
        return list(
            session.scalars(
                select(db.NotificationOutbox.status)
                .where(db.NotificationOutbox.tenant_id == state.tenant_id)
                .order_by(db.NotificationOutbox.id)
            )
        )


def test_notifications_survive_a_restart(settings, apply, client, auth):
    apply("e1")

    restarted = create_app(settings, today=lambda: TODAY)
    try:
        items = TestClient(restarted).get("/notifications", headers=auth("m1")).json()["items"]
    finally:
        restarted.state.leavedesk.close()

    assert [n["event"] for n in items] == ["SUBMITTED"]
    assert "Asha Rao requested leave" in items[0]["message"]


def test_emails_go_out_through_the_outbox(state, apply, notifier):
    apply("e1")

    assert outbox_statuses(state) == ["SENT", "SENT"]
    assert [n.recipient for n in state.email.sent] == ["e1", "m1"]


def test_a_failed_change_saves_no_notification(state, apply):
    apply("e1", reason="no")  # fails validation

    assert outbox_statuses(state) == []
    assert state.inbox.unread_count("e1") == 0


def test_a_broken_mail_server_leaves_the_email_pending(state, apply):
    class Broken:
        async def send(self, notification):
            raise ConnectionError("mail server down")

    state.extra_notifiers.insert(0, Broken())

    response = apply("e1")

    assert response.status_code == 201
    assert outbox_statuses(state) == ["PENDING", "PENDING"]  # retried by the worker later
    assert state.inbox.unread_count("e1") == 1  # in-app still works


def test_unknown_notification_id_is_404(client, auth):
    for bad_id in ("not-a-uuid", "0190a6f0-0000-7000-8000-000000000000"):
        response = client.post(f"/notifications/{bad_id}/read", headers=auth("e1"))
        assert response.status_code == 404


def test_running_server_pushes_from_another_process_to_the_stream(app, settings, auth):
    """Two API processes: a request saved by one reaches a stream open on the other."""
    other = create_app(settings, today=lambda: TODAY)
    try:
        with TestClient(app) as server:  # `with` runs startup: LISTEN and the worker
            state = app.state.leavedesk
            assert state.listener.listening.wait(timeout=5)
            stream = server.portal.call(_subscribe, state, "m1")

            body = {
                "leave_type": "ANNUAL",
                "start_date": "2026-11-16",
                "end_date": "2026-11-18",
                "reason": "Family trip",
            }
            saved = TestClient(other).post("/leave-requests", json=body, headers=auth("e1"))
            assert saved.status_code == 201

            deadline = time.monotonic() + 5
            while stream.empty() and time.monotonic() < deadline:
                time.sleep(0.05)
            notification = stream.get_nowait()
    finally:
        other.state.leavedesk.close()

    assert notification.event.value == "SUBMITTED"
    assert notification.recipient == "m1"


async def _subscribe(state, recipient):
    return state.broker.subscribe(recipient)
