"""Progress page: readiness, topic bars and past sessions (F13)."""

from fastapi import APIRouter, Request

from app import progress
from app.db import Conn
from app.routes import load_profile, render

router = APIRouter()


@router.get("/profiles/{pid}/progress")
def show(request: Request, conn: Conn, pid: int):
    profile = load_profile(conn, pid)
    data = progress.profile_progress(conn, pid, request.app.state.today())
    return render(request, "progress.html", profile=profile, **data)
