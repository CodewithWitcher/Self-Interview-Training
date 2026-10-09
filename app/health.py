"""Environment checks for the status page and the command line (F10, AR 4).

uv run python -m app.health
"""

import importlib
import platform
import sqlite3
import sys
from contextlib import closing
from dataclasses import dataclass

import httpx

from app import db
from app.config import Settings, load_settings

SUPPORTED_PLATFORMS = {("Windows", "AMD64"), ("Darwin", "arm64")}


@dataclass(frozen=True)
class Check:
    name: str
    required: bool
    ok: bool | None  # None means skipped
    detail: str

    @property
    def label(self) -> str:
        return {True: "PASS", False: "FAIL", None: "SKIP"}[self.ok]


def check_python() -> Check:
    version = platform.python_version()
    system, machine = platform.system(), platform.machine()
    ok = sys.version_info[:2] == (3, 13)
    detail = f"Python {version} on {system} {machine}"
    if (system, machine) not in SUPPORTED_PLATFORMS:
        detail += " (not a supported system: Windows x64 and macOS on Apple Silicon are)"
    if not ok:
        detail += ". Python 3.13 is required: run uv sync"
    return Check("Python and system", True, ok, detail)


def check_data_dir(settings: Settings) -> Check:
    path = settings.data_dir
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        return Check("Data folder writable", True, False, f"{path}: {exc.strerror or exc}")
    return Check("Data folder writable", True, True, str(path))


def check_database(settings: Settings) -> Check:
    latest = db.latest_version()
    name = "Database version"
    if not settings.db_path.is_file():
        return Check(
            name, True, True, f"Not created yet. It is created at version {latest} on start."
        )
    try:
        with closing(sqlite3.connect(settings.db_path)) as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
    except sqlite3.Error as exc:
        return Check(name, True, False, f"Cannot read {settings.db_path}: {exc}")
    if version > latest:
        return Check(name, True, False, f"Version {version} is newer than this code ({latest})")
    if version < latest:
        return Check(name, True, True, f"Version {version}, upgraded to {latest} on next start")
    return Check(name, True, True, f"Version {version}")


def check_anthropic_import() -> Check:
    try:
        importlib.import_module("anthropic")
    except ImportError as exc:
        return Check(
            "Claude library",
            True,
            False,
            f"import anthropic failed ({exc.__class__.__name__}). On Windows this usually means "
            "the folder path is too long: see trap 1 in section 7 of docs/05-setup-guide.md",
        )
    return Check("Claude library", True, True, "import anthropic works")


def check_embedding_model(settings: Settings) -> Check:
    name = "Embedding model"
    if settings.dev_fake:
        return Check(name, False, None, "Skipped in fake mode")
    from app.embeddings import model_present

    if model_present(settings):
        return Check(name, False, True, "all-MiniLM-L6-v2 is downloaded")
    return Check(name, False, False, "Not downloaded. Run: uv run python -m app.fetch_models")


def check_speech_model(settings: Settings) -> Check:
    name = "Speech model"
    if settings.dev_fake:
        return Check(name, False, None, "Skipped in fake mode")
    from app.voice import model_present

    if model_present(settings):
        return Check(name, False, True, f"{settings.whisper_model} is downloaded")
    return Check(
        name,
        False,
        False,
        "Not downloaded. Needed only for spoken answers. Run: uv run python -m app.fetch_models --voice",
    )


def check_ollama(settings: Settings) -> Check:
    name = "Ollama"
    if settings.dev_fake:
        return Check(name, False, None, "Skipped in fake mode")
    try:
        r = httpx.get(f"{settings.ollama_url}/api/tags", timeout=3.0)
        r.raise_for_status()
        entries = r.json().get("models", [])
    except (httpx.HTTPError, ValueError) as exc:
        return Check(
            name, False, False, f"Not reachable at {settings.ollama_url} ({exc.__class__.__name__})"
        )
    local = [e.get("name", "?") for e in entries if "remote_host" not in e]
    if not local:
        return Check(
            name, False, False, "Reachable, but no local model. Run: ollama pull llama3.1:8b"
        )
    return Check(name, False, True, "Local models: " + ", ".join(sorted(local)))


def check_claude_key(settings: Settings) -> Check:
    name = "Claude key"
    if settings.dev_fake:
        return Check(name, False, None, "Skipped in fake mode")
    if settings.anthropic_api_key:
        return Check(name, False, True, "ANTHROPIC_API_KEY is set")
    return Check(
        name,
        False,
        False,
        "ANTHROPIC_API_KEY is not set. Only needed for cloud mode. A login made with ant may still work.",
    )


def run_checks(settings: Settings) -> list[Check]:
    return [
        check_python(),
        check_data_dir(settings),
        check_database(settings),
        check_anthropic_import(),
        check_embedding_model(settings),
        check_speech_model(settings),
        check_ollama(settings),
        check_claude_key(settings),
    ]


def format_line(check: Check) -> str:
    kind = "required" if check.required else "optional"
    line = f"[{check.label}] {check.name} ({kind}): {check.detail}"
    return line.encode("ascii", "replace").decode("ascii")


def main(settings: Settings | None = None) -> int:
    if settings is None:
        settings = load_settings()
    checks = run_checks(settings)
    for check in checks:
        print(format_line(check))
    failed = [c for c in checks if c.required and c.ok is False]
    print("Result: " + ("FAIL, a required check failed" if failed else "OK"))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
