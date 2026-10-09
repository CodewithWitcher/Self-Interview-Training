import re
import sqlite3
from contextlib import closing

import pytest

from app import db

TABLES = {"profiles", "resume_chunks", "topics", "questions", "sessions", "attempts", "turns"}
NOW = "2026-10-08T10:00:00Z"


@pytest.fixture
def conn(tmp_path):
    with closing(db.connect(tmp_path / "app.db")) as c:
        db.migrate(c)
        yield c


def tables(c):
    rows = c.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {r[0] for r in rows}


def seed(c):
    """A profile with one row in every table. Returns the ids."""
    with c:
        pid = c.execute(
            "INSERT INTO profiles (name, created_at) VALUES ('Ana', ?)", (NOW,)
        ).lastrowid
        c.execute(
            "INSERT INTO resume_chunks (profile_id, ord, text) VALUES (?, 1, 'Python')", (pid,)
        )
        tid = c.execute(
            "INSERT INTO topics (profile_id, name, kind, source) "
            "VALUES (?, 'Python', 'technical', 'resume')",
            (pid,),
        ).lastrowid
        qid = c.execute(
            "INSERT INTO questions (topic_id, difficulty, text, key_points, reference_answer, "
            "created_at) VALUES (?, 'easy', 'Q?', '[]', 'A', ?)",
            (tid, NOW),
        ).lastrowid
        sid = c.execute(
            "INSERT INTO sessions (profile_id, provider, model, difficulty, created_at) "
            "VALUES (?, 'fake', 'fake', 'easy', ?)",
            (pid, NOW),
        ).lastrowid
        aid = c.execute(
            "INSERT INTO attempts (session_id, question_id, ord) VALUES (?, ?, 1)", (sid, qid)
        ).lastrowid
        c.execute("INSERT INTO turns (attempt_id, level, prompt) VALUES (?, 0, 'Q?')", (aid,))
    return pid, tid, qid, sid, aid


def test_new_database_reaches_version_1_with_seven_tables(conn):
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 1
    assert tables(conn) == TABLES


def test_second_migrate_changes_nothing(conn):
    before = conn.execute("SELECT sql FROM sqlite_master ORDER BY name").fetchall()
    assert db.migrate(conn) == 1
    after = conn.execute("SELECT sql FROM sqlite_master ORDER BY name").fetchall()
    assert [tuple(r) for r in before] == [tuple(r) for r in after]


def test_failing_migration_leaves_no_trace(tmp_path, monkeypatch):
    mig = tmp_path / "migrations"
    mig.mkdir()
    (mig / "001_ok.sql").write_text("CREATE TABLE a (x INTEGER);", encoding="utf-8")
    (mig / "002_bad.sql").write_text(
        "CREATE TABLE b (x INTEGER);\nTHIS IS NOT SQL;", encoding="utf-8"
    )
    monkeypatch.setattr(db, "MIGRATIONS_DIR", mig)
    with closing(db.connect(tmp_path / "t.db")) as c:
        with pytest.raises(sqlite3.Error):
            db.migrate(c)
        assert c.execute("PRAGMA user_version").fetchone()[0] == 1
        assert tables(c) == {"a"}


def test_connection_pragmas(conn):
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "delete"


def test_invariant_1_one_active_session(conn):
    pid, *_ = seed(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO sessions (profile_id, provider, model, difficulty, created_at) "
            "VALUES (?, 'fake', 'fake', 'easy', ?)",
            (pid, NOW),
        )


def test_invariant_2_unique_positions(conn):
    _, _, qid, sid, _ = seed(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO attempts (session_id, question_id, ord) VALUES (?, ?, 1)", (sid, qid)
        )


def test_invariant_3_one_turn_per_level(conn):
    *_, aid = seed(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO turns (attempt_id, level, prompt) VALUES (?, 0, 'again')", (aid,))


def test_invariant_4_score_exactly_when_done(conn):
    *_, aid = seed(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE attempts SET status = 'done' WHERE id = ?", (aid,))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE attempts SET score = 50 WHERE id = ?", (aid,))


def test_invariant_5_score_needs_answer(conn):
    *_, aid = seed(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE turns SET score = 50 WHERE attempt_id = ?", (aid,))


def test_invariant_6_srs_both_or_neither(conn):
    _, _, qid, _, _ = seed(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE questions SET srs_step = 0 WHERE id = ?", (qid,))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE questions SET srs_due = '2026-10-09' WHERE id = ?", (qid,))


def test_profile_name_unique_ignoring_case(conn):
    seed(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO profiles (name, created_at) VALUES ('ANA', ?)", (NOW,))


def test_deleting_profile_leaves_no_row(conn):
    pid, *_ = seed(conn)
    with conn:
        other = conn.execute(
            "INSERT INTO profiles (name, created_at) VALUES ('Other', ?)", (NOW,)
        ).lastrowid
        conn.execute("DELETE FROM profiles WHERE id = ?", (pid,))
    for table in TABLES - {"profiles"}:
        assert conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0, table
    assert conn.execute("SELECT id FROM profiles").fetchall()[0][0] == other


def test_temporary_folder_can_be_deleted(tmp_path):
    folder = tmp_path / "with space"
    folder.mkdir()
    c = db.connect(folder / "app.db")
    db.migrate(c)
    c.close()
    (folder / "app.db").unlink()
    folder.rmdir()
    assert not folder.exists()


def test_utc_now_format():
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", db.utc_now())
