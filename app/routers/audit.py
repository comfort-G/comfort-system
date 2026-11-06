import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates

from app.dependencies import require_role
from app.services import audit_service

EXECUTIVE_ACCESS = ["Chairperson", "Treasurer", "Secretary"]
templates = Jinja2Templates(directory="templates")
router = APIRouter(prefix="/api/audit", tags=["Audit Center"])
logger = logging.getLogger(__name__)


def _validate_executive(current_user: dict) -> None:
    try:
        audit_service.verify_executive_access(current_user)
    except audit_service.AuditAccessDeniedError as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(error),
        ) from error


@router.get("/view", response_class=HTMLResponse)
def render_audit_page(
    request: Request,
    current_user: dict = Depends(require_role(EXECUTIVE_ACCESS)),
):
    """Render the executive-only audit center."""
    _validate_executive(current_user)
    return templates.TemplateResponse(
        request=request,
        name="audit.html",
        context={"request": request},
    )


@router.get("/logs")
def list_audit_logs(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    current_user: dict = Depends(require_role(EXECUTIVE_ACCESS)),
):
    """Return administrative audit logs for executives."""
    _validate_executive(current_user)
    return audit_service.fetch_audit_logs(current_user, limit=limit, offset=offset)


@router.get("/welfare-logs")
def list_welfare_audit_logs(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    current_user: dict = Depends(require_role(EXECUTIVE_ACCESS)),
):
    """Return welfare audit logs for executives."""
    _validate_executive(current_user)
    return audit_service.fetch_welfare_audit_logs(
        current_user,
        limit=limit,
        offset=offset,
    )


@router.get("/pdf")
def download_audit_pdf(
    start_date: date = Query(..., description="First day included in the report"),
    end_date: date = Query(..., description="Last day included in the report"),
    current_user: dict = Depends(require_role(EXECUTIVE_ACCESS)),
):
    """Download audit records for an inclusive date range as a PDF."""
    _validate_executive(current_user)
    if start_date > end_date:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The start date must be on or before the end date.",
        )
    try:
        content = audit_service.build_audit_pdf(
            current_user=current_user,
            start_date=start_date,
            end_date=end_date,
        )
    except Exception as error:
        logger.exception("Could not generate the audit PDF.")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not generate the audit PDF.",
        ) from error
    return Response(
        content=content,
        media_type="application/pdf",
        headers={
            "Content-Disposition": (
                f'attachment; filename="comfort-group-audit-{start_date.isoformat()}'
                f'-to-{end_date.isoformat()}.pdf"'
            )
        },
    )
