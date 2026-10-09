import pytest

from app import llm
from app.llm import InvalidReply
from app.plan import normalise_plan
from app.prompts import Plan, PlanTopic
from tests.helpers import create_profile, save_resume


def topic(name, kind="technical", weight=3, source="resume", rationale="r"):
    return PlanTopic(name=name, kind=kind, weight=weight, source=source, rationale=rationale)


def plan_of(*topics):
    return Plan(summary=" s ", topics=list(topics))


BASE = [topic("A"), topic("B"), topic("Talk", "behavioral")]


def test_rule_1_trims_and_drops_bad_names():
    p = normalise_plan(
        plan_of(topic("  Python  "), topic(" "), topic("x" * 61), topic("resume DEEP-dive"), *BASE),
        False,
    )
    assert [t.name for t in p.topics] == ["Python", "A", "B", "Talk"]
    assert p.summary == "s"


def test_rule_2_merges_names_ignoring_case_keeping_higher_weight():
    p = normalise_plan(plan_of(topic("SQL", weight=2), topic("sql", weight=5), *BASE), False)
    sql = [t for t in p.topics if t.name.lower() == "sql"]
    assert len(sql) == 1 and sql[0].weight == 5


def test_rule_3_without_jd_every_source_is_resume():
    p = normalise_plan(plan_of(topic("K", source="jd"), topic("P", source="both"), *BASE), False)
    assert {t.source for t in p.topics} == {"resume"}


def test_rule_4_with_jd_gaps_get_weight_3():
    p = normalise_plan(plan_of(topic("K", weight=1, source="jd"), *BASE), True)
    assert next(t for t in p.topics if t.name == "K").weight == 3


def test_rule_5_adds_behavioral():
    p = normalise_plan(plan_of(topic("A"), topic("B"), topic("C")), False)
    added = [t for t in p.topics if t.kind == "behavioral"]
    assert [(t.name, t.weight, t.source, t.rationale) for t in added] == [
        ("Behavioral", 3, "resume", "Added by default")
    ]


def test_rule_6_keeps_ten_highest_with_stable_ties():
    many = [topic(f"T{i}", weight=2) for i in range(12)] + [topic("Top", "behavioral", weight=5)]
    p = normalise_plan(plan_of(*many), False)
    assert len(p.topics) == 10
    assert p.topics[0].name == "Top"
    assert [t.name for t in p.topics[1:]] == [f"T{i}" for i in range(9)]


def test_rule_7_fewer_than_three_is_invalid():
    with pytest.raises(InvalidReply):
        normalise_plan(plan_of(topic("A")), False)  # A and the added Behavioral make two


def build(client, pid):
    return client.post(
        f"/profiles/{pid}/plan/build", data={"model": "fake:fake"}, follow_redirects=False
    )


def test_built_plan_lists_topics(client):
    pid = create_profile(client)
    save_resume(client, pid)
    assert build(client, pid).status_code == 303
    page = client.get(f"/profiles/{pid}/plan").text
    for name in ("Python", "SQL", "Teamwork", "Resume deep-dive"):
        assert name in page
    assert "Fake Python." in page
    assert "Resume" in page
    assert "Fake plan" in page


def test_plan_contains_resume_topic_and_behavioral(client, conn):
    pid = create_profile(client)
    save_resume(client, pid)
    build(client, pid)
    rows = conn.execute("SELECT name, kind, weight, source FROM topics").fetchall()
    kinds = {r["kind"] for r in rows}
    assert {"behavioral", "resume_probe"} <= kinds
    deep = next(r for r in rows if r["name"] == "Resume deep-dive")
    assert (deep["kind"], deep["weight"], deep["source"]) == ("resume_probe", 3, "resume")


def test_build_without_resume_calls_no_model(client, monkeypatch):
    calls = []
    monkeypatch.setattr(llm, "chat", lambda *a, **k: calls.append(1))
    pid = create_profile(client)
    r = build(client, pid)
    assert r.status_code == 422
    assert "Save a resume first" in r.text
    assert calls == []


def test_weight_zero_stays_listed_as_off(client, conn):
    pid = create_profile(client)
    save_resume(client, pid)
    build(client, pid)
    tid = conn.execute("SELECT id FROM topics WHERE name = 'SQL'").fetchone()[0]
    r = client.post(f"/profiles/{pid}/topics/{tid}", data={"weight": "0"}, follow_redirects=False)
    assert r.status_code == 303
    page = client.get(f"/profiles/{pid}/plan").text
    assert "SQL" in page and "(off)" in page
    assert conn.execute("SELECT weight FROM topics WHERE id = ?", (tid,)).fetchone()[0] == 0


def test_bad_weight_and_foreign_topic(client, conn):
    pid = create_profile(client)
    other = create_profile(client, "Other")
    save_resume(client, pid)
    build(client, pid)
    tid = conn.execute("SELECT id FROM topics WHERE name = 'SQL'").fetchone()[0]
    assert client.post(f"/profiles/{pid}/topics/{tid}", data={"weight": "9"}).status_code == 422
    assert client.post(f"/profiles/{other}/topics/{tid}", data={"weight": "1"}).status_code == 404


def test_manual_topic_survives_rebuild_and_ids_are_kept(client, conn):
    pid = create_profile(client)
    save_resume(client, pid)
    build(client, pid)
    r = client.post(
        f"/profiles/{pid}/topics",
        data={"name": "Rust", "kind": "technical"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    before = {r["name"]: r["id"] for r in conn.execute("SELECT id, name FROM topics")}
    build(client, pid)
    after = {
        r["name"]: (r["id"], r["weight"], r["source"]) for r in conn.execute("SELECT * FROM topics")
    }
    assert after["Rust"][1] == 3 and after["Rust"][2] == "manual"
    assert {n: v[0] for n, v in after.items()} == before


def test_topic_left_out_by_rebuild_is_switched_off(client, conn):
    pid = create_profile(client)
    save_resume(client, pid)
    with conn:
        conn.execute(
            "INSERT INTO topics (profile_id, name, kind, weight, source) VALUES (?, 'Cobol', 'technical', 4, 'resume')",
            (pid,),
        )
    build(client, pid)
    assert conn.execute("SELECT weight FROM topics WHERE name = 'Cobol'").fetchone()[0] == 0


def test_add_topic_errors_keep_input(client):
    pid = create_profile(client)
    client.post(f"/profiles/{pid}/topics", data={"name": "Rust", "kind": "technical"})
    r = client.post(f"/profiles/{pid}/topics", data={"name": "rust", "kind": "behavioral"})
    assert r.status_code == 422
    assert "already in the plan" in r.text
    assert 'value="rust"' in r.text
    assert (
        client.post(f"/profiles/{pid}/topics", data={"name": "", "kind": "technical"}).status_code
        == 422
    )


def test_model_picker_preselects_fake(client):
    pid = create_profile(client)
    save_resume(client, pid)
    page = client.get(f"/profiles/{pid}/plan").text
    assert '<option value="fake:fake" selected>' in page


def test_build_error_is_shown(client, monkeypatch):
    def down(*a, **k):
        raise llm.LLMUnavailable("Ollama is not running at x.")

    pid = create_profile(client)
    save_resume(client, pid)
    monkeypatch.setattr(llm, "chat", down)
    r = build(client, pid)
    assert r.status_code == 200
    assert "could not be reached" in r.text
