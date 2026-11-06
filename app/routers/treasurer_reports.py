import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates

from app.dependencies import require_role
from app.services import treasurer_reports_service


router = APIRouter(prefix="/api/treasurer-reports", tags=["Treasurer Finance Reports"])
templates = Jinja2Templates(directory="templates")
FINANCE_REPORT_ROLES = ["Treasurer", "Chairperson", "Secretary"]
logger = logging.getLogger(__name__)


@router.get("/view", response_class=HTMLResponse)
def render_treasurer_reports_page(
    request: Request,
    current_user: dict = Depends(require_role(FINANCE_REPORT_ROLES)),
):
    return templates.TemplateResponse(
        request=request,
        name="treasurer_reports.html",
        context={"request": request},
    )


@router.get("/data")
def get_treasurer_report(
    current_user: dict = Depends(require_role(FINANCE_REPORT_ROLES)),
):
    return {
        "status": "success",
        "data": treasurer_reports_service.fetch_treasurer_report(),
    }


@router.get("/pdf")
def download_treasurer_report_pdf(
    current_user: dict = Depends(require_role(FINANCE_REPORT_ROLES)),
):
    try:
        report = treasurer_reports_service.fetch_treasurer_report()
        content = treasurer_reports_service.build_treasurer_pdf(report)
    except Exception as exc:
        logger.exception("Could not generate the Treasurer finance report PDF.")
        raise HTTPException(
            status_code=500,
            detail="Could not generate the Treasurer finance report PDF.",
        ) from exc
    return Response(
        content=content,
        media_type="application/pdf",
        headers={
            "Content-Disposition": 'attachment; filename="comfort-group-finance-report.pdf"'
        },
    )


@router.get(
    "/member-summary/pdf",
    response_class=Response,
    responses={
        200: {
            "content": {
                "application/pdf": {
                    "schema": {"type": "string", "format": "binary"}
                }
            }
        }
    },
)
def download_member_financial_summary_pdf(
    current_user: dict = Depends(require_role(FINANCE_REPORT_ROLES)),
):
    try:
        members = treasurer_reports_service.fetch_member_financial_summary()
        content = treasurer_reports_service.build_member_financial_summary_pdf(members)
    except Exception as exc:
        logger.exception("Could not generate the member financial summary PDF.")
        raise HTTPException(
            status_code=500,
            detail="Could not generate the member financial summary PDF.",
        ) from exc
    return Response(
        content=content,
        media_type="application/pdf",
        headers={
            "Content-Disposition": (
                'attachment; filename="comfort-group-member-financial-summary.pdf"'
            )
        },
    )
