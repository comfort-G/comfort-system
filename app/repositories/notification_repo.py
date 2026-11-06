# app/repositories/notification_repo.py
from app.database import get_db

def get_notifications_for_recipient(recipient_id: str):
    """Fetches all notifications for a specific recipient or broadcast ('ALL')."""
    with get_db() as cursor:
        cursor.execute(
            """
            SELECT id, recipient_type, recipient_id, title, message, is_read, 
                   created_at, category, module_name, priority, action_link, read_at
            FROM notifications
            WHERE recipient_id = %s OR recipient_id = 'ALL'
            ORDER BY created_at DESC;
            """,
            (recipient_id,)
        )
        return cursor.fetchall()

def mark_notification_as_read(notification_id: int, recipient_id: str):
    """Marks a notification as read and updates read_at timestamp."""
    with get_db() as cursor:
        cursor.execute(
            """
            UPDATE notifications
            SET is_read = TRUE, read_at = NOW()
            WHERE id = %s AND (recipient_id = %s OR recipient_id = 'ALL')
            RETURNING id, is_read, read_at;
            """,
            (notification_id, recipient_id)
        )
        return cursor.fetchone()

def insert_notification(
    recipient_type: str, 
    recipient_id: str, 
    title: str, 
    message: str, 
    category: str = "General", 
    module_name: str = "Portal", 
    priority: str = "Normal",
    action_link: str = None
):
    """Inserts a new system notification into Neon using audited columns."""
    with get_db() as cursor:
        cursor.execute(
            """
            INSERT INTO notifications (
                recipient_type, recipient_id, title, message, is_read, 
                category, module_name, priority, action_link, delivery_status, created_at
            )
            VALUES (%s, %s, %s, %s, FALSE, %s, %s, %s, %s, 'Delivered', NOW())
            RETURNING id;
            """,
            (recipient_type, recipient_id, title, message, category, module_name, priority, action_link)
        )
        return cursor.fetchone()