"""Everything the API shares between requests, built once at startup.

Two storage modes:
- In memory (Day 2): no LEAVEDESK_DATABASE_URL. One repository for the whole app.
- PostgreSQL (Day 3): one session, transaction and repository per API request,
  opened by open_store(). The transaction commits when the route succeeds and
  rolls back if it raises, so a request's changes are saved all together or not
  at all.
"""

import asyncio
import logging
import threading
from collections import deque
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Annotated, Protocol

from fastapi import Depends, Request
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from leavedesk.api.auth import LoginPolicy, UserAccount, UserStore, hash_password
from leavedesk.api.settings import Settings
from leavedesk.api.stream import NotificationBroker
from leavedesk.db.engine import create_database_engine
from leavedesk.db.notifications import (
    DatabaseInbox,
    NotificationListener,
    OutboxWorker,
    PostgresInbox,
)
from leavedesk.db.repository import PostgresLeaveRepository
from leavedesk.db.seed import find_tenant, seed_tenant, seed_users
from leavedesk.db.users import PostgresUserStore
from leavedesk.domain.exceptions import NotFoundError
from leavedesk.domain.models import Employee, Manager
from leavedesk.domain.notifications import (
    EmailNotifier,
    InAppNotifier,
    Notification,
    Notifier,
    dispatch,
)
from leavedesk.domain.repository import InMemoryLeaveRepository, LeaveRepository
from leavedesk.domain.service import LeaveService

logger = logging.getLogger("leavedesk.api")


class Inbox(Protocol):
    """In-app notifications: InAppNotifier in memory, PostgresInbox in the database."""

    def save(self, notifications: list[Notification]) -> None: ...
    def page(
        self, recipient: str, unread: bool, limit: int, offset: int
    ) -> tuple[list[Notification], int]: ...
    def mark_read(self, notification_id: str, recipient: str) -> Notification: ...
    def mark_all_read(self, recipient: str) -> int: ...


@dataclass
class Store:
    """What one API request works with: a repository, a service and an inbox,
    all sharing the request's transaction in PostgreSQL mode."""

    repository: LeaveRepository
    service: LeaveService
    inbox: Inbox


@dataclass
class AppState:
    settings: Settings
    repository: LeaveRepository
    users: UserStore | PostgresUserStore
    # In memory mode, the service itself. In PostgreSQL mode, a template that
    # open_store() copies for each request with service.using(repository).
    service: LeaveService
    inbox: InAppNotifier | DatabaseInbox
    email: EmailNotifier
    broker: NotificationBroker
    today: Callable[[], date] = date.today
    extra_notifiers: list[Notifier] = field(default_factory=list)
    engine: Engine | None = None
    session_factory: sessionmaker[Session] | None = None
    tenant_id: int | None = None
    outbox_worker: OutboxWorker | None = None
    listener: NotificationListener | None = None
    _loop: asyncio.AbstractEventLoop | None = None
    _outbox_task: asyncio.Task | None = None
    _pushed: deque[str] = field(default_factory=lambda: deque(maxlen=1000))
    _push_lock: threading.Lock = field(default_factory=threading.Lock)

    @property
    def notifiers(self) -> list[Notifier]:
        """Channels that deliver outside the app. In-app notifications are saved
        with the change (Store.inbox), and SSE streams get them from push_live()."""
        if self.uses_database:
            return [self.email, *self.extra_notifiers]  # sent by the outbox worker
        return [self.email, self.broker, *self.extra_notifiers]

    @property
    def uses_database(self) -> bool:
        return self.session_factory is not None

    @contextmanager
    def open_store(self) -> Iterator[Store]:
        if self.session_factory is None:
            yield Store(self.repository, self.service, self.inbox)
            return
        # begin() commits on success and rolls back if anything raises.
        with self.session_factory.begin() as session:
            repository = PostgresLeaveRepository(session, self.tenant_id, self.today().year)
            yield Store(
                repository,
                self.service.using(repository),
                PostgresInbox(session, self.tenant_id),
            )

    def has_employee(self, employee_id: str) -> bool:
        with self.open_store() as store:
            try:
                store.repository.get_employee(employee_id)
            except NotFoundError:
                return False
            return True

    async def send_notifications(self, notifications: list[Notification]) -> None:
        """Run as a BackgroundTask, after the response and after the commit."""
        if not self.uses_database:
            await dispatch(self.notifiers, notifications)
            return
        for notification in notifications:
            self.push_live(notification)
        # Send the emails now instead of waiting for the next worker round.
        await self.outbox_worker.run_once()

    def push_live(self, notification: Notification) -> None:
        """Push to open SSE streams once, even if the listener hears it too."""
        with self._push_lock:
            if notification.id in self._pushed:
                return
            self._pushed.append(notification.id)
        self.broker.publish(notification)

    def on_database_notify(self, message: dict) -> None:
        """Called by the listener thread for each committed notification."""
        if message.get("tenant_id") != self.tenant_id or self._loop is None:
            return
        notification = self.inbox.find(str(message["id"]))
        if notification is not None:
            # Streams live on the event loop, so hand the push over to it.
            self._loop.call_soon_threadsafe(self.push_live, notification)

    async def start_background_work(self) -> None:
        """At startup in PostgreSQL mode: LISTEN for notifications, and send the
        outbox every few seconds (catches anything a crash or failure left behind)."""
        if not self.uses_database:
            return
        self._loop = asyncio.get_running_loop()
        self.listener = NotificationListener(self.engine, self.on_database_notify)
        self.listener.start()
        self._outbox_task = asyncio.create_task(self._send_outbox_forever())

    async def _send_outbox_forever(self) -> None:
        while True:
            try:
                await self.outbox_worker.run_once()
            except Exception:
                logger.exception("outbox worker round failed")
            await asyncio.sleep(self.settings.outbox_poll_seconds)

    async def stop_background_work(self) -> None:
        if self._outbox_task is not None:
            self._outbox_task.cancel()
            self._outbox_task = None
        if self.listener is not None:
            self.listener.stop()
            self.listener = None

    def close(self) -> None:
        if self.listener is not None:
            self.listener.stop()
            self.listener = None
        if self.engine is not None:
            self.engine.dispose()


class _PerRequestOnly(InMemoryLeaveRepository):
    """Stands in for the shared repository in PostgreSQL mode.

    Routes must use the request's Store instead; touching this is a bug, so it
    fails loudly rather than quietly reading empty in-memory data.
    """

    def __getattribute__(self, name: str):
        if name.startswith("_"):
            return super().__getattribute__(name)
        raise RuntimeError("PostgreSQL mode: use the request's Store, not state.repository")


# Demo people, seeded into memory or into the database's demo tenant.
SEED_PEOPLE: list[Employee] = [
    Manager(id="m1", name="Ravi Kumar", email="ravi@leavedesk.dev"),
    Manager(id="m2", name="Meena Iyer", email="meena@leavedesk.dev"),
    Employee(id="e1", name="Asha Rao", email="asha@leavedesk.dev", manager_id="m1"),
    Employee(id="e2", name="Kiran Das", email="kiran@leavedesk.dev", manager_id="m1"),
    Employee(id="e3", name="Sam Joseph", email="sam@leavedesk.dev", manager_id="m2"),
]


def build_state(settings: Settings, today: Callable[[], date] = date.today) -> AppState:
    policy = LoginPolicy(
        max_failures=settings.login_max_failures,
        lock_for=timedelta(minutes=settings.login_lock_minutes),
    )
    password_hash = hash_password(settings.seed_password.get_secret_value())
    inbox, email, broker = InAppNotifier(), EmailNotifier(), NotificationBroker()

    if settings.database_url is None:
        users = UserStore(policy)
        for person in SEED_PEOPLE:
            role = "manager" if isinstance(person, Manager) else "employee"
            users.add(UserAccount(person.id, person.email, password_hash, role))
        repository = InMemoryLeaveRepository()
        for person in SEED_PEOPLE:
            repository.add_employee(person.model_copy())
        # The service gets no notifiers: the API sends notifications itself, in the
        # background, from the outbox each action fills.
        service = LeaveService(repository, today=today)
        return AppState(settings, repository, users, service, inbox, email, broker, today)

    engine = create_database_engine(settings)  # with statement and lock timeouts
    session_factory = sessionmaker(engine, expire_on_commit=False)
    with session_factory.begin() as session:
        if settings.environment == "dev":
            # Demo people, balances and logins, created once. Never automatic in production.
            tenant_id = seed_tenant(session, settings.tenant_name, SEED_PEOPLE, today().year)
            seed_users(session, tenant_id, password_hash)
        else:
            tenant_id = find_tenant(session, settings.tenant_name)
    users = PostgresUserStore(session_factory, tenant_id, policy)

    placeholder = _PerRequestOnly()
    state = AppState(
        settings,
        placeholder,
        users,
        LeaveService(placeholder, today=today),
        DatabaseInbox(session_factory, tenant_id),
        email,
        broker,
        today,
        engine=engine,
        session_factory=session_factory,
        tenant_id=tenant_id,
    )
    state.outbox_worker = OutboxWorker(
        session_factory,
        tenant_id,
        lambda: state.notifiers,  # read each round, so added notifiers are used
        max_attempts=settings.outbox_max_attempts,
    )
    return state


def get_state(request: Request) -> AppState:
    return request.app.state.leavedesk


async def get_store(request: Request) -> AsyncIterator[Store]:
    with request.app.state.leavedesk.open_store() as store:
        yield store


State = Annotated[AppState, Depends(get_state)]
# scope="function": the transaction commits as soon as the route returns, before
# background tasks run, so notifications never go out for unsaved changes.
StoreDep = Annotated[Store, Depends(get_store, scope="function")]
