"""Live notifications over Server-Sent Events (SSE).

NotificationBroker is one more Notifier, next to EmailNotifier and
InAppNotifier: when a notification is sent, it is pushed to every open stream
of that recipient.
"""

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable

from leavedesk.domain.notifications import Notification, Notifier


class NotificationBroker(Notifier):
    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue[Notification]]] = {}

    def subscribe(self, recipient: str) -> asyncio.Queue[Notification]:
        queue: asyncio.Queue[Notification] = asyncio.Queue()
        self._subscribers.setdefault(recipient, set()).add(queue)
        return queue

    def unsubscribe(self, recipient: str, queue: asyncio.Queue[Notification]) -> None:
        queues = self._subscribers.get(recipient, set())
        queues.discard(queue)
        if not queues:
            self._subscribers.pop(recipient, None)

    def subscriber_count(self, recipient: str) -> int:
        return len(self._subscribers.get(recipient, ()))

    async def send(self, notification: Notification) -> None:
        for queue in self._subscribers.get(notification.recipient, set()).copy():
            queue.put_nowait(notification)


def format_event(notification: Notification) -> str:
    data = {
        "id": notification.id,
        "recipient": notification.recipient,
        "event": notification.event.value,
        "message": notification.message,
        "read": notification.read,
        "created_at": notification.created_at.isoformat(),
    }
    return f"id: {notification.id}\nevent: notification\ndata: {json.dumps(data)}\n\n"


KEEP_ALIVE = ": keep-alive\n\n"


async def event_stream(
    queue: asyncio.Queue[Notification],
    keepalive_seconds: float,
    is_disconnected: Callable[[], Awaitable[bool]],
) -> AsyncIterator[str]:
    """Yield each new notification as an SSE event, or a keep-alive comment."""
    while not await is_disconnected():
        try:
            notification = await asyncio.wait_for(queue.get(), timeout=keepalive_seconds)
        except TimeoutError:
            yield KEEP_ALIVE
        else:
            yield format_event(notification)
