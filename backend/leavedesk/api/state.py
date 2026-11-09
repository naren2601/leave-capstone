"""Everything the API shares between requests, built once at startup."""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Annotated

from fastapi import Depends, Request

from leavedesk.api.auth import UserAccount, UserStore, hash_password
from leavedesk.api.settings import Settings
from leavedesk.api.stream import NotificationBroker
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
class AppState:
    settings: Settings
    repository: LeaveRepository
    users: UserStore
    service: LeaveService
    inbox: InAppNotifier
    email: EmailNotifier
    broker: NotificationBroker
    extra_notifiers: list[Notifier] = field(default_factory=list)

    @property
    def notifiers(self) -> list[Notifier]:
        return [self.email, self.inbox, self.broker, *self.extra_notifiers]

    def has_employee(self, employee_id: str) -> bool:
        try:
            self.repository.get_employee(employee_id)
        except NotFoundError:
            return False
        return True

    async def send_notifications(self, notifications: list[Notification]) -> None:
        """Run as a BackgroundTask after the response has been sent."""
        await dispatch(self.notifiers, notifications)


# Demo people. Day 3 replaces this with rows in PostgreSQL.
SEED_PEOPLE: list[Employee] = [
    Manager(id="m1", name="Ravi Kumar", email="ravi@leavedesk.dev"),
    Manager(id="m2", name="Meena Iyer", email="meena@leavedesk.dev"),
    Employee(id="e1", name="Asha Rao", email="asha@leavedesk.dev", manager_id="m1"),
    Employee(id="e2", name="Kiran Das", email="kiran@leavedesk.dev", manager_id="m1"),
    Employee(id="e3", name="Sam Joseph", email="sam@leavedesk.dev", manager_id="m2"),
]


def build_state(settings: Settings, today: Callable[[], date] = date.today) -> AppState:
    repository = InMemoryLeaveRepository()
    users = UserStore()
    password_hash = hash_password(settings.seed_password.get_secret_value())
    for person in SEED_PEOPLE:
        repository.add_employee(person.model_copy())
        role = "manager" if isinstance(person, Manager) else "employee"
        users.add(UserAccount(person.id, person.email, password_hash, role))

    inbox, email, broker = InAppNotifier(), EmailNotifier(), NotificationBroker()
    # The service gets no notifiers: the API sends notifications itself, in the
    # background, from the outbox each action fills.
    service = LeaveService(repository, today=today)
    return AppState(settings, repository, users, service, inbox, email, broker)


def get_state(request: Request) -> AppState:
    return request.app.state.leavedesk


State = Annotated[AppState, Depends(get_state)]
