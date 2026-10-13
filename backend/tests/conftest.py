import os
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from app.config import ROOT, Settings
from app.db import make_engine, make_session_factory
from app.main import create_app
from app.seed import import_seed
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import make_url


@pytest.fixture
def database(monkeypatch):
    base = Settings()
    url = make_url(os.environ.get("TEST_DATABASE_URL", base.database_url.get_secret_value()))
    if url.database == "after_sales_dev":
        url = url.set(database="after_sales_test")
    if url.database != "after_sales_test":
        pytest.fail("Integration tests only permit the explicit after_sales_test database")
    schema = "after_sales_test_" + uuid4().hex
    monkeypatch.setenv("DATABASE_URL", url.render_as_string(hide_password=False))
    monkeypatch.setenv("DEV_MODE", "true")
    monkeypatch.setenv("DATABASE_SCHEMA", "public")
    admin = make_engine(Settings())
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    monkeypatch.setenv("DATABASE_SCHEMA", schema)
    settings = Settings()
    engine = make_engine(settings)
    try:
        command.upgrade(Config(str(ROOT / "alembic.ini")), "head")
        factory = make_session_factory(engine)
        with factory() as session, session.begin():
            import_seed(session)
        yield settings, engine, factory
    finally:
        engine.dispose()
        with admin.begin() as connection:
            # schema is generated here and is never derived from user input.
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


@pytest.fixture
def client(database):
    with TestClient(create_app(database[0]), client=("127.0.0.1", 51000)) as instance:
        yield instance


@pytest.fixture
def login(client):
    def headers(user_id):
        response = client.post("/api/v1/dev/sessions", json={"user_id": user_id})
        assert response.status_code == 201
        return {"Authorization": "Bearer " + response.json()["data"]["access_token"]}

    return headers
