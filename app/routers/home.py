import logging
from starlette.concurrency import run_in_threadpool
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.dependencies import get_current_user, require_role
from app.services import home_gallery_service, home_service


router = APIRouter(tags=["Home Dashboard"])
templates = Jinja2Templates(directory="templates")
ANNOUNCEMENT_MANAGERS = ["Chairperson", "Secretary"]
GALLERY_MANAGERS = ["Chairperson", "Secretary"]
logger = logging.getLogger(__name__)


class AnnouncementRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=160)
    content: str = Field(min_length=1, max_length=5000)

    @field_validator("title", "content")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        if not value:
            raise ValueError("This field cannot be blank.")
        return value


def _render_home(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="home.html",
        context={"request": request},
    )


@router.get("/home", response_class=HTMLResponse)
def render_home_page(
    request: Request,
    current_user: dict = Depends(get_current_user),
) -> HTMLResponse:
    """Renders the authenticated member home dashboard."""
    return _render_home(request)


@router.get("/api/home/view", response_class=HTMLResponse)
def render_legacy_home_page(
    request: Request,
    current_user: dict = Depends(get_current_user),
) -> HTMLResponse:
    """Keeps the existing sidebar URL working while serving the new dashboard."""
    return _render_home(request)


@router.get("/api/home/summary")
def get_home_summary(current_user: dict = Depends(get_current_user)) -> dict:
    """Returns dashboard data for the authenticated member."""
    try:
        return {
            "status": "success",
            "data": home_service.fetch_home_summary(
                current_user["member_id"],
                current_user.get("role", ""),
            ),
        }
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to load home summary dashboard.")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not load dashboard summary.",
        ) from exc


@router.post("/api/home/announcements", status_code=status.HTTP_201_CREATED)
def create_announcement(
    payload: AnnouncementRequest,
    current_user: dict = Depends(require_role(ANNOUNCEMENT_MANAGERS)),
) -> dict:
    """Publishes an announcement to all members."""
    return {
        "status": "success",
        "data": home_service.publish_announcement(
            title=payload.title,
            content=payload.content,
            author_name=current_user.get("full_name") or current_user["member_id"],
        ),
    }


@router.get("/api/home/gallery")
def get_home_gallery(current_user: dict = Depends(get_current_user)) -> dict:
    return {
        "status": "success",
        "data": home_gallery_service.list_gallery_images(),
    }


@router.post("/api/home/gallery/{slot}", status_code=status.HTTP_201_CREATED)
async def replace_home_gallery_image(
    slot: int,
    image: UploadFile = File(...),
    current_user: dict = Depends(require_role(GALLERY_MANAGERS)),
) -> dict:
    try:
        contents = await image.read(home_gallery_service.MAX_IMAGE_SIZE_BYTES + 1)
    finally:
        await image.close()
    try:
        saved = await run_in_threadpool(
            home_gallery_service.replace_gallery_image,
            slot=slot,
            contents=contents,
            uploaded_by=current_user.get("full_name") or current_user["member_id"],
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except home_gallery_service.CloudinaryError as exc:
        logger.exception("Could not save a Home Dashboard gallery image.")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc
    return {"status": "success", "data": saved}
