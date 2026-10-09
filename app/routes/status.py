"""Status page with environment checks and the Test model button (F10)."""

import time

from fastapi import APIRouter, Form, Request

from app import llm
from app.health import run_checks
from app.prompts import PING_SYSTEM, PING_USER, Ping
from app.routes import parse_model, render

router = APIRouter()


def status_page(request: Request, status_code=200, **extra):
    settings = request.app.state.settings
    options = llm.list_models(settings)
    context = {
        "checks": run_checks(settings),
        "model_options": options,
        "model_selected": options[0].value if options else "",
        "has_local_model": any(o.is_local for o in options),
        "test_result": None,
        "test_error": None,
    }
    context.update(extra)
    return render(request, "status.html", status_code, **context)


@router.get("/status")
def status(request: Request):
    return status_page(request)


@router.post("/status/test")
def test_model(request: Request, model: str = Form("")):
    settings = request.app.state.settings
    choice = parse_model(model, settings)
    if choice is None:
        return status_page(request, 422, test_error="Choose a model from the list.")
    started = time.monotonic()
    try:
        llm.chat(*choice, PING_SYSTEM, PING_USER, Ping, settings=settings)
    except llm.LLMError as exc:
        return status_page(request, model_selected=model, test_error=f"{model}: {exc.title}. {exc}")
    elapsed = time.monotonic() - started
    return status_page(
        request, model_selected=model, test_result=f"{model} answered in {elapsed:.1f} seconds."
    )
