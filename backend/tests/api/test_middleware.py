import logging

from fastapi.testclient import TestClient

# API-26 Request id and access log


def test_every_response_has_a_request_id(client, auth):
    for response in (
        client.get("/health"),
        client.get("/leave-requests"),  # 401
        client.get("/leave-requests", headers=auth("e1")),
        client.get("/nowhere"),  # 404
    ):
        assert len(response.headers["x-request-id"]) == 32


def test_error_body_carries_the_same_request_id(client):
    response = client.get("/leave-requests")

    assert response.json()["error"]["request_id"] == response.headers["x-request-id"]


def test_safe_client_request_id_is_reused(client):
    response = client.get("/health", headers={"X-Request-ID": "trace-abc_123"})

    assert response.headers["x-request-id"] == "trace-abc_123"


def test_unsafe_client_request_id_is_replaced(client):
    response = client.get("/health", headers={"X-Request-ID": "bad id\nINJECTED"})

    assert response.headers["x-request-id"] != "bad id\nINJECTED"


def test_access_log_has_method_path_status_and_duration(client, caplog):
    caplog.set_level(logging.INFO, logger="leavedesk.api")

    response = client.get("/health")

    request_id = response.headers["x-request-id"]
    line = next(r.getMessage() for r in caplog.records if request_id in r.getMessage())
    assert line.startswith("GET /health -> 200 in ")
    assert " ms " in line


# API-27 Unexpected errors


def test_unexpected_error_is_500_without_a_stack_trace(app, caplog):
    def explode():
        raise RuntimeError("database password is hunter2")

    app.add_api_route("/explode", explode)

    response = TestClient(app).get("/explode")

    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "INTERNAL_ERROR"
    assert body["error"]["message"] == "something went wrong"
    assert "hunter2" not in response.text
    assert "Traceback" not in response.text
    assert response.headers["x-request-id"] == body["error"]["request_id"]
    assert "hunter2" in caplog.text  # the detail is in the log, not the response


def test_docs_are_served_in_dev(client):
    assert client.get("/docs").status_code == 200
    assert client.get("/openapi.json").json()["info"]["title"] == "LeaveDesk API"
