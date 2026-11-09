from typing import Annotated

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

from leavedesk.api.auth import StreamUser, User
from leavedesk.api.schemas import NotificationOut, Page, ReadAllOut
from leavedesk.api.state import State
from leavedesk.api.stream import event_stream
from leavedesk.domain.exceptions import NotFoundError
from leavedesk.domain.notifications import Notification

router = APIRouter(tags=["notifications"])


@router.get("/notifications", response_model=Page[NotificationOut])
def list_notifications(
    user: User,
    state: State,
    unread: bool = False,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict:
    notifications = state.inbox.inbox(user.id)
    if unread:
        notifications = [n for n in notifications if not n.read]
    # Unread first, then newest first.
    notifications.sort(key=lambda n: n.created_at, reverse=True)
    notifications.sort(key=lambda n: n.read)

    return {
        "items": notifications[offset : offset + limit],
        "total": len(notifications),
        "limit": limit,
        "offset": offset,
    }


# Declared before /notifications/{id}/read so "read-all" is never taken as an id.
@router.post("/notifications/read-all", response_model=ReadAllOut)
def mark_all_read(user: User, state: State) -> ReadAllOut:
    return ReadAllOut(updated=state.inbox.mark_all_read(user.id))


@router.post("/notifications/{notification_id}/read", response_model=NotificationOut)
def mark_read(notification_id: str, user: User, state: State) -> Notification:
    notification = state.inbox.find(notification_id)
    # Someone else's notification gets the same 404 as a missing one.
    if notification is None or notification.recipient != user.id:
        raise NotFoundError(f"no notification with id {notification_id}")
    notification.mark_read()
    return notification


@router.get(
    "/notifications/stream",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {}}}},
)
async def stream_notifications(
    request: Request, user: StreamUser, state: State
) -> StreamingResponse:
    queue = state.broker.subscribe(user.id)

    async def events():
        try:
            async for chunk in event_stream(
                queue, state.settings.sse_keepalive_seconds, request.is_disconnected
            ):
                yield chunk
        finally:
            state.broker.unsubscribe(user.id, queue)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
