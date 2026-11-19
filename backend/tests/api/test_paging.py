"""Day 3, step 6: keyset pagination and name search. Both backends."""

import pytest

from tests.api.conftest import error_code
from tests.postgres import requires_postgres


@pytest.fixture
def six_requests(apply):
    """Six one-day requests for Asha, on six different days."""
    days = ["2026-11-16", "2026-11-17", "2026-11-18", "2026-11-19", "2026-11-20", "2026-11-23"]
    return [apply("e1", start=d, end=d).json()["id"] for d in days]


def walk(client, auth, url):
    """Follow next_cursor until the last page. Returns every id and the page count."""
    ids, pages, cursor = [], 0, None
    while True:
        response = client.get(url + (f"&cursor={cursor}" if cursor else ""), headers=auth("e1"))
        assert response.status_code == 200
        body = response.json()
        ids += [item["id"] for item in body["items"]]
        pages += 1
        cursor = body["next_cursor"]
        if cursor is None:
            return ids, pages


def test_cursor_pages_return_everything_once_in_order(client, auth, six_requests):
    ids, pages = walk(client, auth, "/leave-requests?limit=4")

    assert ids == six_requests  # applied in date order
    assert pages == 2


def test_cursor_pages_newest_first(client, auth, six_requests):
    ids, _ = walk(client, auth, "/leave-requests?limit=4&sort=-start_date")

    assert ids == list(reversed(six_requests))


def test_cursor_and_offset_give_the_same_pages(client, auth, six_requests):
    first = client.get("/leave-requests?limit=2", headers=auth("e1")).json()
    by_cursor = client.get(
        f"/leave-requests?limit=2&cursor={first['next_cursor']}", headers=auth("e1")
    ).json()
    by_offset = client.get("/leave-requests?limit=2&offset=2", headers=auth("e1")).json()

    assert by_cursor["items"] == by_offset["items"]
    assert by_cursor["total"] == 6


def test_last_page_has_no_cursor(client, auth, six_requests):
    body = client.get("/leave-requests?limit=6", headers=auth("e1")).json()

    assert len(body["items"]) == 6
    assert body["next_cursor"] is None


def test_cursor_with_a_status_filter(client, auth, six_requests):
    client.post(f"/leave-requests/{six_requests[0]}/approve", headers=auth("m1"))

    ids, _ = walk(client, auth, "/leave-requests?limit=2&status=PENDING")

    assert ids == six_requests[1:]


@pytest.mark.parametrize("cursor", ["nonsense", "bm90LWEtZGF0ZXx4"])  # junk; "not-a-date|x"
def test_a_bad_cursor_is_422(client, auth, six_requests, cursor):
    response = client.get(f"/leave-requests?cursor={cursor}", headers=auth("e1"))

    assert response.status_code == 422
    assert error_code(response) == "VALIDATION_ERROR"


@requires_postgres
@pytest.mark.parametrize("backend", ["postgres"], indirect=True)
def test_a_cursor_with_a_made_up_id_is_422(client, auth, six_requests):
    cursor = "MjAyNi0xMS0xNnxub3QtYW4taWQ="  # "2026-11-16|not-an-id"

    response = client.get(f"/leave-requests?cursor={cursor}", headers=auth("e1"))

    assert response.status_code == 422


def test_cursor_and_offset_together_is_422(client, auth, six_requests):
    cursor = client.get("/leave-requests?limit=2", headers=auth("e1")).json()["next_cursor"]

    response = client.get(f"/leave-requests?cursor={cursor}&offset=2", headers=auth("e1"))

    assert response.status_code == 422


def test_manager_pages_through_the_team(client, auth, apply):
    apply("e1", start="2026-11-16", end="2026-11-16")
    apply("e2", start="2026-11-17", end="2026-11-17")
    apply("e3", start="2026-11-18", end="2026-11-18")  # Meena's team, not Ravi's

    ids = walk_as(client, auth("m1"), "/leave-requests?limit=1")

    assert len(ids) == 2


def walk_as(client, headers, url):
    ids, cursor = [], None
    while True:
        body = client.get(url + (f"&cursor={cursor}" if cursor else ""), headers=headers).json()
        ids += [item["id"] for item in body["items"]]
        cursor = body["next_cursor"]
        if cursor is None:
            return ids


# Name search


def test_manager_finds_people_by_part_of_a_name(client, auth):
    response = client.get("/employees?q=ASH", headers=auth("m1"))

    assert response.status_code == 200
    assert response.json() == [{"id": "e1", "name": "Asha Rao", "manager_id": "m1"}]


def test_search_finds_several_sorted_by_name(client, auth):
    names = [e["name"] for e in client.get("/employees?q=ra", headers=auth("m1")).json()]

    assert names == ["Asha Rao", "Kiran Das", "Ravi Kumar"]


def test_search_wildcards_are_plain_characters(client, auth):
    for q in ("%%", "__", "a%"):
        assert client.get(f"/employees?q={q}", headers=auth("m1")).json() == []


def test_employees_cannot_search(client, auth):
    assert client.get("/employees?q=asha", headers=auth("e1")).status_code == 403


def test_search_needs_two_characters(client, auth):
    assert client.get("/employees?q=a", headers=auth("m1")).status_code == 422


# The manager's team (Day 4: the Approvals screen shows names, not ids)


def test_manager_gets_their_direct_reports_by_name(client, auth):
    ravi = client.get("/team", headers=auth("m1")).json()
    meena = client.get("/team", headers=auth("m2")).json()

    assert ravi == [
        {"id": "e1", "name": "Asha Rao", "manager_id": "m1"},
        {"id": "e2", "name": "Kiran Das", "manager_id": "m1"},
    ]
    assert [e["id"] for e in meena] == ["e3"]


def test_employees_have_no_team(client, auth):
    assert client.get("/team", headers=auth("e1")).status_code == 403
