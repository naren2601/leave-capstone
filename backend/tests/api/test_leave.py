import pytest

from tests.api.conftest import error_code

# API-4 Apply


def test_apply_returns_201_pending_without_weekends(apply):
    # Friday 13 to Tuesday 17 Nov: 3 working days.
    response = apply(start="2026-11-13", end="2026-11-17", leave_type="SICK")

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "PENDING"
    assert body["days"] == 3
    assert body["employee_id"] == "e1"


def test_half_day_costs_half(apply):
    response = apply(start="2026-11-16", end="2026-11-16", day_part="AM")

    assert response.status_code == 201
    assert response.json()["days"] == 0.5


# API-5 Overlap


def test_overlapping_request_is_409(apply):
    apply(start="2026-11-16", end="2026-11-18")

    response = apply(start="2026-11-18", end="2026-11-20")

    assert response.status_code == 409
    assert error_code(response) == "OVERLAPPING_LEAVE"


# API-6 Invalid dates


@pytest.mark.parametrize(
    "start, end",
    [
        ("2026-11-18", "2026-11-16"),  # end before start
        ("2026-11-21", "2026-11-22"),  # Saturday and Sunday only
    ],
)
def test_invalid_dates_are_422_with_details(apply, start, end):
    response = apply(start=start, end=end)

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert error["details"]


def test_short_reason_is_422_and_names_the_field(apply):
    response = apply(reason="abc")

    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["field"] == "reason"


@pytest.mark.parametrize(
    "body",
    [
        {
            "leave_type": "HOLIDAY",
            "start_date": "2026-11-16",
            "end_date": "2026-11-16",
            "reason": "Trip!",
        },
        {
            "leave_type": "ANNUAL",
            "start_date": "16/11/2026",
            "end_date": "2026-11-16",
            "reason": "Trip!",
        },
        {"leave_type": "ANNUAL", "start_date": "2026-11-16", "reason": "Trip!"},
    ],
)
def test_badly_typed_body_is_422(client, auth, body):
    response = client.post("/leave-requests", json=body, headers=auth("e1"))

    assert response.status_code == 422
    assert error_code(response) == "VALIDATION_ERROR"


def test_malformed_json_is_400(client, auth):
    response = client.post(
        "/leave-requests",
        content=b'{"leave_type": ',
        headers={**auth("e1"), "Content-Type": "application/json"},
    )

    assert response.status_code == 400
    assert error_code(response) == "BAD_REQUEST"


# API-7 Balance


def test_more_days_than_available_is_422(apply):
    # Sick leave has 10 days; 1 to 18 Dec is 14 working days.
    response = apply(start="2026-12-01", end="2026-12-18", leave_type="SICK")

    assert response.status_code == 422
    assert error_code(response) == "INSUFFICIENT_BALANCE"


# API-8 Policy


def test_annual_leave_tomorrow_breaks_policy(apply):
    response = apply(start="2026-11-10", end="2026-11-10")

    assert response.status_code == 422
    assert error_code(response) == "POLICY_VIOLATION"


# API-9 to API-12 Listing


def test_employee_sees_only_their_own_requests(client, auth, apply):
    apply("e1")
    apply("e2")

    body = client.get("/leave-requests", headers=auth("e1")).json()

    assert body["total"] == 1
    assert {r["employee_id"] for r in body["items"]} == {"e1"}


def test_manager_sees_reports_pending_requests_sorted(client, auth, apply):
    apply("e2", start="2026-11-23", end="2026-11-23")
    apply("e1", start="2026-11-16", end="2026-11-16")
    apply("e3", start="2026-11-17", end="2026-11-17")  # Meena's report

    body = client.get("/leave-requests?status=PENDING", headers=auth("m1")).json()

    assert [r["employee_id"] for r in body["items"]] == ["e1", "e2"]
    assert [r["start_date"] for r in body["items"]] == ["2026-11-16", "2026-11-23"]


def test_sort_newest_first(client, auth, apply):
    apply("e1", start="2026-11-16", end="2026-11-16")
    apply("e1", start="2026-11-23", end="2026-11-23")

    body = client.get("/leave-requests?sort=-start_date", headers=auth("e1")).json()

    assert [r["start_date"] for r in body["items"]] == ["2026-11-23", "2026-11-16"]


def test_status_filter(client, auth, apply):
    first = apply("e1", start="2026-11-16", end="2026-11-16").json()
    apply("e1", start="2026-11-23", end="2026-11-23")
    client.post(f"/leave-requests/{first['id']}/approve", headers=auth("m1"))

    body = client.get("/leave-requests?status=APPROVED", headers=auth("e1")).json()

    assert [r["id"] for r in body["items"]] == [first["id"]]


def test_employee_cannot_filter_by_someone_else(client, auth):
    response = client.get("/leave-requests?employee_id=e2", headers=auth("e1"))

    assert response.status_code == 403


def test_manager_can_filter_by_their_report(client, auth, apply):
    apply("e1")
    apply("e2", start="2026-11-23", end="2026-11-23")

    body = client.get("/leave-requests?employee_id=e2", headers=auth("m1")).json()

    assert {r["employee_id"] for r in body["items"]} == {"e2"}


def test_pagination(client, auth, apply):
    for day in ("16", "17", "18", "19", "20"):
        apply("e1", start=f"2026-11-{day}", end=f"2026-11-{day}")

    body = client.get("/leave-requests?limit=2&offset=2", headers=auth("e1")).json()

    assert body["total"] == 5
    assert (body["limit"], body["offset"]) == (2, 2)
    assert [r["start_date"] for r in body["items"]] == ["2026-11-18", "2026-11-19"]


@pytest.mark.parametrize("query", ["limit=0", "limit=101", "offset=-1", "sort=name", "status=LOST"])
def test_bad_list_parameters_are_422(client, auth, query):
    response = client.get(f"/leave-requests?{query}", headers=auth("e1"))

    assert response.status_code == 422


# API-13 Get by id


def test_owner_and_manager_can_get_a_request(client, auth, apply):
    request_id = apply("e1").json()["id"]

    assert client.get(f"/leave-requests/{request_id}", headers=auth("e1")).status_code == 200
    assert client.get(f"/leave-requests/{request_id}", headers=auth("m1")).status_code == 200


@pytest.mark.parametrize("viewer", ["e2", "m2"])
def test_someone_elses_request_is_404(client, auth, apply, viewer):
    request_id = apply("e1").json()["id"]

    response = client.get(f"/leave-requests/{request_id}", headers=auth(viewer))

    assert response.status_code == 404


def test_missing_request_is_404(client, auth):
    response = client.get("/leave-requests/LR-999", headers=auth("e1"))

    assert response.status_code == 404
    assert error_code(response) == "NOT_FOUND"


# API-14 to API-16 Approve


def balance(client, auth, employee_id="e1", leave_type="ANNUAL"):
    rows = client.get(f"/employees/{employee_id}/balance", headers=auth(employee_id)).json()
    return next(row for row in rows if row["leave_type"] == leave_type)


def test_manager_approves_and_days_become_used(client, auth, apply):
    request_id = apply("e1").json()["id"]

    response = client.post(f"/leave-requests/{request_id}/approve", headers=auth("m1"))

    assert response.status_code == 200
    assert response.json()["status"] == "APPROVED"
    row = balance(client, auth)
    assert (row["pending"], row["used"], row["available"]) == (0, 3, 15)


@pytest.mark.parametrize("approver", ["e1", "e2", "m2"])
def test_only_the_owners_manager_can_approve(client, auth, apply, approver):
    request_id = apply("e1").json()["id"]

    response = client.post(f"/leave-requests/{request_id}/approve", headers=auth(approver))

    assert response.status_code == 403
    assert error_code(response) == "FORBIDDEN"
    status = client.get(f"/leave-requests/{request_id}", headers=auth("e1")).json()["status"]
    assert status == "PENDING"


def test_approving_twice_is_409(client, auth, apply):
    request_id = apply("e1").json()["id"]
    client.post(f"/leave-requests/{request_id}/approve", headers=auth("m1"))

    response = client.post(f"/leave-requests/{request_id}/approve", headers=auth("m1"))

    assert response.status_code == 409
    assert error_code(response) == "INVALID_TRANSITION"


def test_approving_missing_request_is_404(client, auth):
    response = client.post("/leave-requests/LR-999/approve", headers=auth("m1"))

    assert response.status_code == 404


# API-17 Reject


def test_reject_with_reason(client, auth, apply):
    request_id = apply("e1").json()["id"]

    response = client.post(
        f"/leave-requests/{request_id}/reject",
        json={"reason": "Release week"},
        headers=auth("m1"),
    )

    assert response.status_code == 200
    assert response.json()["status"] == "REJECTED"
    assert response.json()["decision_note"] == "Release week"
    assert balance(client, auth)["available"] == 18


@pytest.mark.parametrize("body", [{"reason": ""}, {"reason": "   "}, {}])
def test_reject_needs_a_reason(client, auth, apply, body):
    request_id = apply("e1").json()["id"]

    response = client.post(f"/leave-requests/{request_id}/reject", json=body, headers=auth("m1"))

    assert response.status_code == 422
    status = client.get(f"/leave-requests/{request_id}", headers=auth("e1")).json()["status"]
    assert status == "PENDING"


# API-18, API-19 Cancel


def test_owner_cancels_pending_request(client, auth, apply):
    request_id = apply("e1").json()["id"]

    response = client.delete(f"/leave-requests/{request_id}", headers=auth("e1"))

    assert response.status_code == 200
    assert response.json()["status"] == "CANCELLED"
    assert balance(client, auth)["available"] == 18


def test_cancelling_approved_request_is_409(client, auth, apply):
    request_id = apply("e1").json()["id"]
    client.post(f"/leave-requests/{request_id}/approve", headers=auth("m1"))

    response = client.delete(f"/leave-requests/{request_id}", headers=auth("e1"))

    assert response.status_code == 409
    assert error_code(response) == "INVALID_TRANSITION"


@pytest.mark.parametrize("who", ["e2", "m1"])
def test_cancelling_someone_elses_request_is_403(client, auth, apply, who):
    request_id = apply("e1").json()["id"]

    response = client.delete(f"/leave-requests/{request_id}", headers=auth(who))

    assert response.status_code == 403


# API-20 Balance


def test_balance_for_self_and_manager(client, auth):
    for viewer in ("e1", "m1"):
        response = client.get("/employees/e1/balance", headers=auth(viewer))

        assert response.status_code == 200
        assert {row["leave_type"] for row in response.json()} == {"ANNUAL", "SICK", "CASUAL"}


@pytest.mark.parametrize("viewer", ["e2", "m2"])
def test_balance_of_someone_else_is_403(client, auth, viewer):
    assert client.get("/employees/e1/balance", headers=auth(viewer)).status_code == 403


def test_balance_of_unknown_employee_is_404(client, auth):
    assert client.get("/employees/nobody/balance", headers=auth("m1")).status_code == 404
