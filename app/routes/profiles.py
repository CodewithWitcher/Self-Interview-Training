"""Home page and profiles (F1)."""

from fastapi import APIRouter, Request

from app.db import Conn
from app.routes import render

router = APIRouter()


@router.get("/")
def home(request: Request, conn: Conn):
    profiles = conn.execute("SELECT id, name FROM profiles ORDER BY name").fetchall()
    return render(request, "home.html", profiles=profiles, form_name="", error=None)
