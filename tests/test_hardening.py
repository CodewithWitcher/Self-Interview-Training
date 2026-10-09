"""v1 hardening: isolation, template rules, log privacy and form labels (PR 8, DM 4, AR 9)."""

import logging
import re
from html.parser import HTMLParser
from pathlib import Path

from app.db import utc_now
from app.routes import TEMPLATES_DIR
from tests.helpers import answer, current, ready_profile, save_resume, start_session

TABLES = ("resume_chunks", "topics", "questions", "sessions", "attempts", "turns")

RESUME_A = (
    "Alpha Candidate\nBuilt the AlphaQuasar billing engine in Rust and owned its rollout.\n"
    + "Ran AlphaQuasar load tests every week and fixed the slowest queries.\n" * 3
)
RESUME_B = (
    "Beta Candidate\nDesigned the BetaNebula search cluster and its ranking pipeline.\n"
    + "Tuned BetaNebula relevance with weekly offline evaluations.\n" * 3
)


def all_pages(client, conn, pid):
    urls = [
        f"/profiles/{pid}",
        f"/profiles/{pid}/resume",
        f"/profiles/{pid}/plan",
        f"/profiles/{pid}/progress",
    ]
    for (sid,) in conn.execute("SELECT id FROM sessions WHERE profile_id = ?", (pid,)):
        urls.append(f"/profiles/{pid}/sessions/{sid}/summary")
        for (aid,) in conn.execute("SELECT id FROM attempts WHERE session_id = ?", (sid,)):
            urls.append(f"/profiles/{pid}/sessions/{sid}/attempts/{aid}")
    return urls


def make_history(client, conn, name, resume, marker):
    pid = ready_profile(client, name)
    save_resume(client, pid, resume)
    sid = start_session(client, conn, pid, ("Python", "Resume deep-dive"), 3)
    for i in range(3):
        answer(client, conn, pid, sid, f"{marker} answer {i}")
    client.post(f"/profiles/{pid}/topics", data={"name": f"{marker} topic", "kind": "technical"})
    return pid


def test_no_page_of_one_profile_shows_the_other(client, conn):
    a = make_history(client, conn, "Alpha", RESUME_A, "AlphaMarker")
    b = make_history(client, conn, "Beta", RESUME_B, "BetaMarker")
    a_questions = [
        r[0]
        for r in conn.execute(
            "SELECT q.text FROM questions q JOIN topics t ON t.id = q.topic_id WHERE t.profile_id = ?",
            (a,),
        )
    ]
    for url in all_pages(client, conn, b):
        text = client.get(url).text
        assert "AlphaQuasar" not in text, url
        assert "AlphaMarker" not in text, url
        assert all(q not in text for q in a_questions), url
    for url in all_pages(client, conn, a):
        text = client.get(url).text
        assert "BetaNebula" not in text and "BetaMarker" not in text, url


def test_ids_of_another_profile_are_404(client, conn):
    a = make_history(client, conn, "Alpha", RESUME_A, "AlphaMarker")
    b = ready_profile(client, "Beta")
    for url in all_pages(client, conn, a)[4:]:
        assert client.get(url.replace(f"/profiles/{a}/", f"/profiles/{b}/")).status_code == 404


def test_deleting_a_profile_leaves_no_row(client, conn):
    a = make_history(client, conn, "Alpha", RESUME_A, "AlphaMarker")
    b = make_history(client, conn, "Beta", RESUME_B, "BetaMarker")
    before = {t: conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in TABLES}
    client.post(f"/profiles/{a}/delete", data={"confirm": "Alpha"})
    checks = {
        "resume_chunks": "SELECT count(*) FROM resume_chunks WHERE profile_id = ?",
        "topics": "SELECT count(*) FROM topics WHERE profile_id = ?",
        "sessions": "SELECT count(*) FROM sessions WHERE profile_id = ?",
        "questions": "SELECT count(*) FROM questions WHERE topic_id NOT IN (SELECT id FROM topics)",
        "attempts": "SELECT count(*) FROM attempts WHERE session_id NOT IN (SELECT id FROM sessions)",
        "turns": "SELECT count(*) FROM turns WHERE attempt_id NOT IN (SELECT id FROM attempts)",
    }
    for table, sql in checks.items():
        args = (a,) if "?" in sql else ()
        assert conn.execute(sql, args).fetchone()[0] == 0, table
    after = {t: conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in TABLES}
    assert all(0 < after[t] < before[t] for t in TABLES)
    assert conn.execute("SELECT name FROM profiles").fetchall()[0][0] == "Beta"
    assert b


def test_templates_never_use_safe_or_remote_assets():
    remote = re.compile(r"""(?:src|href)\s*=\s*["']\s*(?:https?:)?//""", re.IGNORECASE)
    unsafe = re.compile(r"\|\s*safe\b|autoescape\s+false|Markup\(")
    templates = sorted(Path(TEMPLATES_DIR).glob("*.html"))
    assert len(templates) >= 10
    for path in templates:
        text = path.read_text(encoding="utf-8")
        assert not unsafe.search(text), path.name
        assert not remote.search(text), path.name
        assert "http://" not in text and "https://" not in text, path.name


def test_static_files_load_nothing_remote():
    static = Path(TEMPLATES_DIR).parent / "static"
    for path in static.iterdir():
        text = path.read_text(encoding="utf-8")
        assert "http://" not in text and "https://" not in text, path.name
        assert "@import" not in text and 'fetch("http' not in text, path.name


def test_logs_contain_no_private_text(client, conn, caplog):
    caplog.set_level(logging.DEBUG)
    pid = ready_profile(client, "Logger")
    save_resume(client, pid, RESUME_A)
    client.post(f"/profiles/{pid}/jd", data={"title": "SecretTitleXyz", "text": "SecretJdXyz text"})
    client.post(f"/profiles/{pid}/plan/build", data={"model": "fake:fake"})
    sid = start_session(client, conn, pid, ("Python", "Resume deep-dive"), 3)
    answer(client, conn, pid, sid, "SecretAnswerXyz one #followup")
    answer(client, conn, pid, sid, "SecretAnswerXyz two")
    answer(client, conn, pid, sid, "SecretAnswerXyz three #down")
    client.post(f"/profiles/{pid}/sessions/{sid}/end")
    logged = "\n".join(r.getMessage() for r in caplog.records)
    for secret in (
        "AlphaQuasar",
        "SecretTitleXyz",
        "SecretJdXyz",
        "SecretAnswerXyz",
        "You are a fair",
        "<answer>",
        "Fake follow-up",
        "Fake feedback",
        "Fake Python question",
    ):
        assert secret not in logged, secret
    assert "model call ok" in logged


class LabelChecker(HTMLParser):
    """Collects form controls and the label ids that point at them."""

    def __init__(self):
        super().__init__()
        self.controls = []
        self.labelled = set()
        self.label_depth = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "label":
            self.label_depth += 1
            if a.get("for"):
                self.labelled.add(a["for"])
        if tag in ("input", "select", "textarea") and a.get("type") not in ("hidden", "submit"):
            self.controls.append((a.get("id"), self.label_depth > 0 or bool(a.get("aria-label"))))

    def handle_endtag(self, tag):
        if tag == "label":
            self.label_depth -= 1


def test_every_control_on_every_page_has_a_label(client, conn):
    pid = make_history(client, conn, "Alpha", RESUME_A, "AlphaMarker")
    sid2 = start_session(client, conn, pid, ("SQL",), 3)
    aid, _ = current(conn, sid2)
    urls = [
        "/",
        "/status",
        f"/profiles/{pid}/sessions/{sid2}/attempts/{aid}",
        *all_pages(client, conn, pid),
    ]
    for url in urls:
        checker = LabelChecker()
        checker.feed(client.get(url).text)
        for control_id, wrapped in checker.controls:
            assert wrapped or control_id in checker.labelled, (url, control_id)


def test_every_page_has_one_h1_and_a_skip_link(client, conn):
    pid = make_history(client, conn, "Alpha", RESUME_A, "AlphaMarker")
    for url in ["/", "/status", *all_pages(client, conn, pid)]:
        text = client.get(url).text
        assert text.count("<h1") == 1, url
        assert 'href="#main"' in text, url


def test_delete_error_keeps_typed_name(client):
    pid = ready_profile(client, "Alpha")
    r = client.post(f"/profiles/{pid}/delete", data={"confirm": "Alhpa"})
    assert r.status_code == 422
    assert 'value="Alhpa"' in r.text


def test_utc_now_is_used_for_timestamps():
    assert utc_now().endswith("Z")
