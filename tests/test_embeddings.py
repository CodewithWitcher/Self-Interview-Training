import os
from contextlib import closing
from dataclasses import replace

import numpy as np
import pytest

from app import db, embeddings
from app.embeddings import DIM, backfill, embed, fake_embed, from_blob, to_blob, top_k


def test_fake_vectors_are_deterministic_and_unit_length(settings):
    a = embed(["Kafka and event streaming", "Python lists"], settings)
    b = embed(["Kafka and event streaming", "Python lists"], settings)
    assert a.shape == (2, DIM)
    assert np.array_equal(a, b)
    assert np.allclose(np.linalg.norm(a, axis=1), 1.0)


def test_fake_text_without_tokens_is_first_unit_vector():
    v = fake_embed(["!!! ---"])[0]
    assert v[0] == 1.0 and np.count_nonzero(v) == 1


def test_identical_texts_have_similarity_one():
    v = fake_embed(["same text here", "same text here"])
    assert float(v[0] @ v[1]) == pytest.approx(1.0)


def test_blob_round_trip_is_1536_bytes():
    v = fake_embed(["hello world"])[0]
    blob = to_blob(v)
    assert len(blob) == 1536
    assert np.array_equal(from_blob(blob), v)


def test_top_k_orders_by_similarity():
    q = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    vectors = np.array([[0.1, 1, 0], [0.9, 0.1, 0], [0.5, 0.5, 0], [-1, 0, 0]], dtype=np.float32)
    result = top_k(q, vectors, 3)
    assert [i for i, _ in result] == [1, 2, 0]
    assert result[0][1] == pytest.approx(0.9)
    assert top_k(q, vectors[:0], 3) == []


def test_backfill_fills_only_null_rows(settings):
    settings.data_dir.mkdir(parents=True)
    with closing(db.connect(settings.db_path)) as conn:
        db.migrate(conn)
        with conn:
            pid = conn.execute(
                "INSERT INTO profiles (name, created_at) VALUES ('A', 'x')"
            ).lastrowid
            marker = to_blob(np.ones(DIM, dtype=np.float32))
            conn.execute(
                "INSERT INTO resume_chunks (profile_id, ord, text, embedding) "
                "VALUES (?, 1, 'kept', ?)",
                (pid, marker),
            )
            conn.execute(
                "INSERT INTO resume_chunks (profile_id, ord, text) VALUES (?, 2, 'Kafka')", (pid,)
            )
        assert backfill(conn, settings) == 1
        rows = conn.execute("SELECT ord, embedding FROM resume_chunks ORDER BY ord").fetchall()
        assert rows[0]["embedding"] == marker
        assert np.array_equal(from_blob(rows[1]["embedding"]), fake_embed(["Kafka"])[0])
        assert backfill(conn, settings) == 0


def test_missing_model_names_fetch_command(settings):
    real = replace(settings, dev_fake=False)
    with pytest.raises(embeddings.EmbeddingModelMissing, match="app.fetch_models"):
        embed(["x"], real)


def test_startup_skips_backfill_when_model_missing(settings, conn):
    from app.main import create_app

    with conn:
        pid = conn.execute("INSERT INTO profiles (name, created_at) VALUES ('A', 'x')").lastrowid
        conn.execute("INSERT INTO resume_chunks (profile_id, ord, text) VALUES (?, 1, 'x')", (pid,))
    create_app(replace(settings, dev_fake=False))


@pytest.fixture
def real_settings(settings):
    from app.config import REPO_ROOT

    real = replace(settings, dev_fake=False, data_dir=REPO_ROOT / "data")
    if not embeddings.model_present(real):
        pytest.fail("Run uv run python -m app.fetch_models first")
    return real


@pytest.mark.models
def test_real_vectors_have_shape_and_unit_length(real_settings):
    v = embed(["one sentence", "another sentence", "third"], real_settings)
    assert v.shape == (3, DIM)
    assert np.allclose(np.linalg.norm(v, axis=1), 1.0, atol=1e-5)


@pytest.mark.models
def test_real_query_ranks_kafka_first(real_settings):
    chunks = [
        "Led the migration of the reporting stack to PostgreSQL and dbt.",
        "Built event pipelines on Apache Kafka processing 2 million messages a day.",
        "Mentored three junior engineers and ran the weekly design review.",
    ]
    vectors = embed(chunks, real_settings)
    query = embed(["Kafka and event streaming"], real_settings)[0]
    assert top_k(query, vectors, 3)[0][0] == 1


@pytest.mark.models
def test_real_model_loads_offline(real_settings, monkeypatch):
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    embeddings._models.clear()
    assert embed(["offline"], real_settings).shape == (1, DIM)
    assert os.environ["HF_HUB_OFFLINE"] == "1"
