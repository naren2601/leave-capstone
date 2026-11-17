"""Everything the API shares between requests, built once at startup.

Two storage modes:
- In memory (Day 2): no LEAVEDESK_DATABASE_URL. One repository for the whole app.
- PostgreSQL (Day 3): one session, transaction and repository per API request,
  opened by open_store(). The transaction commits when the route succeeds and
  rolls back if it raises, so a request's changes are saved all together or not
  at all.
"""

from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from leavedesk.api.auth import UserAccount, UserStore, hash_password
from leavedesk.api.settings import Settings
from leavedesk.api.stream import NotificationBroker
from leavedesk.db.repository import PostgresLeaveRepository
from leavedesk.db.seed import find_tenant, seed_tenant
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


@dataclass
class Store:
    """What one API request works with: a repository and a service using it."""

    repository: LeaveRepository
    service: LeaveService


@dataclass
class AppState:
    settings: Settings
    repository: LeaveRepository
    users: UserStore
    # In memory mode, the service itself. In PostgreSQL mode, a template that
    # open_store() copies for each request with service.using(repository).
    service: LeaveService
    inbox: InAppNotifier
    email: EmailNotifier
    broker: NotificationBroker
    today: Callable[[], date] = date.today
    extra_notifiers: list[Notifier] = field(default_factory=list)
    engine: Engine | None = None
    session_factory: sessionmaker[Session] | None = None
    tenant_id: int | None = None

    @property
    def notifiers(self) -> list[Notifier]:
        return [self.email, self.inbox, self.broker, *self.extra_notifiers]

    @property
    def uses_database(self) -> bool:
        return self.session_factory is not None

    @contextmanager
    def open_store(self) -> Iterator[Store]:
        if self.session_factory is None:
            yield Store(self.repository, self.service)
            return
        # begin() commits on success and rolls back if anything raises.
        with self.session_factory.begin() as session:
            repository = PostgresLeaveRepository(session, self.tenant_id, self.today().year)
            yield Store(repository, self.service.using(repository))

    def has_employee(self, employee_id: str) -> bool:
        with self.open_store() as store:
            try:
                store.repository.get_employee(employee_id)
            except NotFoundError:
                return False
            return True

    async def send_notifications(self, notifications: list[Notification]) -> None:
        """Run as a BackgroundTask, after the response and after the commit."""
        await dispatch(self.notifiers, notifications)

    def close(self) -> None:
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
    users = UserStore()
    password_hash = hash_password(settings.seed_password.get_secret_value())
    for person in SEED_PEOPLE:
        role = "manager" if isinstance(person, Manager) else "employee"
        users.add(UserAccount(person.id, person.email, password_hash, role))

    inbox, email, broker = InAppNotifier(), EmailNotifier(), NotificationBroker()

    if settings.database_url is None:
        repository = InMemoryLeaveRepository()
        for person in SEED_PEOPLE:
            repository.add_employee(person.model_copy())
        # The service gets no notifiers: the API sends notifications itself, in the
        # background, from the outbox each action fills.
        service = LeaveService(repository, today=today)
        return AppState(settings, repository, users, service, inbox, email, broker, today)

    engine = create_engine(
        settings.database_url.get_secret_value(),
        echo=settings.database_echo,
        pool_pre_ping=True,  # replace connections the database has closed
    )
    session_factory = sessionmaker(engine, expire_on_commit=False)
    with session_factory.begin() as session:
        if settings.environment == "dev":
            # Demo people and balances, created once. Never automatic in production.
            tenant_id = seed_tenant(session, settings.tenant_name, SEED_PEOPLE, today().year)
        else:
            tenant_id = find_tenant(session, settings.tenant_name)

    placeholder = _PerRequestOnly()
    return AppState(
        settings,
        placeholder,
        users,
        LeaveService(placeholder, today=today),
        inbox,
        email,
        broker,
        today,
        engine=engine,
        session_factory=session_factory,
        tenant_id=tenant_id,
    )


def get_state(request: Request) -> AppState:
    return request.app.state.leavedesk


async def get_store(request: Request) -> AsyncIterator[Store]:
    with request.app.state.leavedesk.open_store() as store:
        yield store


State = Annotated[AppState, Depends(get_state)]
# scope="function": the transaction commits as soon as the route returns, before
# background tasks run, so notifications never go out for unsaved changes.
StoreDep = Annotated[Store, Depends(get_store, scope="function")]
