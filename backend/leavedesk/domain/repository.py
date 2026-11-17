"""Storage for LeaveDesk.

LeaveService only talks to the abstract LeaveRepository, so the in-memory
version can later be swapped for a database without changing the service.
"""

from abc import ABC, abstractmethod
from itertools import count

from leavedesk.domain.exceptions import NotFoundError
from leavedesk.domain.models import Employee, LeaveRequest, LeaveType
from leavedesk.domain.policies import LeaveBalance


class LeaveRepository(ABC):
    @abstractmethod
    def add_employee(self, employee: Employee) -> None: ...

    @abstractmethod
    def get_employee(self, employee_id: str) -> Employee: ...

    @abstractmethod
    def list_employees(self) -> list[Employee]: ...

    @abstractmethod
    def next_request_id(self) -> str: ...

    @abstractmethod
    def save_request(self, request: LeaveRequest) -> None: ...

    @abstractmethod
    def get_request(self, request_id: str) -> LeaveRequest: ...

    @abstractmethod
    def requests_for(self, employee_id: str) -> list[LeaveRequest]: ...

    @abstractmethod
    def find_balance(self, employee_id: str, leave_type: LeaveType) -> LeaveBalance | None: ...

    @abstractmethod
    def save_balance(self, balance: LeaveBalance) -> None: ...

    @abstractmethod
    def find_by_idempotency_key(self, employee_id: str, key: str) -> LeaveRequest | None:
        """The request first created with this Idempotency-Key, if any."""

    @abstractmethod
    def remember_idempotency_key(self, employee_id: str, key: str, request_id: str) -> None:
        """Record which request an Idempotency-Key created."""

    def save_changes(self, request: LeaveRequest, balance: LeaveBalance) -> None:
        """Save a request and the balance it changed, as one unit.

        A database repository overrides this so it can record the balance change
        in its ledger, linked to the request that caused it.
        """
        self.save_balance(balance)
        self.save_request(request)


class InMemoryLeaveRepository(LeaveRepository):
    """Keeps everything in dictionaries. Data is lost when the program ends."""

    def __init__(self) -> None:
        self._employees: dict[str, Employee] = {}
        self._requests: dict[str, LeaveRequest] = {}
        self._balances: dict[tuple[str, LeaveType], LeaveBalance] = {}
        self._ids = count(1)
        self._idempotency_keys: dict[tuple[str, str], str] = {}

    def add_employee(self, employee: Employee) -> None:
        self._employees[employee.id] = employee

    def get_employee(self, employee_id: str) -> Employee:
        try:
            return self._employees[employee_id]
        except KeyError:
            raise NotFoundError(f"no employee with id {employee_id}") from None

    def list_employees(self) -> list[Employee]:
        return list(self._employees.values())

    def next_request_id(self) -> str:
        return f"LR-{next(self._ids)}"

    def save_request(self, request: LeaveRequest) -> None:
        self._requests[request.id] = request

    def get_request(self, request_id: str) -> LeaveRequest:
        try:
            return self._requests[request_id]
        except KeyError:
            raise NotFoundError(f"no leave request with id {request_id}") from None

    def requests_for(self, employee_id: str) -> list[LeaveRequest]:
        return [
            request for request in self._requests.values() if request.employee_id == employee_id
        ]

    def find_balance(self, employee_id: str, leave_type: LeaveType) -> LeaveBalance | None:
        return self._balances.get((employee_id, leave_type))

    def save_balance(self, balance: LeaveBalance) -> None:
        self._balances[(balance.employee_id, balance.leave_type)] = balance

    def find_by_idempotency_key(self, employee_id: str, key: str) -> LeaveRequest | None:
        request_id = self._idempotency_keys.get((employee_id, key))
        return None if request_id is None else self._requests[request_id]

    def remember_idempotency_key(self, employee_id: str, key: str, request_id: str) -> None:
        self._idempotency_keys[(employee_id, key)] = request_id
