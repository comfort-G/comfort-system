from collections.abc import Mapping, Sequence
from datetime import datetime
from decimal import Decimal
from html import escape
from io import BytesIO
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.repositories import treasurer_reports_repo
from app.subscription_rules import MONTHLY_SUBSCRIPTION_TARGET


def fetch_treasurer_report() -> dict:
    report = treasurer_reports_repo.fetch_treasurer_report()
    report["generated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    report["monthly_subscription_target"] = MONTHLY_SUBSCRIPTION_TARGET
    return report


def fetch_member_financial_summary() -> Sequence[Mapping[str, Any]]:
    return treasurer_reports_repo.fetch_member_financial_summary()


def _money(value) -> str:
    amount = Decimal(str(value or 0))
    return f"UGX {amount:,.2f}"


def _text(value) -> str:
    if value is None:
        return "-"
    if hasattr(value, "isoformat"):
        return value.isoformat(sep=" ", timespec="minutes") if hasattr(value, "hour") else value.isoformat()
    return str(value)


def build_treasurer_pdf(report: dict) -> bytes:
    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=landscape(letter),
        rightMargin=0.35 * inch,
        leftMargin=0.35 * inch,
        topMargin=0.45 * inch,
        bottomMargin=0.45 * inch,
        title="Comfort Group Treasurer Finance Report",
        author="Comfort Group Portal",
    )
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name="ReportTitle",
        parent=styles["Title"],
        alignment=TA_CENTER,
        textColor=colors.HexColor("#174c3c"),
        fontSize=17,
        leading=21,
        spaceAfter=5,
    ))
    styles.add(ParagraphStyle(
        name="SectionHeading",
        parent=styles["Heading2"],
        textColor=colors.HexColor("#174c3c"),
        fontSize=11,
        leading=14,
        spaceBefore=10,
        spaceAfter=5,
    ))
    styles.add(ParagraphStyle(
        name="SmallCell",
        parent=styles["BodyText"],
        fontSize=7,
        leading=9,
        wordWrap="CJK",
    ))

    def paragraph(value) -> Paragraph:
        return Paragraph(escape(_text(value)), styles["SmallCell"])

    def add_table(rows, widths, font_size=7):
        rendered = [[paragraph(cell) for cell in row] for row in rows]
        table = Table(rendered, colWidths=widths, repeatRows=1, hAlign="LEFT")
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#174c3c")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), font_size),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#d5ddd9")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [
                colors.white, colors.HexColor("#f3f7f5")
            ]),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        return table

    subscriptions = report["subscriptions"]
    loans = report["loans"]
    sharing = report["sharing"]
    welfare = report["welfare"]
    story = [
        Paragraph("Comfort Group - Treasurer Finance Report", styles["ReportTitle"]),
        Paragraph(
            f"Generated: {escape(report['generated_at'])} | "
            f"All amounts in Ugandan shillings (UGX)",
            styles["BodyText"],
        ),
        Spacer(1, 10),
        Paragraph("Financial summary", styles["SectionHeading"]),
        add_table([
            ["Area", "Receipts / Funding", "Payments / Balance", "Outstanding / Reserved"],
            [
                "Subscriptions",
                _money(subscriptions["paid_total"]),
                f"{subscriptions['paid_count']} paid entries",
                f"{subscriptions['other_count']} other entries / {_money(subscriptions['other_total'])}",
            ],
            [
                "Loans",
                f"Principal issued {_money(loans['approved_principal'])}",
                f"Principal repaid {_money(loans['principal_repaid'])}",
                f"Outstanding {_money(loans['outstanding_balance'])}; pending {loans['pending_count']}",
            ],
            [
                "Loan interest",
                _money(loans["interest_collected"]),
                "Included in repayment ledger",
                "See loan detail below",
            ],
            [
                "Sharing",
                f"Savings {_money(sharing['savings'])}",
                f"Withdrawn {_money(sharing['disbursed'])}",
                f"Dividends {_money(Decimal(str(sharing['borrower_dividends'])) + Decimal(str(sharing['group_dividends'])))}; savings available for welfare transfers {_money(sharing['available_savings'])}; reserved {_money(sharing['reserved'])}",
            ],
            [
                "Welfare",
                f"Member contributions received {_money(welfare['total_funding'])}",
                _money(welfare["total_disbursed"]),
                f"Personal-balance total {_money(welfare['account_balance'])}; "
                f"emergency reversals returned {_money(welfare['total_returned'])}; "
                f"savings assessed {_money(welfare['savings_assessed'])}; "
                f"arrears paid {_money(welfare['arrears_paid'])}; "
                f"arrears due {_money(welfare['member_arrears'])}",
            ],
        ], [1.05 * inch, 2.0 * inch, 2.0 * inch, 3.8 * inch]),
        Paragraph("Subscriptions ledger", styles["SectionHeading"]),
    ]

    subscription_rows = [[
        "ID", "Member", "Name", "Billing month", "Amount", "Status"
    ]]
    subscription_rows.extend([
        [
            row["id"], row["member_id"], row["full_name"] or "",
            _text(row["billing_month"]), _money(row["amount_paid"]),
            (
                "Partially Paid"
                if (row["status"] or "").strip().casefold() == "paid"
                and Decimal(str(row["amount_paid"] or 0))
                < Decimal(MONTHLY_SUBSCRIPTION_TARGET)
                else row["status"]
            ),
        ]
        for row in report["subscription_rows"]
    ] or [["-", "No subscription records", "", "", "", ""]])
    story.append(add_table(
        subscription_rows,
        [0.45 * inch, 0.8 * inch, 1.65 * inch, 1.15 * inch, 1.1 * inch, 1.0 * inch],
    ))
    story.extend([
        Spacer(1, 10),
        Paragraph("Subscription payment proofs and verification", styles["SectionHeading"]),
    ])
    proof_rows = [[
        "Proof", "Member", "Name", "Month/year", "Amount", "Method",
        "Reference", "Status", "Uploaded", "Verified by", "Comment",
    ]]
    proof_rows.extend([
        [
            row["proof_id"], row["member_id"], row["member_name"],
            f"{row['subscription_month']}/{row['subscription_year']}",
            (
                (
                    "Awaiting Treasurer verification"
                    if (row["verification_status"] or "").strip().casefold()
                    == "pending verification"
                    else "Not verified"
                )
                if row["amount_paid"] is None
                else _money(row["amount_paid"])
            ),
            row["payment_method"],
            row["transaction_reference"], row["verification_status"],
            _text(row["upload_timestamp"]),
            f"{row['verified_by'] or ''} {_text(row['verification_date'])}",
            row["verification_comment"],
        ]
        for row in report["subscription_proofs"]
    ] or [["-", "No subscription proofs", "", "", "", "", "", "", "", "", ""]])
    story.append(add_table(
        proof_rows,
        [0.45 * inch, 0.7 * inch, 1.05 * inch, 0.75 * inch, 0.8 * inch,
         0.75 * inch, 1.05 * inch, 0.75 * inch, 1.0 * inch, 1.0 * inch, 1.3 * inch],
    ))
    story.extend([PageBreak(), Paragraph("Loans and repayments", styles["SectionHeading"])])
    loan_rows = [[
        "Loan", "Member", "Name", "Applied", "Requested", "Principal repaid",
        "Interest repaid", "Outstanding", "Status",
    ]]
    loan_rows.extend([
        [
            row["loan_id"], row["member_id"], row["full_name"] or "",
            _text(row["applied_date"]), _money(row["amount_requested"]),
            _money(row["principal_paid"]), _money(row["interest_paid"]),
            _money(row["outstanding_balance"]), row["status"],
        ]
        for row in report["loan_rows"]
    ] or [["-", "No loan records", "", "", "", "", "", "", ""]])
    story.append(add_table(
        loan_rows,
        [0.45 * inch, 0.75 * inch, 1.35 * inch, 0.9 * inch,
         1.0 * inch, 1.0 * inch, 1.0 * inch, 1.0 * inch, 0.75 * inch],
    ))
    story.extend([
        Spacer(1, 10),
        Paragraph("Loan repayment transactions", styles["SectionHeading"]),
    ])
    repayment_rows = [[
        "Loan", "Member", "Name", "Principal paid", "Interest paid",
    ]]
    repayment_rows.extend([
        [
            row["loan_id"], row["member_id"], row["full_name"] or "",
            _money(row["principal_paid"]), _money(row["interest_paid"]),
        ]
        for row in report["loan_repayment_rows"]
    ] or [["-", "No repayment transactions", "", "", ""]])
    story.append(add_table(
        repayment_rows,
        [0.8 * inch, 0.85 * inch, 2.0 * inch, 1.3 * inch, 1.3 * inch],
    ))

    story.extend([PageBreak(), Paragraph("Sharing and member payout balances", styles["SectionHeading"])])
    sharing_rows = [[
        "Member", "Name", "Savings", "Available savings", "Borrower dividend",
        "Group dividend", "Withdrawn", "Reserved", "Available payout",
    ]]
    sharing_rows.extend([
        [
            row["member_id"], row["full_name"], _money(row["savings"]),
            _money(row["available_savings"]), _money(row["borrower_dividend"]),
            _money(row["group_dividend"]),
            _money(row["disbursed_amount"]), _money(row["reserved_amount"]),
            _money(row["available_payout"]),
        ]
        for row in report["sharing_rows"]
    ] or [["-", "No member payout records", "", "", "", "", "", "", ""]])
    story.append(add_table(
        sharing_rows,
        [0.7 * inch, 1.1 * inch, 0.95 * inch, 1.0 * inch, 1.05 * inch,
         1.0 * inch, 0.85 * inch, 0.85 * inch, 1.0 * inch],
    ))
    story.extend([
        Spacer(1, 10),
        Paragraph("Sharing withdrawal transactions", styles["SectionHeading"]),
    ])
    withdrawal_rows = [[
        "ID", "Member", "Name", "Amount", "Status", "Requested",
        "Approved by", "Rejected by", "Disbursed by", "Review note",
    ]]
    withdrawal_rows.extend([
        [
            row["id"], row["member_id"], row["full_name"] or "",
            _money(row["amount"]), row["status"], _text(row["requested_on"]),
            f"{row['approved_by'] or ''} {_text(row['approved_on'])}",
            f"{row['rejected_by'] or ''} {_text(row['rejected_on'])}",
            f"{row['disbursed_by'] or ''} {_text(row['disbursed_on'])}",
            row["review_comment"] or "",
        ]
        for row in report["sharing_withdrawal_rows"]
    ] or [["-", "No sharing withdrawals", "", "", "", "", "", "", "", ""]])
    story.append(add_table(
        withdrawal_rows,
        [0.35 * inch, 0.65 * inch, 1.05 * inch, 0.8 * inch, 0.7 * inch,
         1.0 * inch, 1.05 * inch, 1.05 * inch, 1.05 * inch, 1.7 * inch],
    ))

    story.extend([PageBreak(), Paragraph("Welfare support requests", styles["SectionHeading"])])
    request_rows = [[
        "Case", "Applicant", "Category", "Status / stage", "Created",
        "Target", "Disbursed", "Welfare funded", "Savings funded", "Member arrears",
        "Payment reference",
    ]]
    request_rows.extend([
        [
            row["case_number"],
            (
                f"{row['member_name']} ({row['member_id']})\nFor: "
                f"{row.get('beneficiary_relationship') or ''} "
                f"{row.get('beneficiary_name') or 'Legacy claim'}"
            ),
            row["support_category"], f"{row['status']} / {row['current_stage']}",
            _text(row["created_at"]), _money(row["target_amount"]),
            _money(row["disbursed_amount"]), _money(row["welfare_funding"]),
            _money(row["savings_funding"]), _money(row["member_arrears"]),
            row["payment_reference"] or "",
        ]
        for row in report["welfare_requests"]
    ] or [["-", "No welfare requests", "", "", "", "", "", "", "", "", ""]])
    story.append(add_table(
        request_rows,
        [0.75 * inch, 1.15 * inch, 0.8 * inch, 1.05 * inch,
         0.85 * inch, 0.8 * inch, 0.8 * inch, 0.9 * inch,
         0.9 * inch, 0.85 * inch, 1.05 * inch],
    ))
    story.extend([
        Spacer(1, 10),
        Paragraph("Welfare disbursement transactions", styles["SectionHeading"]),
    ])
    disbursement_rows = [[
        "ID", "Case", "Applicant", "Category", "Target", "Amount paid",
        "Paid by", "Role", "Reference", "Date",
    ]]
    disbursement_rows.extend([
        [
            row["id"], row["case_number"],
            (
                f"{row['applicant_name']} ({row['applicant_member_id']})\nFor: "
                f"{row.get('beneficiary_relationship') or ''} "
                f"{row.get('beneficiary_name') or 'Legacy claim'}"
            ),
            row["support_category"], _money(row["target_amount"]),
            _money(row["amount"]), row["disbursed_by"], row["disbursed_role"],
            row["payment_reference"], _text(row["disbursed_at"]),
        ]
        for row in report["welfare_disbursement_rows"]
    ] or [["-", "No welfare disbursements", "", "", "", "", "", "", "", ""]])
    story.append(add_table(
        disbursement_rows,
        [0.35 * inch, 0.65 * inch, 1.2 * inch, 0.7 * inch, 0.85 * inch,
         0.85 * inch, 0.9 * inch, 0.6 * inch, 1.15 * inch, 1.0 * inch],
    ))

    story.extend([
        PageBreak(),
        Paragraph("Personal welfare account balances", styles["SectionHeading"]),
    ])
    member_welfare_rows = [[
        "Member", "Name", "Contributions received", "Welfare allocated",
        "Arrears paid to requests", "Current personal balance",
    ]]
    member_welfare_rows.extend([
        [
            row["member_id"], row["full_name"], _money(row["total_contributed"]),
            _money(row["amount_assessed"]), _money(row["arrears_paid"]),
            _money(row["welfare_balance"]),
        ]
        for row in report["welfare_member_balances"]
    ] or [["-", "No member welfare accounts", "", "", "", ""]])
    story.append(add_table(
        member_welfare_rows,
        [0.85 * inch, 1.55 * inch, 1.45 * inch, 1.3 * inch,
         1.45 * inch, 1.45 * inch],
    ))
    story.extend([
        Spacer(1, 10),
        Paragraph("Welfare funding by member and request", styles["SectionHeading"]),
    ])
    contributor_rows = [[
        "Case", "Member", "Name", "Contribution status", "Target",
        "Welfare balance used", "Savings used", "Outstanding due",
    ]]
    contributor_rows.extend([
        [
            row["case_number"], row["member_id"], row["full_name"],
            row["contribution_status"],
            _money(row["target_amount"]), _money(row["welfare_amount"]),
            _money(row["savings_amount"]), _money(row["outstanding_amount"]),
        ]
        for row in report["welfare_contributors"]
    ] or [["-", "No welfare funding transactions", "", "", "", "", "", ""]])
    story.append(add_table(
        contributor_rows,
        [0.85 * inch, 0.8 * inch, 1.4 * inch, 1.15 * inch,
         0.9 * inch, 1.25 * inch, 0.95 * inch, 1.0 * inch],
    ))
    story.extend([
        PageBreak(),
        Paragraph("Welfare contribution transfers", styles["SectionHeading"]),
    ])
    welfare_transfer_rows = [[
        "ID", "Reference", "Member", "Name", "Amount", "Recorded by", "Role", "Date",
    ]]
    welfare_transfer_rows.extend([
        [
            row["id"], row["transfer_reference"], row["member_id"],
            row["full_name"] or "", _money(row["amount"]), row["created_by"],
            row["created_by_role"], _text(row["created_at"]),
        ]
        for row in report["welfare_contribution_rows"]
    ] or [["-", "No welfare transfers", "", "", "", "", "", ""]])
    story.append(add_table(
        welfare_transfer_rows,
        [0.4 * inch, 1.25 * inch, 0.7 * inch, 1.35 * inch,
         0.85 * inch, 1.2 * inch, 0.8 * inch, 1.0 * inch],
    ))
    story.extend([
        Spacer(1, 10),
        Paragraph("Welfare arrears repayments", styles["SectionHeading"]),
    ])
    arrears_rows = [[
        "ID", "Reference", "Case", "Member", "Name", "Amount", "Recorded by",
        "Role", "Date",
    ]]
    arrears_rows.extend([
        [
            row["id"], row["payment_reference"], row["case_number"],
            row["member_id"], row["full_name"], _money(row["amount"]),
            row["created_by"], row["created_by_role"], _text(row["created_at"]),
        ]
        for row in report["welfare_arrears_payment_rows"]
    ] or [["-", "No welfare arrears repayments", "", "", "", "", "", "", ""]])
    story.append(add_table(
        arrears_rows,
        [0.4 * inch, 1.15 * inch, 0.7 * inch, 0.65 * inch,
         1.2 * inch, 0.8 * inch, 1.0 * inch, 0.7 * inch, 0.9 * inch],
    ))
    story.append(Spacer(1, 8))
    story.append(Paragraph(
        "Group welfare account balance is the sum of current personal welfare balances. "
        "Request assessments reduce a member's balance once; disbursements are reported "
        "separately and are not subtracted from those same balances a second time. "
        "This report combines the system's subscription, loan-repayment, sharing, "
        "welfare-contribution, and disbursement ledgers. Verify source vouchers and "
        "bank/mobile-money statements during audit reconciliation.",
        styles["SmallCell"],
    ))

    document.build(story)
    return buffer.getvalue()


def build_member_financial_summary_pdf(
    members: Sequence[Mapping[str, Any]],
) -> bytes:
    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=landscape(letter),
        rightMargin=0.3 * inch,
        leftMargin=0.3 * inch,
        topMargin=0.45 * inch,
        bottomMargin=0.55 * inch,
        title="Comfort Group Member Financial Summary",
        author="Comfort Group Portal",
    )
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name="MemberSummaryTitle",
        parent=styles["Title"],
        alignment=TA_CENTER,
        textColor=colors.HexColor("#174c3c"),
        fontSize=17,
        leading=21,
        spaceAfter=5,
    ))
    styles.add(ParagraphStyle(
        name="MemberSummaryCell",
        parent=styles["BodyText"],
        fontSize=7,
        leading=9,
        wordWrap="CJK",
    ))
    styles.add(ParagraphStyle(
        name="MemberSummaryHeader",
        parent=styles["MemberSummaryCell"],
        textColor=colors.white,
        fontName="Helvetica-Bold",
    ))

    def cell(value, style="MemberSummaryCell") -> Paragraph:
        return Paragraph(escape(_text(value)), styles[style])

    columns = [
        ("Member ID", "member_id"),
        ("Member name", "full_name"),
        ("Total contributions", "total_contributions"),
        ("Welfare contributed", "total_welfare_contributions"),
        ("Current welfare balance", "current_welfare_balance"),
        ("Current savings", "current_savings"),
        ("Total paid out", "total_paid_out"),
        ("Payout available now", "available_payout"),
    ]
    money_fields = {key for _, key in columns[2:]}
    rows = [[cell(label, "MemberSummaryHeader") for label, _ in columns]]
    totals = {key: Decimal("0") for _, key in columns[2:]}
    for member in members:
        row = []
        for _, key in columns:
            value = member.get(key)
            if key in money_fields:
                amount = Decimal(str(value or 0))
                totals[key] += amount
                value = _money(amount)
            row.append(cell(value))
        rows.append(row)
    if not members:
        rows.append([cell("No registered members")] + [cell("") for _ in columns[1:]])

    total_row = [cell("TOTAL", "MemberSummaryHeader"), cell("", "MemberSummaryHeader")]
    total_row.extend(
        cell(_money(totals[key]), "MemberSummaryHeader")
        for _, key in columns[2:]
    )
    rows.append(total_row)

    table = Table(
        rows,
        colWidths=[
            0.75 * inch,
            1.65 * inch,
            1.25 * inch,
            1.25 * inch,
            1.3 * inch,
            1.15 * inch,
            1.2 * inch,
            1.35 * inch,
        ],
        repeatRows=1,
        hAlign="LEFT",
    )
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#174c3c")),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#174c3c")),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#d5ddd9")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2), [
            colors.white, colors.HexColor("#f3f7f5")
        ]),
        ("ALIGN", (2, 1), (-1, -1), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))

    generated_at = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z")
    story = [
        Paragraph("Comfort Group - Member Financial Summary", styles["MemberSummaryTitle"]),
        Paragraph(
            f"Generated: {escape(generated_at)} | All amounts in Ugandan shillings (UGX)",
            styles["BodyText"],
        ),
        Spacer(1, 8),
        Paragraph(
            "Contributions are paid subscription amounts. Welfare contributed is the "
            "member's recorded welfare transfers; current welfare balance and current "
            "savings are calculated account balances. Total paid out is completed sharing "
            "withdrawals. Payout available now is the member's currently available payout "
            "after withdrawals and reservations. Members with no recorded activity are "
            "included; the TOTAL row sums the member-level figures.",
            styles["BodyText"],
        ),
        Spacer(1, 10),
        table,
    ]

    def add_page_number(canvas, _document):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#547167"))
        canvas.drawRightString(
            _document.pagesize[0] - 0.3 * inch,
            0.3 * inch,
            f"Page {canvas.getPageNumber()}",
        )
        canvas.restoreState()

    document.build(story, onFirstPage=add_page_number, onLaterPages=add_page_number)
    return buffer.getvalue()
