import base64
import binascii
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Query, Response, status

from leavedesk.api.auth import CurrentUser, ManagerUser, User
from leavedesk.api.schemas import (
    ApplyLeaveIn,
    BalanceOut,
    EmployeeOut,
    LeaveRequestOut,
    Page,
    RejectIn,
)
from leavedesk.api.state import AppState, State, Store, StoreDep
from leavedesk.domain.exceptions import (
    InvalidLeaveRequestError,
    InvalidTransitionError,
    NotAuthorizedError,
    NotFoundError,
    VersionConflictError,
)
from leavedesk.domain.models import Employee, LeaveRequest, LeaveStatus, LeaveType
from leavedesk.domain.notifications import Notification

router = APIRouter(tags=["leave"])


# Who can see what


def visible_employee_ids(store: Store, user: CurrentUser) -> set[str]:
    """An employee sees themselves. A manager also sees their direct reports."""
    ids = {user.id}
    if user.is_manager:
        # Only the reports, not every employee in the company (step 6).
        ids |= {e.id for e in store.repository.direct_reports(user.id)}
    return ids


def load_visible_request(store: Store, user: CurrentUser, request_id: str) -> LeaveRequest:
    """Return the request, or 404 if it is missing or not the user's to see."""
    request = store.repository.get_request(request_id)  # NotFoundError -> 404
    if request.employee_id not in visible_employee_ids(store, user):
        raise NotFoundError(f"no leave request with id {request_id}")
    return request


def send_later(
    background: BackgroundTasks, state: AppState, store: Store, outbox: list[Notification]
):
    """Save in-app notifications with the change, then send the rest after the commit."""
    if outbox:
        store.inbox.save(outbox)  # same transaction as the change: both or neither
        background.add_task(state.send_notifications, outbox)


# Safe changes: optimistic locking and idempotency

IfMatch = Annotated[
    str | None,
    Header(
        alias="If-Match",
        description="The request's version, from its `version` field or `ETag` header. "
        "If someone changed the request since, the API answers 409 VERSION_CONFLICT.",
    ),
]
IdempotencyKey = Annotated[
    str | None,
    Header(
        alias="Idempotency-Key",
        min_length=1,
        max_length=200,
        description="Any unique text, such as a UUID. Retrying with the same key returns "
        "the first result instead of creating a second request.",
    ),
]


def expected_version(if_match: str | None) -> int | None:
    """Read If-Match. Accepts 3, "3" or W/"3" (how browsers send ETags back)."""
    if if_match is None:
        return None
    value = if_match.strip().removeprefix("W/").strip('"')
    if not value.isdigit():
        raise InvalidLeaveRequestError("If-Match must be the request's version number")
    return int(value)


def tag(response: Response, request: LeaveRequest) -> LeaveRequest:
    """Send the version back as an ETag, ready to use as the next If-Match."""
    response.headers["ETag"] = f'"{request.version}"'
    return request


def same_request(request: LeaveRequest, body: ApplyLeaveIn) -> bool:
    return (
        request.leave_type is body.leave_type
        and request.start_date == body.start_date
        and request.end_date == body.end_date
        and request.day_part is body.day_part
        and request.reason == body.reason.strip()
    )


# Balance


@router.get("/employees/{employee_id}/balance", response_model=list[BalanceOut])
def get_balance(employee_id: str, user: User, store: StoreDep) -> list[BalanceOut]:
    employee = store.repository.get_employee(employee_id)  # NotFoundError -> 404
    if user.id != employee.id and employee.manager_id != user.id:
        raise NotAuthorizedError("you can only see your own or your team's balance")

    balances = []
    for leave_type in LeaveType:
        b = store.service.get_balance(employee_id, leave_type)
        balances.append(
            BalanceOut(
                leave_type=leave_type,
                entitled=b.entitled,
                used=b.used,
                pending=b.pending,
                available=b.available,
            )
        )
    return balances


# Leave requests


@router.post(
    "/leave-requests",
    response_model=LeaveRequestOut,
    status_code=status.HTTP_201_CREATED,
)
async def apply_for_leave(
    body: ApplyLeaveIn,
    user: User,
    state: State,
    store: StoreDep,
    background: BackgroundTasks,
    response: Response,
    idempotency_key: IdempotencyKey = None,
) -> LeaveRequest:
    if idempotency_key is not None:
        first = store.repository.find_by_idempotency_key(user.id, idempotency_key)
        if first is not None:
            if not same_request(first, body):
                raise InvalidLeaveRequestError(
                    "this Idempotency-Key was already used for a different request"
                )
            response.headers["Idempotent-Replayed"] = "true"
            return tag(response, first)

    outbox: list[Notification] = []
    request = await store.service.apply(
        user.id,
        body.leave_type,
        body.start_date,
        body.end_date,
        body.reason,
        body.day_part,
        outbox=outbox,
    )
    if idempotency_key is not None:
        store.repository.remember_idempotency_key(user.id, idempotency_key, request.id)
    send_later(background, state, store, outbox)
    return tag(response, request)


@router.get("/leave-requests", response_model=Page[LeaveRequestOut])
def list_leave_requests(
    user: User,
    store: StoreDep,
    status_filter: Annotated[LeaveStatus | None, Query(alias="status")] = None,
    employee_id: str | None = None,
    sort: Literal["start_date", "-start_date"] = "start_date",
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    cursor: Annotated[
        str | None,
        Query(description="The `next_cursor` from the previous page. Use instead of offset."),
    ] = None,
) -> dict:
    visible = visible_employee_ids(store, user)
    if employee_id is not None:
        if employee_id not in visible:
            raise HTTPException(403, "you cannot see this employee's requests")
        visible = {employee_id}
    if cursor is not None and offset:
        raise InvalidLeaveRequestError("use either cursor or offset, not both")

    descending = sort.startswith("-")
    page = store.repository.page_requests(
        visible,
        status_filter,
        descending,
        limit,
        offset,
        after=decode_cursor(cursor) if cursor else None,
    )
    last = page.items[-1] if page.items else None
    return {
        "items": page.items,
        "total": page.total,
        "limit": limit,
        "offset": offset,
        "next_cursor": encode_cursor(last) if page.has_more and last else None,
    }


def encode_cursor(request: LeaveRequest) -> str:
    """The last item's sort key, made opaque so clients do not build their own."""
    raw = f"{request.start_date.isoformat()}|{request.id}".encode()
    return base64.urlsafe_b64encode(raw).decode()


def decode_cursor(cursor: str) -> tuple[date, str]:
    try:
        start, request_id = base64.urlsafe_b64decode(cursor.encode()).decode().split("|", 1)
        return date.fromisoformat(start), request_id
    except (binascii.Error, UnicodeDecodeError, ValueError):
        raise InvalidLeaveRequestError("the cursor is not valid") from None


@router.get("/employees", response_model=list[EmployeeOut])
def search_employees(
    user: ManagerUser,
    store: StoreDep,
    q: Annotated[str, Query(min_length=2, max_length=100, description="Part of a name")],
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> list[Employee]:
    """Managers find people by name, for example ?q=ash finds Asha Rao."""
    return store.repository.search_employees(q.strip(), limit)


@router.get("/leave-requests/{request_id}", response_model=LeaveRequestOut)
def get_leave_request(
    request_id: str, user: User, store: StoreDep, response: Response
) -> LeaveRequest:
    return tag(response, load_visible_request(store, user, request_id))


@router.post("/leave-requests/{request_id}/approve", response_model=LeaveRequestOut)
async def approve_leave(
    request_id: str,
    user: ManagerUser,
    state: State,
    store: StoreDep,
    background: BackgroundTasks,
    response: Response,
    if_match: IfMatch = None,
) -> LeaveRequest:
    outbox: list[Notification] = []
    request = await store.service.approve(
        request_id, user.id, outbox=outbox, expected_version=expected_version(if_match)
    )
    send_later(background, state, store, outbox)
    return tag(response, request)


@router.post("/leave-requests/{request_id}/reject", response_model=LeaveRequestOut)
async def reject_leave(
    request_id: str,
    body: RejectIn,
    user: ManagerUser,
    state: State,
    store: StoreDep,
    background: BackgroundTasks,
    response: Response,
    if_match: IfMatch = None,
) -> LeaveRequest:
    outbox: list[Notification] = []
    request = await store.service.reject(
        request_id,
        user.id,
        body.reason,
        outbox=outbox,
        expected_version=expected_version(if_match),
    )
    send_later(background, state, store, outbox)
    return tag(response, request)


@router.delete("/leave-requests/{request_id}", response_model=LeaveRequestOut)
async def cancel_leave(
    request_id: str,
    user: User,
    state: State,
    store: StoreDep,
    background: BackgroundTasks,
    response: Response,
    if_match: IfMatch = None,
) -> LeaveRequest:
    request = store.repository.get_request(request_id)  # NotFoundError -> 404
    if request.employee_id != user.id:
        raise NotAuthorizedError("only the owner can cancel a request")
    version = expected_version(if_match)
    if version is not None and version != request.version:
        raise VersionConflictError(
            f"request {request.id} is at version {request.version}, not {version}"
        )
    if request.status is not LeaveStatus.PENDING:
        # The API only cancels pending requests, as the approved spec says.
        raise InvalidTransitionError(
            f"only PENDING requests can be cancelled here, this one is {request.status.value}"
        )

    outbox: list[Notification] = []
    request = await store.service.cancel(
        request_id, user.id, outbox=outbox, expected_version=version
    )
    send_later(background, state, store, outbox)
    return tag(response, request)
