from typing import Annotated

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

from leavedesk.api.auth import StreamUser, User
from leavedesk.api.schemas import NotificationOut, Page, ReadAllOut
from leavedesk.api.state import State, StoreDep
from leavedesk.api.stream import event_stream
from leavedesk.domain.notifications import Notification

router = APIRouter(tags=["notifications"])


@router.get("/notifications", response_model=Page[NotificationOut])
def list_notifications(
    user: User,
    store: StoreDep,
    unread: bool = False,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict:
    # Unread first, then newest first. In PostgreSQL the database sorts and pages.
    items, total = store.inbox.page(user.id, unread, limit, offset)
    return {"items": items, "total": total, "limit": limit, "offset": offset}


# Declared before /notifications/{id}/read so "read-all" is never taken as an id.
@router.post("/notifications/read-all", response_model=ReadAllOut)
def mark_all_read(user: User, store: StoreDep) -> ReadAllOut:
    return ReadAllOut(updated=store.inbox.mark_all_read(user.id))


@router.post("/notifications/{notification_id}/read", response_model=NotificationOut)
def mark_read(notification_id: str, user: User, store: StoreDep) -> Notification:
    # Someone else's notification gets the same 404 as a missing one.
    return store.inbox.mark_read(notification_id, user.id)


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
