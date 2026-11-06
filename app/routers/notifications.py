# app/routers/notifications.py
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from app.dependencies import get_current_user
from app.services import notification_service

router = APIRouter(prefix="/api/notifications", tags=["Notifications & Reminders"])
templates = Jinja2Templates(directory="templates")

@router.get("/")
def get_my_notifications(current_user: dict = Depends(get_current_user)):
    """API endpoint to fetch current member's notifications."""
    data = notification_service.fetch_member_notifications(current_user["member_id"])
    return {"status": "success", "data": data}

@router.put("/{notification_id}/read")
def mark_read(notification_id: int, current_user: dict = Depends(get_current_user)):
    """API endpoint to mark a notification as read."""
    try:
        return notification_service.set_notification_read(notification_id, current_user["member_id"])
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.get("/view", response_class=HTMLResponse)
def render_notifications_page(request: Request):
    """Renders the HTML notifications dashboard view."""
    return templates.TemplateResponse(
        request=request,
        name="notifications.html",
        context={"request": request},
    )