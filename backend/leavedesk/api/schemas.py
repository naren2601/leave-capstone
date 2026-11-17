"""Request and response bodies. Field rules live in the domain, not here."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from leavedesk.domain.models import DayPart, LeaveStatus, LeaveType
from leavedesk.domain.notifications import NotificationEvent


class Page[T](BaseModel):
    items: list[T]
    total: int
    limit: int
    offset: int
    # Keyset pagination (Day 3, step 6): pass this as ?cursor= to get the next page.
    # None when there is no next page, or where a list does not support cursors.
    next_cursor: str | None = None


class LoginIn(BaseModel):
    email: str
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"  # noqa: S105 (a token type, not a secret)
    expires_in: int  # seconds


class ApplyLeaveIn(BaseModel):
    leave_type: LeaveType
    start_date: date
    end_date: date
    day_part: DayPart = DayPart.FULL
    reason: str


class RejectIn(BaseModel):
    reason: str


class LeaveRequestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    employee_id: str
    leave_type: LeaveType
    start_date: date
    end_date: date
    day_part: DayPart
    reason: str
    status: LeaveStatus
    days: float
    decision_note: str | None
    version: int  # send it back as If-Match to approve, reject or cancel safely


class EmployeeOut(BaseModel):
    id: str
    name: str
    manager_id: str | None


class BalanceOut(BaseModel):
    leave_type: LeaveType
    entitled: float
    used: float
    pending: float
    available: float


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    recipient: str
    event: NotificationEvent
    message: str
    read: bool
    created_at: datetime


class ReadAllOut(BaseModel):
    updated: int
