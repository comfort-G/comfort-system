from datetime import date, datetime
from html import escape
from io import BytesIO
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import landscape, legal
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.repositories import audit_repo

EXECUTIVE_ROLES = frozenset({"chairperson", "treasurer", "secretary"})


class AuditAccessDeniedError(PermissionError):
    """Raised when a non-executive attempts to access audit information."""


def verify_executive_access(current_user: dict) -> None:
    """Require an authenticated executive role before exposing audit records."""
    role = current_user.get("role")
    if not isinstance(role, str) or role.casefold() not in EXECUTIVE_ROLES:
        raise AuditAccessDeniedError("Audit Center access is restricted to executives.")


def _format_row(row: dict) -> dict[str, Any]:
    """Convert database timestamps to JSON-ready ISO 8601 values."""
    return {
        key: value.isoformat() if isinstance(value, (datetime, date)) else value
        for key, value in row.items()
    }


def fetch_audit_logs(current_user: dict, limit: int = 100, offset: int = 0) -> dict:
    verify_executive_access(current_user)
    rows = audit_repo.get_audit_logs(limit=limit, offset=offset)
    return {
        "status": "success",
        "count": len(rows),
        "limit": limit,
        "offset": offset,
        "data": [_format_row(row) for row in rows],
    }


def fetch_welfare_audit_logs(
    current_user: dict,
    limit: int = 100,
    offset: int = 0,
) -> dict:
    verify_executive_access(current_user)
    rows = audit_repo.get_welfare_audit_logs(limit=limit, offset=offset)
    return {
        "status": "success",
        "count": len(rows),
        "limit": limit,
        "offset": offset,
        "data": [_format_row(row) for row in rows],
    }


def build_audit_pdf(
    current_user: dict,
    start_date: date,
    end_date: date,
) -> bytes:
    verify_executive_access(current_user)
    if start_date > end_date:
        raise ValueError("The start date must be on or before the end date.")

    admin_rows = audit_repo.get_audit_logs_for_period(start_date, end_date)
    welfare_rows = audit_repo.get_welfare_audit_logs_for_period(start_date, end_date)

    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=landscape(legal),
        rightMargin=0.35 * inch,
        leftMargin=0.35 * inch,
        topMargin=0.45 * inch,
        bottomMargin=0.45 * inch,
        title=f"Comfort Group Audit Report {start_date} to {end_date}",
        author="Comfort Group Portal",
    )
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name="AuditReportTitle",
        parent=styles["Title"],
        alignment=TA_CENTER,
        textColor=colors.HexColor("#2c3e50"),
        fontSize=17,
        leading=21,
        spaceAfter=6,
    ))
    styles.add(ParagraphStyle(
        name="AuditSectionHeading",
        parent=styles["Heading2"],
        textColor=colors.HexColor("#2c3e50"),
        fontSize=11,
        leading=14,
        spaceBefore=10,
        spaceAfter=5,
    ))
    styles.add(ParagraphStyle(
        name="AuditSmallCell",
        parent=styles["BodyText"],
        fontSize=7,
        leading=9,
        wordWrap="CJK",
    ))

    def cell_text(value: Any) -> str:
        if value is None or value == "":
            return "—"
        if isinstance(value, (datetime, date)):
            value = value.isoformat(sep=" ", timespec="seconds") if isinstance(value, datetime) else value.isoformat()
        return escape(str(value)).replace("\n", "<br/>")

    def build_table(rows: list[list[Any]], widths: list[float]) -> Table:
        rendered = [
            [Paragraph(cell_text(value), styles["AuditSmallCell"]) for value in row]
            for row in rows
        ]
        table = Table(rendered, colWidths=widths, repeatRows=1, hAlign="LEFT")
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2c3e50")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#d0d5dd")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [
                colors.white, colors.HexColor("#f8fafc")
            ]),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        return table

    admin_data = [[
        "Date & time", "Action", "Entity", "Actor", "Details",
        "Previous value", "New value",
    ]]
    for row in admin_rows:
        entity = str(row.get("entity_type") or "—")
        if row.get("entity_id"):
            entity += f" #{row['entity_id']}"
        actor = str(row.get("actor_name") or "—")
        if row.get("actor_role"):
            actor += f" ({row['actor_role']})"
        admin_data.append([
            row.get("created_at"),
            row.get("action"),
            entity,
            actor,
            row.get("details"),
            row.get("previous_value"),
            row.get("new_value"),
        ])

    welfare_data = [[
        "Date & time", "Request", "Action", "User", "Status change",
        "Details", "Payment reference", "IP address",
    ]]
    for row in welfare_rows:
        user = str(row.get("user_name") or row.get("user_id") or "—")
        if row.get("role"):
            user += f" ({row['role']})"
        welfare_data.append([
            row.get("created_at"),
            f"#{row.get('request_id')}" if row.get("request_id") else "—",
            row.get("action"),
            user,
            f"{row.get('previous_status') or '—'} → {row.get('new_status') or '—'}",
            row.get("details"),
            row.get("payment_reference"),
            row.get("ip_address"),
        ])

    story = [
        Paragraph("Comfort Group - Audit Report", styles["AuditReportTitle"]),
        Paragraph(
            f"Period: {start_date.isoformat()} through {end_date.isoformat()} "
            "(inclusive) | Generated: "
            f"{datetime.now().astimezone().isoformat(timespec='seconds')}",
            styles["BodyText"],
        ),
        Spacer(1, 8),
        Paragraph(
            f"Administrative Actions ({len(admin_rows)} records)",
            styles["AuditSectionHeading"],
        ),
        build_table(
            admin_data,
            [1.35 * inch, 1.0 * inch, 1.25 * inch, 1.3 * inch,
             3.2 * inch, 1.3 * inch, 1.3 * inch],
        ),
        Spacer(1, 12),
        Paragraph(
            f"Welfare Audit History ({len(welfare_rows)} records)",
            styles["AuditSectionHeading"],
        ),
        build_table(
            welfare_data,
            [1.35 * inch, 0.7 * inch, 1.0 * inch, 1.3 * inch,
             1.4 * inch, 3.1 * inch, 1.6 * inch, 1.0 * inch],
        ),
    ]
    document.build(story)
    return buffer.getvalue()
