"""Plan page: build, set weights, add topics (F3, F11)."""

from fastapi import APIRouter, Form, HTTPException, Request

from app import llm, plan
from app.db import Conn
from app.routes import load_profile, model_picker, parse_model, redirect, render

router = APIRouter()

JD_TITLE_MAX = 120
JD_TEXT_MAX = 6000

SOURCE_LABELS = {
    "resume": "Resume",
    "jd": "Job description",
    "both": "Resume and job description",
    "manual": "Added by you",
}


def plan_page(request, conn, profile, status_code=200, **extra):
    context = {
        "profile": profile,
        "topics": plan.topics(conn, profile["id"]),
        "source_labels": SOURCE_LABELS,
        "build_error": None,
        "topic_error": None,
        "topic_name": "",
        "topic_kind": "technical",
        "jd_title": profile["jd_title"] or "",
        "jd_text": profile["jd_text"] or "",
        "jd_error": None,
        "jd_title_max": JD_TITLE_MAX,
        "jd_text_max": JD_TEXT_MAX,
    }
    context.update(model_picker(conn, profile["id"], request.app.state.settings))
    context.update(extra)
    return render(request, "plan.html", status_code, **context)


@router.get("/profiles/{pid}/plan")
def show(request: Request, conn: Conn, pid: int):
    return plan_page(request, conn, load_profile(conn, pid))


@router.post("/profiles/{pid}/plan/build")
def build(request: Request, conn: Conn, pid: int, model: str = Form("")):
    profile = load_profile(conn, pid)
    settings = request.app.state.settings
    if not profile["resume_text"]:
        return plan_page(
            request,
            conn,
            profile,
            422,
            build_error="Save a resume first. The plan is built from it.",
        )
    choice = parse_model(model, settings)
    if choice is None:
        return plan_page(request, conn, profile, 422, build_error="Choose a model from the list.")
    try:
        plan.build_plan(conn, pid, choice[0], choice[1], settings)
    except llm.LLMError as exc:
        return plan_page(request, conn, profile, build_error=f"{exc.title}. {exc}")
    return redirect(f"/profiles/{pid}/plan?notice=plan_built")


@router.post("/profiles/{pid}/topics")
def add_topic(
    request: Request, conn: Conn, pid: int, name: str = Form(""), kind: str = Form("technical")
):
    profile = load_profile(conn, pid)
    error = plan.add_topic(conn, pid, name, kind)
    if error:
        return plan_page(
            request, conn, profile, 422, topic_error=error, topic_name=name, topic_kind=kind
        )
    return redirect(f"/profiles/{pid}/plan?notice=topic_added")


@router.post("/profiles/{pid}/topics/{tid}")
def set_weight(request: Request, conn: Conn, pid: int, tid: int, weight: str = Form("")):
    load_profile(conn, pid)
    topic = conn.execute(
        "SELECT id FROM topics WHERE id = ? AND profile_id = ?", (tid, pid)
    ).fetchone()
    if topic is None:
        raise HTTPException(status_code=404)
    if weight not in {"0", "1", "2", "3", "4", "5"}:
        raise HTTPException(status_code=422, detail="A weight is a whole number from 0 to 5.")
    with conn:
        conn.execute("UPDATE topics SET weight = ? WHERE id = ?", (int(weight), tid))
    return redirect(f"/profiles/{pid}/plan?notice=topic_updated#topic-{tid}")


@router.post("/profiles/{pid}/jd")
def save_jd(
    request: Request,
    conn: Conn,
    pid: int,
    title: str = Form(""),
    text: str = Form(""),
    action: str = Form("save"),
):
    profile = load_profile(conn, pid)
    if action == "clear":
        with conn:
            conn.execute("UPDATE profiles SET jd_title = NULL, jd_text = NULL WHERE id = ?", (pid,))
        return redirect(f"/profiles/{pid}/plan?notice=jd_cleared")
    clean_title, clean_text = title.strip(), text.strip()
    error = None
    if len(clean_title) > JD_TITLE_MAX:
        error = f"The job title has {len(clean_title)} characters. The limit is {JD_TITLE_MAX}."
    elif not clean_text:
        error = "Paste the job description, or press Remove to clear it."
    elif len(clean_text) > JD_TEXT_MAX:
        error = (
            f"The job description has {len(clean_text):,} characters. "
            f"The limit is {JD_TEXT_MAX:,}. Shorten it and save again."
        )
    if error:
        return plan_page(request, conn, profile, 422, jd_title=title, jd_text=text, jd_error=error)
    with conn:
        conn.execute(
            "UPDATE profiles SET jd_title = ?, jd_text = ? WHERE id = ?",
            (clean_title or None, clean_text, pid),
        )
    return redirect(f"/profiles/{pid}/plan?notice=jd_saved")
