"""Notifications in PostgreSQL: the inbox, the outbox worker and the listener.

How a notification travels (Day 3, step 4):

1. The route saves the change, the `notifications` rows and one
   `notification_outbox` row each, all in ONE transaction. If anything fails,
   all of it rolls back, so there is never a notification for an unsaved change.
2. On commit, a trigger's pg_notify tells every listening API process about the
   new row. The NotificationListener hears it and pushes it to open SSE streams.
3. The OutboxWorker claims pending outbox rows with FOR UPDATE SKIP LOCKED,
   sends the email, and marks each row SENT. A failed send is retried later.
"""

import json
import logging
import threading
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import Engine, func, select, update
from sqlalchemy.orm import Session, sessionmaker

from leavedesk.db import models as db
from leavedesk.db.ids import uuid7
from leavedesk.domain.exceptions import NotFoundError
from leavedesk.domain.notifications import (
    Notification,
    NotificationEvent,
    Notifier,
    dispatch,
)

logger = logging.getLogger("leavedesk.notifications")

CHANNEL = "leavedesk_notifications"  # the pg_notify channel, see migration 0002
LISTEN_SQL = "LISTEN leavedesk_notifications"  # a fixed statement: no values inside


def _uuid_or_none(notification_id: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(notification_id)
    except ValueError:
        return None


def _to_domain(row: db.Notification, recipient_code: str) -> Notification:
    return Notification(
        recipient=recipient_code,
        event=NotificationEvent(row.event),
        message=row.payload.get("message", ""),
        read=row.read_at is not None,
        id=str(row.id),
        created_at=row.created_at,
    )


class PostgresInbox:
    """Each user's in-app notifications, inside the current request's transaction.

    Same methods as the in-memory InAppNotifier, so the routes work with either.
    """

    def __init__(self, session: Session, tenant_id: int) -> None:
        self.session = session
        self.tenant_id = tenant_id

    def save(self, notifications: list[Notification]) -> None:
        """Insert the notifications and their outbox rows. Commits with the change."""
        if not notifications:
            return
        codes = {n.recipient for n in notifications}
        employee_ids = dict(
            self.session.execute(
                select(db.Employee.code, db.Employee.id).where(
                    db.Employee.tenant_id == self.tenant_id, db.Employee.code.in_(codes)
                )
            ).all()
        )
        for notification in notifications:
            row_id = uuid7()
            notification.id = str(row_id)  # the API shows the database id
            self.session.add(
                db.Notification(
                    id=row_id,
                    tenant_id=self.tenant_id,
                    recipient_id=employee_ids[notification.recipient],
                    event=notification.event.value,
                    payload={"message": notification.message},
                    created_at=notification.created_at,
                )
            )
        self.session.flush()  # the outbox rows point at these, so they go first
        self.session.add_all(
            db.NotificationOutbox(tenant_id=self.tenant_id, notification_id=uuid.UUID(n.id))
            for n in notifications
        )
        self.session.flush()

    def page(
        self, recipient: str, unread: bool, limit: int, offset: int
    ) -> tuple[list[Notification], int]:
        """One page of a user's notifications, unread first, then newest first."""
        query = self._for(recipient)
        if unread:
            query = query.where(db.Notification.read_at.is_(None))
        total = self.session.scalar(select(func.count()).select_from(query.subquery()))
        rows = self.session.scalars(
            query.order_by(
                db.Notification.read_at.is_not(None),
                db.Notification.created_at.desc(),
                db.Notification.id.desc(),
            )
            .limit(limit)
            .offset(offset)
        ).all()
        return [_to_domain(row, recipient) for row in rows], total or 0

    def inbox(self, recipient: str) -> list[Notification]:
        rows = self.session.scalars(self._for(recipient).order_by(db.Notification.created_at))
        return [_to_domain(row, recipient) for row in rows]

    def unread_count(self, recipient: str) -> int:
        query = self._for(recipient).where(db.Notification.read_at.is_(None))
        return self.session.scalar(select(func.count()).select_from(query.subquery())) or 0

    def find(self, notification_id: str) -> Notification | None:
        row_id = _uuid_or_none(notification_id)
        if row_id is None:
            return None
        found = self.session.execute(
            select(db.Notification, db.Employee.code)
            .join(
                db.Employee,
                (db.Employee.tenant_id == db.Notification.tenant_id)
                & (db.Employee.id == db.Notification.recipient_id),
            )
            .where(db.Notification.tenant_id == self.tenant_id, db.Notification.id == row_id)
        ).first()
        return _to_domain(*found) if found else None

    def mark_read(self, notification_id: str, recipient: str) -> Notification:
        row_id = _uuid_or_none(notification_id)
        row = None
        if row_id is not None:
            row = self.session.scalars(
                self._for(recipient).where(db.Notification.id == row_id)
            ).first()
        # Someone else's notification gets the same 404 as a missing one.
        if row is None:
            raise NotFoundError(f"no notification with id {notification_id}")
        if row.read_at is None:
            row.read_at = datetime.now(UTC)
            self.session.flush()
        return _to_domain(row, recipient)

    def mark_all_read(self, recipient: str) -> int:
        result = self.session.execute(
            update(db.Notification)
            .where(
                db.Notification.tenant_id == self.tenant_id,
                db.Notification.recipient_id == self._employee_id(recipient),
                db.Notification.read_at.is_(None),
            )
            .values(read_at=func.now())
        )
        return result.rowcount

    def _employee_id(self, code: str):
        return (
            select(db.Employee.id)
            .where(db.Employee.tenant_id == self.tenant_id, db.Employee.code == code)
            .scalar_subquery()
        )

    def _for(self, recipient: str):
        return select(db.Notification).where(
            db.Notification.tenant_id == self.tenant_id,
            db.Notification.recipient_id == self._employee_id(recipient),
        )


class DatabaseInbox:
    """state.inbox in PostgreSQL mode: opens its own short transaction per call.

    Routes use the request's PostgresInbox instead; this is for checks and tools.
    """

    def __init__(self, session_factory: sessionmaker[Session], tenant_id: int) -> None:
        self.session_factory = session_factory
        self.tenant_id = tenant_id

    def _call(self, method: str, *args):
        with self.session_factory.begin() as session:
            return getattr(PostgresInbox(session, self.tenant_id), method)(*args)

    def inbox(self, recipient: str) -> list[Notification]:
        return self._call("inbox", recipient)

    def unread_count(self, recipient: str) -> int:
        return self._call("unread_count", recipient)

    def find(self, notification_id: str) -> Notification | None:
        return self._call("find", notification_id)

    def mark_all_read(self, recipient: str) -> int:
        return self._call("mark_all_read", recipient)


class OutboxWorker:
    """Sends pending outbox rows (email) and records the result.

    FOR UPDATE SKIP LOCKED: rows another worker is busy with are skipped, not
    waited for, so several workers (or API processes) never send the same row twice.
    """

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        tenant_id: int,
        notifiers: Callable[[], list[Notifier]],
        max_attempts: int = 5,
        batch_size: int = 50,
        retry_after: timedelta = timedelta(seconds=30),
    ) -> None:
        self.session_factory = session_factory
        self.tenant_id = tenant_id
        self.notifiers = notifiers
        self.max_attempts = max_attempts
        self.batch_size = batch_size
        self.retry_after = retry_after

    def claim(self, session: Session) -> list[tuple[db.NotificationOutbox, Notification]]:
        """Lock up to batch_size due rows. The locks last until the transaction ends."""
        rows = session.execute(
            select(db.NotificationOutbox, db.Notification, db.Employee.code)
            .join(
                db.Notification,
                (db.Notification.tenant_id == db.NotificationOutbox.tenant_id)
                & (db.Notification.id == db.NotificationOutbox.notification_id),
            )
            .join(
                db.Employee,
                (db.Employee.tenant_id == db.Notification.tenant_id)
                & (db.Employee.id == db.Notification.recipient_id),
            )
            .where(
                db.NotificationOutbox.tenant_id == self.tenant_id,
                db.NotificationOutbox.status == "PENDING",
                db.NotificationOutbox.available_at <= func.now(),
            )
            .order_by(db.NotificationOutbox.id)
            .limit(self.batch_size)
            .with_for_update(of=db.NotificationOutbox, skip_locked=True)
        ).all()
        return [(outbox, _to_domain(row, code)) for outbox, row, code in rows]

    async def run_once(self) -> int:
        """Send one batch. Returns how many were sent."""
        sent = 0
        with self.session_factory.begin() as session:
            for outbox, notification in self.claim(session):
                failures = await dispatch(self.notifiers(), [notification])
                now = datetime.now(UTC)
                outbox.attempts += 1
                outbox.claimed_at = now
                if not failures:
                    outbox.status, outbox.sent_at, outbox.last_error = "SENT", now, None
                    sent += 1
                    continue
                outbox.last_error = repr(failures[0])[:500]
                if outbox.attempts >= self.max_attempts:
                    outbox.status = "FAILED"  # give up; visible for a person to check
                else:
                    # Wait longer after each failure: 30 s, 60 s, 120 s, ...
                    outbox.available_at = now + self.retry_after * 2 ** (outbox.attempts - 1)
        return sent


class NotificationListener:
    """Runs LISTEN leavedesk_notifications on its own connection, in a thread.

    Calls on_message(payload) for every notification another transaction commits,
    including ones saved by other API processes. Reconnects if the connection drops.
    """

    def __init__(
        self, engine: Engine, on_message: Callable[[dict], None], poll_seconds: float = 0.5
    ) -> None:
        self.engine = engine
        self.on_message = on_message
        self.poll_seconds = poll_seconds
        self.listening = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="pg-listener", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._listen()
            except Exception:
                logger.exception("LISTEN connection failed; reconnecting")
                self.listening.clear()
                self._stop.wait(1)

    def _listen(self) -> None:
        connection = self.engine.raw_connection()
        try:
            driver = connection.driver_connection
            # LISTEN only starts when its transaction commits. The pool's pre-ping
            # may have opened one (pg8000 does), so end it, then use autocommit.
            driver.rollback()
            driver.autocommit = True
            for payload in _driver_notifications(driver, self.poll_seconds, self._ready):
                self._handle(payload)
                if self._stop.is_set():
                    break
        finally:
            # Never hand an autocommit, listening connection back to the pool.
            connection.invalidate()

    def _ready(self) -> bool:
        """Called once LISTEN is active, then on every poll. False means stop."""
        self.listening.set()
        return not self._stop.is_set()

    def _handle(self, payload: str) -> None:
        try:
            self.on_message(json.loads(payload))
        except Exception:
            logger.exception("could not handle notification %s", payload)


def _driver_notifications(driver, poll_seconds: float, keep_going: Callable[[], bool]):
    """Yield each NOTIFY payload. psycopg and pg8000 receive them differently."""
    if hasattr(driver, "notifies"):  # psycopg 3
        driver.execute(LISTEN_SQL)
        while keep_going():
            for notify in driver.notifies(timeout=poll_seconds):
                yield notify.payload
        return
    # pg8000 collects notifications as they arrive with any query's response.
    cursor = driver.cursor()
    cursor.execute(LISTEN_SQL)
    stop = threading.Event()
    while keep_going():
        cursor.execute("SELECT 1")
        while driver.notifications:
            _pid, _channel, payload = driver.notifications.popleft()
            yield payload
        stop.wait(poll_seconds)
