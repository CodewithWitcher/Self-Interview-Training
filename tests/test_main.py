from fastapi import APIRouter

from tests.conftest import make_client


def test_home_shows_empty_state(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "No profiles yet" in r.text
    assert 'href="#main"' in r.text
    assert 'aria-label="Main"' in r.text


def test_wrong_host_is_rejected(client):
    r = client.get("/", headers={"Host": "evil.example"})
    assert r.status_code == 400


def test_localhost_host_is_accepted(client):
    assert client.get("/", headers={"Host": "localhost:8000"}).status_code == 200


def test_cross_origin_post_is_rejected(client):
    r = client.post("/profiles", data={"name": "x"}, headers={"Origin": "http://evil.example"})
    assert r.status_code == 403


def test_cross_site_fetch_post_is_rejected(client):
    r = client.post("/profiles", data={"name": "x"}, headers={"Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403


def test_same_origin_post_passes_the_check(client):
    r = client.post(
        "/nowhere",
        headers={"Origin": "http://127.0.0.1:8000", "Sec-Fetch-Site": "same-origin"},
    )
    assert r.status_code != 403


def test_origin_with_other_port_is_rejected(client):
    r = client.post("/profiles", data={"name": "x"}, headers={"Origin": "http://127.0.0.1:9999"})
    assert r.status_code == 403


def test_unknown_path_shows_404_page(client):
    r = client.get("/no/such/page")
    assert r.status_code == 404
    assert "Not found" in r.text
    assert "<html" in r.text


def test_exception_shows_500_page_without_traceback(settings):
    c = make_client(settings, raise_server_exceptions=False)
    router = APIRouter()

    @router.get("/boom")
    def boom():
        raise RuntimeError("secret internal detail")

    c.app.include_router(router)
    with c:
        r = c.get("/boom")
    assert r.status_code == 500
    assert "Error id:" in r.text
    assert "Traceback" not in r.text
    assert "secret internal detail" not in r.text


def test_static_files_are_served(client):
    assert client.get("/static/app.css").status_code == 200
    assert client.get("/static/app.js").status_code == 200


def test_oversized_body_is_refused(client):
    r = client.post("/profiles", content=b"x", headers={"Content-Length": str(30 * 1024 * 1024)})
    assert r.status_code == 413
