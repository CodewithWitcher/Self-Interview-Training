import random
from contextlib import closing
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app import db
from app.config import Settings
from app.main import create_app

BASE_URL = "http://127.0.0.1:8000"
TODAY = date(2026, 10, 12)


@pytest.fixture
def settings(tmp_path):
    return Settings(repo_root=tmp_path, data_dir=tmp_path / "data", dev_fake=True)


def make_client(settings, today=TODAY, raise_server_exceptions=True) -> TestClient:
    app = create_app(settings)
    app.state.today = lambda: today
    app.state.rng = random.Random(1234)
    return TestClient(app, base_url=BASE_URL, raise_server_exceptions=raise_server_exceptions)


@pytest.fixture
def app(settings):
    return create_app(settings)


@pytest.fixture
def client(settings):
    with make_client(settings) as c:
        yield c


@pytest.fixture
def conn(settings, client):
    """A connection to the same database the client uses. Closed after the test."""
    with closing(db.connect(settings.db_path)) as c:
        yield c
