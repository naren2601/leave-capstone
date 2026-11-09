"""Shared fixtures for the API tests.

Each test gets a fresh app with in-memory data, a fixed "today", and a
recording notifier standing in for real delivery.
"""

from datetime import date

import pytest
from fastapi.testclient import TestClient

from leavedesk.api.auth import create_access_token
from leavedesk.api.main import create_app
from leavedesk.api.settings import Settings
from leavedesk.domain.notifications import Notification, Notifier

TODAY = date(2026, 11, 9)  # a Monday
PASSWORD = "test-password-123"

# Seeded people (see leavedesk/api/state.py):
#   m1 Ravi (manager of e1 and e2), m2 Meena (manager of e3)
#   e1 Asha, e2 Kiran, e3 Sam


class RecordingNotifier(Notifier):
    """A mocked notifier: records what would have been sent."""

    def __init__(self) -> None:
        self.sent: list[Notification] = []

    async def send(self, notification: Notification) -> None:
        self.sent.append(notification)


@pytest.fixture
def settings() -> Settings:
    return Settings(
        jwt_secret="test-secret-that-is-at-least-32-characters",
        seed_password=PASSWORD,
        _env_file=None,
    )


@pytest.fixture
def app(settings):
    return create_app(settings, today=lambda: TODAY)


@pytest.fixture
def state(app):
    return app.state.leavedesk


@pytest.fixture
def notifier(state) -> RecordingNotifier:
    recorder = RecordingNotifier()
    state.extra_notifiers.append(recorder)
    return recorder


@pytest.fixture
def client(app, notifier) -> TestClient:
    return TestClient(app)


@pytest.fixture
def auth(settings):
    """auth("e1") returns headers with a valid token for that person."""

    def make(employee_id: str) -> dict[str, str]:
        role = "manager" if employee_id.startswith("m") else "employee"
        token = create_access_token(employee_id, role, settings)
        return {"Authorization": f"Bearer {token}"}

    return make


@pytest.fixture
def apply(client, auth):
    """apply("e1", start=..., end=...) posts a leave request and returns the response."""

    def make(
        employee_id: str = "e1",
        start: str = "2026-11-16",
        end: str = "2026-11-18",
        leave_type: str = "ANNUAL",
        reason: str = "Family trip",
        **extra,
    ):
        body = {
            "leave_type": leave_type,
            "start_date": start,
            "end_date": end,
            "reason": reason,
            **extra,
        }
        return client.post("/leave-requests", json=body, headers=auth(employee_id))

    return make


def error_code(response) -> str:
    return response.json()["error"]["code"]
