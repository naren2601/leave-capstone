from datetime import date

import pytest

from leavedesk.domain.dates import (
    count_leave_days,
    find_overlap,
    requests_overlap,
    working_days,
)
from leavedesk.domain.exceptions import InvalidLeaveRequestError
from leavedesk.domain.models import DayPart, LeaveRequest, LeaveStatus, LeaveType

MONDAY = date(2026, 11, 9)
TUESDAY = date(2026, 11, 10)
WEDNESDAY = date(2026, 11, 11)
THURSDAY = date(2026, 11, 12)
FRIDAY = date(2026, 11, 13)
SATURDAY = date(2026, 11, 14)
SUNDAY = date(2026, 11, 15)
NEXT_MONDAY = date(2026, 11, 16)
NEXT_TUESDAY = date(2026, 11, 17)


def make_request(id="r1", start=MONDAY, end=TUESDAY, **changes):
    data = {
        "id": id,
        "employee_id": "e1",
        "leave_type": LeaveType.ANNUAL,
        "start_date": start,
        "end_date": end,
        "reason": "Family trip",
    }
    return LeaveRequest(**{**data, **changes})


# Working days (FR-2, EC-2)


def test_friday_to_tuesday_skips_the_weekend():
    assert working_days(FRIDAY, NEXT_TUESDAY) == 3


def test_full_week_has_five_working_days():
    assert working_days(MONDAY, SUNDAY) == 5


def test_single_weekday_is_one_day():
    assert working_days(WEDNESDAY, WEDNESDAY) == 1


def test_weekend_only_has_no_working_days():
    assert working_days(SATURDAY, SUNDAY) == 0


def test_working_days_rejects_end_before_start():
    with pytest.raises(InvalidLeaveRequestError):
        working_days(TUESDAY, MONDAY)


def test_full_day_leave_cost():
    assert count_leave_days(FRIDAY, NEXT_TUESDAY) == 3.0


@pytest.mark.parametrize("day_part", [DayPart.AM, DayPart.PM])
def test_half_day_costs_half(day_part):
    assert count_leave_days(MONDAY, MONDAY, day_part) == 0.5


def test_weekend_only_request_is_rejected():
    with pytest.raises(InvalidLeaveRequestError):
        count_leave_days(SATURDAY, SUNDAY)


# Overlaps (FR-3, EC-3)


@pytest.mark.parametrize(
    "start, end",
    [
        (MONDAY, TUESDAY),  # same dates
        (TUESDAY, WEDNESDAY),  # shares the last day
        (date(2026, 11, 6), MONDAY),  # shares the first day
        (date(2026, 11, 6), FRIDAY),  # covers the whole request
        (TUESDAY, TUESDAY),  # inside the request
    ],
)
def test_requests_that_share_a_date_overlap(start, end):
    existing = make_request(id="old")
    new = make_request(id="new", start=start, end=end)

    assert requests_overlap(new, existing)


def test_requests_on_separate_dates_do_not_overlap():
    existing = make_request(id="old")
    new = make_request(id="new", start=WEDNESDAY, end=THURSDAY)

    assert not requests_overlap(new, existing)


def test_am_and_pm_on_same_date_do_not_overlap():
    morning = make_request(id="am", end=MONDAY, day_part=DayPart.AM)
    afternoon = make_request(id="pm", end=MONDAY, day_part=DayPart.PM)

    assert not requests_overlap(afternoon, morning)


def test_same_half_on_same_date_overlaps():
    first = make_request(id="a", end=MONDAY, day_part=DayPart.AM)
    second = make_request(id="b", end=MONDAY, day_part=DayPart.AM)

    assert requests_overlap(second, first)


def test_half_day_inside_full_day_leave_overlaps():
    full = make_request(id="full")
    half = make_request(id="half", end=MONDAY, day_part=DayPart.PM)

    assert requests_overlap(half, full)


@pytest.mark.parametrize("status", [LeaveStatus.PENDING, LeaveStatus.APPROVED])
def test_find_overlap_returns_active_clash(status):
    existing = make_request(id="old", status=status)
    new = make_request(id="new")

    assert find_overlap(new, [existing]) is existing


@pytest.mark.parametrize("status", [LeaveStatus.REJECTED, LeaveStatus.CANCELLED])
def test_find_overlap_ignores_closed_requests(status):
    existing = make_request(id="old", status=status)
    new = make_request(id="new")

    assert find_overlap(new, [existing]) is None


def test_find_overlap_ignores_other_employees():
    existing = make_request(id="old", employee_id="e2")
    new = make_request(id="new")

    assert find_overlap(new, [existing]) is None


def test_find_overlap_ignores_the_request_itself():
    request = make_request()

    assert find_overlap(request, [request]) is None


def test_find_overlap_with_no_requests():
    assert find_overlap(make_request(), []) is None
