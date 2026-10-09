"""Building and updating the prep plan (F3, F11, PS 3)."""

import sqlite3

from app import llm
from app.config import Settings
from app.llm import InvalidReply
from app.prompts import Plan, PlanTopic, plan_prompt

RESUME_TOPIC = "Resume deep-dive"
RESUME_TOPIC_RATIONALE = "Questions drawn from single lines of your resume"
TOPIC_NAME_MAX = 60
PLAN_MAX_TOPICS = 10
PLAN_MIN_TOPICS = 3
GAP_MIN_WEIGHT = 3
KINDS = ("technical", "behavioral", "resume_probe")


class NoResume(ValueError):
    pass


def normalise_plan(plan: Plan, has_jd: bool) -> Plan:
    """The seven normalisation rules of PS 3. Raises InvalidReply for an unusable plan."""
    merged: dict[str, PlanTopic] = {}
    for topic in plan.topics:
        name = topic.name.strip()
        if not name or len(name) > TOPIC_NAME_MAX or name.lower() == RESUME_TOPIC.lower():
            continue
        topic = topic.model_copy(update={"name": name, "rationale": topic.rationale.strip()})
        key = name.lower()
        if key in merged:
            if topic.weight > merged[key].weight:
                merged[key] = merged[key].model_copy(update={"weight": topic.weight})
            continue
        merged[key] = topic
    topics = list(merged.values())
    for i, topic in enumerate(topics):
        if not has_jd:
            topics[i] = topic = topic.model_copy(update={"source": "resume"})
        elif topic.source == "jd" and topic.weight < GAP_MIN_WEIGHT:
            topics[i] = topic.model_copy(update={"weight": GAP_MIN_WEIGHT})
    if not any(t.kind == "behavioral" for t in topics):
        topics.append(
            PlanTopic(
                name="Behavioral",
                kind="behavioral",
                weight=3,
                source="resume",
                rationale="Added by default",
            )
        )
    topics = sorted(topics, key=lambda t: -t.weight)[:PLAN_MAX_TOPICS]
    if len(topics) < PLAN_MIN_TOPICS:
        raise InvalidReply("fewer than 3 topics")
    return Plan(summary=plan.summary.strip(), topics=topics)


def existing_topic_names(conn: sqlite3.Connection, profile_id: int) -> list[str]:
    rows = conn.execute(
        "SELECT name FROM topics WHERE profile_id = ? AND kind != 'resume_probe' "
        "ORDER BY weight DESC, id",
        (profile_id,),
    ).fetchall()
    return [r["name"] for r in rows]


def save_plan(conn: sqlite3.Connection, profile_id: int, plan: Plan) -> None:
    """Apply a normalised plan in one transaction, as the saving rules of PS 3 say."""
    with conn:
        existing = {
            r["name"].lower(): r
            for r in conn.execute("SELECT * FROM topics WHERE profile_id = ?", (profile_id,))
        }
        seen = set()
        for topic in plan.topics:
            key = topic.name.lower()
            seen.add(key)
            row = existing.get(key)
            if row is None:
                conn.execute(
                    "INSERT INTO topics (profile_id, name, kind, weight, source, rationale) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        profile_id,
                        topic.name,
                        topic.kind,
                        topic.weight,
                        topic.source,
                        topic.rationale,
                    ),
                )
                continue
            # A topic the user added keeps its manual source, so a later rebuild keeps it (F3.5).
            source = "manual" if row["source"] == "manual" else topic.source
            conn.execute(
                "UPDATE topics SET weight = ?, source = ?, rationale = ? WHERE id = ?",
                (topic.weight, source, topic.rationale, row["id"]),
            )
        for key, row in existing.items():
            if key in seen or row["source"] == "manual" or row["kind"] == "resume_probe":
                continue
            conn.execute("UPDATE topics SET weight = 0 WHERE id = ?", (row["id"],))
        if RESUME_TOPIC.lower() not in existing:
            conn.execute(
                "INSERT INTO topics (profile_id, name, kind, weight, source, rationale) "
                "VALUES (?, ?, 'resume_probe', 3, 'resume', ?)",
                (profile_id, RESUME_TOPIC, RESUME_TOPIC_RATIONALE),
            )
        conn.execute(
            "UPDATE profiles SET plan_summary = ? WHERE id = ?", (plan.summary or None, profile_id)
        )


def build_plan(
    conn: sqlite3.Connection, profile_id: int, provider: str, model: str, settings: Settings
) -> Plan:
    """Call the model and save the plan. Raises NoResume or an LLMError."""
    profile = conn.execute(
        "SELECT resume_text, jd_text FROM profiles WHERE id = ?", (profile_id,)
    ).fetchone()
    if not profile["resume_text"]:
        raise NoResume()
    has_jd = bool(profile["jd_text"])
    system, user = plan_prompt(
        profile["resume_text"], profile["jd_text"], existing_topic_names(conn, profile_id)
    )
    plan = llm.chat(
        provider,
        model,
        system,
        user,
        Plan,
        settings=settings,
        check=lambda p: normalise_plan(p, has_jd),
    )
    save_plan(conn, profile_id, plan)
    return plan


def topics(conn: sqlite3.Connection, profile_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM topics WHERE profile_id = ? ORDER BY weight DESC, name COLLATE NOCASE",
        (profile_id,),
    ).fetchall()


def add_topic(conn: sqlite3.Connection, profile_id: int, name: str, kind: str) -> str | None:
    """Add a manual topic. Returns an error message, or None."""
    name = name.strip()
    if not 1 <= len(name) <= TOPIC_NAME_MAX:
        return f"A topic name has 1 to {TOPIC_NAME_MAX} characters."
    if kind not in ("technical", "behavioral"):
        return "Choose technical or behavioral."
    if conn.execute(
        "SELECT 1 FROM topics WHERE profile_id = ? AND name = ?", (profile_id, name)
    ).fetchone():
        return "This topic is already in the plan. Change its weight instead."
    with conn:
        conn.execute(
            "INSERT INTO topics (profile_id, name, kind, weight, source, rationale) "
            "VALUES (?, ?, ?, 3, 'manual', 'Added by you')",
            (profile_id, name, kind),
        )
    return None
