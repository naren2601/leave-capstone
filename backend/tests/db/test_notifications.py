"""Step 4: notifications in PostgreSQL.

- The outbox: notifications are saved in the same transaction as the change.
- pg_notify: listeners hear about a notification only after its transaction commits.
- The worker: FOR UPDATE SKIP LOCKED, retries, and giving up after too many failures.
"""

import asyncio
import json
import threading
import time
import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session, sessionmaker

from leavedesk.api.state import SEED_PEOPLE
from leavedesk.db import models as db
from leavedesk.db.notifications import (
    CHANNEL,
    NotificationListener,
    OutboxWorker,
    PostgresInbox,
)
from leavedesk.db.seed import seed_tenant
from leavedesk.domain.notifications import Notification, NotificationEvent, Notifier
from tests.postgres import requires_postgres

pytestmark = requires_postgres

TODAY = date(2026, 11, 9)


class Recorder(Notifier):
    def __init__(self, fail: bool = False) -> None:
        self.sent: list[Notification] = []
        self.fail = fail

    async def send(self, notification: Notification) -> None:
        if self.fail:
            raise ConnectionError("mail server down")
        self.sent.append(notification)


@pytest.fixture
def factory(engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False)


@pytest.fixture
def tenant_id(factory) -> int:
    with factory.begin() as session:
        return seed_tenant(session, f"Notify {uuid.uuid4().hex[:8]}", SEED_PEOPLE, TODAY.year)


def submitted(recipient: str = "e1", message: str = "Your leave was submitted.") -> Notification:
    return Notification(recipient, NotificationEvent.SUBMITTED, message)


def save(factory, tenant_id, *notifications: Notification) -> None:
    with factory.begin() as session:
        PostgresInbox(session, tenant_id).save(list(notifications))


def count(factory, model, tenant_id) -> int:
    with factory() as session:
        return session.scalar(
            select(func.count()).select_from(model).where(model.tenant_id == tenant_id)
        )


def outbox_rows(factory, tenant_id) -> list[db.NotificationOutbox]:
    with factory() as session:
        return list(
            session.scalars(
                select(db.NotificationOutbox)
                .where(db.NotificationOutbox.tenant_id == tenant_id)
                .order_by(db.NotificationOutbox.id)
            )
        )


# The outbox: saved with the change, or not at all


def test_saving_writes_a_notification_and_an_outbox_row(factory, tenant_id):
    notification = submitted()

    save(factory, tenant_id, notification)

    [row] = outbox_rows(factory, tenant_id)
    assert row.status == "PENDING" and row.attempts == 0
    assert str(row.notification_id) == notification.id  # the id is now the database id
    assert uuid.UUID(notification.id).version == 7


def test_a_rolled_back_change_leaves_no_notification_and_no_outbox_row(factory, tenant_id):
    with pytest.raises(RuntimeError), factory.begin() as session:
        PostgresInbox(session, tenant_id).save([submitted(), submitted("m1")])
        raise RuntimeError("the leave change failed after the notifications were added")

    assert count(factory, db.Notification, tenant_id) == 0
    assert count(factory, db.NotificationOutbox, tenant_id) == 0


# pg_notify: only after commit


@pytest.fixture
def listen(engine):
    """A raw LISTEN connection; returns a function that collects what arrived."""
    connection = engine.raw_connection()
    driver = connection.driver_connection
    driver.autocommit = True
    cursor = driver.cursor()
    cursor.execute(f"LISTEN {CHANNEL}")

    def received(wait: float = 0.3) -> list[dict]:
        time.sleep(wait)
        if hasattr(driver, "notifies"):  # psycopg
            return [json.loads(n.payload) for n in driver.notifies(timeout=0.2)]
        cursor.execute("SELECT 1")  # pg8000 reads notifications with any reply
        found = [json.loads(payload) for _pid, _channel, payload in driver.notifications]
        driver.notifications.clear()
        return found

    yield received
    connection.invalidate()


def test_listeners_hear_nothing_until_commit(factory, tenant_id, listen):
    notification = submitted()
    with factory.begin() as session:
        PostgresInbox(session, tenant_id).save([notification])
        before_commit = listen()

    after_commit = listen()

    assert before_commit == []
    assert after_commit == [{"id": notification.id, "tenant_id": tenant_id}]


def test_listeners_hear_nothing_after_a_rollback(factory, tenant_id, listen):
    with pytest.raises(RuntimeError), factory.begin() as session:
        PostgresInbox(session, tenant_id).save([submitted()])
        raise RuntimeError("rolled back")

    assert listen() == []


def test_the_listener_thread_receives_committed_notifications(engine, factory, tenant_id):
    heard: list[dict] = []
    arrived = threading.Event()

    def on_message(message):
        heard.append(message)
        arrived.set()

    listener = NotificationListener(engine, on_message, poll_seconds=0.1)
    listener.start()
    try:
        assert listener.listening.wait(timeout=5)
        notification = submitted()
        save(factory, tenant_id, notification)
        assert arrived.wait(timeout=5)
    finally:
        listener.stop()

    assert heard == [{"id": notification.id, "tenant_id": tenant_id}]


# The outbox worker


def worker(factory, tenant_id, recorder, **options) -> OutboxWorker:
    return OutboxWorker(factory, tenant_id, lambda: [recorder], **options)


def test_worker_sends_each_pending_row_once(factory, tenant_id):
    save(factory, tenant_id, submitted("e1", "first"), submitted("m1", "second"))
    recorder = Recorder()

    first_round = asyncio.run(worker(factory, tenant_id, recorder).run_once())
    second_round = asyncio.run(worker(factory, tenant_id, recorder).run_once())

    assert (first_round, second_round) == (2, 0)
    assert [(n.recipient, n.message) for n in recorder.sent] == [("e1", "first"), ("m1", "second")]
    assert all(row.status == "SENT" and row.sent_at for row in outbox_rows(factory, tenant_id))


def test_skip_locked_two_workers_never_take_the_same_row(factory, tenant_id):
    save(factory, tenant_id, submitted("e1", "first"), submitted("e2", "second"))
    a = worker(factory, tenant_id, Recorder(), batch_size=1)
    b = worker(factory, tenant_id, Recorder(), batch_size=1)

    with factory.begin() as session_a, factory.begin() as session_b:
        # Without SKIP LOCKED, B would wait for A forever; fail after 2 s instead.
        session_b.execute(text("SET LOCAL lock_timeout = '2s'"))
        claimed_by_a = a.claim(session_a)  # A holds the lock on the first row
        claimed_by_b = b.claim(session_b)  # B skips it instead of waiting

    assert [n.message for _, n in claimed_by_a] == ["first"]
    assert [n.message for _, n in claimed_by_b] == ["second"]


def test_a_failed_send_is_retried_later(factory, tenant_id):
    save(factory, tenant_id, submitted())
    broken = worker(factory, tenant_id, Recorder(fail=True))

    sent = asyncio.run(broken.run_once())

    [row] = outbox_rows(factory, tenant_id)
    assert sent == 0
    assert (row.status, row.attempts) == ("PENDING", 1)
    assert "mail server down" in row.last_error
    assert row.available_at > row.claimed_at  # not due again yet
    # Not due, so a working worker does not pick it up straight away.
    assert asyncio.run(worker(factory, tenant_id, Recorder()).run_once()) == 0


def test_a_retry_that_works_marks_the_row_sent(factory, tenant_id):
    save(factory, tenant_id, submitted())
    asyncio.run(worker(factory, tenant_id, Recorder(fail=True)).run_once())
    make_due_now(factory, tenant_id)

    recorder = Recorder()
    asyncio.run(worker(factory, tenant_id, recorder).run_once())

    [row] = outbox_rows(factory, tenant_id)
    assert (row.status, row.attempts, row.last_error) == ("SENT", 2, None)
    assert len(recorder.sent) == 1


def test_the_worker_gives_up_after_max_attempts(factory, tenant_id):
    save(factory, tenant_id, submitted())
    broken = worker(factory, tenant_id, Recorder(fail=True), max_attempts=2)

    for _ in range(3):
        asyncio.run(broken.run_once())
        make_due_now(factory, tenant_id)

    [row] = outbox_rows(factory, tenant_id)
    assert (row.status, row.attempts) == ("FAILED", 2)


def test_the_worker_only_sends_its_own_tenant(factory, tenant_id):
    with factory.begin() as session:
        other = seed_tenant(session, f"Other {uuid.uuid4().hex[:8]}", SEED_PEOPLE, TODAY.year)
    save(factory, other, submitted())
    recorder = Recorder()

    asyncio.run(worker(factory, tenant_id, recorder).run_once())

    assert recorder.sent == []
    assert outbox_rows(factory, other)[0].status == "PENDING"


def make_due_now(factory, tenant_id) -> None:
    with factory.begin() as session:
        session.execute(
            update(db.NotificationOutbox)
            .where(db.NotificationOutbox.tenant_id == tenant_id)
            .values(available_at=text("now() - interval '1 second'"))
        )


# The inbox


def test_inbox_lists_unread_first_then_newest(factory, tenant_id):
    old, new = submitted(message="old"), submitted(message="new")
    new.created_at = old.created_at + timedelta(seconds=1)
    save(factory, tenant_id, old, new)

    with factory.begin() as session:
        inbox = PostgresInbox(session, tenant_id)
        inbox.mark_read(new.id, "e1")
        items, total = inbox.page("e1", unread=False, limit=10, offset=0)

    assert total == 2
    assert [(n.message, n.read) for n in items] == [("old", False), ("new", True)]
