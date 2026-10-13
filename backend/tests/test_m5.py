"""Real PostgreSQL checks for the new read-only discovery surface."""

from datetime import UTC, datetime

import pytest
from app.clock import FixedClock
from app.models import AfterSalesCase, Order, Policy, SupportTicket
from app.workspace import CasePageQuery, PageQuery, WorkspaceService
from sqlalchemy import select

NOW = datetime(2026, 10, 11, 2, tzinfo=UTC)


@pytest.fixture
def populated(database):
    with database[2]() as session, session.begin():
        for actor, order, tenant in [
            ("C-A1", "O-A101", "TENANT-A"),
            ("C-A2", "O-A108", "TENANT-A"),
            ("C-B1", "O-B101", "TENANT-B"),
        ]:
            # Resource ACLs join actual orders; tenant names are copied from their rows.
            source = session.get(Order, order)
            policy = session.scalar(
                select(Policy)
                .where(Policy.tenant_id == source.tenant_id)
                .order_by(Policy.effective_from.desc())
            )
            for index in range(2):
                session.add(
                    AfterSalesCase(
                        id=f"CASE-{actor}-{index}",
                        tenant_id=source.tenant_id,
                        order_id=order,
                        case_type="RETURN_REFUND",
                        status="CANCELLED",
                        reason="M5测试",
                        evidence_refs=[],
                        requested_amount_fen=source.paid_amount_fen,
                        policy_version=policy.id,
                        policy_digest="0" * 64,
                        rules_snapshot={},
                        version=1,
                        order_version=source.version,
                        created_by=actor,
                        created_at=NOW,
                    )
                )
            session.add(
                SupportTicket(
                    id=f"TICKET-{actor}",
                    tenant_id=source.tenant_id,
                    order_id=order,
                    category="LOGISTICS",
                    summary="<img src=x onerror=alert(1)>",
                    status="OPEN",
                    created_by=actor,
                    created_at=NOW,
                )
            )
    return database


@pytest.mark.parametrize(
    "actor,owners",
    [
        ("C-A1", ["C-A1"]),
        ("C-A2", ["C-A2"]),
        ("C-B1", ["C-B1"]),
        ("E-A1", ["C-A1", "C-A2"]),
        ("E-A2", ["C-A1", "C-A2"]),
        ("E-A3", ["C-A1", "C-A2"]),
        ("E-B2", ["C-B1"]),
    ],
)
def test_collections_scoped(populated, actor, owners):
    with populated[2]() as session:
        service = WorkspaceService(session, actor, FixedClock(NOW), "m5-test")
        cases = service.cases(CasePageQuery())["items"]
        tickets = service.tickets(PageQuery())["items"]
        assert {c["id"] for c in cases} == {
            f"CASE-{owner}-{i}" for owner in owners for i in range(2)
        }
        assert {t["id"] for t in tickets} == {f"TICKET-{owner}" for owner in owners}
        assert all(t["summary"] == "<img src=x onerror=alert(1)>" for t in tickets)


def test_pagination_and_filter(populated):
    with populated[2]() as session:
        service = WorkspaceService(session, "E-A2", FixedClock(NOW), "m5-test")
        first = service.cases(CasePageQuery(limit=2))
        second = service.cases(CasePageQuery(limit=2, cursor=first["next_cursor"]))
        assert len(first["items"]) == len(second["items"]) == 2
        assert not {c["id"] for c in first["items"]} & {c["id"] for c in second["items"]}
        assert second["next_cursor"] is None
        assert service.cases(CasePageQuery(status="PENDING_REVIEW"))["items"] == []


@pytest.mark.parametrize(
    "path",
    [
        "/cases?tenant_id=TENANT-B",
        "/tickets?limit=51",
        "/conversations?owner_id=C-A2",
        "/cases?status=HACK",
    ],
)
def test_query_tampering_rejected(client, login, path):
    assert client.get("/api/v1" + path, headers=login("C-A1")).status_code == 422


def test_evidence_and_identity(client, login):
    assert (
        client.get("/api/v1/orders/O-A101/evidence", headers=login("C-A1")).json()["data"]["items"][
            0
        ]["id"]
        == "EVIDENCE-A1"
    )
    assert (
        client.get("/api/v1/orders/O-A108/evidence", headers=login("C-A2")).json()["data"]["items"]
        == []
    )
    assert client.get("/api/v1/orders/O-A101/evidence", headers=login("C-A2")).status_code == 404
    assert client.get("/api/v1/orders/O-A101/evidence", headers=login("E-A2")).status_code == 403
    me = client.get("/api/v1/me", headers=login("E-A2")).json()["data"]
    assert me["roles"] == ["reviewer"] and me["simulated"] is True


def test_conversation_listing_own_only(client, login):
    created = []
    for actor in ["C-A1", "C-A2", "E-A1", "C-B1"]:
        result = client.post(
            "/api/v1/conversations",
            json={},
            headers={**login(actor), "Idempotency-Key": "m5-unique-conversation"},
        )
        assert result.status_code == 201
        created.append((actor, result.json()["data"]["conversation_id"]))
    for actor, id in created:
        rows = client.get("/api/v1/conversations", headers=login(actor)).json()["data"]["items"]
        assert [r["conversation_id"] for r in rows] == [id]
    assert client.get("/api/v1/conversations", headers=login("E-A3")).status_code == 403


def test_history_does_not_bypass_resource_acl(populated, client, login):
    assert (
        client.get("/api/v1/cases/CASE-C-A1-0/timeline", headers=login("C-A2")).status_code == 404
    )
    assert (
        client.get("/api/v1/cases/CASE-C-A1-0/timeline", headers=login("C-B1")).status_code == 404
    )
    assert (
        client.get("/api/v1/cases/CASE-C-A1-0/timeline", headers=login("E-A2")).json()["data"][
            "items"
        ]
        == []
    )
