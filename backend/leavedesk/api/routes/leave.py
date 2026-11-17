from typing import Annotated, Literal

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, status

from leavedesk.api.auth import CurrentUser, ManagerUser, User
from leavedesk.api.schemas import (
    ApplyLeaveIn,
    BalanceOut,
    LeaveRequestOut,
    Page,
    RejectIn,
)
from leavedesk.api.state import AppState, State, Store, StoreDep
from leavedesk.domain.exceptions import (
    InvalidTransitionError,
    NotAuthorizedError,
    NotFoundError,
)
from leavedesk.domain.models import LeaveRequest, LeaveStatus, LeaveType
from leavedesk.domain.notifications import Notification

router = APIRouter(tags=["leave"])


# Who can see what


def visible_employee_ids(store: Store, user: CurrentUser) -> set[str]:
    """An employee sees themselves. A manager also sees their direct reports."""
    ids = {user.id}
    if user.is_manager:
        ids |= {e.id for e in store.repository.list_employees() if e.manager_id == user.id}
    return ids


def load_visible_request(store: Store, user: CurrentUser, request_id: str) -> LeaveRequest:
    """Return the request, or 404 if it is missing or not the user's to see."""
    request = store.repository.get_request(request_id)  # NotFoundError -> 404
    if request.employee_id not in visible_employee_ids(store, user):
        raise NotFoundError(f"no leave request with id {request_id}")
    return request


def send_later(background: BackgroundTasks, state: AppState, outbox: list[Notification]):
    if outbox:
        background.add_task(state.send_notifications, outbox)


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
) -> LeaveRequest:
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
    send_later(background, state, outbox)
    return request


@router.get("/leave-requests", response_model=Page[LeaveRequestOut])
def list_leave_requests(
    user: User,
    store: StoreDep,
    status_filter: Annotated[LeaveStatus | None, Query(alias="status")] = None,
    employee_id: str | None = None,
    sort: Literal["start_date", "-start_date"] = "start_date",
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict:
    visible = visible_employee_ids(store, user)
    if employee_id is not None:
        if employee_id not in visible:
            raise HTTPException(403, "you cannot see this employee's requests")
        visible = {employee_id}

    requests = [r for e in sorted(visible) for r in store.repository.requests_for(e)]
    if status_filter is not None:
        requests = [r for r in requests if r.status is status_filter]
    requests.sort(key=lambda r: (r.start_date, r.id), reverse=sort.startswith("-"))

    return {
        "items": requests[offset : offset + limit],
        "total": len(requests),
        "limit": limit,
        "offset": offset,
    }


@router.get("/leave-requests/{request_id}", response_model=LeaveRequestOut)
def get_leave_request(request_id: str, user: User, store: StoreDep) -> LeaveRequest:
    return load_visible_request(store, user, request_id)


@router.post("/leave-requests/{request_id}/approve", response_model=LeaveRequestOut)
async def approve_leave(
    request_id: str,
    user: ManagerUser,
    state: State,
    store: StoreDep,
    background: BackgroundTasks,
) -> LeaveRequest:
    outbox: list[Notification] = []
    request = await store.service.approve(request_id, user.id, outbox=outbox)
    send_later(background, state, outbox)
    return request


@router.post("/leave-requests/{request_id}/reject", response_model=LeaveRequestOut)
async def reject_leave(
    request_id: str,
    body: RejectIn,
    user: ManagerUser,
    state: State,
    store: StoreDep,
    background: BackgroundTasks,
) -> LeaveRequest:
    outbox: list[Notification] = []
    request = await store.service.reject(request_id, user.id, body.reason, outbox=outbox)
    send_later(background, state, outbox)
    return request


@router.delete("/leave-requests/{request_id}", response_model=LeaveRequestOut)
async def cancel_leave(
    request_id: str,
    user: User,
    state: State,
    store: StoreDep,
    background: BackgroundTasks,
) -> LeaveRequest:
    request = store.repository.get_request(request_id)  # NotFoundError -> 404
    if request.employee_id != user.id:
        raise NotAuthorizedError("only the owner can cancel a request")
    if request.status is not LeaveStatus.PENDING:
        # The API only cancels pending requests, as the approved spec says.
        raise InvalidTransitionError(
            f"only PENDING requests can be cancelled here, this one is {request.status.value}"
        )

    outbox: list[Notification] = []
    request = await store.service.cancel(request_id, user.id, outbox=outbox)
    send_later(background, state, outbox)
    return request
