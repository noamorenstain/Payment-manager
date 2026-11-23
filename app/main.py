"""FastAPI application factory and startup sequence.

Startup (plan §2): data folders → open database → migrate (with a pre-migration snapshot
when upgrading existing data) → integrity checks (problems become a Hebrew banner).
Later phases add recurring generation and backups to this sequence.
"""

from __future__ import annotations

import datetime as dt
import logging
import sqlite3
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import APP_NAME, __version__
from app.clock import Clock
from app.config import AppConfig
from app.db.connection import Database
from app.db.migrate import migrate
from app.domain import dates as d
from app.domain import money as m
from app.i18n import he
from app.paths import DataPaths
from app.services import lookups
from app.services.common import NotFound
from app.services.integrity import run_integrity_checks
from app.web.deps import get_conn
from app.web.routes import invoices as invoice_routes
from app.web.routes import lists as list_routes
from app.web.routes import obligations as obligation_routes
from app.web.routes import settings as settings_routes
from app.web.security import SecurityMiddleware, csrf_protect, new_csrf_token

log = logging.getLogger(__name__)

APP_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = APP_DIR / "templates"
STATIC_DIR = APP_DIR / "static"


# ------------------------------------------------------------------ template filters

def filter_he_date(value) -> str:
    """Display format required by the spec: DD/MM/YYYY (accepts date or ISO string)."""
    if not value:
        return ""
    if isinstance(value, str):
        value = d.from_iso(value)
    return d.format_he(value)


def filter_money(minor, currency: str) -> str:
    return m.format_money(minor, currency)


def filter_he_datetime(value: str | None) -> str:
    """'2026-11-12 09:05:00' → '12/11/2026 09:05'."""
    if not value:
        return ""
    stamp = dt.datetime.fromisoformat(value)
    return stamp.strftime("%d/%m/%Y %H:%M")


def static_version() -> str:
    """Cache-busting token for /static URLs: changes whenever any static file changes, so the
    browser never keeps running an outdated script or stylesheet after an update."""
    stamp = max((p.stat().st_mtime_ns for p in STATIC_DIR.rglob("*") if p.is_file()), default=0)
    return format(stamp // 1_000_000 % (36 ** 8), "x")


def initialise_database(paths: DataPaths, clock: Clock) -> tuple[Database, list]:
    db = Database(paths.db_file)
    result = migrate(db, backup_dir=paths.backup_dir("pre-migration"),
                     now_label=clock.now().strftime("%Y%m%d-%H%M%S"))
    if result["from"] != result["to"]:
        log.info("Database migrated from v%s to v%s", result["from"], result["to"])
    with db.connection() as conn:
        issues = run_integrity_checks(conn)
    for issue in issues:
        log.error("Integrity issue [%s] %s %s", issue.code, issue.message, issue.detail)
    return db, issues


def create_app(config: AppConfig, clock: Clock | None = None) -> FastAPI:
    clock = clock or Clock()
    paths = DataPaths(config.data_root)
    paths.ensure_layout()
    db, issues = initialise_database(paths, clock)

    app = FastAPI(title=APP_NAME, version=__version__, docs_url=None, redoc_url=None,
                  openapi_url=None, dependencies=[Depends(csrf_protect)])
    app.state.config = config
    app.state.paths = paths
    app.state.clock = clock
    app.state.db = db
    app.state.integrity_issues = issues
    app.state.csrf_token = new_csrf_token()

    app.add_middleware(SecurityMiddleware, port=config.port)

    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    templates.env.filters["he_date"] = filter_he_date
    templates.env.filters["money"] = filter_money
    # Globals are visible inside imported macros ({% import %} does not pass page context).
    templates.env.globals.update(
        he=he,
        csrf_token=app.state.csrf_token,
        static_v=static_version(),
        OBLIGATION_STATES=he.OBLIGATION_STATES,
        INVOICE_STATES=he.INVOICE_STATES,
        PAYMENT_METHODS=he.PAYMENT_METHODS,
        AUDIT_ACTIONS=he.AUDIT_ACTIONS,
        ENTITY_TYPES=he.ENTITY_TYPES,
    )
    templates.env.filters["he_datetime"] = filter_he_datetime
    app.state.templates = templates

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    def render(request: Request, template: str, status_code: int = 200, **context) -> HTMLResponse:
        today: dt.date = clock.today()
        base = {
            "he": he,
            "nav_items": he.NAV_ITEMS,
            "current_path": request.url.path,
            "today": today,
            "today_weekday": he.WEEKDAYS[today.weekday()],
            "last_backup": None,  # wired up in Phase E
            "version": __version__,
            "csrf_token": app.state.csrf_token,
            "integrity_issues": app.state.integrity_issues,
        }
        base.update(context)
        return templates.TemplateResponse(request, template, base, status_code=status_code)

    app.state.render = render

    @app.get("/health")
    def health():
        return {"app": APP_NAME, "version": __version__, "status": "ok"}

    @app.get("/", response_class=HTMLResponse)
    def dashboard(request: Request, conn: sqlite3.Connection = Depends(get_conn)):
        return render(request, "dashboard.html", page_title=he.PAGE_TITLES["/"],
                      onboarding=lookups.is_onboarding_needed(conn))

    for router in (settings_routes.router, invoice_routes.router, obligation_routes.router, list_routes.router):
        app.include_router(router)

    # Placeholder screens for later phases, so the navigation shell is complete.
    for path in ("/recurring",):

        def _placeholder(request: Request, _path=path):
            return render(request, "placeholder.html", page_title=he.PAGE_TITLES[_path])

        app.add_api_route(path, _placeholder, methods=["GET"], response_class=HTMLResponse)

    def _error_page(request: Request, status: int, title: str, body: str):
        return render(request, "error.html", status_code=status,
                      page_title=title, error_title=title, error_body=body)

    @app.exception_handler(NotFound)
    async def not_found(request: Request, exc: NotFound):
        return _error_page(request, 404, he.NOT_FOUND_TITLE, he.NOT_FOUND_BODY)

    @app.exception_handler(RequestValidationError)
    async def bad_request(request: Request, exc: RequestValidationError):
        # e.g. /invoices/abc — a malformed id is simply a page that does not exist
        return _error_page(request, 404, he.NOT_FOUND_TITLE, he.NOT_FOUND_BODY)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        if request.url.path.startswith(("/api/", "/health", "/static/")):
            return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
        if exc.status_code in (404, 405):
            return _error_page(request, exc.status_code, he.NOT_FOUND_TITLE, he.NOT_FOUND_BODY)
        if exc.status_code == 403:
            body = exc.detail if isinstance(exc.detail, str) else he.CSRF_FAILED
            return _error_page(request, 403, he.FORBIDDEN_TITLE, body)
        return _error_page(request, exc.status_code, he.SERVER_ERROR_TITLE, he.SERVER_ERROR_BODY)

    @app.exception_handler(Exception)
    async def unhandled_error(request: Request, exc: Exception):
        log.exception("Unhandled error on %s %s", request.method, request.url.path)
        return _error_page(request, 500, he.SERVER_ERROR_TITLE, he.SERVER_ERROR_BODY)

    log.info("Payment Manager %s initialised; data root: %s", __version__, paths.root)
    return app
