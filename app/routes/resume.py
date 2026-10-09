"""Resume page: upload or paste, review, save (F2)."""

from typing import Annotated

from fastapi import APIRouter, File, Form, Request, UploadFile

from app import embeddings
from app.db import Conn
from app.resume import MAX_CHARS, MAX_FILE_BYTES, ResumeError, check_text, extract_text, save_resume
from app.routes import load_profile, redirect, render

router = APIRouter()


def resume_page(request, profile, status_code=200, **extra):
    context = {
        "profile": profile,
        "review_text": None,
        "review_name": "",
        "paste_text": "",
        "upload_error": None,
        "save_error": None,
        "max_chars": MAX_CHARS,
    }
    context.update(extra)
    return render(request, "resume.html", status_code, **context)


@router.get("/profiles/{pid}/resume")
def show(request: Request, conn: Conn, pid: int):
    profile = load_profile(conn, pid)
    return resume_page(request, profile)


@router.post("/profiles/{pid}/resume/extract")
async def extract(
    request: Request,
    conn: Conn,
    pid: int,
    file: Annotated[UploadFile | None, File()] = None,
    text: str = Form(""),
):
    profile = load_profile(conn, pid)
    if file is not None and file.filename:
        data = await file.read(MAX_FILE_BYTES + 1)
        try:
            extracted = extract_text(file.filename, data)
        except ResumeError as exc:
            return resume_page(request, profile, 422, upload_error=str(exc), paste_text=text)
        return resume_page(request, profile, review_text=extracted, review_name=file.filename)
    if not text.strip():
        return resume_page(
            request, profile, 422, upload_error="Choose a file or paste the resume text."
        )
    return resume_page(request, profile, review_text=text)


@router.post("/profiles/{pid}/resume")
def save(request: Request, conn: Conn, pid: int, text: str = Form(""), name: str = Form("")):
    profile = load_profile(conn, pid)
    error = check_text(text)
    if error:
        return resume_page(
            request, profile, 422, review_text=text, review_name=name, save_error=error
        )
    try:
        save_resume(conn, pid, text, name.strip()[:200] or None, request.app.state.settings)
    except embeddings.EmbeddingModelMissing as exc:
        return resume_page(
            request, profile, 422, review_text=text, review_name=name, save_error=str(exc)
        )
    return redirect(f"/profiles/{pid}/resume?notice=resume_saved")
