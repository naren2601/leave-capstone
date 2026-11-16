"""Turn database constraint errors into LeaveDesk's own errors.

The domain checks every rule first, so these only fire in a race: for example,
two requests for the same dates arriving at the same moment. The database is the
last line of defence, and the API still answers with the right error code.
"""

import re

from sqlalchemy.exc import IntegrityError

from leavedesk.domain.exceptions import (
    InsufficientBalanceError,
    InvalidLeaveRequestError,
    LeaveDeskError,
    OverlappingLeaveError,
)

_CONSTRAINT_IN_MESSAGE = re.compile(r'constraint "([^"]+)"')


def constraint_name(error: IntegrityError) -> str | None:
    """The violated constraint's name, with psycopg or pg8000."""
    original = error.orig
    diag = getattr(original, "diag", None)  # psycopg
    if diag is not None and diag.constraint_name:
        return diag.constraint_name
    details = original.args[0] if original.args else None  # pg8000: a dict of fields
    if isinstance(details, dict) and details.get("n"):
        return details["n"]
    match = _CONSTRAINT_IN_MESSAGE.search(str(original))
    return match.group(1) if match else None


def domain_error(error: IntegrityError) -> LeaveDeskError | None:
    """The matching LeaveDesk error, or None if the error is unexpected."""
    name = constraint_name(error) or ""
    if name == "no_overlapping_leave":
        return OverlappingLeaveError("these dates overlap another active leave request")
    if name == "ck_leave_balances_no_overspend":
        return InsufficientBalanceError("not enough leave left for this request")
    if name.startswith("ck_leave_requests_"):
        return InvalidLeaveRequestError(f"the request breaks the rule {name}")
    return None
