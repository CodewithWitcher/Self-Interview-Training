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
