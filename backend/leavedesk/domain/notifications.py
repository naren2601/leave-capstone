"""Notifications for LeaveDesk (FR-8).

Each event creates one Notification per recipient. Every notifier (email
and in-app) then delivers each one, all at the same time with asyncio.gather.
"""

import asyncio
import logging
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

from leavedesk.domain.exceptions import NotFoundError
from leavedesk.domain.models import Employee, LeaveRequest

logger = logging.getLogger("leavedesk")


class NotificationEvent(StrEnum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


def _now() -> datetime:
    return datetime.now(UTC)


def _new_id() -> str:
    return uuid.uuid4().hex


@dataclass
class Notification:
    recipient: str  # employee id
    event: NotificationEvent
    message: str
    read: bool = False
    id: str = field(default_factory=_new_id)
    created_at: datetime = field(default_factory=_now)

    def mark_read(self) -> None:
        self.read = True


class Notifier(ABC):
    """A delivery channel, such as email or in-app."""

    @abstractmethod
    async def send(self, notification: Notification) -> None: ...


class EmailNotifier(Notifier):
    """A stub: it records and logs emails instead of sending them."""

    def __init__(self) -> None:
        self.sent: list[Notification] = []

    async def send(self, notification: Notification) -> None:
        await asyncio.sleep(0)  # stands in for a real network call
        self.sent.append(notification)
        logger.info("EMAIL to %s: %s", notification.recipient, notification.message)


class InAppNotifier(Notifier):
    """Keeps an inbox for each user, with read and unread messages."""

    def __init__(self) -> None:
        self._inboxes: dict[str, list[Notification]] = {}

    async def send(self, notification: Notification) -> None:
        await asyncio.sleep(0)
        self._inboxes.setdefault(notification.recipient, []).append(notification)

    def inbox(self, recipient: str) -> list[Notification]:
        return list(self._inboxes.get(recipient, []))

    def unread_count(self, recipient: str) -> int:
        return sum(1 for n in self.inbox(recipient) if not n.read)

    def find(self, notification_id: str) -> Notification | None:
        for notifications in self._inboxes.values():
            for notification in notifications:
                if notification.id == notification_id:
                    return notification
        return None

    def mark_all_read(self, recipient: str) -> int:
        """Mark every unread notification read. Returns how many changed."""
        unread = [n for n in self._inboxes.get(recipient, []) if not n.read]
        for notification in unread:
            notification.mark_read()
        return len(unread)

    # The same methods as PostgresInbox (Day 3), so routes work with either.

    def save(self, notifications: list[Notification]) -> None:
        for notification in notifications:
            self._inboxes.setdefault(notification.recipient, []).append(notification)

    def page(
        self, recipient: str, unread: bool, limit: int, offset: int
    ) -> tuple[list[Notification], int]:
        """One page of a user's notifications, unread first, then newest first."""
        notifications = self.inbox(recipient)
        if unread:
            notifications = [n for n in notifications if not n.read]
        notifications.sort(key=lambda n: n.created_at, reverse=True)
        notifications.sort(key=lambda n: n.read)
        return notifications[offset : offset + limit], len(notifications)

    def mark_read(self, notification_id: str, recipient: str) -> Notification:
        notification = self.find(notification_id)
        # Someone else's notification gets the same 404 as a missing one.
        if notification is None or notification.recipient != recipient:
            raise NotFoundError(f"no notification with id {notification_id}")
        notification.mark_read()
        return notification


def build_notifications(
    event: NotificationEvent,
    request: LeaveRequest,
    employee: Employee,
    manager: Employee | None,
) -> list[Notification]:
    """Apply the 'who is notified' table from section 2 of the spec."""
    dates = f"{request.start_date} to {request.end_date}"
    summary = f"{request.id} ({request.leave_type.value}, {dates})"

    employee_messages = {
        NotificationEvent.SUBMITTED: f"Your leave request {summary} was submitted.",
        NotificationEvent.APPROVED: f"Your leave request {summary} was approved.",
        NotificationEvent.REJECTED: (
            f"Your leave request {summary} was rejected: {request.decision_note}"
        ),
        NotificationEvent.CANCELLED: f"Your leave request {summary} was cancelled.",
    }
    manager_messages = {
        NotificationEvent.SUBMITTED: (
            f"{employee.name} requested leave {summary}. Please review it."
        ),
        NotificationEvent.CANCELLED: (f"{employee.name} cancelled leave request {summary}."),
    }

    notifications = [Notification(employee.id, event, employee_messages[event])]
    if manager is not None and event in manager_messages:
        notifications.append(Notification(manager.id, event, manager_messages[event]))
    return notifications


async def dispatch(notifiers: list[Notifier], notifications: list[Notification]) -> list[Exception]:
    """Send every notification on every channel at the same time.

    A failed delivery is logged and returned, but never raised, so the
    other deliveries still finish and the leave action stays saved.
    """
    deliveries = [
        notifier.send(notification) for notification in notifications for notifier in notifiers
    ]
    results = await asyncio.gather(*deliveries, return_exceptions=True)

    failures = [result for result in results if isinstance(result, Exception)]
    for failure in failures:
        logger.error("Notification delivery failed: %r", failure)
    return failures
