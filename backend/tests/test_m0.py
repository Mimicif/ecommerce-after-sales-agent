import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from alembic import command
from alembic.config import Config
from app.cli import validate_reset
from app.config import ROOT, Settings
from app.main import create_app, digest
from app.models import DevSession, Evidence, LogisticsEvent, Order, Policy, SeedImport, Tenant, User
from app.seed import import_seed, parse_time
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError


def test_health_and_seed_counts(client, database):
    result = client.get("/api/v1/health")
    assert result.status_code == 200
    assert result.json()["data"]["database"] == "reachable"
    assert result.headers["X-Trace-Id"] == result.json()["trace_id"]
    with database[2]() as session:
        for model, count in (
            (Tenant, 2),
            (User, 8),
            (Order, 14),
            (LogisticsEvent, 2),
            (Evidence, 1),
            (Policy, 3),
            (SeedImport, 1),
        ):
            assert session.scalar(select(func.count()).select_from(model)) == count
        assert session.scalar(text("SHOW timezone")) == "UTC"
        order = session.get(Order, "O-A101")
        assert order.delivered_at == datetime(2026, 10, 9, 2, tzinfo=UTC)
        policy = session.get(Policy, "POLICY-A-2026-10-v1")
        assert policy.rules["standard_return_window_seconds"] == 604800
        assert len(policy.clauses) == 6
        assert session.get(SeedImport, "base").fixture_clock == datetime(
            2026, 10, 11, 2, tzinfo=UTC
        )


@pytest.mark.parametrize(
    "user,own,other",
    [
        ("C-A1", "O-A101", "O-B101"),
        ("C-B1", "O-B101", "O-A101"),
        ("C-A1", "O-A101", "O-A108"),
        ("C-A2", "O-A108", "O-A101"),
    ],
)
def test_order_isolation(client, login, user, own, other):
    headers = login(user)
    assert client.get(f"/api/v1/orders/{own}", headers=headers).status_code == 200
    denied = client.get(f"/api/v1/orders/{other}", headers=headers)
    absent = client.get("/api/v1/orders/O-ABSENT", headers=headers)
    assert denied.status_code == absent.status_code == 404
    assert denied.json()["code"] == absent.json()["code"] == "RESOURCE_NOT_FOUND"
    ids = {o["id"] for o in client.get("/api/v1/orders", headers=headers).json()["data"]["items"]}
    assert own in ids and other not in ids


def test_support_scope_and_pagination(client, login):
    headers = login("E-A1")
    assert client.get("/api/v1/orders/O-A108", headers=headers).status_code == 200
    assert client.get("/api/v1/orders/O-B101", headers=headers).status_code == 404
    seen, cursor = [], None
    while True:
        params = {"limit": 3}
        if cursor:
            params["cursor"] = cursor
        data = client.get("/api/v1/orders", headers=headers, params=params).json()["data"]
        seen.extend(o["id"] for o in data["items"])
        cursor = data["next_cursor"]
        if cursor is None:
            break
    assert len(seen) == len(set(seen)) == 13
    assert client.get("/api/v1/orders", headers=headers, params={"limit": 21}).status_code == 422


@pytest.mark.parametrize("user", ["E-A2", "E-A3", "E-B2"])
def test_roles_do_not_grant_order_access(client, login, user):
    assert client.get("/api/v1/orders", headers=login(user)).status_code == 403


def test_identity_forgery_and_unknown_user(client, login):
    for extra in ({"tenant_id": "TENANT-B"}, {"roles": ["support"]}):
        response = client.post("/api/v1/dev/sessions", json={"user_id": "C-A1", **extra})
        assert response.status_code == 422
    assert client.post("/api/v1/dev/sessions", json={"user_id": "C-A99"}).status_code == 404
    headers = {**login("C-A1"), "X-Tenant-Id": "TENANT-B", "X-Role": "support"}
    assert client.get("/api/v1/orders/O-B101", headers=headers).status_code == 404
    assert client.get("/api/v1/orders/O-A108", headers=headers).status_code == 404


def test_session_invalid_expired_and_no_raw_token(client, login, database):
    headers = login("C-A1")
    token = headers["Authorization"].split()[1]
    assert client.get("/api/v1/orders").status_code == 401
    assert client.get("/api/v1/orders", headers={"Authorization": "Bearer bad"}).status_code == 401
    assert (
        client.get("/api/v1/orders", headers={"Authorization": "Bearer " + token + "x"}).status_code
        == 401
    )
    with database[2]() as session, session.begin():
        stored = session.get(DevSession, digest(token))
        assert stored is not None and stored.token_digest != token
        stored.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    assert client.get("/api/v1/orders", headers=headers).status_code == 401


def test_dev_mode_disabled_and_remote_peer(database):
    settings = database[0].model_copy(update={"dev_mode": False})
    with TestClient(create_app(settings), client=("127.0.0.1", 1)) as closed:
        assert closed.post("/api/v1/dev/sessions", json={"user_id": "C-A1"}).status_code == 404
        assert (
            closed.get("/api/v1/orders", headers={"Authorization": "Bearer anything"}).status_code
            == 401
        )
    with TestClient(create_app(database[0]), client=("192.0.2.10", 1)) as remote:
        headers = {"X-Forwarded-For": "127.0.0.1"}
        assert (
            remote.post(
                "/api/v1/dev/sessions", json={"user_id": "C-A1"}, headers=headers
            ).status_code
            == 404
        )
        assert remote.get("/api/v1/orders", headers=headers).status_code == 401


def test_seed_concurrent_idempotency(database):
    config = Config(str(ROOT / "alembic.ini"))
    command.downgrade(config, "base")
    command.upgrade(config, "head")

    def seed():
        with database[2]() as session, session.begin():
            return import_seed(session)

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(lambda _: seed(), range(2))) == ["already_imported", "imported"]
    with database[2]() as session:
        assert session.scalar(select(func.count()).select_from(Order)) == 14


def test_migration_roundtrip_atomic_import_and_changed_source(database, tmp_path):
    config = Config(str(ROOT / "alembic.ini"))
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    source = json.loads((ROOT / "data/fixtures.json").read_text(encoding="utf-8"))
    policies = json.loads((ROOT / "data/policy.json").read_text(encoding="utf-8"))
    (tmp_path / "fixtures.json").write_text(json.dumps(source), encoding="utf-8")
    policies["policies"][-1]["tenant_id"] = "TENANT-UNKNOWN"
    (tmp_path / "policy.json").write_text(json.dumps(policies), encoding="utf-8")
    with pytest.raises(IntegrityError), database[2]() as session, session.begin():
        import_seed(session, tmp_path)
    with database[2]() as session:
        assert session.scalar(select(func.count()).select_from(Tenant)) == 0
    with database[2]() as session, session.begin():
        assert import_seed(session) == "imported"
    with (
        pytest.raises(ValueError, match="Dataset changed"),
        database[2]() as session,
        session.begin(),
    ):
        import_seed(session, tmp_path)


@pytest.mark.parametrize(
    "changes",
    [
        {"paid_amount_fen": -1},
        {"refunded_amount_fen": 999999},
        {"version": 0},
        {"customer_id": "C-B1"},
    ],
)
def test_database_enforces_amount_version_and_tenant(database, changes):
    with pytest.raises(IntegrityError), database[2]() as session, session.begin():
        order = session.get(Order, "O-A101")
        for key, value in changes.items():
            setattr(order, key, value)
        session.flush()
    with database[2]() as session:
        assert session.get(Order, "O-A101").paid_amount_fen == 14900


def test_reset_guard(database):
    with pytest.raises(ValueError):
        validate_reset(database[0], "production")
    settings = Settings(
        _env_file=None,
        database_url=database[0].database_url,
        dev_mode=False,
        database_schema="public",
    )
    with pytest.raises(ValueError):
        validate_reset(settings, "after_sales_test")
    validate_reset(settings.model_copy(update={"dev_mode": True}), "after_sales_test")


def test_configuration_rejects_sqlite_remote_and_schema_injection():
    for url, schema in (
        ("sqlite:///bad.db", "public"),
        ("postgresql+psycopg://u:p@example.com/db", "public"),
        ("postgresql+psycopg://u:p@127.0.0.1/db", "public; DROP TABLE orders"),
    ):
        with pytest.raises(ValidationError):
            Settings(_env_file=None, database_url=url, database_schema=schema)
    with pytest.raises(ValueError):
        parse_time("2026-10-11T10:00:00")


def test_health_database_failure_is_503(database):
    url = database[0].database_url.get_secret_value()
    from sqlalchemy.engine import make_url

    bad_url = make_url(url).set(database="after_sales_database_does_not_exist")
    settings = database[0].model_copy(
        update={"database_url": bad_url.render_as_string(hide_password=False)}
    )
    # model_copy does not revalidate: construct real settings to preserve SecretStr handling.
    settings = Settings(_env_file=None, database_url=settings.database_url, dev_mode=True)
    with TestClient(create_app(settings), client=("127.0.0.1", 1)) as bad:
        response = bad.get("/api/v1/health")
        assert response.status_code == 503
        assert response.json()["code"] == "DATABASE_UNAVAILABLE"
        assert "password" not in response.text.lower()
