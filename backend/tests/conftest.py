"""Fixtures shared by every test folder."""

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
