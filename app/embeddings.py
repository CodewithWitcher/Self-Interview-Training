"""Embedding and similarity (DM 6, PS 8.2, PS 10, D4)."""

import hashlib
import logging
import re
import sqlite3
import threading

import numpy as np

from app.config import Settings

log = logging.getLogger(__name__)

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
DIM = 384
FETCH_COMMAND = "uv run python -m app.fetch_models"

_TOKEN = re.compile(r"[a-z0-9]+")
_lock = threading.Lock()
_models: dict[str, object] = {}


class EmbeddingModelMissing(RuntimeError):
    """The embedding model files are not downloaded."""

    def __init__(self) -> None:
        super().__init__(f"The embedding model is not downloaded. Run: {FETCH_COMMAND}")


def cache_dir(settings: Settings):
    return settings.models_dir / "fastembed"


def model_present(settings: Settings) -> bool:
    return any(cache_dir(settings).rglob("model.onnx"))


def fake_embed(texts: list[str]) -> np.ndarray:
    out = np.zeros((len(texts), DIM), dtype=np.float32)
    for row, text in enumerate(texts):
        for token in _TOKEN.findall(text.lower()):
            index = int.from_bytes(hashlib.sha256(token.encode()).digest()[:4], "big") % DIM
            out[row, index] += 1.0
        norm = np.linalg.norm(out[row])
        if norm == 0:
            out[row, 0] = 1.0
        else:
            out[row] /= norm
    return out


def _load(settings: Settings):
    key = str(cache_dir(settings))
    with _lock:
        model = _models.get(key)
        if model is None:
            from fastembed import TextEmbedding

            if not model_present(settings):
                raise EmbeddingModelMissing()
            try:
                model = TextEmbedding(MODEL_NAME, cache_dir=key, local_files_only=True)
            except (ValueError, OSError) as exc:
                raise EmbeddingModelMissing() from exc
            _models[key] = model
    return model


def embed(texts: list[str], settings: Settings) -> np.ndarray:
    """Return an (n, 384) float32 array of unit vectors."""
    if not texts:
        return np.zeros((0, DIM), dtype=np.float32)
    if settings.dev_fake:
        return fake_embed(texts)
    model = _load(settings)
    vectors = np.asarray(list(model.embed(texts)), dtype=np.float32)
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    return vectors / np.where(norms == 0, 1, norms)


def to_blob(vec: np.ndarray) -> bytes:
    return np.asarray(vec, dtype="<f4").tobytes()


def from_blob(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype="<f4")


def top_k(query: np.ndarray, vectors: np.ndarray, k: int) -> list[tuple[int, float]]:
    """Indexes and similarities of the k rows most similar to query, best first."""
    if len(vectors) == 0 or k <= 0:
        return []
    sims = np.asarray(vectors, dtype=np.float32) @ np.asarray(query, dtype=np.float32)
    order = np.argsort(-sims, kind="stable")[:k]
    return [(int(i), float(sims[i])) for i in order]


def backfill(conn: sqlite3.Connection, settings: Settings) -> int:
    """Embed every stored text whose embedding is NULL. Returns the number of rows filled."""
    filled = 0
    for table in ("resume_chunks", "questions"):
        rows = conn.execute(f"SELECT id, text FROM {table} WHERE embedding IS NULL").fetchall()
        if not rows:
            continue
        vectors = embed([r["text"] for r in rows], settings)
        with conn:
            conn.executemany(
                f"UPDATE {table} SET embedding = ? WHERE id = ?",
                [(to_blob(v), r["id"]) for v, r in zip(vectors, rows, strict=True)],
            )
        filled += len(rows)
    if filled:
        log.info("backfilled %s embeddings", filled)
    return filled
