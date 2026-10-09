"""Generating and de-duplicating questions (F4.3, F7.1, PS 4, PS 8)."""

import json
import random
import sqlite3
from dataclasses import dataclass

import numpy as np

from app import embeddings, llm
from app.config import Settings
from app.db import utc_now
from app.llm import InvalidReply
from app.prompts import QuestionBatch, questions_prompt
from app.scoring import DEDUPE_COSINE, RETRIEVE_K, RETRIEVE_MIN_COSINE

QUESTION_MAX_CHARS = 600
REFERENCE_MAX_CHARS = 2000
KEY_POINT_MAX_CHARS = 300
KEY_POINTS_MAX = 6
KEY_POINTS_MIN = 2
PROBE_MIN_CHUNK_CHARS = 80
ASKED_LOOKBACK = 20


class GenerationError(Exception):
    """Questions cannot be generated for a reason the user can fix. The message says why."""


@dataclass(frozen=True)
class Candidate:
    text: str
    key_points: list[str]
    reference_answer: str
    context: str | None


def drop_duplicates(
    candidates: np.ndarray, existing: np.ndarray, threshold: float = DEDUPE_COSINE
) -> list[int]:
    """Indexes of the candidates to keep: none is a near copy of an existing vector or of an
    earlier kept candidate."""
    kept: list[int] = []
    for i, vec in enumerate(candidates):
        if len(existing) and float(np.max(existing @ vec)) >= threshold:
            continue
        if kept and float(np.max(candidates[kept] @ vec)) >= threshold:
            continue
        kept.append(i)
    return kept


def normalise_batch(
    batch: QuestionBatch, n: int, kind: str, excerpts: list[str]
) -> list[Candidate]:
    """Rules 1 to 4 of the question normalisation in PS 4."""
    out: list[Candidate] = []
    used_sources: set[int] = set()
    for q in batch.questions:
        text = q.text.strip()
        reference = q.reference_answer.strip()
        if not text or len(text) > QUESTION_MAX_CHARS:
            continue
        if not reference or len(reference) > REFERENCE_MAX_CHARS:
            continue
        points = [p.strip() for p in q.key_points]
        points = [p for p in points if p and len(p) <= KEY_POINT_MAX_CHARS][:KEY_POINTS_MAX]
        if len(points) < KEY_POINTS_MIN:
            continue
        source = q.source if 1 <= q.source <= len(excerpts) else 0
        if kind == "resume_probe":
            if source == 0 or source in used_sources:
                continue
            used_sources.add(source)
        context = excerpts[source - 1] if kind == "resume_probe" else None
        out.append(Candidate(text, points, reference, context))
    return out[:n]


def _chunks(conn: sqlite3.Connection, profile_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT text, embedding FROM resume_chunks WHERE profile_id = ? ORDER BY ord",
        (profile_id,),
    ).fetchall()


def similar_chunks(
    conn: sqlite3.Connection, profile_id: int, query: str, k: int, settings: Settings
) -> list[str]:
    """Up to k resume chunks most similar to query, keeping those at the floor or above."""
    rows = [r for r in _chunks(conn, profile_id) if r["embedding"] is not None]
    if not rows:
        return []
    vectors = np.stack([embeddings.from_blob(r["embedding"]) for r in rows])
    q = embeddings.embed([query], settings)[0]
    return [
        rows[i]["text"] for i, sim in embeddings.top_k(q, vectors, k) if sim >= RETRIEVE_MIN_COSINE
    ]


def choose_excerpts(
    conn: sqlite3.Connection, topic: sqlite3.Row, n: int, rng: random.Random, settings: Settings
) -> tuple[list[str], int]:
    """The excerpts for the prompt and the number of questions to ask for."""
    if topic["kind"] == "resume_probe":
        long_chunks = [
            r["text"]
            for r in _chunks(conn, topic["profile_id"])
            if len(r["text"]) >= PROBE_MIN_CHUNK_CHARS
        ]
        if not long_chunks:
            raise GenerationError("Resume questions need a saved resume with longer lines.")
        n = min(n, len(long_chunks))
        return rng.sample(long_chunks, n), n
    query = f"{topic['name']}. {topic['rationale']}"
    return similar_chunks(conn, topic["profile_id"], query, RETRIEVE_K, settings), n


def already_asked(conn: sqlite3.Connection, topic_id: int) -> list[str]:
    rows = conn.execute(
        "SELECT text FROM questions WHERE topic_id = ? ORDER BY created_at DESC, id DESC LIMIT ?",
        (topic_id, ASKED_LOOKBACK),
    ).fetchall()
    return [r["text"] for r in rows]


def profile_question_vectors(conn: sqlite3.Connection, profile_id: int) -> np.ndarray:
    rows = conn.execute(
        "SELECT q.embedding FROM questions q JOIN topics t ON t.id = q.topic_id "
        "WHERE t.profile_id = ? AND q.embedding IS NOT NULL",
        (profile_id,),
    ).fetchall()
    if not rows:
        return np.zeros((0, embeddings.DIM), dtype=np.float32)
    return np.stack([embeddings.from_blob(r["embedding"]) for r in rows])


def generate(
    conn: sqlite3.Connection,
    topic: sqlite3.Row,
    n: int,
    difficulty: str,
    provider: str,
    model: str,
    rng: random.Random,
    settings: Settings,
) -> list[int]:
    """Generate up to n questions for a topic and store them. Returns the new question ids.

    Raises GenerationError or an LLMError. Every input is read before the model call, and the
    batch is stored in its own transaction after it.
    """
    try:
        return _generate(conn, topic, n, difficulty, provider, model, rng, settings)
    except embeddings.EmbeddingModelMissing as exc:
        raise GenerationError(str(exc)) from exc


def _generate(conn, topic, n, difficulty, provider, model, rng, settings) -> list[int]:
    excerpts, n = choose_excerpts(conn, topic, n, rng, settings)
    existing = profile_question_vectors(conn, topic["profile_id"])
    system, user = questions_prompt(
        topic["name"],
        topic["kind"],
        difficulty,
        n,
        topic["rationale"],
        excerpts,
        already_asked(conn, topic["id"]),
    )
    kept: dict[str, object] = {}

    def check(batch: QuestionBatch) -> QuestionBatch:
        candidates = normalise_batch(batch, n, topic["kind"], excerpts)
        if candidates:
            vectors = embeddings.embed([c.text for c in candidates], settings)
            keep = drop_duplicates(vectors, existing)
            candidates = [candidates[i] for i in keep]
            kept["vectors"] = vectors[keep]
        if not candidates:
            raise InvalidReply("no usable question")
        kept["candidates"] = candidates
        return batch

    llm.chat(
        provider, model, system, user, QuestionBatch, settings=settings, creative=True, check=check
    )
    candidates: list[Candidate] = kept["candidates"]
    now = utc_now()
    ids = []
    with conn:
        for c, vec in zip(candidates, kept["vectors"], strict=True):
            ids.append(
                conn.execute(
                    "INSERT INTO questions (topic_id, difficulty, text, key_points, "
                    "reference_answer, context, embedding, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        topic["id"],
                        difficulty,
                        c.text,
                        json.dumps(c.key_points, ensure_ascii=False),
                        c.reference_answer,
                        c.context,
                        embeddings.to_blob(vec),
                        now,
                    ),
                ).lastrowid
            )
    return ids
