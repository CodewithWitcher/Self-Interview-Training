"""Home page and profiles (F1)."""

import sqlite3

from fastapi import APIRouter, Form, Request

from app import sessions
from app.db import Conn, utc_now
from app.routes import load_profile, redirect, render

router = APIRouter()

NAME_MAX = 60


def list_profiles(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT id, name FROM profiles ORDER BY name COLLATE NOCASE").fetchall()


@router.get("/")
def home(request: Request, conn: Conn):
    return render(request, "home.html", profiles=list_profiles(conn), form_name="", error=None)


@router.post("/profiles")
def create_profile(request: Request, conn: Conn, name: str = Form("")):
    clean = name.strip()
    error = None
    if not 1 <= len(clean) <= NAME_MAX:
        error = f"A profile name has 1 to {NAME_MAX} characters."
    elif conn.execute("SELECT 1 FROM profiles WHERE name = ?", (clean,)).fetchone():
        error = "A profile with this name already exists. Names are compared ignoring case."
    if error:
        return render(
            request, "home.html", 422, profiles=list_profiles(conn), form_name=name, error=error
        )
    with conn:
        pid = conn.execute(
            "INSERT INTO profiles (name, created_at) VALUES (?, ?)", (clean, utc_now())
        ).lastrowid
    return redirect(f"/profiles/{pid}?notice=profile_created")


def profile_page(request: Request, conn: sqlite3.Connection, profile, status_code=200, **extra):
    from app.routes.sessions import start_form_context

    active = sessions.active_session(conn, profile["id"])
    context = {
        "profile": profile,
        "delete_error": None,
        "active": active,
        "active_position": sessions.progress(conn, active["id"]) if active else None,
        "due": sessions.due_count(conn, profile["id"], request.app.state.today()),
        "form_review_only": False,
    }
    context.update(start_form_context(conn, profile, request.app.state.settings))
    context.update(extra)
    return render(request, "profile.html", status_code, **context)


@router.get("/profiles/{pid}")
def profile_home(request: Request, conn: Conn, pid: int):
    profile = load_profile(conn, pid)
    return profile_page(request, conn, profile)


@router.post("/profiles/{pid}/delete")
def delete_profile(request: Request, conn: Conn, pid: int, confirm: str = Form("")):
    profile = load_profile(conn, pid)
    if confirm.strip() != profile["name"]:
        return profile_page(
            request,
            conn,
            profile,
            422,
            delete_error="The name you typed does not match. Nothing was deleted.",
        )
    with conn:
        conn.execute("DELETE FROM profiles WHERE id = ?", (pid,))
    return redirect("/")
