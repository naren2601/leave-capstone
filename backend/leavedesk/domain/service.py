"""LeaveService: applies, approves, rejects and cancels leave.

LeaveService uses composition. It has a repository, one policy per leave
type and a list of notifiers, and any of them can be swapped.
"""

from collections.abc import Callable
from datetime import date

from pydantic import ValidationError

from leavedesk.domain.dates import count_leave_days, find_overlap
from leavedesk.domain.exceptions import (
    InvalidLeaveRequestError,
    NotAuthorizedError,
    OverlappingLeaveError,
)
from leavedesk.domain.instrumentation import audit
from leavedesk.domain.models import (
    DayPart,
    Employee,
    LeaveRequest,
    LeaveStatus,
    LeaveType,
    Manager,
)
from leavedesk.domain.notifications import (
    Notification,
    NotificationEvent,
    Notifier,
    build_notifications,
    dispatch,
)
from leavedesk.domain.policies import LeaveBalance, LeavePolicy, default_policies
from leavedesk.domain.repository import LeaveRepository

# A placeholder id used while a new request is being checked.
NEW_REQUEST_ID = "NEW"


class LeaveService:
    def __init__(
        self,
        repository: LeaveRepository,
        policies: dict[LeaveType, LeavePolicy] | None = None,
        notifiers: list[Notifier] | None = None,
        today: Callable[[], date] = date.today,
    ) -> None:
        self.repository = repository
        self.policies = policies or default_policies()
        self.notifiers = notifiers or []
        # Tests and the demo pass a fixed date so results never change.
        self.today = today
        self.sent: list[Notification] = []

    def using(self, repository: LeaveRepository) -> "LeaveService":
        """A copy of this service that works on another repository.

        The API makes one per request, so each request uses its own database
        session while sharing the same policies, notifiers and clock.
        """
        return LeaveService(repository, self.policies, self.notifiers, self.today)

    # Public actions

    @audit
    async def apply(
        self,
        employee_id: str,
        leave_type: LeaveType,
        start_date: date,
        end_date: date,
        reason: str,
        day_part: DayPart = DayPart.FULL,
        outbox: list[Notification] | None = None,
    ) -> LeaveRequest:
        employee = self.repository.get_employee(employee_id)
        if employee.manager_id is None:
            raise InvalidLeaveRequestError(
                "you have no manager, so nobody can approve this request"
            )
        self.repository.get_employee(employee.manager_id)  # must exist

        request = self._build_request(
            employee_id, leave_type, start_date, end_date, reason, day_part
        )
        request.days = count_leave_days(start_date, end_date, request.day_part)

        policy = self.policies[request.leave_type]
        policy.validate(request, self.today())

        clash = find_overlap(request, self.repository.requests_for(employee_id))
        if clash is not None:
            raise OverlappingLeaveError(
                f"these dates overlap request {clash.id} "
                f"({clash.start_date} to {clash.end_date}, {clash.status.value})"
            )

        balance = self.get_balance(employee_id, request.leave_type)
        balance.reserve(request.days)  # raises InsufficientBalanceError

        # Give the request a real id only once every check has passed.
        request.id = self.repository.next_request_id()
        self._save(request, balance)
        await self._notify(NotificationEvent.SUBMITTED, request, employee, outbox)
        return request

    @audit
    async def approve(
        self,
        request_id: str,
        manager_id: str,
        outbox: list[Notification] | None = None,
    ) -> LeaveRequest:
        request, employee = self._load_for_manager(request_id, manager_id)

        request.transition_to(LeaveStatus.APPROVED, self.today())
        balance = self.get_balance(employee.id, request.leave_type)
        balance.confirm(request.days)

        self._save(request, balance)
        await self._notify(NotificationEvent.APPROVED, request, employee, outbox)
        return request

    @audit
    async def reject(
        self,
        request_id: str,
        manager_id: str,
        note: str,
        outbox: list[Notification] | None = None,
    ) -> LeaveRequest:
        if not note or not note.strip():
            raise InvalidLeaveRequestError("a reason is needed to reject leave")
        request, employee = self._load_for_manager(request_id, manager_id)

        request.transition_to(LeaveStatus.REJECTED, self.today())
        request.decision_note = note.strip()
        balance = self.get_balance(employee.id, request.leave_type)
        balance.release_pending(request.days)

        self._save(request, balance)
        await self._notify(NotificationEvent.REJECTED, request, employee, outbox)
        return request

    @audit
    async def cancel(
        self,
        request_id: str,
        employee_id: str,
        outbox: list[Notification] | None = None,
    ) -> LeaveRequest:
        request = self.repository.get_request(request_id)
        if request.employee_id != employee_id:
            raise NotAuthorizedError("only the owner can cancel a request")
        employee = self.repository.get_employee(employee_id)

        was_approved = request.status is LeaveStatus.APPROVED
        request.transition_to(LeaveStatus.CANCELLED, self.today())

        balance = self.get_balance(employee_id, request.leave_type)
        if was_approved:
            balance.restore_used(request.days)
        else:
            balance.release_pending(request.days)

        self._save(request, balance)
        await self._notify(NotificationEvent.CANCELLED, request, employee, outbox)
        return request

    def get_balance(self, employee_id: str, leave_type: LeaveType) -> LeaveBalance:
        balance = self.repository.find_balance(employee_id, leave_type)
        if balance is None:
            balance = self.policies[leave_type].new_balance(employee_id)
        return balance

    # Helpers

    def _build_request(
        self, employee_id, leave_type, start_date, end_date, reason, day_part
    ) -> LeaveRequest:
        """Create the request, turning Pydantic errors into our own error."""
        try:
            return LeaveRequest(
                id=NEW_REQUEST_ID,
                employee_id=employee_id,
                leave_type=leave_type,
                start_date=start_date,
                end_date=end_date,
                reason=reason,
                day_part=day_part,
            )
        except ValidationError as error:
            details = [
                {
                    "field": ".".join(str(part) for part in e["loc"]) or None,
                    "problem": e["msg"].removeprefix("Value error, "),
                }
                for e in error.errors()
            ]
            message = "; ".join(d["problem"] for d in details)
            raise InvalidLeaveRequestError(message, details) from None

    def _load_for_manager(self, request_id: str, manager_id: str) -> tuple[LeaveRequest, Employee]:
        request = self.repository.get_request(request_id)
        employee = self.repository.get_employee(request.employee_id)
        approver = self.repository.get_employee(manager_id)
        if not (isinstance(approver, Manager) and approver.manages(employee)):
            raise NotAuthorizedError(f"{approver.name} is not {employee.name}'s manager")
        return request, employee

    def _save(self, request: LeaveRequest, balance: LeaveBalance) -> None:
        self.repository.save_changes(request, balance)

    async def _notify(
        self,
        event: NotificationEvent,
        request: LeaveRequest,
        employee: Employee,
        outbox: list[Notification] | None,
    ) -> None:
        """Send notifications now, or add them to outbox for the caller to send.

        The API passes an outbox so it can send them in a background task,
        after the response has gone back to the client.
        """
        manager = self.repository.get_employee(employee.manager_id)
        notifications = build_notifications(event, request, employee, manager)
        self.sent.extend(notifications)
        if outbox is not None:
            outbox.extend(notifications)
            return
        await dispatch(self.notifiers, notifications)
