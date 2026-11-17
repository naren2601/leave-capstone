"""What the app's own database role, leavedesk_app, may do.

Two roles (Day 3, step 5):
- leavedesk_migrator owns the tables and runs Alembic: it can CREATE, ALTER and DROP.
- leavedesk_app is what the API logs in as. It can only read and write rows, and it
  cannot UPDATE, DELETE or TRUNCATE the append-only leave_ledger and audit_log.
  If the API is ever tricked into running bad SQL, it still cannot drop a table
  or rewrite history.

The roles themselves are created once per server by docker/initdb/01-roles.sh.
These grants are re-applied after every `alembic upgrade` (see migrations/env.py),
so a table added by a later migration is never forgotten.
"""

from sqlalchemy import Connection, text

APP_ROLE = "leavedesk_app"
APPEND_ONLY_TABLES = ("leave_ledger", "audit_log")

# Built only from the constants above, never from user input.
GRANT_APP_PRIVILEGES = f"""
DO $$
DECLARE
    append_only text;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
        RETURN;  -- no app role on this server (for example a quick local setup)
    END IF;
    GRANT USAGE ON SCHEMA public TO {APP_ROLE};
    GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {APP_ROLE};
    GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {APP_ROLE};
    FOREACH append_only IN ARRAY ARRAY{list(APPEND_ONLY_TABLES)} LOOP
        IF to_regclass(append_only) IS NOT NULL THEN  -- missing after a full downgrade
            EXECUTE format(
                'REVOKE UPDATE, DELETE, TRUNCATE ON %I FROM {APP_ROLE}', append_only
            );
        END IF;
    END LOOP;
    REVOKE ALL ON alembic_version FROM {APP_ROLE};
END
$$
"""  # noqa: S608


def grant_app_privileges(connection: Connection) -> None:
    connection.execute(text(GRANT_APP_PRIVILEGES))
