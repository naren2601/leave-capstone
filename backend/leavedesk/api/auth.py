"""Passwords, JWT tokens and the dependencies that protect routes."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import Depends, HTTPException, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from leavedesk.api.settings import Settings

Role = Literal["employee", "manager"]

_hasher = PasswordHasher()  # Argon2id with the library's safe defaults
_bearer = HTTPBearer(auto_error=False)

INVALID_LOGIN = "invalid email or password"
INVALID_TOKEN = "missing, invalid or expired token"  # noqa: S105 (a message, not a secret)


# Passwords


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


# Checked when the email is unknown or the account is locked, so every failed
# login takes as long as a wrong password, and response times reveal nothing.
_DUMMY_HASH = hash_password("not-a-real-password")


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass
class UserAccount:
    employee_id: str
    email: str
    password_hash: str
    role: Role
    failed_logins: int = 0
    locked_until: datetime | None = None


@dataclass(frozen=True)
class LoginPolicy:
    """Day 3, step 5: 5 wrong passwords in a row lock the account for 15 minutes."""

    max_failures: int = 5
    lock_for: timedelta = timedelta(minutes=15)


def check_login(account: UserAccount, password: str, now: datetime, policy: LoginPolicy) -> bool:
    """Check the password and update the account's lockout counters.

    Shared by the in-memory and PostgreSQL stores, so both follow the same rule.
    A locked account is refused even with the right password, with the same
    message as a wrong password, so an attacker cannot tell it is locked.
    """
    if account.locked_until is not None:
        if account.locked_until > now:
            verify_password(_DUMMY_HASH, password)  # same time as a real check
            return False
        account.locked_until, account.failed_logins = None, 0  # the lock has expired

    if verify_password(account.password_hash, password):
        account.failed_logins = 0
        return True

    account.failed_logins += 1
    if account.failed_logins >= policy.max_failures:
        account.locked_until = now + policy.lock_for
        account.failed_logins = 0
    return False


class UserStore:
    """Login accounts in memory (Day 2). PostgreSQL mode uses PostgresUserStore."""

    def __init__(
        self, policy: LoginPolicy | None = None, now: Callable[[], datetime] = _utc_now
    ) -> None:
        self._by_email: dict[str, UserAccount] = {}
        self.policy = policy or LoginPolicy()
        self.now = now

    def add(self, account: UserAccount) -> None:
        self._by_email[account.email.lower()] = account

    def authenticate(self, email: str, password: str) -> UserAccount | None:
        account = self._by_email.get(email.strip().lower())
        if account is None:
            verify_password(_DUMMY_HASH, password)
            return None
        return account if check_login(account, password, self.now(), self.policy) else None


# Tokens


@dataclass(frozen=True)
class CurrentUser:
    id: str
    role: Role

    @property
    def is_manager(self) -> bool:
        return self.role == "manager"


def create_access_token(employee_id: str, role: Role, settings: Settings) -> str:
    now = datetime.now(UTC)
    claims = {
        "sub": employee_id,
        "role": role,
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_minutes),
    }
    return jwt.encode(
        claims, settings.jwt_secret.get_secret_value(), algorithm=settings.jwt_algorithm
    )


def decode_access_token(token: str, settings: Settings) -> CurrentUser:
    try:
        claims = jwt.decode(
            token,
            settings.jwt_secret.get_secret_value(),
            algorithms=[settings.jwt_algorithm],  # never trust the token's own "alg"
            options={"require": ["sub", "role", "exp"]},
        )
    except jwt.InvalidTokenError:
        raise _unauthorized(INVALID_TOKEN) from None
    if claims["role"] not in ("employee", "manager"):
        raise _unauthorized(INVALID_TOKEN)
    return CurrentUser(id=claims["sub"], role=claims["role"])


def _unauthorized(message: str) -> HTTPException:
    return HTTPException(401, message, headers={"WWW-Authenticate": "Bearer"})


# Dependencies


def _settings(request: Request) -> Settings:
    return request.app.state.leavedesk.settings


def _check_still_exists(request: Request, user: CurrentUser) -> CurrentUser:
    # A valid token for a deleted employee must not keep working.
    if not request.app.state.leavedesk.has_employee(user.id):
        raise _unauthorized(INVALID_TOKEN)
    return user


def current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> CurrentUser:
    if credentials is None:
        raise _unauthorized(INVALID_TOKEN)
    user = decode_access_token(credentials.credentials, _settings(request))
    return _check_still_exists(request, user)


def require_manager(user: Annotated[CurrentUser, Depends(current_user)]) -> CurrentUser:
    if not user.is_manager:
        raise HTTPException(403, "only managers can do this")
    return user


def stream_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    access_token: Annotated[str | None, Query()] = None,
) -> CurrentUser:
    """Like current_user, but also accepts ?access_token= for EventSource."""
    token = credentials.credentials if credentials else access_token
    if not token:
        raise _unauthorized(INVALID_TOKEN)
    user = decode_access_token(token, _settings(request))
    return _check_still_exists(request, user)


User = Annotated[CurrentUser, Depends(current_user)]
ManagerUser = Annotated[CurrentUser, Depends(require_manager)]
StreamUser = Annotated[CurrentUser, Depends(stream_user)]
