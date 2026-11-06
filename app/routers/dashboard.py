from fastapi import APIRouter, Depends, HTTPException
from app.dependencies import get_current_user, require_role
from app.services import dashboard_service

router = APIRouter(prefix="/api", tags=["Protected Endpoints"])


@router.get("/dashboard/summary")
def get_dashboard_summary(current_user: dict = Depends(get_current_user)):
    try:
        return {
            "status": "success",
            "data": dashboard_service.fetch_member_dashboard_summary(
                current_user["member_id"]
            ),
        }
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# 1. Any authenticated member can access this
@router.get("/profile/me")
def get_my_profile(current_user: dict = Depends(get_current_user)):
    return {
        "status": "success",
        "profile": current_user
    }

# 2. Only Chairperson or Secretary can post announcements
@router.post("/announcements")
def post_announcement(
    title: str, 
    content: str, 
    current_user: dict = Depends(require_role(["Chairperson", "Secretary"]))
):
    # Your business logic here to save announcement to Neon
    return {
        "status": "success",
        "message": f"Announcement posted by {current_user['full_name']}"
    }

# 3. Only Chairperson can access financial reconciliation
@router.get("/admin/reconciliation")
def historical_reconciliation(
    current_user: dict = Depends(require_role(["Chairperson"]))
):
    return {
        "status": "success",
        "data": "Chairperson-only historical reconciliation data..."
    }