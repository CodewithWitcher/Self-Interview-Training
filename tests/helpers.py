"""Small helpers shared by the flow tests."""

from pathlib import Path

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def create_profile(client, name="Ana") -> int:
    r = client.post("/profiles", data={"name": name}, follow_redirects=False)
    assert r.status_code == 303, r.text
    return int(r.headers["location"].split("/")[2].split("?")[0])


def sample_resume() -> str:
    return (FIXTURES / "sample_resume.txt").read_text(encoding="utf-8")


def save_resume(client, pid, text=None) -> None:
    r = client.post(
        f"/profiles/{pid}/resume",
        data={"text": text or sample_resume(), "name": "sample_resume.txt"},
        follow_redirects=False,
    )
    assert r.status_code == 303, r.text


def build_plan(client, pid) -> None:
    r = client.post(
        f"/profiles/{pid}/plan/build", data={"model": "fake:fake"}, follow_redirects=False
    )
    assert r.status_code == 303, r.text


def ready_profile(client, name="Ana") -> int:
    """A profile with the sample resume and a fake plan."""
    pid = create_profile(client, name)
    save_resume(client, pid)
    build_plan(client, pid)
    return pid


def topic_row(conn, pid, name):
    return conn.execute(
        "SELECT * FROM topics WHERE profile_id = ? AND name = ?", (pid, name)
    ).fetchone()


def start_session(client, conn, pid, topics=("Python",), count=3, difficulty="easy"):
    """Start a session on the named topics. Returns the session id."""
    ids = [str(topic_row(conn, pid, name)["id"]) for name in topics]
    r = client.post(
        f"/profiles/{pid}/sessions",
        data={"topics": ids, "count": str(count), "difficulty": difficulty, "model": "fake:fake"},
        follow_redirects=False,
    )
    assert r.status_code == 303, r.text
    return int(r.headers["location"].rsplit("/", 1)[1])


def current(conn, sid):
    """(attempt id, current turn row) of the session's current attempt."""
    attempt = conn.execute(
        "SELECT id FROM attempts WHERE session_id = ? AND status != 'done' ORDER BY ord LIMIT 1",
        (sid,),
    ).fetchone()
    if attempt is None:
        return None, None
    turn = conn.execute(
        "SELECT * FROM turns WHERE attempt_id = ? ORDER BY level DESC LIMIT 1", (attempt[0],)
    ).fetchone()
    return attempt[0], turn


def answer(client, conn, pid, sid, text, follow=False):
    aid, turn = current(conn, sid)
    return client.post(
        f"/profiles/{pid}/sessions/{sid}/attempts/{aid}/answer",
        data={"text": text, "turn_id": str(turn["id"])},
        follow_redirects=follow,
    )


def skip(client, conn, pid, sid):
    aid, turn = current(conn, sid)
    return client.post(
        f"/profiles/{pid}/sessions/{sid}/attempts/{aid}/skip",
        data={"turn_id": str(turn["id"])},
        follow_redirects=False,
    )
