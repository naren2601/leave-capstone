"""Turn database constraint errors into LeaveDesk's own errors.

The domain checks every rule first, so these only fire in a race: for example,
two requests for the same dates arriving at the same moment. The database is the
last line of defence, and the API still answers with the right error code.
"""

import re

from sqlalchemy.exc import DBAPIError

from leavedesk.domain.exceptions import (
    InsufficientBalanceError,
    InvalidLeaveRequestError,
    LeaveDeskError,
    OverlappingLeaveError,
)

_CONSTRAINT_IN_MESSAGE = re.compile(r'constraint "([^"]+)"')


def _fields(error: DBAPIError) -> dict:
    """pg8000 puts PostgreSQL's error fields in a dict as its first argument."""
    original = error.orig
    details = original.args[0] if getattr(original, "args", None) else None
    return details if isinstance(details, dict) else {}


def sqlstate(error: DBAPIError) -> str | None:
    """PostgreSQL's error code, with psycopg or pg8000. Codes starting 23 are broken rules."""
    original = error.orig
    code = getattr(original, "sqlstate", None)  # psycopg
    return code or _fields(error).get("C")  # pg8000


def constraint_name(error: DBAPIError) -> str | None:
    """The violated constraint's name, with psycopg or pg8000."""
    original = error.orig
    diag = getattr(original, "diag", None)  # psycopg
    if diag is not None and diag.constraint_name:
        return diag.constraint_name
    if _fields(error).get("n"):  # pg8000
        return _fields(error)["n"]
    match = _CONSTRAINT_IN_MESSAGE.search(str(original))
    return match.group(1) if match else None


def domain_error(error: DBAPIError) -> LeaveDeskError | None:
    """The matching LeaveDesk error, or None if the error is unexpected.

    Drivers report broken rules differently (psycopg as IntegrityError, pg8000 as
    ProgrammingError), so the SQLSTATE code decides, not the Python class.
    """
    if not (sqlstate(error) or "").startswith("23"):
        return None
    name = constraint_name(error) or ""
    if name == "no_overlapping_leave":
        return OverlappingLeaveError("these dates overlap another active leave request")
    if name == "ck_leave_balances_no_overspend":
        return InsufficientBalanceError("not enough leave left for this request")
    if name.startswith("ck_leave_requests_"):
        return InvalidLeaveRequestError(f"the request breaks the rule {name}")
    return None
