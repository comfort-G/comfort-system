# app/services/notification_service.py
from app.repositories import notification_repo

def fetch_member_notifications(member_id: str) -> dict:
    """Business logic: Retrieves member notifications and unread counts."""
    rows = notification_repo.get_notifications_for_recipient(member_id)
    unread_count = sum(1 for r in rows if not r["is_read"])
    return {
        "member_id": member_id,
        "unread_count": unread_count,
        "notifications": rows
    }

def set_notification_read(notification_id: int, member_id: str) -> dict:
    """Business logic: Updates read status for a notification."""
    result = notification_repo.mark_notification_as_read(notification_id, member_id)
    if not result:
        raise ValueError("Notification not found or unauthorized.")
    return {"status": "success", "message": "Notification marked as read."}