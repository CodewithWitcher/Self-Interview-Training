import io

import pypdf
import pytest

from app.resume import CHUNK_MAX_CHARS, ResumeError, chunk_text, extract_text
from tests.helpers import FIXTURES, create_profile, sample_resume, save_resume


def pdf_bytes(writer: pypdf.PdfWriter) -> bytes:
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def blank_pdf() -> bytes:
    w = pypdf.PdfWriter()
    w.add_blank_page(width=200, height=200)
    return pdf_bytes(w)


def locked_pdf() -> bytes:
    w = pypdf.PdfWriter(clone_from=io.BytesIO((FIXTURES / "sample_resume.pdf").read_bytes()))
    w.encrypt("secret")
    return pdf_bytes(w)


def test_pdf_fixture_yields_lines_in_order():
    text = extract_text("resume.pdf", (FIXTURES / "sample_resume.pdf").read_bytes())
    expected = [line for line in sample_resume().splitlines() if line]
    assert [line for line in text.splitlines() if line] == expected


def test_text_with_and_without_bom():
    assert extract_text("a.txt", "﻿Python".encode()) == "Python"
    assert extract_text("a.md", b"Python") == "Python"


@pytest.mark.parametrize(
    ("name", "data", "message"),
    [
        ("blank.pdf", blank_pdf(), "no text"),
        ("locked.pdf", locked_pdf(), "password"),
        ("resume.docx", b"PK\x03\x04", "Only PDF, TXT and MD"),
        ("big.txt", b"a" * (6 * 1024 * 1024), "5 MB"),
        ("fake.pdf", b"not a pdf at all", "could not be read"),
        ("broken.pdf", b"%PDF-1.4\n garbage", "could not be read"),
        ("latin.txt", "café".encode("latin-1"), "UTF-8"),
    ],
)
def test_bad_files_are_rejected(name, data, message):
    with pytest.raises(ResumeError, match=message):
        extract_text(name, data)


@pytest.mark.parametrize(
    ("name", "data"),
    [
        ("blank.pdf", blank_pdf()),
        ("locked.pdf", locked_pdf()),
        ("resume.docx", b"PK\x03\x04"),
        ("big.pdf", b"%PDF-" + b"a" * (6 * 1024 * 1024)),
    ],
)
def test_rejected_upload_keeps_typed_text(client, name, data):
    pid = create_profile(client)
    r = client.post(
        f"/profiles/{pid}/resume/extract",
        files={"file": (name, data)},
        data={"text": "my typed words"},
    )
    assert r.status_code == 422
    assert "paste" in r.text
    assert "my typed words" in r.text


@pytest.mark.parametrize("length", [199, 12_001])
def test_text_outside_limits_is_rejected_and_kept(client, conn, length):
    pid = create_profile(client)
    text = "x" * length
    r = client.post(f"/profiles/{pid}/resume", data={"text": text})
    assert r.status_code == 422
    assert text in r.text
    assert conn.execute("SELECT resume_text FROM profiles").fetchone()[0] is None


def test_extract_shows_text_for_review_and_saves_nothing(client, conn):
    pid = create_profile(client)
    pdf = (FIXTURES / "sample_resume.pdf").read_bytes()
    r = client.post(f"/profiles/{pid}/resume/extract", files={"file": ("cv.pdf", pdf)})
    assert r.status_code == 200
    assert "Apache Kafka" in r.text
    assert "Save resume" in r.text
    assert conn.execute("SELECT resume_text FROM profiles").fetchone()[0] is None


def test_chunks_respect_size_and_keep_every_line():
    text = (
        sample_resume()
        + "\n"
        + ("long " * 400)
        + "\n\n"
        + "\n".join(f"line {i}" for i in range(300))
    )
    chunks = chunk_text(text)
    assert all(len(c) <= CHUNK_MAX_CHARS for c in chunks)
    joined = "".join(c.replace("\n", "") for c in chunks)
    expected = "".join(line.strip() for line in text.splitlines() if line.strip())
    assert joined == expected


def test_short_paragraphs_join_until_200_characters():
    assert chunk_text("a\n\nb") == ["a\nb"]
    long_para = "x" * 200
    assert chunk_text(f"{long_para}\n\nb") == [long_para, "b"]


def test_saving_twice_leaves_one_set_of_chunks(client, conn):
    pid = create_profile(client)
    save_resume(client, pid)
    first = conn.execute("SELECT count(*) FROM resume_chunks").fetchone()[0]
    save_resume(client, pid)
    assert conn.execute("SELECT count(*) FROM resume_chunks").fetchone()[0] == first
    rows = conn.execute("SELECT embedding FROM resume_chunks").fetchall()
    assert first >= 1 and all(len(r[0]) == 1536 for r in rows)
    profile = conn.execute("SELECT resume_text, resume_name FROM profiles").fetchone()
    assert profile[0] == sample_resume().strip()
    assert profile[1] == "sample_resume.txt"


def test_nothing_but_the_database_is_written(client, settings):
    pid = create_profile(client)
    pdf = (FIXTURES / "sample_resume.pdf").read_bytes()
    client.post(f"/profiles/{pid}/resume/extract", files={"file": ("cv.pdf", pdf)})
    save_resume(client, pid)
    files = [p.relative_to(settings.data_dir).as_posix() for p in settings.data_dir.rglob("*")]
    assert files == ["app.db"]
