"""Tell listeners about each new notification, with pg_notify.

A trigger on notifications calls pg_notify('leavedesk_notifications', ...).
PostgreSQL holds the message until the transaction commits, and drops it if the
transaction rolls back, so listeners only ever hear about saved notifications.

Revision ID: 0002
Revises: 0001
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CHANNEL = "leavedesk_notifications"

NOTIFY_FUNCTION = f"""
CREATE FUNCTION notify_new_notification() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    -- Only ids: the payload limit is 8000 bytes, and the listener reads the row.
    PERFORM pg_notify(
        '{CHANNEL}',
        json_build_object('id', NEW.id, 'tenant_id', NEW.tenant_id)::text
    );
    RETURN NULL;
END;
$$
"""


def upgrade() -> None:
    op.execute(NOTIFY_FUNCTION)
    op.execute(
        "CREATE TRIGGER notifications_notify AFTER INSERT ON notifications "
        "FOR EACH ROW EXECUTE FUNCTION notify_new_notification()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER notifications_notify ON notifications")
    op.execute("DROP FUNCTION notify_new_notification()")
