from datetime import date, timedelta

from app.database import get_db


def get_audit_logs(limit: int, offset: int) -> list[dict]:
    """Fetch administrative audit records in reverse chronological order."""
    with get_db() as cursor:
        cursor.execute(
            """
            SELECT id, entity_type, entity_id, action, actor_name, actor_role,
                   details, previous_value, new_value, created_at
            FROM audit_logs
            ORDER BY created_at DESC, id DESC
            LIMIT %s OFFSET %s;
            """,
            (limit, offset),
        )
        return cursor.fetchall()


def get_welfare_audit_logs(limit: int, offset: int) -> list[dict]:
    """Fetch welfare audit records in reverse chronological order."""
    with get_db() as cursor:
        cursor.execute(
            """
            SELECT id, request_id, user_id, user_name, role, action,
                   previous_status, new_status, details, payment_reference,
                   ip_address, created_at
            FROM welfare_audit_log
            ORDER BY created_at DESC, id DESC
            LIMIT %s OFFSET %s;
            """,
            (limit, offset),
        )
        return cursor.fetchall()


def get_audit_logs_for_period(start_date: date, end_date: date) -> list[dict]:
    """Fetch all administrative audit records for an inclusive date range."""
    with get_db() as cursor:
        cursor.execute(
            """
            SELECT id, entity_type, entity_id, action, actor_name, actor_role,
                   details, previous_value, new_value, created_at
            FROM public.audit_logs
            WHERE created_at >= %s
              AND created_at < %s
            ORDER BY created_at ASC, id ASC;
            """,
            (start_date, end_date + timedelta(days=1)),
        )
        return cursor.fetchall()


def get_welfare_audit_logs_for_period(
    start_date: date,
    end_date: date,
) -> list[dict]:
    """Fetch all welfare audit records for an inclusive date range."""
    with get_db() as cursor:
        cursor.execute(
            """
            SELECT id, request_id, user_id, user_name, role, action,
                   previous_status, new_status, details, payment_reference,
                   ip_address, created_at
            FROM public.welfare_audit_log
            WHERE created_at >= %s
              AND created_at < %s
            ORDER BY created_at ASC, id ASC;
            """,
            (start_date, end_date + timedelta(days=1)),
        )
        return cursor.fetchall()
