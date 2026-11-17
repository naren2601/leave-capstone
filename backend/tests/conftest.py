"""Fixtures shared by every test folder."""

import os
from collections.abc import Iterator

import pytest
from alembic import command

from tests.postgres import ADMIN_URL, alembic_config, temporary_database


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    if not ADMIN_URL:
        pytest.skip("LEAVEDESK_TEST_DATABASE_URL is not set")
    with temporary_database() as url:
        command.upgrade(alembic_config(url), "head")
        yield url


@pytest.fixture(autouse=True)
def no_settings_from_the_shell(monkeypatch):
    """Tests ignore LEAVEDESK_* variables set in your terminal.

    Otherwise a LEAVEDESK_DATABASE_URL you set to run the API would quietly turn
    the in-memory tests into database tests. Only LEAVEDESK_TEST_DATABASE_URL is
    meant for tests, and it is read once, in tests/postgres.py.
    """
    for name in os.environ:
        if name.startswith("LEAVEDESK_") and name != "LEAVEDESK_TEST_DATABASE_URL":
            monkeypatch.delenv(name)
