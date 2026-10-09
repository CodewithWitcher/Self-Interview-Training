from datetime import UTC, datetime, timedelta

import pytest

from app.scoring import TopicReadiness, readiness, topic_score
from tests.helpers import answer, ready_profile, start_session, topic_row

NOW = datetime(2026, 10, 12, 12, 0, tzinfo=UTC)


def ago(days):
    return NOW - timedelta(days=days)


def test_worked_example_gives_47():
    a = topic_score([(s, ago(0)) for s in (80, 70, 90, 60, 75)], NOW)
    b = topic_score([(90, ago(0)), (50, ago(14))], NOW)
    c = topic_score([], NOW)
    assert a.score == pytest.approx(75.00) and a.coverage == 1.0
    assert b.score == pytest.approx(76.67, abs=0.005) and b.coverage == pytest.approx(0.4)
    assert b.readiness == pytest.approx(30.67, abs=0.005)
    assert (c.score, c.readiness) == (None, 0.0)
    assert readiness([(5, a), (3, b), (2, c)]) == 47


def test_window_is_20_rows():
    rows = [(100, ago(0))] * 20 + [(0, ago(1))] * 5
    assert topic_score(rows, NOW).score == pytest.approx(100)
    assert topic_score(rows, NOW).answered == 20


def test_negative_age_counts_as_zero():
    future = topic_score([(80, NOW + timedelta(days=3)), (40, ago(0))], NOW)
    assert future.score == pytest.approx(60)


def test_no_active_topic_gives_no_value():
    t = TopicReadiness(50.0, 1.0, 50.0, 5)
    assert readiness([]) is None
    assert readiness([(0, t)]) is None


def test_readiness_rounds_half_up():
    t = TopicReadiness(50.5, 1.0, 50.5, 5)
    assert readiness([(1, t)]) == 51


def test_empty_state(client):
    pid = ready_profile(client)
    text = client.get(f"/profiles/{pid}/progress").text
    assert "No answers yet" in text
    assert "<meter" not in text


def test_progress_with_history(client, conn):
    pid = ready_profile(client)
    sid = start_session(client, conn, pid, ("Python", "SQL"), 3)
    for _ in range(3):
        answer(client, conn, pid, sid, "x")
    text = client.get(f"/profiles/{pid}/progress").text
    assert '<p class="readiness">' in text
    assert text.count("<meter") >= 7
    assert "Python" in text and "SQL" in text
    assert "fake:fake" in text  # the session row
    assert "Weakest rubric dimension" in text
    assert "Readiness:" in client.get(f"/profiles/{pid}").text


def test_topic_with_weight_zero_is_left_out(client, conn):
    pid = ready_profile(client)
    sid = start_session(client, conn, pid, ("Python",), 3)
    for _ in range(3):
        answer(client, conn, pid, sid, "x")
    sql = topic_row(conn, pid, "SQL")
    client.post(f"/profiles/{pid}/topics/{sql['id']}", data={"weight": "0"})
    text = client.get(f"/profiles/{pid}/progress").text
    assert ">SQL<" not in text
    assert ">Python<" in text


def test_readiness_matches_hand_computation(client, conn):
    pid = ready_profile(client)
    sid = start_session(client, conn, pid, ("Python",), 3)
    for _ in range(3):
        answer(client, conn, pid, sid, "x")  # 75 each
    from app.progress import profile_progress

    data = profile_progress(conn, pid, client.app.state.today())
    weights = {t["topic"]["name"]: t["topic"]["weight"] for t in data["topics"]}
    total = sum(weights.values())
    expected = int(5 * 75 * 0.6 / total + 0.5)  # Python weight 5, 3 rows of 75, coverage 0.6
    assert data["readiness"] == expected
