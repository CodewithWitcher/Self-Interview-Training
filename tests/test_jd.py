from tests.helpers import FIXTURES, build_plan, create_profile, save_resume


def jd_text():
    return (FIXTURES / "sample_jd.txt").read_text(encoding="utf-8")


def setup(client):
    pid = create_profile(client)
    save_resume(client, pid)
    return pid


def test_jd_plan_shows_kubernetes_as_gap(client, conn):
    pid = setup(client)
    r = client.post(
        f"/profiles/{pid}/jd",
        data={"title": "Senior Platform Engineer", "text": jd_text()},
        follow_redirects=False,
    )
    assert r.status_code == 303
    row = conn.execute("SELECT jd_title, jd_text FROM profiles").fetchone()
    assert row[0] == "Senior Platform Engineer" and "Kubernetes" in row[1]
    build_plan(client, pid)
    k = conn.execute("SELECT * FROM topics WHERE name = 'Kubernetes'").fetchone()
    assert k["source"] == "jd" and k["weight"] >= 3
    page = client.get(f"/profiles/{pid}/plan").text
    row_html = page.split(f'id="topic-{k["id"]}"')[1].split("</tr>")[0]
    assert "<strong>Gap</strong>" in row_html
    python = conn.execute("SELECT source FROM topics WHERE name = 'Python'").fetchone()[0]
    assert python == "both"


def test_clearing_jd_and_rebuilding_switches_gap_off(client, conn):
    pid = setup(client)
    client.post(f"/profiles/{pid}/jd", data={"title": "", "text": jd_text()})
    build_plan(client, pid)
    kid = conn.execute("SELECT id FROM topics WHERE name = 'Kubernetes'").fetchone()[0]
    r = client.post(f"/profiles/{pid}/jd", data={"action": "clear"}, follow_redirects=False)
    assert r.status_code == 303
    assert conn.execute("SELECT jd_text FROM profiles").fetchone()[0] is None
    build_plan(client, pid)
    k = conn.execute("SELECT id, weight FROM topics WHERE name = 'Kubernetes'").fetchone()
    assert (k[0], k[1]) == (kid, 0)
    sources = {r[0] for r in conn.execute("SELECT source FROM topics WHERE weight > 0")}
    assert sources == {"resume"}


def test_long_jd_is_rejected_with_text_kept(client, conn):
    pid = setup(client)
    long = "k" * 6001
    r = client.post(f"/profiles/{pid}/jd", data={"title": "T", "text": long})
    assert r.status_code == 422
    assert long in r.text
    assert "6,000" in r.text
    assert conn.execute("SELECT jd_text FROM profiles").fetchone()[0] is None


def test_long_title_is_rejected(client):
    pid = setup(client)
    r = client.post(f"/profiles/{pid}/jd", data={"title": "t" * 121, "text": "ok"})
    assert r.status_code == 422
    assert "t" * 121 in r.text
