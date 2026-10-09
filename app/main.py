"""App factory, security middleware, error pages and the startup sequence (AR 1, 9, 10)."""

import logging
import os
import random
import secrets
from datetime import date
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.formparsers import MultiPartParser
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import PlainTextResponse

from app import db, embeddings
from app.config import Settings, load_settings
from app.routes import plan, profiles, progress, render, resume, sessions, status, voice

log = logging.getLogger("app")

STATIC_DIR = Path(__file__).resolve().parent / "static"
ALLOWED_HOSTS = ["127.0.0.1", "localhost"]
ALLOWED_FETCH_SITES = {"same-origin", "none"}
# The largest upload is a 25 MB recording (DM 5). Anything bigger is refused before parsing.
MAX_BODY_BYTES = 27 * 1024 * 1024

# AR 9 rules 7 and 13: uploads stay in memory and are never spooled to a temporary file.
MultiPartParser.spool_max_size = MAX_BODY_BYTES


def startup(settings: Settings) -> None:
    """Steps 2 to 4 of the startup sequence in AR 1."""
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    conn = db.connect(settings.db_path)
    try:
        version = db.migrate(conn)
        log.info("database ready at version %s", version)
        try:
            embeddings.backfill(conn, settings)
        except embeddings.EmbeddingModelMissing:
            log.warning("embedding model missing, backfill skipped")
    finally:
        conn.close()


def create_app(settings: Settings | None = None) -> FastAPI:
    if settings is None:
        settings = load_settings()
    # AR 9 rule 11: no model file is ever fetched while the app runs.
    os.environ["HF_HUB_OFFLINE"] = "1"
    startup(settings)

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.state.settings = settings
    app.state.today = date.today
    app.state.rng = random.Random()
    app.state.flash = {}

    allowed_origins = {f"http://{host}:{settings.port}" for host in ALLOWED_HOSTS}

    @app.middleware("http")
    async def reject_cross_site_posts(request: Request, call_next):
        length = request.headers.get("content-length", "")
        if length.isdigit() and int(length) > MAX_BODY_BYTES:
            return PlainTextResponse("The upload is too large.", status_code=413)
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("origin")
            site = request.headers.get("sec-fetch-site")
            if (origin is not None and origin not in allowed_origins) or (
                site is not None and site not in ALLOWED_FETCH_SITES
            ):
                log.warning("cross-site %s rejected", request.method)
                return PlainTextResponse("Cross-site request rejected.", status_code=403)
        return await call_next(request)

    # Added last, so it runs first: a wrong Host header never reaches anything else.
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=ALLOWED_HOSTS)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        if exc.status_code == 404:
            return render(
                request, "error.html", 404, title="Not found", message="This page does not exist."
            )
        if exc.status_code == 405:
            return render(
                request,
                "error.html",
                405,
                title="Not allowed",
                message="That action is not allowed here.",
            )
        return render(
            request, "error.html", exc.status_code, title="Error", message=str(exc.detail)
        )

    @app.exception_handler(Exception)
    async def server_error(request: Request, exc: Exception):
        error_id = secrets.token_hex(4)
        log.error("error %s on %s %s", error_id, request.method, request.url.path, exc_info=exc)
        return render(
            request,
            "error.html",
            500,
            title="Something went wrong",
            message=f"The app hit an unexpected error. Error id: {error_id}. Details are in the log.",
        )

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.include_router(profiles.router)
    app.include_router(resume.router)
    app.include_router(plan.router)
    app.include_router(sessions.router)
    app.include_router(progress.router)
    app.include_router(voice.router)
    app.include_router(status.router)
    return app
