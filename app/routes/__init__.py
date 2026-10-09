"""Shared helpers for the route modules: templates, rendering and profile loading."""

import sqlite3
from pathlib import Path

from fastapi import HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"

templates = Jinja2Templates(directory=TEMPLATES_DIR)

# Messages shown after a redirect. The query string carries only the code, never text.
NOTICES = {
    "profile_created": "Profile created.",
    "resume_saved": "Resume saved.",
    "plan_built": "Plan built.",
    "topic_added": "Topic added.",
    "topic_updated": "Weight saved.",
    "jd_saved": "Job description saved. Rebuild the plan to use it.",
    "jd_cleared": "Job description removed. Rebuild the plan to return to a resume-only plan.",
    "session_ended": "The session was ended. Nothing was scored, so it was removed.",
    "model_changed": "Model changed. The next answer is scored with it.",
}


def render(request: Request, name: str, status_code: int = 200, **context) -> object:
    notice = NOTICES.get(request.query_params.get("notice", ""))
    context.setdefault("notice", notice)
    return templates.TemplateResponse(request, name, context, status_code=status_code)


def redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


def load_profile(conn: sqlite3.Connection, pid: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM profiles WHERE id = ?", (pid,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404)
    return row


def model_picker(conn: sqlite3.Connection, profile_id: int, settings) -> dict:
    """Template context for _model_picker.html."""
    from app import llm, sessions

    options = llm.list_models(settings)
    return {
        "model_options": options,
        "model_selected": sessions.preselected_model(conn, profile_id, settings, options),
        "has_local_model": any(o.is_local for o in options),
    }


def parse_model(value: str, settings) -> tuple[str, str] | None:
    """Split a picker value "provider:model". None when it is not usable."""
    provider, _, model = value.partition(":")
    model = model.strip()
    if not model or len(model) > 200:
        return None
    if settings.dev_fake:
        return (provider, model) if provider == "fake" else None
    if provider not in ("ollama", "anthropic"):
        return None
    return provider, model
