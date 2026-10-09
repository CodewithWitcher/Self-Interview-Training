"""Session life cycle (F4, F8, AR 6)."""

import sqlite3

from app.config import Settings
from app.llm import ModelOption


def last_used_model(conn: sqlite3.Connection, profile_id: int) -> tuple[str, str] | None:
    row = conn.execute(
        "SELECT provider, model FROM sessions WHERE profile_id = ? ORDER BY id DESC LIMIT 1",
        (profile_id,),
    ).fetchone()
    return (row["provider"], row["model"]) if row else None


def preselected_model(
    conn: sqlite3.Connection, profile_id: int, settings: Settings, options: list[ModelOption]
) -> str:
    """The picker value to preselect: the profile's last choice, else the configured default (F9.1)."""
    values = [o.value for o in options]
    last = last_used_model(conn, profile_id)
    if last and f"{last[0]}:{last[1]}" in values:
        return f"{last[0]}:{last[1]}"
    if settings.dev_fake:
        return "fake:fake"
    if settings.default_provider == "anthropic":
        return f"anthropic:{settings.anthropic_model}"
    preferred = f"ollama:{settings.ollama_model}"
    if preferred in values:
        return preferred
    local = [o.value for o in options if o.is_local]
    return local[0] if local else preferred
