from datetime import UTC, datetime, timedelta

import jwt
import pytest

from tests.api.conftest import PASSWORD, error_code


def login(client, email, password):
    return client.post("/auth/login", json={"email": email, "password": password})


def test_health_needs_no_token(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


# API-1


def test_login_returns_a_token_for_the_employee(client, settings):
    response = login(client, "asha@leavedesk.dev", PASSWORD)

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 30 * 60
    claims = jwt.decode(
        body["access_token"],
        settings.jwt_secret.get_secret_value(),
        algorithms=["HS256"],
    )
    assert claims["sub"] == "e1"
    assert claims["role"] == "employee"


def test_login_email_is_case_insensitive(client):
    assert login(client, "  ASHA@leavedesk.dev ", PASSWORD).status_code == 200


def test_manager_token_has_manager_role(client, settings):
    token = login(client, "ravi@leavedesk.dev", PASSWORD).json()["access_token"]
    claims = jwt.decode(token, settings.jwt_secret.get_secret_value(), algorithms=["HS256"])

    assert claims["role"] == "manager"


# API-2


def test_wrong_password_and_unknown_email_get_the_same_401(client):
    wrong_password = login(client, "asha@leavedesk.dev", "wrong-password")
    unknown_email = login(client, "nobody@leavedesk.dev", PASSWORD)

    assert wrong_password.status_code == unknown_email.status_code == 401
    assert wrong_password.json()["error"]["message"] == unknown_email.json()["error"]["message"]


def test_login_with_missing_fields_is_422(client):
    response = client.post("/auth/login", json={"email": "asha@leavedesk.dev"})

    assert response.status_code == 422
    assert error_code(response) == "VALIDATION_ERROR"


def test_password_is_stored_as_argon2_hash(state):
    account = state.users._by_email["asha@leavedesk.dev"]

    assert account.password_hash.startswith("$argon2id$")
    assert PASSWORD not in account.password_hash


# API-3


@pytest.mark.parametrize(
    "method, path",
    [
        ("get", "/leave-requests"),
        ("post", "/leave-requests"),
        ("get", "/employees/e1/balance"),
        ("get", "/notifications"),
        ("post", "/notifications/read-all"),
    ],
)
def test_protected_routes_need_a_token(client, method, path):
    response = getattr(client, method)(path)

    assert response.status_code == 401
    assert error_code(response) == "UNAUTHORIZED"
    assert response.headers["www-authenticate"] == "Bearer"


def make_token(settings, secret=None, **claim_changes):
    now = datetime.now(UTC)
    claims = {"sub": "e1", "role": "employee", "exp": now + timedelta(minutes=5)}
    claims.update(claim_changes)
    return jwt.encode(claims, secret or settings.jwt_secret.get_secret_value(), algorithm="HS256")


@pytest.mark.parametrize(
    "token_changes",
    [
        {"exp": datetime(2020, 1, 1, tzinfo=UTC)},  # expired
        {"secret": "a-different-secret-that-is-32-chars-long"},  # forged
        {"role": "admin"},  # unknown role
        {"sub": "deleted-user"},  # employee no longer exists
    ],
)
def test_bad_tokens_are_rejected(client, settings, token_changes):
    token = make_token(settings, **token_changes)

    response = client.get("/leave-requests", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401


def test_token_with_none_algorithm_is_rejected(client):
    token = jwt.encode({"sub": "m1", "role": "manager", "exp": 4102444800}, None, algorithm="none")

    response = client.get("/leave-requests", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401
