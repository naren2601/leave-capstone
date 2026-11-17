#!/bin/sh
# Runs once, when the db container starts with an empty data volume.
# To run it again: docker compose down -v   (this deletes the database data!)
#
# leavedesk           the server's superuser (POSTGRES_USER): for emergencies only
# leavedesk_migrator  owns the tables; Alembic runs as this role
# leavedesk_app       the API logs in as this role: rows only, with timeouts
set -eu

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
     -v migrator_password="$LEAVEDESK_MIGRATOR_DB_PASSWORD" \
     -v app_password="$LEAVEDESK_APP_DB_PASSWORD" <<'SQL'
CREATE ROLE leavedesk_migrator LOGIN PASSWORD :'migrator_password';
CREATE ROLE leavedesk_app LOGIN PASSWORD :'app_password';

-- Nobody but the migrator creates objects. (Extensions such as btree_gist are
-- "trusted", so CREATE on the database is enough to add them.)
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT CREATE, USAGE ON SCHEMA public TO leavedesk_migrator;
GRANT CREATE, CONNECT ON DATABASE leavedesk TO leavedesk_migrator;
GRANT CONNECT ON DATABASE leavedesk TO leavedesk_app;

-- Safety timeouts for the app, even in a psql session.
ALTER ROLE leavedesk_app SET statement_timeout = '5s';
ALTER ROLE leavedesk_app SET lock_timeout = '2s';
ALTER ROLE leavedesk_app SET idle_in_transaction_session_timeout = '30s';
SQL
