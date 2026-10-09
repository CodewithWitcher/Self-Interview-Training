"""Scoring one turn (F5, F6, F7.3, PS 5)."""

import json
import sqlite3
from dataclasses import dataclass

import numpy as np

from app import embeddings, llm
from app.config import Settings
from app.llm import InvalidReply
from app.prompts import Evaluation, evaluation_prompt
from app.scoring import MAX_FOLLOW_UPS, RETRIEVE_MIN_COSINE, answer_score

FOLLOW_UP_MAX_CHARS = 400
LIST_MAX = 3
BEHAVIORAL_EXCERPTS = 2


@dataclass(frozen=True)
class Result:
    evaluation: Evaluation
    score: int
    eval_model: str


def normalise_evaluation(e: Evaluation, level: int, n_key_points: int) -> Evaluation:
    """The four normalisation rules of PS 5."""
    feedback = e.feedback.strip()
    if not feedback:
        raise InvalidReply("empty feedback")
    strengths = [s.strip() for s in e.strengths if s.strip()][:LIST_MAX]
    gaps = [g.strip() for g in e.gaps if g.strip()][:LIST_MAX]
    hit = [] if level > 0 else sorted({k for k in e.key_points_hit if 1 <= k <= n_key_points})
    follow_up = e.follow_up.strip()
    if level >= MAX_FOLLOW_UPS or len(follow_up) > FOLLOW_UP_MAX_CHARS:
        follow_up = ""
    return e.model_copy(
        update={
            "strengths": strengths,
            "gaps": gaps,
            "key_points_hit": hit,
            "feedback": feedback,
            "follow_up": follow_up,
        }
    )


def resume_excerpts(
    conn: sqlite3.Connection, question: sqlite3.Row, kind: str, answer: str, settings: Settings
) -> list[str]:
    if kind == "resume_probe":
        return [question["context"]] if question["context"] else []
    if kind != "behavioral":
        return []
    rows = conn.execute(
        "SELECT c.text, c.embedding FROM resume_chunks c JOIN topics t ON t.profile_id = c.profile_id "
        "WHERE t.id = ? AND c.embedding IS NOT NULL ORDER BY c.ord",
        (question["topic_id"],),
    ).fetchall()
    if not rows:
        return []
    vectors = np.stack([embeddings.from_blob(r["embedding"]) for r in rows])
    query = embeddings.embed([answer], settings)[0]
    return [
        rows[i]["text"]
        for i, sim in embeddings.top_k(query, vectors, BEHAVIORAL_EXCERPTS)
        if sim >= RETRIEVE_MIN_COSINE
    ]


def evaluate_turn(conn: sqlite3.Connection, turn_id: int, settings: Settings) -> Result:
    """Build the prompt for an answered turn, call the model and compute the answer score.

    Reads only. No transaction is open during the model call. Raises an LLMError.
    """
    turn = conn.execute("SELECT * FROM turns WHERE id = ?", (turn_id,)).fetchone()
    row = conn.execute(
        "SELECT a.question_id, s.provider, s.model FROM attempts a "
        "JOIN sessions s ON s.id = a.session_id WHERE a.id = ?",
        (turn["attempt_id"],),
    ).fetchone()
    question = conn.execute(
        "SELECT q.*, t.kind FROM questions q JOIN topics t ON t.id = q.topic_id WHERE q.id = ?",
        (row["question_id"],),
    ).fetchone()
    earlier = conn.execute(
        "SELECT prompt, answer_text FROM turns WHERE attempt_id = ? AND level < ? ORDER BY level",
        (turn["attempt_id"], turn["level"]),
    ).fetchall()
    level = turn["level"]
    kind = question["kind"]
    key_points = json.loads(question["key_points"]) if level == 0 else []
    try:
        excerpts = resume_excerpts(conn, question, kind, turn["answer_text"], settings)
    except embeddings.EmbeddingModelMissing:
        excerpts = []
    system, user = evaluation_prompt(
        kind,
        MAX_FOLLOW_UPS - level,
        question["text"],
        key_points,
        question["reference_answer"] if level == 0 else None,
        excerpts,
        [(t["prompt"], t["answer_text"]) for t in earlier],
        turn["prompt"],
        turn["answer_text"],
    )
    evaluation = llm.chat(
        row["provider"],
        row["model"],
        system,
        user,
        Evaluation,
        settings=settings,
        check=lambda e: normalise_evaluation(e, level, len(key_points)),
    )
    score = answer_score(
        kind, evaluation.correctness, evaluation.depth, evaluation.clarity, evaluation.structure
    )
    return Result(evaluation, score, f"{row['provider']}:{row['model']}")
