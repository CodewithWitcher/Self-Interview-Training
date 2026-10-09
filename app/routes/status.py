"""Status page (F10)."""

from fastapi import APIRouter, Request

from app.health import run_checks
from app.routes import render

router = APIRouter()


@router.get("/status")
def status(request: Request):
    checks = run_checks(request.app.state.settings)
    return render(request, "status.html", checks=checks)
