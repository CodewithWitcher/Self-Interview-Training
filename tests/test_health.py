from dataclasses import replace

from app import health


def test_status_page_lists_every_check(client, settings):
    r = client.get("/status")
    assert r.status_code == 200
    for check in health.run_checks(settings):
        assert check.name in r.text


def test_fake_mode_skips_model_checks(settings):
    checks = {c.name: c for c in health.run_checks(settings)}
    for name in ("Embedding model", "Speech model", "Ollama", "Claude key"):
        assert checks[name].ok is None
    assert [c.required for c in checks.values()] == [
        True,
        True,
        True,
        True,
        False,
        False,
        False,
        False,
    ]


def test_command_exits_0_in_healthy_fake_setup(settings, capsys):
    assert health.main(settings) == 0
    out = capsys.readouterr().out
    assert "[PASS] Data folder writable" in out
    assert "[SKIP] Ollama" in out


def test_command_exits_1_when_file_occupies_data_folder(tmp_path, settings, capsys):
    blocker = tmp_path / "blocked"
    blocker.write_text("not a folder", encoding="utf-8")
    assert health.main(replace(settings, data_dir=blocker)) == 1
    assert "[FAIL] Data folder writable" in capsys.readouterr().out


def test_output_is_ascii_only(tmp_path, settings, capsys):
    odd = tmp_path / "données ☃"
    health.main(replace(settings, data_dir=odd))
    capsys.readouterr().out.encode("ascii")


def test_failed_import_points_to_trap_1(monkeypatch):
    def fail(name):
        raise ModuleNotFoundError("No module named 'anthropic.types.beta'")

    monkeypatch.setattr(health.importlib, "import_module", fail)
    check = health.check_anthropic_import()
    assert check.ok is False
    assert "trap 1" in check.detail


def test_newer_database_fails(settings):
    import sqlite3
    from contextlib import closing

    settings.data_dir.mkdir(parents=True)
    with closing(sqlite3.connect(settings.db_path)) as conn:
        conn.execute("PRAGMA user_version = 99")
    assert health.check_database(settings).ok is False


def test_model_with_fake_provider_shows_time(client):
    r = client.post("/status/test", data={"model": "fake:fake"})
    assert r.status_code == 200
    assert "fake:fake answered in" in r.text
    assert "seconds" in r.text


def test_model_with_unreachable_ollama_shows_message(settings, monkeypatch):
    import httpx

    from app import llm
    from tests.conftest import make_client

    def refuse(request):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(llm, "http_transport", httpx.MockTransport(refuse))
    real = replace(settings, dev_fake=False)
    with make_client(real) as c:
        r = c.post("/status/test", data={"model": "ollama:llama3.1:8b"})
        assert r.status_code == 200
        assert "could not be reached" in r.text
        assert "Traceback" not in r.text
        page = c.get("/status").text
        assert "Cloud: claude-opus-5-5" in page


def test_status_page_lists_models_with_labels(client):
    text = client.get("/status").text
    assert "Fake model" in text and "local, nothing leaves this computer" in text


def test_speech_model_check_names_fetch_command(settings):
    check = health.check_speech_model(replace(settings, dev_fake=False))
    assert check.ok is False and "--voice" in check.detail and not check.required
