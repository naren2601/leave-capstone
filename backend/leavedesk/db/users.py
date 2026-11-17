"""Login accounts in PostgreSQL, with the lockout counters saved in the users table."""

from collections.abc import Callable
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from leavedesk.api.auth import (
    _DUMMY_HASH,
    LoginPolicy,
    UserAccount,
    _utc_now,
    check_login,
    verify_password,
)
from leavedesk.db import models as db


class PostgresUserStore:
    """Same job as the in-memory UserStore, but every server shares the counters,
    so an attacker cannot get 5 more tries by hitting another server."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        tenant_id: int,
        policy: LoginPolicy | None = None,
        now: Callable[[], datetime] = _utc_now,
    ) -> None:
        self.session_factory = session_factory
        self.tenant_id = tenant_id
        self.policy = policy or LoginPolicy()
        self.now = now

    def authenticate(self, email: str, password: str) -> UserAccount | None:
        # Its own transaction: a failed login must still save the failure count.
        with self.session_factory.begin() as session:
            found = session.execute(
                self._accounts()
                .where(func.lower(db.Employee.email) == email.strip().lower())
                # Lock the row, so 5 parallel guesses are counted one after another.
                .with_for_update(of=db.User)
            ).first()
            if found is None:
                verify_password(_DUMMY_HASH, password)
                return None

            user, employee = found
            account = _to_account(user, employee)
            ok = check_login(account, password, self.now(), self.policy)
            user.failed_login_count = account.failed_logins
            user.locked_until = account.locked_until
            if ok:
                user.last_login_at = self.now()
            return account if ok else None

    @property
    def _by_email(self) -> dict[str, UserAccount]:
        """Every account by email, read fresh. Kept so the Day 2 tests still work."""
        with self.session_factory() as session:
            rows = session.execute(self._accounts()).all()
            return {employee.email.lower(): _to_account(u, employee) for u, employee in rows}

    def _accounts(self):
        return (
            select(db.User, db.Employee)
            .join(
                db.Employee,
                (db.Employee.tenant_id == db.User.tenant_id)
                & (db.Employee.id == db.User.employee_id),
            )
            .where(db.User.tenant_id == self.tenant_id)
        )


def _to_account(user: db.User, employee: db.Employee) -> UserAccount:
    return UserAccount(
        employee_id=employee.code,
        email=employee.email,
        password_hash=user.password_hash,
        role="manager" if employee.is_manager else "employee",
        failed_logins=user.failed_login_count,
        locked_until=user.locked_until,
    )
