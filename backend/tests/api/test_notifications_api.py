import asyncio

from leavedesk.api.stream import KEEP_ALIVE, event_stream, format_event
from leavedesk.domain.notifications import Notification, NotificationEvent
from tests.api.conftest import error_code

# API-21 Notifications are queued in the background


def test_submit_queues_notifications_for_employee_and_manager(apply, notifier):
    apply("e1")

    sent = [(n.recipient, n.event.value) for n in notifier.sent]
    assert sent == [("e1", "SUBMITTED"), ("m1", "SUBMITTED")]


def test_approve_reject_and_cancel_queue_notifications(client, auth, apply, notifier):
    first = apply("e1", start="2026-11-16", end="2026-11-16").json()["id"]
    second = apply("e1", start="2026-11-17", end="2026-11-17").json()["id"]
    third = apply("e1", start="2026-11-18", end="2026-11-18").json()["id"]
    notifier.sent.clear()

    client.post(f"/leave-requests/{first}/approve", headers=auth("m1"))
    client.post(
        f"/leave-requests/{second}/reject", json={"reason": "Busy week"}, headers=auth("m1")
    )
    client.delete(f"/leave-requests/{third}", headers=auth("e1"))

    events = [(n.recipient, n.event.value) for n in notifier.sent]
    assert events == [
        ("e1", "APPROVED"),
        ("e1", "REJECTED"),
        ("e1", "CANCELLED"),
        ("m1", "CANCELLED"),
    ]


def test_failed_action_queues_nothing(apply, notifier):
    apply("e1", reason="no")

    assert notifier.sent == []


def test_service_itself_sends_nothing(state):
    """The API sends notifications from BackgroundTasks, not inside the service."""
    assert state.service.notifiers == []


def test_broken_notifier_does_not_break_the_request(state, client, apply):
    class Broken:
        async def send(self, notification):
            raise ConnectionError("mail server down")

    state.extra_notifiers.insert(0, Broken())

    response = apply("e1")

    assert response.status_code == 201
    assert state.inbox.unread_count("e1") == 1


# API-22 List notifications


def test_unread_filter_newest_first(client, auth, apply):
    apply("e1", start="2026-11-16", end="2026-11-16")
    apply("e1", start="2026-11-17", end="2026-11-17")
    first = client.get("/notifications", headers=auth("e1")).json()["items"][-1]
    client.post(f"/notifications/{first['id']}/read", headers=auth("e1"))

    body = client.get("/notifications?unread=true", headers=auth("e1")).json()

    assert body["total"] == 1
    assert all(not n["read"] for n in body["items"])
    assert "2026-11-17" in body["items"][0]["message"]


def test_unread_notifications_come_first(client, auth, apply):
    apply("e1", start="2026-11-16", end="2026-11-16")
    apply("e1", start="2026-11-17", end="2026-11-17")
    newest = client.get("/notifications", headers=auth("e1")).json()["items"][0]
    client.post(f"/notifications/{newest['id']}/read", headers=auth("e1"))

    items = client.get("/notifications", headers=auth("e1")).json()["items"]

    assert [n["read"] for n in items] == [False, True]


def test_each_user_sees_only_their_notifications(client, auth, apply):
    apply("e1")

    items = client.get("/notifications", headers=auth("e2")).json()["items"]

    assert items == []


# API-23 Mark one read


def test_mark_own_notification_read(client, auth, apply):
    apply("e1")
    notification_id = client.get("/notifications", headers=auth("e1")).json()["items"][0]["id"]

    response = client.post(f"/notifications/{notification_id}/read", headers=auth("e1"))

    assert response.status_code == 200
    assert response.json()["read"] is True


def test_mark_someone_elses_notification_is_404(client, auth, apply):
    apply("e1")
    notification_id = client.get("/notifications", headers=auth("m1")).json()["items"][0]["id"]

    response = client.post(f"/notifications/{notification_id}/read", headers=auth("e1"))

    assert response.status_code == 404
    assert error_code(response) == "NOT_FOUND"


# API-24 Mark all read


def test_read_all(client, auth, apply):
    apply("e1", start="2026-11-16", end="2026-11-16")
    apply("e1", start="2026-11-17", end="2026-11-17")

    response = client.post("/notifications/read-all", headers=auth("e1"))

    assert response.json() == {"updated": 2}
    unread = client.get("/notifications?unread=true", headers=auth("e1")).json()
    assert unread["total"] == 0
    assert client.post("/notifications/read-all", headers=auth("e1")).json() == {"updated": 0}


# API-25 Live stream


def test_submitted_request_reaches_the_managers_stream(state, apply):
    stream = state.broker.subscribe("m1")

    apply("e1")

    event = format_event(stream.get_nowait())
    assert event.startswith("id: ")
    assert "event: notification\n" in event
    assert '"event": "SUBMITTED"' in event
    assert "Asha Rao requested leave" in event


def test_stream_only_gets_the_subscribers_notifications(state, apply):
    stream = state.broker.subscribe("e3")

    apply("e1")

    assert stream.empty()


def test_event_stream_yields_events_then_keep_alive():
    async def scenario():
        queue = asyncio.Queue()
        queue.put_nowait(Notification("e1", NotificationEvent.APPROVED, "Approved"))
        connected = iter([False, False, True])

        async def is_disconnected():
            return next(connected)

        return [chunk async for chunk in event_stream(queue, 0.01, is_disconnected)]

    chunks = asyncio.run(scenario())

    assert chunks[0].startswith("id: ") and '"event": "APPROVED"' in chunks[0]
    assert chunks[1] == KEEP_ALIVE


def test_stream_needs_a_valid_token(client):
    assert client.get("/notifications/stream").status_code == 401
    assert client.get("/notifications/stream?access_token=nonsense").status_code == 401


def test_unsubscribe_cleans_up(state):
    queue = state.broker.subscribe("e1")

    state.broker.unsubscribe("e1", queue)

    assert state.broker.subscriber_count("e1") == 0
