"""The app's database engine, with safety timeouts on every connection.

statement_timeout   a query running longer than this is cancelled
lock_timeout        waiting longer than this for a row lock gives up
idle_in_transaction_session_timeout
                    a transaction left open and idle this long is closed, so it
                    cannot hold locks forever

A cancelled query becomes HTTP 503 TRY_AGAIN (see api/errors.py) instead of
leaving the request hanging. In production the same values are also set on the
leavedesk_app role (docker/initdb/01-roles.sh), so they apply even to a psql session.
"""

from sqlalchemy import Engine, create_engine, event

from leavedesk.api.settings import Settings


def timeouts(settings: Settings) -> dict[str, str]:
    return {
        "statement_timeout": f"{settings.database_statement_timeout_ms}ms",
        "lock_timeout": f"{settings.database_lock_timeout_ms}ms",
        "idle_in_transaction_session_timeout": f"{settings.database_idle_timeout_ms}ms",
    }


def create_database_engine(settings: Settings) -> Engine:
    engine = create_engine(
        settings.database_url.get_secret_value(),
        echo=settings.database_echo,
        pool_pre_ping=True,  # replace connections the database has closed
    )
    values = timeouts(settings)

    @event.listens_for(engine, "connect")
    def set_timeouts(dbapi_connection, _record) -> None:
        cursor = dbapi_connection.cursor()
        for name, value in values.items():
            # Bound parameters, never pasted into the SQL text.
            cursor.execute("SELECT set_config(%s, %s, false)", (name, value))
        cursor.close()
        dbapi_connection.commit()

    return engine
