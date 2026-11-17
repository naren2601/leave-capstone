"""Alembic environment: connects to the database and runs migrations."""

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from leavedesk.db.models import Base
from leavedesk.db.roles import grant_app_privileges

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def database_url() -> str:
    # Tests pass the URL in directly; everyone else uses the environment.
    # Migrations run as the table owner (leavedesk_migrator), not as the app's role.
    url = (
        config.attributes.get("database_url")
        or os.environ.get("LEAVEDESK_MIGRATION_DATABASE_URL")
        or os.environ.get("LEAVEDESK_DATABASE_URL")
    )
    if not url:
        raise RuntimeError(
            "Set LEAVEDESK_DATABASE_URL, for example "
            "postgresql+psycopg://leavedesk:<password>@localhost:5432/leavedesk"
        )
    return url


def include_object(obj, name, type_, reflected, compare_to):
    # Extensions create their own objects; they are not part of our models.
    return not (type_ == "table" and reflected and compare_to is None and name.startswith("pg_"))


def run_migrations_offline() -> None:
    """Print the SQL instead of running it: alembic upgrade head --sql"""
    context.configure(
        url=database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:
        _run(connection)
        return

    engine = create_engine(database_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        _run(connection)


def _run(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        include_object=include_object,
        transaction_per_migration=True,
    )
    with context.begin_transaction():
        context.run_migrations()
    # Every upgrade re-applies the app role's grants, so new tables are covered too.
    grant_app_privileges(connection)
    connection.commit()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
