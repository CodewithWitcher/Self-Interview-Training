"""Resume text extraction, chunking and saving (F2, PS 8.1, DM 5)."""

import io
import sqlite3
from pathlib import PurePath

import pypdf
from pypdf.errors import PyPdfError

from app import embeddings
from app.config import Settings

MAX_FILE_BYTES = 5 * 1024 * 1024
MIN_CHARS = 200
MAX_CHARS = 12_000
CHUNK_MAX_CHARS = 800
CHUNK_MIN_CLOSE = 200
EXTENSIONS = (".pdf", ".txt", ".md")

PASTE_HINT = "You can paste the text into the box instead."


class ResumeError(ValueError):
    """Input the app cannot use. The message is shown to the user."""


def extract_text(filename: str, data: bytes) -> str:
    """Text of an uploaded resume. The file name is only used for its extension."""
    suffix = PurePath(filename).suffix.lower()
    if suffix not in EXTENSIONS:
        raise ResumeError(f"Only PDF, TXT and MD files can be read. {PASTE_HINT}")
    if len(data) > MAX_FILE_BYTES:
        raise ResumeError(f"The file is larger than 5 MB. {PASTE_HINT}")
    if suffix == ".pdf":
        return _pdf_text(data)
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ResumeError(f"The file is not UTF-8 text. {PASTE_HINT}") from None


def _pdf_text(data: bytes) -> str:
    unreadable = f"This PDF could not be read. {PASTE_HINT}"
    if not data.startswith(b"%PDF-"):
        raise ResumeError(unreadable)
    try:
        reader = pypdf.PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise ResumeError(f"This PDF is password protected. {PASTE_HINT}")
        pages = [page.extract_text() or "" for page in reader.pages]
    except PyPdfError:
        raise ResumeError(unreadable) from None
    text = "\n".join(p.strip("\n") for p in pages).strip()
    if not text:
        raise ResumeError(
            f"This PDF has no text that can be extracted, for example a scan. {PASTE_HINT}"
        )
    return text


def check_text(text: str) -> str | None:
    """The error message for resume text outside the limits, or None."""
    n = len(text.strip())
    if n < MIN_CHARS:
        return f"The resume text has {n} characters. It needs at least {MIN_CHARS:,}."
    if n > MAX_CHARS:
        return f"The resume text has {n:,} characters. The limit is {MAX_CHARS:,}. Shorten it and save again."
    return None


def chunk_text(text: str) -> list[str]:
    """Pack lines into chunks of at most 800 characters, exactly as PS 8.1."""
    chunks: list[str] = []
    current = ""

    def close() -> None:
        nonlocal current
        if current:
            chunks.append(current)
        current = ""

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            if len(current) >= CHUNK_MIN_CLOSE:
                close()
            continue
        while len(line) > CHUNK_MAX_CHARS:
            close()
            chunks.append(line[:CHUNK_MAX_CHARS])
            line = line[CHUNK_MAX_CHARS:]
        if current and len(current) + 1 + len(line) > CHUNK_MAX_CHARS:
            close()
        current = f"{current}\n{line}" if current else line
    close()
    return chunks


def save_resume(
    conn: sqlite3.Connection, profile_id: int, text: str, name: str | None, settings: Settings
) -> int:
    """Replace the profile's resume text, chunks and embeddings in one transaction."""
    text = text.strip()
    chunks = chunk_text(text)
    vectors = embeddings.embed(chunks, settings)
    with conn:
        conn.execute(
            "UPDATE profiles SET resume_text = ?, resume_name = ? WHERE id = ?",
            (text, name, profile_id),
        )
        conn.execute("DELETE FROM resume_chunks WHERE profile_id = ?", (profile_id,))
        conn.executemany(
            "INSERT INTO resume_chunks (profile_id, ord, text, embedding) VALUES (?, ?, ?, ?)",
            [
                (profile_id, i, chunk, embeddings.to_blob(vec))
                for i, (chunk, vec) in enumerate(zip(chunks, vectors, strict=True), start=1)
            ],
        )
    return len(chunks)
