def create(client, name):
    return client.post("/profiles", data={"name": name}, follow_redirects=False)


def test_created_profile_is_listed(client):
    r = create(client, "Ana")
    assert r.status_code == 303
    assert client.get("/").text.count("Ana") >= 1
    page = client.get(r.headers["location"])
    assert page.status_code == 200
    assert "<h1>Ana</h1>" in page.text


def test_same_name_other_case_is_rejected(client):
    create(client, "Ana")
    r = create(client, "ANA")
    assert r.status_code == 422
    assert "already exists" in r.text
    assert 'value="ANA"' in r.text


def test_name_length_is_checked(client):
    assert create(client, "   ").status_code == 422
    r = create(client, "x" * 61)
    assert r.status_code == 422
    assert "1 to 60" in r.text


def test_delete_with_wrong_confirmation_changes_nothing(client, conn):
    pid = int(create(client, "Ana").headers["location"].split("/")[2].split("?")[0])
    r = client.post(f"/profiles/{pid}/delete", data={"confirm": "ana"})
    assert r.status_code == 422
    assert "does not match" in r.text
    assert conn.execute("SELECT count(*) FROM profiles").fetchone()[0] == 1


def test_delete_with_right_confirmation_removes_profile(client, conn):
    pid = int(create(client, "Ana").headers["location"].split("/")[2].split("?")[0])
    r = client.post(f"/profiles/{pid}/delete", data={"confirm": "Ana"}, follow_redirects=False)
    assert r.status_code == 303
    assert conn.execute("SELECT count(*) FROM profiles").fetchone()[0] == 0
    assert client.get(f"/profiles/{pid}").status_code == 404


def test_unknown_profile_is_404(client):
    assert client.get("/profiles/999").status_code == 404
    assert client.post("/profiles/999/delete", data={"confirm": "x"}).status_code == 404
