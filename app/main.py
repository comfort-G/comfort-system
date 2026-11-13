# app/main.py
import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from psycopg2 import InterfaceError, OperationalError
from psycopg2.errors import ObjectNotInPrerequisiteState
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from starlette.concurrency import run_in_threadpool
from app.database import init_db_pool, close_db_pool, get_db
from app.limiter import limiter
from app.repositories import loan_repo
from app.repositories import welfare_refill_repo
from app.routers import auth
from app.routers import subscriptions
from app.routers import loans
from app.routers import admin_members
from app.routers import sharing
from app.routers import home
from app.routers import family
from app.routers import audit
from app.routers import welfare
from app.routers import notifications
from app.routers import dashboard
from app.routers import executive_actions
from app.routers import treasurer_reports
from app.routers import about
from app.routers import profile

logger = logging.getLogger(__name__)


async def _run_loan_interest_scheduler() -> None:
    while True:
        try:
            result = await run_in_threadpool(loan_repo.apply_due_loan_interest)
            if result["loan_count"]:
                logger.info(
                    "Applied monthly interest to %s loan(s) across %s due installment(s); "
                    "total interest added: UGX %s.",
                    result["loan_count"],
                    result["installment_count"],
                    result["interest_added"],
                )
        except Exception:
            logger.exception("Automatic monthly loan-interest accrual failed.")
        await asyncio.sleep(60)


async def _run_welfare_refill_scheduler() -> None:
    while True:
        try:
            top_ups = await run_in_threadpool(
                welfare_refill_repo.top_up_existing_welfare_balances
            )
            result = await run_in_threadpool(
                welfare_refill_repo.process_due_welfare_refills
            )
            transfer_count = top_ups["transfer_count"] + result["transfer_count"]
            if transfer_count:
                logger.info(
                    "Automatically refilled welfare accounts for %s member(s); "
                    "total transferred from savings: UGX %s.",
                    top_ups["member_count"] + result["member_count"],
                    top_ups["amount"] + result["amount"],
                )
        except Exception:
            logger.exception("Automatic welfare-account refill failed.")
        await asyncio.sleep(60)


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Startup: Initialize DB Pool
    init_db_pool()
    initial_top_up = await run_in_threadpool(
        welfare_refill_repo.top_up_existing_welfare_balances
    )
    while initial_top_up["has_more"]:
        initial_top_up = await run_in_threadpool(
            welfare_refill_repo.top_up_existing_welfare_balances
        )
    if initial_top_up["transfer_count"]:
        logger.info(
            "Startup welfare sweep transferred UGX %s from savings for %s member(s).",
            initial_top_up["amount"],
            initial_top_up["member_count"],
        )
    interest_scheduler = asyncio.create_task(_run_loan_interest_scheduler())
    welfare_refill_scheduler = asyncio.create_task(
        _run_welfare_refill_scheduler()
    )
    try:
        yield
    finally:
        interest_scheduler.cancel()
        welfare_refill_scheduler.cancel()
        try:
            await interest_scheduler
        except asyncio.CancelledError:
            pass
        try:
            await welfare_refill_scheduler
        except asyncio.CancelledError:
            pass
        # Shutdown: Close DB pool
        close_db_pool()

app = FastAPI(
    title="Comfort Group API",
    description="Backend API for Comfort Group Portal connected to Neon PostgreSQL",
    version="2.0.0",
    lifespan=lifespan
)
app.state.limiter = limiter

STATIC_DIR = Path(__file__).resolve().parents[1] / "static"


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return FileResponse(STATIC_DIR / "images" / "favicon.ico")


async def rate_limit_exceeded_handler(request: Request, exc: Exception):
    if not isinstance(exc, RateLimitExceeded):
        raise exc
    return _rate_limit_exceeded_handler(request, exc)


app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)


@app.exception_handler(ObjectNotInPrerequisiteState)
async def suspended_member_transaction_error(_request, _exc):
    del _request, _exc
    return JSONResponse(
        status_code=409,
        content={"detail": "Transactions for suspended member accounts are blocked."},
    )


async def database_connection_error(request: Request, exc: Exception):
    logger.error(
        "Database connection failed while handling %s %s.",
        request.method,
        request.url.path,
        exc_info=(type(exc), exc, exc.__traceback__),
    )
    message = (
        "The database is temporarily unreachable. Please wait a moment and try again. "
        "If you were submitting a transaction, check its status before retrying."
    )
    headers = {"Retry-After": "5"}

    if "text/html" in request.headers.get("accept", "").lower():
        return HTMLResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            headers=headers,
            content=(
                "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
                "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
                "<title>Service temporarily unavailable</title></head>"
                "<body style=\"font-family:system-ui,sans-serif;max-width:42rem;"
                "margin:12vh auto;padding:1.5rem;color:#243447\">"
                "<main><h1>We will be back shortly</h1>"
                f"<p>{message}</p><p>Please try again in a few moments.</p>"
                "</main></body></html>"
            ),
        )

    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        headers=headers,
        content={"detail": message},
    )


app.add_exception_handler(OperationalError, database_connection_error)
app.add_exception_handler(InterfaceError, database_connection_error)


@app.get("/")
def read_root():
    """Redirect visitors to the login page."""
    return RedirectResponse(url="/api/auth/page")


@app.get("/my-details")
def read_my_details():
    """Provide a short, memorable URL for the member's personal details page."""
    return RedirectResponse(url="/api/profile/my-details")


app.include_router(home.router)
app.include_router(family.router)
app.include_router(audit.router)
app.include_router(auth.router)
app.include_router(auth.password_reset_page_router)
app.include_router(subscriptions.router)
app.include_router(loans.router)
app.include_router(admin_members.router)
app.include_router(admin_members.account_router)
app.include_router(sharing.router)  # Year-End Sharing & Dividends
app.include_router(welfare.router)
app.include_router(notifications.router)
app.include_router(dashboard.router)
app.include_router(executive_actions.router)
app.include_router(treasurer_reports.router)
app.include_router(about.router)
app.include_router(profile.router)


# CORS Middleware setup
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8000", "http://127.0.0.1:8000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/sw.js", include_in_schema=False)
def service_worker():
    return FileResponse(
        STATIC_DIR / "sw.js",
        media_type="application/javascript",
        headers={"Service-Worker-Allowed": "/"},
    )


# Health Check Route
@app.get("/api/health")
def health_check():
    """Verifies that the API can communicate with Neon PostgreSQL."""
    try:
        with get_db() as cursor:
            cursor.execute("SELECT 1 AS status;")
            result = cursor.fetchone()
            return {"status": "healthy", "database": "connected", "result": result}
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database health check failed.",
        ) from exc