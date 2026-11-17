"""LeaveRepository backed by PostgreSQL through SQLAlchemy.

One repository is made per API request, around one session and one transaction.
It translates between the domain objects (Day 1) and the database rows (Day 3):

- Employees are identified by their code ("e1") in the domain and by a bigint id
  in the database.
- Leave requests use UUIDv7 ids; the domain sees them as strings.
- Every balance change appends a ledger row, so a balance always equals the sum
  of its ledger movements.
- Requests and balances are read with SELECT ... FOR UPDATE, so two transactions
  that change the same request or balance run one after the other, never at once.
"""

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import Select, func, select, text, tuple_
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, selectinload
from sqlalchemy.orm.exc import StaleDataError

from leavedesk.db import models as db
from leavedesk.db.errors import domain_error
from leavedesk.db.ids import uuid7
from leavedesk.domain.exceptions import (
    InvalidLeaveRequestError,
    NotFoundError,
    VersionConflictError,
)
from leavedesk.domain.models import (
    DayPart,
    Employee,
    LeaveRequest,
    LeaveStatus,
    LeaveType,
    Manager,
)
from leavedesk.domain.policies import LeaveBalance
from leavedesk.domain.repository import LeaveRepository, RequestPage


class PostgresLeaveRepository(LeaveRepository):
    def __init__(self, session: Session, tenant_id: int, year: int) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.year = year  # balances are kept per calendar year
        # Employee code -> internal id, remembered for this request only (step 6).
        # Codes never change, and a repository lives for one transaction.
        self._ids_by_code: dict[str, int] = {}

    # Employees

    def add_employee(self, employee: Employee) -> None:
        manager_id = None
        if employee.manager_id is not None:
            manager_id = self._employee_row(employee.manager_id).id
        self.session.add(
            db.Employee(
                tenant_id=self.tenant_id,
                code=employee.id,
                name=employee.name,
                email=employee.email,
                is_manager=isinstance(employee, Manager),
                manager_id=manager_id,
            )
        )
        self._flush()

    def get_employee(self, employee_id: str) -> Employee:
        return _to_domain_employee(self._employee_row(employee_id, load_manager=True))

    def list_employees(self) -> list[Employee]:
        rows = self.session.scalars(
            select(db.Employee)
            .where(db.Employee.tenant_id == self.tenant_id)
            .options(selectinload(db.Employee.manager))
            .order_by(db.Employee.code)
        )
        return [_to_domain_employee(row) for row in rows]

    # Leave requests

    def next_request_id(self) -> str:
        return str(uuid7())

    def save_request(self, request: LeaveRequest) -> None:
        row = self._save_request_row(request)
        self._flush()
        request.version = row.version

    def get_request(self, request_id: str) -> LeaveRequest:
        return _to_domain_request(self._request_row(request_id))

    def requests_for(self, employee_id: str) -> list[LeaveRequest]:
        rows = self.session.scalars(
            select(db.LeaveRequest)
            .join(
                db.Employee,
                (db.Employee.id == db.LeaveRequest.employee_id)
                & (db.Employee.tenant_id == db.LeaveRequest.tenant_id),
            )
            .where(db.LeaveRequest.tenant_id == self.tenant_id, db.Employee.code == employee_id)
            .options(
                selectinload(db.LeaveRequest.employee), selectinload(db.LeaveRequest.leave_type)
            )
            .order_by(db.LeaveRequest.start_date, db.LeaveRequest.id)
        )
        return [_to_domain_request(row) for row in rows]

    # Lists and search (step 6): the database filters, sorts and pages

    def direct_reports(self, manager_id: str) -> list[Employee]:
        manager = manager_id_of(self.tenant_id, manager_id)
        rows = self.session.scalars(
            select(db.Employee)
            .where(db.Employee.tenant_id == self.tenant_id, db.Employee.manager_id == manager)
            .options(selectinload(db.Employee.manager))
            .order_by(db.Employee.code)
        ).all()
        self._ids_by_code.update((row.code, row.id) for row in rows)
        return [_to_domain_employee(row) for row in rows]

    def search_employees(self, text: str, limit: int) -> list[Employee]:
        # Contains-search, ignoring case. The trigram index (migration 0003) makes
        # '%text%' fast; a normal B-tree index cannot help with a leading '%'.
        # Escape LIKE's wildcards, so a search for "50%" means the characters "50%".
        escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        rows = self.session.scalars(
            select(db.Employee)
            .where(
                db.Employee.tenant_id == self.tenant_id,
                db.Employee.name.ilike(f"%{escaped}%", escape="\\"),
            )
            .options(selectinload(db.Employee.manager))
            .order_by(db.Employee.name, db.Employee.code)
            .limit(limit)
        )
        return [_to_domain_employee(row) for row in rows]

    def page_requests(
        self,
        employee_ids: set[str],
        status: LeaveStatus | None,
        descending: bool,
        limit: int,
        offset: int = 0,
        after: tuple[date, str] | None = None,
    ) -> RequestPage:
        query = self.request_list_query(employee_ids, status)
        total = self.session.scalar(select(func.count()).select_from(query.subquery()))
        rows = self.session.scalars(
            self.request_page_query(query, descending, limit + 1, offset, after).options(
                selectinload(db.LeaveRequest.employee), selectinload(db.LeaveRequest.leave_type)
            )
        ).all()
        items = [_to_domain_request(row) for row in rows[:limit]]
        return RequestPage(items, total or 0, has_more=len(rows) > limit)

    def request_list_query(
        self, employee_ids: set[str], status: LeaveStatus | None
    ) -> Select[tuple[db.LeaveRequest]]:
        query = select(db.LeaveRequest).where(
            db.LeaveRequest.tenant_id == self.tenant_id,
            db.LeaveRequest.employee_id.in_(self._employee_ids(employee_ids)),
        )
        if status is not None:
            query = query.where(db.LeaveRequest.status == status.value)
        return query

    @staticmethod
    def request_page_query(
        query: Select,
        descending: bool,
        limit: int,
        offset: int = 0,
        after: tuple[date, str] | None = None,
    ) -> Select:
        key = tuple_(db.LeaveRequest.start_date, db.LeaveRequest.id)
        if after is not None:
            start, request_id = after
            try:
                last_seen = tuple_(start, uuid.UUID(request_id))
            except ValueError:
                raise InvalidLeaveRequestError("the cursor is not valid") from None
            # Keyset: "after the last row I saw". The index jumps straight there,
            # instead of reading and throwing away `offset` rows.
            query = query.where(key < last_seen if descending else key > last_seen)
        order = (
            (db.LeaveRequest.start_date.desc(), db.LeaveRequest.id.desc())
            if descending
            else (db.LeaveRequest.start_date, db.LeaveRequest.id)
        )
        return query.order_by(*order).limit(limit).offset(offset)

    # Balances

    def find_balance(self, employee_id: str, leave_type: LeaveType) -> LeaveBalance | None:
        row = self._balance_row(employee_id, leave_type)
        return None if row is None else _to_domain_balance(row, employee_id, leave_type)

    def save_balance(self, balance: LeaveBalance) -> None:
        """Save a balance with no request behind the change: entitlements only."""
        row = self._balance_row(balance.employee_id, balance.leave_type, create=True)
        self._apply_balance_change(row, balance, request_id=None)
        self._flush()

    def save_changes(self, request: LeaveRequest, balance: LeaveBalance) -> None:
        # The request first, because its ledger row refers to it.
        request_row = self._save_request_row(request)
        self._flush()
        balance_row = self._balance_row(balance.employee_id, balance.leave_type, create=True)
        self._apply_balance_change(balance_row, balance, request_id=request_row.id)
        self._flush()
        request.version = request_row.version  # the database's count is the real one

    # Idempotency keys

    def find_by_idempotency_key(self, employee_id: str, key: str) -> LeaveRequest | None:
        # Two retries with the same key can arrive at the same moment. This lock makes
        # the second wait until the first commits, so it then finds the first's request
        # instead of creating a duplicate. The lock ends with the transaction.
        self.session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:lock, 0))"),
            {"lock": f"idempotency:{self.tenant_id}:{employee_id}:{key}"},
        )
        request_id = self.session.scalar(
            select(db.IdempotencyKey.leave_request_id).where(
                db.IdempotencyKey.tenant_id == self.tenant_id,
                db.IdempotencyKey.employee_id == self._employee_row(employee_id).id,
                db.IdempotencyKey.key == key,
            )
        )
        return None if request_id is None else self.get_request(str(request_id))

    def remember_idempotency_key(self, employee_id: str, key: str, request_id: str) -> None:
        self.session.add(
            db.IdempotencyKey(
                tenant_id=self.tenant_id,
                employee_id=self._employee_row(employee_id).id,
                key=key,
                leave_request_id=uuid.UUID(request_id),
            )
        )
        self._flush()

    def ledger_total(self, employee_id: str, leave_type: LeaveType) -> dict[str, Decimal]:
        """The sum of every ledger movement for one balance (used to check it)."""
        employee, leave_type_row = self._employee_row(employee_id), self._leave_type_row(leave_type)
        entitled, pending, used = self.session.execute(
            select(
                func.coalesce(func.sum(db.LeaveLedger.entitled_delta), 0),
                func.coalesce(func.sum(db.LeaveLedger.pending_delta), 0),
                func.coalesce(func.sum(db.LeaveLedger.used_delta), 0),
            ).where(
                db.LeaveLedger.tenant_id == self.tenant_id,
                db.LeaveLedger.employee_id == employee.id,
                db.LeaveLedger.leave_type_id == leave_type_row.id,
                db.LeaveLedger.year == self.year,
            )
        ).one()
        return {"entitled": entitled, "pending": pending, "used": used}

    # Rows

    def _employee_row(self, code: str, load_manager: bool = False) -> db.Employee:
        query = select(db.Employee).where(
            db.Employee.tenant_id == self.tenant_id, db.Employee.code == code
        )
        if load_manager:
            query = query.options(selectinload(db.Employee.manager))
        row = self.session.scalar(query)
        if row is None:
            raise NotFoundError(f"no employee with id {code}")
        self._ids_by_code[row.code] = row.id
        return row

    def _employee_ids(self, codes: set[str]) -> list[int]:
        """Internal ids for these codes. Looks up only the ones not seen yet, so
        a manager's team (just loaded by direct_reports) costs no query at all."""
        missing = codes - self._ids_by_code.keys()
        if missing:
            found = self.session.execute(
                select(db.Employee.code, db.Employee.id).where(
                    db.Employee.tenant_id == self.tenant_id, db.Employee.code.in_(missing)
                )
            ).all()
            self._ids_by_code.update(found)
        return [self._ids_by_code[c] for c in codes if c in self._ids_by_code]

    def _leave_type_row(self, leave_type: LeaveType) -> db.LeaveType:
        row = self.session.scalar(
            select(db.LeaveType).where(
                db.LeaveType.tenant_id == self.tenant_id, db.LeaveType.code == leave_type.value
            )
        )
        if row is None:
            raise NotFoundError(f"leave type {leave_type.value} is not set up")
        return row

    def _request_row(self, request_id: str) -> db.LeaveRequest:
        try:
            key = uuid.UUID(request_id)
        except ValueError:
            raise NotFoundError(f"no leave request with id {request_id}") from None
        row = self.session.scalar(
            select(db.LeaveRequest)
            .where(db.LeaveRequest.tenant_id == self.tenant_id, db.LeaveRequest.id == key)
            .options(
                selectinload(db.LeaveRequest.employee), selectinload(db.LeaveRequest.leave_type)
            )
            .with_for_update(of=db.LeaveRequest)
        )
        if row is None:
            raise NotFoundError(f"no leave request with id {request_id}")
        return row

    def _save_request_row(self, request: LeaveRequest) -> db.LeaveRequest:
        key = uuid.UUID(request.id)
        row = self.session.get(db.LeaveRequest, key)
        if row is None:
            row = db.LeaveRequest(
                id=key,
                tenant_id=self.tenant_id,
                employee_id=self._employee_row(request.employee_id).id,
                leave_type_id=self._leave_type_row(request.leave_type).id,
                start_date=request.start_date,
                end_date=request.end_date,
                day_part=request.day_part.value,
                reason=request.reason,
                days=Decimal(str(request.days)),
            )
            self.session.add(row)
        # Only these can change after a request is created.
        row.status = request.status.value
        row.decision_note = request.decision_note
        return row

    def _balance_row(
        self, employee_id: str, leave_type: LeaveType, create: bool = False
    ) -> db.LeaveBalance | None:
        employee = self._employee_row(employee_id)
        leave_type_row = self._leave_type_row(leave_type)
        key = (self.tenant_id, employee.id, leave_type_row.id, self.year)
        row = self.session.get(db.LeaveBalance, key, with_for_update=True)
        if row is None and create:
            row = db.LeaveBalance(
                tenant_id=self.tenant_id,
                employee_id=employee.id,
                leave_type_id=leave_type_row.id,
                year=self.year,
                entitled=Decimal("0"),
                used=Decimal("0"),
                pending=Decimal("0"),
            )
            self.session.add(row)
            self._flush()
        return row

    def _apply_balance_change(
        self, row: db.LeaveBalance, balance: LeaveBalance, request_id: uuid.UUID | None
    ) -> None:
        entitled = Decimal(str(balance.entitled)) - row.entitled
        pending = Decimal(str(balance.pending)) - row.pending
        used = Decimal(str(balance.used)) - row.used

        # A brand-new balance gets its entitlement as its own ledger row first.
        if entitled != 0 and (pending != 0 or used != 0):
            self._append_ledger(row, "ENTITLEMENT", entitled, Decimal(0), Decimal(0), None)
            entitled = Decimal(0)

        movement = _movement(entitled, pending, used, request_id)
        if movement is not None:
            self._append_ledger(row, movement, entitled, pending, used, request_id)

    def _append_ledger(
        self,
        row: db.LeaveBalance,
        movement: str,
        entitled: Decimal,
        pending: Decimal,
        used: Decimal,
        request_id: uuid.UUID | None,
    ) -> None:
        """Add one ledger row and apply the same change to the balance row."""
        row.entitled += entitled
        row.pending += pending
        row.used += used
        self.session.add(
            db.LeaveLedger(
                tenant_id=self.tenant_id,
                employee_id=row.employee_id,
                leave_type_id=row.leave_type_id,
                year=row.year,
                leave_request_id=request_id if movement != "ENTITLEMENT" else None,
                movement=movement,
                entitled_delta=entitled,
                pending_delta=pending,
                used_delta=used,
            )
        )

    def _flush(self) -> None:
        try:
            self.session.flush()
        except StaleDataError as error:
            # The version column did not match: someone else changed the row first.
            raise VersionConflictError("the request was changed by someone else") from error
        except DBAPIError as error:
            known = domain_error(error)
            if known is None:
                raise
            raise known from error


def _movement(
    entitled: Decimal, pending: Decimal, used: Decimal, request_id: uuid.UUID | None
) -> str | None:
    """Name the ledger movement for a balance change, as in SCHEMA.md."""
    if entitled == pending == used == 0:
        return None
    if pending == used == 0:
        return "ENTITLEMENT"
    if request_id is None:
        raise ValueError("only entitlements can change a balance without a request")
    if entitled == 0 and used == 0:
        return "RESERVE" if pending > 0 else "RELEASE"
    if entitled == 0 and pending < 0 and used == -pending:
        return "CONSUME"
    if entitled == 0 and pending == 0 and used < 0:
        return "RESTORE"
    raise ValueError(f"unexpected balance change: {entitled=} {pending=} {used=}")


# Rows to domain objects


def _to_domain_employee(row: db.Employee) -> Employee:
    model = Manager if row.is_manager else Employee
    return model(
        id=row.code,
        name=row.name,
        email=row.email,
        manager_id=row.manager.code if row.manager is not None else None,
    )


def _to_domain_request(row: db.LeaveRequest) -> LeaveRequest:
    return LeaveRequest(
        id=str(row.id),
        employee_id=row.employee.code,
        leave_type=LeaveType(row.leave_type.code),
        start_date=row.start_date,
        end_date=row.end_date,
        day_part=DayPart(row.day_part),
        reason=row.reason,
        status=LeaveStatus(row.status),
        days=float(row.days),
        decision_note=row.decision_note,
        version=row.version,
    )


def _to_domain_balance(
    row: db.LeaveBalance, employee_id: str, leave_type: LeaveType
) -> LeaveBalance:
    return LeaveBalance(
        employee_id=employee_id,
        leave_type=leave_type,
        entitled=float(row.entitled),
        used=float(row.used),
        pending=float(row.pending),
    )


def manager_id_of(tenant_id: int, manager_code: str):
    """The manager's internal id, as a subquery (one round trip, not two)."""
    return (
        select(db.Employee.id)
        .where(db.Employee.tenant_id == tenant_id, db.Employee.code == manager_code)
        .scalar_subquery()
    )
