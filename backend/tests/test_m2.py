from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier

import pytest
from alembic import command
from alembic.config import Config
from app.clock import FixedClock
from app.config import ROOT
from app.errors import BusinessError
from app.main import create_app
from app.models import (
    AfterSalesCase,
    AuditEvent,
    Confirmation,
    IdempotencyRecord,
    Order,
    Policy,
    RefundJob,
    RefundTransaction,
    ReviewDecision,
    SimulatedProviderOperation,
    SupportTicket,
    User,
)
from app.policy import content_digest
from app.refunds import (
    ProviderFailure,
    ProviderResult,
    RefundWorker,
    SimulatedCrash,
    SimulatedProvider,
)
from app.write_schemas import DraftInput, VersionInput
from app.writes import WriteService
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

NOW = datetime(2026, 10, 11, 2, tzinfo=UTC)


@pytest.fixture
def driver(database):
    with TestClient(
        create_app(database[0], clock=FixedClock(NOW)), client=("127.0.0.1", 52000)
    ) as client:
        yield Driver(client, database[2])


class Driver:
    def __init__(self, client, factory):
        self.client, self.factory, self.identities, self.sequence = client, factory, {}, 0

    def headers(self, actor, key=None):
        if actor not in self.identities:
            login = self.client.post("/api/v1/dev/sessions", json={"user_id": actor})
            assert login.status_code == 201
            self.identities[actor] = {
                "Authorization": "Bearer " + login.json()["data"]["access_token"]
            }
        headers = dict(self.identities[actor])
        if key:
            headers["Idempotency-Key"] = key
        return headers

    def request(self, path, body, actor="C-A1", *, key=None, method="POST"):
        self.sequence += 1
        return self.client.request(
            method,
            "/api/v1" + path,
            json=body,
            headers=self.headers(actor, key or f"m2-request-{self.sequence:05d}"),
        )

    def ok(self, path, body, actor="C-A1", **kwargs):
        response = self.request(path, body, actor, **kwargs)
        assert response.status_code in {200, 201}, response.json()
        assert response.json()["ok"]
        return response.json()["data"]

    def get(self, path, actor="C-A1"):
        return self.client.get("/api/v1" + path, headers=self.headers(actor))

    def draft(self, *, order="O-A101", kind="RETURN_REFUND", actor="C-A1", evidence=None, key=None):
        return self.ok(
            "/cases/drafts",
            {
                "order_id": order,
                "case_type": kind,
                "reason": "模拟商品损坏" if kind == "DAMAGE_REFUND" else "不合适，申请退回",
                "evidence_refs": evidence or [],
            },
            actor,
            key=key,
        )

    def summary(self, case):
        return self.ok(f"/cases/{case['id']}/confirmation", {"expected_version": case["version"]})

    def confirmed(self, case):
        summary = self.summary(case)
        self.ok(
            f"/confirmations/{summary['confirmation_id']}/confirm",
            {"payload_digest": summary["payload_digest"]},
        )
        return summary["summary"], summary

    def submitted(self, case):
        summary, conf = self.confirmed(case)
        case = self.ok(f"/cases/{case['id']}/submit", {"expected_version": summary["version"]})
        return case, conf

    def ready(self, *, damage=False, actor="C-A1"):
        case = self.draft(
            order="O-A103" if damage else "O-A101",
            kind="DAMAGE_REFUND" if damage else "RETURN_REFUND",
            actor=actor,
            evidence=["EVIDENCE-A1"] if damage else [],
        )
        case, _ = self.submitted(case)
        case = self.ok(
            f"/cases/{case['id']}/review",
            {
                "expected_version": case["version"],
                "decision": "APPROVE",
                "return_required": not damage,
                "reason": "人工核验模拟申请",
            },
            "E-A2",
        )
        if not damage:
            case = self.ok(
                f"/cases/{case['id']}/return-received",
                {"expected_version": case["version"]},
                "E-A3",
            )
        return case


def counts(factory, *models):
    with factory() as session:
        return [session.scalar(select(func.count()).select_from(model)) for model in models]


def due(factory, delta=60):
    with factory() as session, session.begin():
        for job in session.scalars(select(RefundJob)):
            job.next_attempt_at = datetime.now(UTC) - timedelta(seconds=delta)
            if job.lease_until:
                job.lease_until = datetime.now(UTC) - timedelta(seconds=delta)


@pytest.mark.parametrize("damage", [False, True])
def test_full_flow_and_exactly_one_bookkeeping(driver, damage):
    case = driver.ready(damage=damage)
    assert case["status"] == "READY_TO_REFUND"
    worker = RefundWorker(driver.factory)
    assert worker.run_once()["status"] == "REFUNDED"
    assert worker.run_once()["status"] == "IDLE"
    refund = driver.get(f"/cases/{case['id']}/refund").json()["data"]
    assert refund["funds_state"] == "SUCCEEDED" and refund["status"] == "REFUNDED"
    with driver.factory() as session:
        order = session.get(Order, case["order_id"])
        assert order.refunded_amount_fen == order.paid_amount_fen == case["requested_amount_fen"]
        assert order.version == 2
    assert counts(driver.factory, RefundJob, RefundTransaction, SimulatedProviderOperation) == [
        1,
        1,
        1,
    ]


def test_customer_confirmation_required_and_consumed_atomic(driver):
    case = driver.draft()
    summary = driver.summary(case)
    response = driver.request(
        f"/cases/{case['id']}/submit", {"expected_version": summary["summary"]["version"]}
    )
    assert response.status_code == 409 and response.json()["code"] == "CONFIRMATION_REQUIRED"
    assert driver.get(f"/cases/{case['id']}").json()["data"]["status"] == "WAITING_FOR_USER"
    driver.ok(
        f"/confirmations/{summary['confirmation_id']}/confirm",
        {"payload_digest": summary["payload_digest"]},
    )
    result = driver.ok(
        f"/cases/{case['id']}/submit", {"expected_version": summary["summary"]["version"]}
    )
    assert result["status"] == "PENDING_REVIEW"
    with driver.factory() as session:
        conf = session.get(Confirmation, summary["confirmation_id"])
        assert conf.confirmed_by == "C-A1" and conf.consumed_at == NOW


@pytest.mark.parametrize("offset,expected", [(899, 200), (900, 409), (901, 409)])
def test_confirmation_expiry_boundary(driver, database, offset, expected):
    summary = driver.summary(driver.draft())
    with TestClient(
        create_app(database[0], clock=FixedClock(NOW + timedelta(seconds=offset))),
        client=("127.0.0.1", 52001),
    ) as client:
        response = client.post(
            f"/api/v1/confirmations/{summary['confirmation_id']}/confirm",
            json={"payload_digest": summary["payload_digest"]},
            headers=driver.headers("C-A1", "expiry-test-key"),
        )
    assert response.status_code == expected
    if expected == 409:
        assert response.json()["code"] == "CONFIRMATION_EXPIRED"


def test_confirmed_then_expired_submission_and_regenerate(driver, database):
    case, conf = driver.confirmed(driver.draft())
    with TestClient(
        create_app(database[0], clock=FixedClock(NOW + timedelta(seconds=900))),
        client=("127.0.0.1", 52001),
    ) as client:
        response = client.post(
            f"/api/v1/cases/{case['id']}/submit",
            json={"expected_version": case["version"]},
            headers=driver.headers("C-A1", "expired-submit-key"),
        )
        assert response.json()["code"] == "CONFIRMATION_EXPIRED"
    fresh = driver.summary(case)
    assert fresh["confirmation_id"] != conf["confirmation_id"]
    assert fresh["summary"]["version"] == case["version"] + 1


def test_edit_invalidates_confirmation(driver):
    case, conf = driver.confirmed(driver.draft())
    edited = driver.ok(
        f"/cases/{case['id']}/draft",
        {"expected_version": case["version"], "reason": "更改原因", "evidence_refs": []},
        method="PATCH",
    )
    assert edited["status"] == "DRAFT" and edited["version"] == case["version"] + 1
    response = driver.request(
        f"/confirmations/{conf['confirmation_id']}/confirm",
        {"payload_digest": conf["payload_digest"]},
    )
    assert response.status_code == 409
    assert (
        driver.request(
            f"/cases/{case['id']}/submit", {"expected_version": edited["version"]}
        ).status_code
        == 409
    )


@pytest.mark.parametrize("change", ["order_version", "balance", "policy", "reason", "digest"])
def test_stale_confirmation_rejects_and_rolls_back(driver, change):
    case, conf = driver.confirmed(driver.draft())
    with driver.factory() as session, session.begin():
        order = session.get(Order, case["order_id"])
        if change == "order_version":
            order.version += 1
        elif change == "balance":
            order.refunded_amount_fen = 100
        elif change == "policy":
            policy = session.get(Policy, case["policy_version"])
            policy.rules = {**policy.rules, "standard_return_window_seconds": 604801}
            policy.content_digest = content_digest(policy.rules, policy.clauses)
        elif change == "reason":
            session.get(AfterSalesCase, case["id"]).reason = "摘要外修改"
        else:
            session.get(Confirmation, conf["confirmation_id"]).payload_digest = "f" * 64
    response = driver.request(f"/cases/{case['id']}/submit", {"expected_version": case["version"]})
    assert response.status_code == 409 and response.json()["code"] == "VERSION_CONFLICT"
    with driver.factory() as session:
        assert session.get(Confirmation, conf["confirmation_id"]).consumed_at is None
        assert session.get(AfterSalesCase, case["id"]).status == "WAITING_FOR_USER"


def test_regenerate_updates_order_and_policy_snapshot(driver):
    case, _ = driver.confirmed(driver.draft())
    with driver.factory() as session, session.begin():
        session.get(Order, case["order_id"]).version = 2
        policy = session.get(Policy, case["policy_version"])
        policy.rules = {**policy.rules, "standard_return_window_seconds": 604801}
        policy.content_digest = content_digest(policy.rules, policy.clauses)
    fresh = driver.summary(case)
    assert fresh["summary"]["order_version"] == 2
    driver.ok(
        f"/confirmations/{fresh['confirmation_id']}/confirm",
        {"payload_digest": fresh["payload_digest"]},
    )
    assert (
        driver.ok(f"/cases/{case['id']}/submit", {"expected_version": fresh["summary"]["version"]})[
            "status"
        ]
        == "PENDING_REVIEW"
    )


def test_idempotent_submit_replays_after_expiry_and_review(driver, database):
    case, _ = driver.confirmed(driver.draft())
    body = {"expected_version": case["version"]}
    original = driver.ok(f"/cases/{case['id']}/submit", body, key="submit-stable-key")
    driver.ok(
        f"/cases/{case['id']}/review",
        {
            "expected_version": original["version"],
            "decision": "REJECT",
            "reason": "拒绝演示",
            "return_required": False,
        },
        "E-A2",
    )
    with TestClient(
        create_app(database[0], clock=FixedClock(NOW + timedelta(minutes=30))),
        client=("127.0.0.1", 52001),
    ) as client:
        replay = client.post(
            f"/api/v1/cases/{case['id']}/submit",
            json=body,
            headers=driver.headers("C-A1", "submit-stable-key"),
        )
        assert replay.json()["data"] == original
    conflict = driver.request(
        f"/cases/{case['id']}/submit", {"expected_version": 99}, key="submit-stable-key"
    )
    assert conflict.json()["code"] == "IDEMPOTENCY_CONFLICT"
    assert counts(driver.factory, AfterSalesCase, ReviewDecision) == [1, 1]


def test_all_side_effects_replay_and_conflict(driver):
    case = driver.draft(key="stable-draft-key")
    assert driver.draft(key="stable-draft-key") == case
    changed = driver.request(
        "/cases/drafts",
        {"order_id": "O-A102", "case_type": "RETURN_REFUND", "reason": "原因"},
        key="stable-draft-key",
    )
    assert changed.json()["code"] == "IDEMPOTENCY_CONFLICT"
    summary = driver.summary(case)
    body = {"payload_digest": summary["payload_digest"]}
    assert driver.ok(
        f"/confirmations/{summary['confirmation_id']}/confirm", body, key="stable-confirm-key"
    ) == driver.ok(
        f"/confirmations/{summary['confirmation_id']}/confirm", body, key="stable-confirm-key"
    )
    case = driver.ok(
        f"/cases/{case['id']}/submit", {"expected_version": summary["summary"]["version"]}
    )
    body = {
        "expected_version": case["version"],
        "decision": "APPROVE",
        "return_required": True,
        "reason": "批准",
    }
    approved = driver.ok(f"/cases/{case['id']}/review", body, "E-A2", key="stable-review-key")
    assert (
        driver.ok(f"/cases/{case['id']}/review", body, "E-A2", key="stable-review-key") == approved
    )
    body = {"expected_version": approved["version"]}
    ready = driver.ok(
        f"/cases/{case['id']}/return-received", body, "E-A3", key="stable-receive-key"
    )
    assert (
        driver.ok(f"/cases/{case['id']}/return-received", body, "E-A3", key="stable-receive-key")
        == ready
    )
    assert counts(driver.factory, RefundJob, ReviewDecision) == [1, 1]


@pytest.mark.parametrize("actor", ["C-A2", "C-B1", "E-B2"])
def test_resource_isolation_every_case_path(driver, actor):
    case = driver.draft()
    for path in [f"/cases/{case['id']}", f"/cases/{case['id']}/refund"]:
        assert driver.get(path, actor).status_code == 404
    for endpoint in ["submit", "review", "return-received", "refund-reconcile", "confirmation"]:
        body = {"expected_version": 1}
        if endpoint == "review":
            body.update(decision="APPROVE", reason="试图越权", return_required=True)
        response = driver.request(f"/cases/{case['id']}/{endpoint}", body, actor)
        assert response.status_code in {403, 404}
    assert driver.request(
        "/cases/drafts",
        {"order_id": case["order_id"], "case_type": "RETURN_REFUND", "reason": "越权"},
        actor,
    ).status_code in {403, 404}


@pytest.mark.parametrize("actor", ["E-A1", "E-A2", "E-A3", "C-A2", "C-B1"])
def test_customer_confirm_cannot_be_impersonated(driver, actor):
    summary = driver.summary(driver.draft())
    response = driver.request(
        f"/confirmations/{summary['confirmation_id']}/confirm",
        {"payload_digest": summary["payload_digest"]},
        actor,
    )
    assert response.status_code in {403, 404}
    assert counts(driver.factory, RefundJob) == [0]


def test_support_draft_requires_owner_and_self_approval_blocked(driver):
    case = driver.draft(actor="E-A4")
    assert (
        driver.request(
            f"/cases/{case['id']}/confirmation", {"expected_version": 1}, "E-A4"
        ).status_code
        == 403
    )
    case, _ = driver.submitted(case)
    body = {
        "expected_version": case["version"],
        "decision": "APPROVE",
        "reason": "自己审核",
        "return_required": True,
    }
    assert driver.request(f"/cases/{case['id']}/review", body, "E-A4").status_code == 403
    assert driver.request(f"/cases/{case['id']}/review", body, "C-A1").status_code == 403
    assert driver.ok(f"/cases/{case['id']}/review", body, "E-A2")["status"] == "AWAITING_RETURN"


def test_customer_plus_reviewer_does_not_gain_customer_write_scope(driver):
    case = driver.draft()
    with driver.factory() as session, session.begin():
        session.get(User, "C-A2").roles = ["customer", "reviewer"]
    response = driver.request(
        f"/cases/{case['id']}/draft",
        {"expected_version": 1, "reason": "越权"},
        "C-A2",
        method="PATCH",
    )
    assert response.status_code == 404


def test_role_revocation_prevents_cached_write(driver):
    case = driver.draft(key="revoked-draft-key")
    with driver.factory() as session, session.begin():
        session.get(User, "C-A1").roles = []
    response = driver.request(
        "/cases/drafts",
        {
            "order_id": "O-A101",
            "case_type": "RETURN_REFUND",
            "reason": case["reason"],
            "evidence_refs": [],
        },
        key="revoked-draft-key",
    )
    assert response.status_code == 403


def test_standard_requires_return_and_warehouse_role(driver):
    case, _ = driver.submitted(driver.draft())
    body = {
        "expected_version": case["version"],
        "decision": "APPROVE",
        "reason": "审核",
        "return_required": False,
    }
    assert (
        driver.request(f"/cases/{case['id']}/review", body, "E-A2").json()["code"]
        == "INVALID_STATE_TRANSITION"
    )
    assert RefundWorker(driver.factory).run_once()["status"] == "IDLE"
    body["return_required"] = True
    case = driver.ok(f"/cases/{case['id']}/review", body, "E-A2")
    assert RefundWorker(driver.factory).run_once()["status"] == "IDLE"
    assert (
        driver.request(
            f"/cases/{case['id']}/return-received", {"expected_version": case["version"]}, "E-A2"
        ).status_code
        == 403
    )
    assert (
        driver.ok(
            f"/cases/{case['id']}/return-received", {"expected_version": case["version"]}, "E-A3"
        )["status"]
        == "READY_TO_REFUND"
    )


@pytest.mark.parametrize(
    "refs,code",
    [
        ([], "INVALID_ARGUMENT"),
        (["EV-B101-1"], "RESOURCE_NOT_FOUND"),
        (["EV-MISSING"], "RESOURCE_NOT_FOUND"),
        (["EVIDENCE-A1", "EVIDENCE-A1"], "INVALID_ARGUMENT"),
    ],
)
def test_damage_evidence_validation(driver, refs, code):
    response = driver.request(
        "/cases/drafts",
        {
            "order_id": "O-A103",
            "case_type": "DAMAGE_REFUND",
            "reason": "破损",
            "evidence_refs": refs,
        },
    )
    assert response.json()["code"] == code
    assert counts(driver.factory, AfterSalesCase) == [0]


def test_evidence_owner_checked_for_support(driver):
    response = driver.request(
        "/cases/drafts",
        {
            "order_id": "O-A101",
            "case_type": "DAMAGE_REFUND",
            "reason": "破损",
            "evidence_refs": ["EVIDENCE-A1"],
        },
        "E-A1",
    )
    # EVIDENCE-A1 belongs to the same customer and is acceptable as a simulated reference;
    # changing owner must fail, even for support.
    assert response.status_code == 201
    with driver.factory() as session, session.begin():
        from app.models import Evidence

        session.get(Evidence, "EVIDENCE-A1").owner_id = "C-A2"
    case = response.json()["data"]
    assert (
        driver.request(f"/cases/{case['id']}/confirmation", {"expected_version": 1}).status_code
        == 404
    )


@pytest.mark.parametrize(
    "order",
    ["O-A103", "O-A105", "O-A106", "O-A107", "O-A108", "O-A109", "O-A110", "O-A111", "O-A112"],
)
def test_unpayable_return_goes_manual_without_case(driver, order):
    response = driver.request(
        "/cases/drafts", {"order_id": order, "case_type": "RETURN_REFUND", "reason": "退货"}
    )
    assert response.status_code in {404, 409}, response.json()
    assert counts(driver.factory, AfterSalesCase, RefundJob) == [0, 0]


def test_missing_policy_damage_ticket_and_isolation(driver):
    with driver.factory() as session, session.begin():
        session.get(Policy, "POLICY-A-2026-10-v1").status = "DRAFT"
    response = driver.request(
        "/cases/drafts",
        {
            "order_id": "O-A103",
            "case_type": "DAMAGE_REFUND",
            "reason": "破损",
            "evidence_refs": ["EVIDENCE-A1"],
        },
    )
    assert response.status_code == 503 and response.json()["code"] == "POLICY_UNAVAILABLE"
    body = {
        "order_id": "O-A103",
        "category": "MANUAL_AFTER_SALES",
        "summary": "政策缺失，需人工处理损坏诉求",
    }
    ticket = driver.ok("/tickets", body, key="stable-ticket-key")
    assert driver.ok("/tickets", body, key="stable-ticket-key") == ticket
    assert driver.get(f"/tickets/{ticket['id']}", "C-A2").status_code == 404
    assert driver.get(f"/tickets/{ticket['id']}", "E-B2").status_code == 404
    assert driver.get(f"/tickets/{ticket['id']}", "E-A2").status_code == 200
    assert counts(driver.factory, AfterSalesCase, SupportTicket) == [0, 1]


def test_activity_guard_and_cancel_releases_it(driver):
    case = driver.draft()
    response = driver.request(
        "/cases/drafts", {"order_id": "O-A101", "case_type": "RETURN_REFUND", "reason": "再次申请"}
    )
    assert response.json()["code"] == "ACTIVE_CASE_EXISTS"
    eligibility = driver.ok("/orders/O-A101/eligibility", {"case_type": "RETURN_REFUND"})
    assert eligibility["reason_codes"] == ["ACTIVE_CASE_EXISTS"]
    cancelled = driver.ok(f"/cases/{case['id']}/cancel", {"expected_version": case["version"]})
    assert cancelled["status"] == "CANCELLED"
    assert driver.draft()["id"] != case["id"]


def test_reject_releases_activity_without_payment(driver):
    case, _ = driver.submitted(driver.draft())
    rejected = driver.ok(
        f"/cases/{case['id']}/review",
        {
            "expected_version": case["version"],
            "decision": "REJECT",
            "reason": "人工拒绝",
            "return_required": False,
        },
        "E-A2",
    )
    assert rejected["status"] == "REJECTED"
    assert driver.draft()["status"] == "DRAFT"
    assert counts(driver.factory, RefundJob, RefundTransaction) == [0, 0]


@pytest.mark.parametrize(
    "fields",
    [
        {"tenant_id": "TENANT-B"},
        {"requested_amount_fen": 1},
        {"now": "2026-10-01"},
        {"reviewer_id": "E-A2"},
        {"case_type": "UNKNOWN"},
        {"reason": ""},
        {"evidence_refs": ["https://example.com"]},
    ],
)
def test_untrusted_or_invalid_draft_parameters(driver, fields):
    body = {"order_id": "O-A101", "case_type": "RETURN_REFUND", "reason": "退货", **fields}
    response = driver.request("/cases/drafts", body)
    assert response.status_code == 422 and response.json()["data"] == {}
    assert counts(driver.factory, AfterSalesCase) == [0]


def test_missing_key_and_forged_confirmation_digest(driver):
    response = driver.client.post(
        "/api/v1/cases/drafts",
        json={"order_id": "O-A101", "case_type": "RETURN_REFUND", "reason": "退货"},
        headers=driver.headers("C-A1"),
    )
    assert response.status_code == 422
    summary = driver.summary(driver.draft())
    response = driver.request(
        f"/confirmations/{summary['confirmation_id']}/confirm", {"payload_digest": "0" * 64}
    )
    assert response.json()["code"] == "VERSION_CONFLICT"


def test_review_revalidates_order_and_rules(driver):
    case, _ = driver.submitted(driver.draft())
    with driver.factory() as session, session.begin():
        session.get(Order, case["order_id"]).version += 1
    response = driver.request(
        f"/cases/{case['id']}/review",
        {
            "expected_version": case["version"],
            "decision": "APPROVE",
            "return_required": True,
            "reason": "审核",
        },
        "E-A2",
    )
    assert response.json()["code"] == "VERSION_CONFLICT"
    assert counts(driver.factory, ReviewDecision, RefundJob) == [0, 0]


@pytest.mark.parametrize("fault", ["timeout_before", "timeout_after", "unavailable"])
def test_unknown_timeout_query_then_recover_same_operation(driver, fault):
    case = driver.ready(damage=True)
    assert (
        RefundWorker(driver.factory, SimulatedProvider(driver.factory, fault=fault)).run_once()[
            "status"
        ]
        == "REFUND_PENDING"
    )
    data = driver.get(f"/cases/{case['id']}/refund").json()["data"]
    assert data["funds_state"] == "UNKNOWN" and data["transaction"] is None
    with driver.factory() as session:
        key = session.scalar(select(RefundJob.operation_key))
        assert session.get(Order, case["order_id"]).refunded_amount_fen == 0
    due(driver.factory)
    assert RefundWorker(driver.factory).run_once()["status"] == "REFUNDED"
    with driver.factory() as session:
        assert session.scalar(select(RefundTransaction.operation_key)) == key
    assert counts(driver.factory, RefundTransaction, SimulatedProviderOperation) == [1, 1]


def test_provider_success_local_crash_and_worker_restart(driver):
    case = driver.ready(damage=True)
    with pytest.raises(SimulatedCrash):
        RefundWorker(driver.factory).run_once(crash_after_provider=True)
    assert counts(driver.factory, RefundTransaction, SimulatedProviderOperation) == [0, 1]
    assert driver.get(f"/cases/{case['id']}/refund").json()["data"]["funds_state"] == "UNKNOWN"
    due(driver.factory)

    class QueryOnly(SimulatedProvider):
        def submit(self, operation_key, amount_fen):
            pytest.fail(
                "A persisted successful provider operation must be queried, not resubmitted"
            )

    assert (
        RefundWorker(driver.factory, QueryOnly(driver.factory)).run_once()["status"] == "REFUNDED"
    )
    assert counts(driver.factory, RefundTransaction, SimulatedProviderOperation) == [1, 1]


def test_failed_retries_manual_and_authorized_reconcile(driver):
    case = driver.ready(damage=True)
    worker = RefundWorker(driver.factory, SimulatedProvider(driver.factory, fault="unavailable"))
    for attempt in range(3):
        status = worker.run_once()["status"]
        assert status == ("MANUAL_INTERVENTION" if attempt == 2 else "REFUND_PENDING")
        due(driver.factory)
    case = driver.get(f"/cases/{case['id']}").json()["data"]
    assert (
        driver.request(
            "/cases/drafts",
            {
                "order_id": case["order_id"],
                "case_type": "DAMAGE_REFUND",
                "reason": "重新退",
                "evidence_refs": ["EVIDENCE-A1"],
            },
        ).json()["code"]
        == "ACTIVE_CASE_EXISTS"
    )
    assert (
        driver.request(
            f"/cases/{case['id']}/refund-reconcile", {"expected_version": case["version"]}
        ).status_code
        == 403
    )
    with driver.factory() as session:
        original_key = session.scalar(select(RefundJob.operation_key))
    restored = driver.ok(
        f"/cases/{case['id']}/refund-reconcile", {"expected_version": case["version"]}, "E-A2"
    )
    assert restored["status"] == "REFUND_PENDING"
    assert RefundWorker(driver.factory).run_once()["status"] == "REFUNDED"
    with driver.factory() as session:
        assert session.scalar(select(RefundTransaction.operation_key)) == original_key


@pytest.mark.parametrize(
    "change",
    [
        "balance",
        "order_version",
        "case_version",
        "snapshot",
        "review",
        "amount",
        "key",
        "receipt",
        "order_status",
        "category",
    ],
)
def test_worker_guards_prevent_payment(driver, change):
    case = driver.ready()
    with driver.factory() as session, session.begin():
        row = session.get(AfterSalesCase, case["id"])
        order = session.get(Order, row.order_id)
        job = session.scalar(select(RefundJob))
        if change == "balance":
            order.refunded_amount_fen = 100
        elif change == "order_version":
            order.version += 1
        elif change == "case_version":
            row.version += 1
        elif change == "snapshot":
            row.rules_snapshot = {**row.rules_snapshot, "all_refunds_require_review": False}
        elif change == "review":
            session.scalar(select(ReviewDecision)).decision = "REJECT"
        elif change == "amount":
            job.amount_fen += 1
        elif change == "key":
            job.operation_key = "FORGED-KEY"
        elif change == "order_status":
            order.status = "IN_TRANSIT"
        elif change == "category":
            order.product_category = "CUSTOM"
        else:
            row.received_at = None
    assert RefundWorker(driver.factory).run_once()["status"] == "GUARD_BLOCKED_OR_STALE"
    assert driver.get(f"/cases/{case['id']}").json()["data"]["status"] == "MANUAL_INTERVENTION"
    assert counts(driver.factory, RefundTransaction, SimulatedProviderOperation) == [0, 0]


def test_provider_wrong_amount_fail_closed(driver):
    case = driver.ready(damage=True)

    class WrongAmount(SimulatedProvider):
        def submit(self, operation_key, amount_fen):
            return ProviderResult(
                operation_key, "SIM-BAD", amount_fen + 1, "SUCCEEDED", "SIM-BAD-REF"
            )

    assert (
        RefundWorker(driver.factory, WrongAmount(driver.factory)).run_once()["status"]
        == "MANUAL_INTERVENTION"
    )
    with driver.factory() as session:
        assert session.get(Order, case["order_id"]).refunded_amount_fen == 0
    assert counts(driver.factory, RefundTransaction) == [0]


def test_provider_idempotency_amount_conflict(driver):
    provider = SimulatedProvider(driver.factory)
    first = provider.submit("SIM-TEST-KEY", 100)
    assert provider.submit("SIM-TEST-KEY", 100) == first
    with pytest.raises(ProviderFailure, match="PROVIDER_AMOUNT_CONFLICT"):
        provider.submit("SIM-TEST-KEY", 101)
    assert counts(driver.factory, SimulatedProviderOperation) == [1]


def test_expired_lease_old_worker_cannot_bookkeep(driver):
    driver.ready(damage=True)
    old = RefundWorker(driver.factory)
    job_id, old_token = old.claim()
    key, amount, _ = old.prepare(job_id, old_token)
    result = old.provider.submit(key, amount)
    due(driver.factory)
    new = RefundWorker(driver.factory)
    assert new.run_once()["status"] == "REFUNDED"
    assert old.finish(job_id, old_token, result) == "STALE_LEASE"
    assert counts(driver.factory, RefundTransaction, SimulatedProviderOperation) == [1, 1]


def test_live_lease_not_stolen_or_reconciled(driver):
    case = driver.ready(damage=True)
    worker = RefundWorker(driver.factory)
    job, token = worker.claim()
    worker.prepare(job, token)
    case = driver.get(f"/cases/{case['id']}").json()["data"]
    assert RefundWorker(driver.factory).run_once()["status"] == "IDLE"
    response = driver.request(
        f"/cases/{case['id']}/refund-reconcile", {"expected_version": case["version"]}, "E-A2"
    )
    assert response.status_code == 409


def test_two_workers_concurrent_only_one_result(driver):
    driver.ready(damage=True)
    barrier = Barrier(2)

    def execute():
        barrier.wait(timeout=10)
        return RefundWorker(driver.factory).run_once()["status"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: execute(), range(2)))
    assert sorted(results) == ["IDLE", "REFUNDED"]
    assert counts(driver.factory, RefundTransaction, SimulatedProviderOperation) == [1, 1]


@pytest.mark.parametrize("same_key", [True, False])
def test_concurrent_drafts_idempotency_and_active_unique(driver, same_key):
    barrier = Barrier(2)
    args = DraftInput(order_id="O-A101", case_type="RETURN_REFUND", reason="并发申请")

    def execute(i):
        barrier.wait(timeout=10)
        with driver.factory() as session:
            try:
                result = WriteService(session, "C-A1", FixedClock(NOW), f"trace-{i}").draft(
                    args, "concurrent-key" if same_key else f"concurrent-key-{i}"
                )
                session.commit()
                return "OK", result["id"]
            except BusinessError as exc:
                session.rollback()
                return exc.code, None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(execute, range(2)))
    if same_key:
        assert results[0] == results[1] and results[0][0] == "OK"
    else:
        assert sorted(r[0] for r in results) == ["ACTIVE_CASE_EXISTS", "OK"]
    assert counts(driver.factory, AfterSalesCase, IdempotencyRecord) == [1, 1]


def test_concurrent_submit_consumes_one_confirmation(driver):
    case, conf = driver.confirmed(driver.draft())
    barrier = Barrier(2)

    def execute(i):
        barrier.wait(timeout=10)
        with driver.factory() as session:
            try:
                data = WriteService(session, "C-A1", FixedClock(NOW), f"trace-{i}").submit(
                    case["id"],
                    VersionInput(expected_version=case["version"]),
                    f"submit-concurrent-{i}",
                )
                session.commit()
                return data["status"]
            except BusinessError as exc:
                session.rollback()
                return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(execute, range(2)))
    assert sorted(results) == ["PENDING_REVIEW", "VERSION_CONFLICT"]
    with driver.factory() as session:
        assert session.get(Confirmation, conf["confirmation_id"]).consumed_at == NOW


def test_database_unique_activity_and_money_constraints(driver):
    case = driver.draft()
    with driver.factory() as session:
        original = session.get(AfterSalesCase, case["id"])
        values = {
            column.name: getattr(original, column.name)
            for column in AfterSalesCase.__table__.columns
        }
        values["id"] = "CASE-DUPLICATE"
        session.add(AfterSalesCase(**values))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
        session.get(Order, case["order_id"]).refunded_amount_fen = 9999999
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
    assert counts(driver.factory, AfterSalesCase) == [1]


def test_audit_redacted_and_transactional(driver):
    case = driver.ready(damage=True)
    RefundWorker(driver.factory).run_once()
    with driver.factory() as session:
        events = session.scalars(select(AuditEvent)).all()
        assert {e.action for e in events} >= {
            "CREATE_DRAFT",
            "CUSTOMER_CONFIRM",
            "SUBMIT_CASE",
            "REVIEW_CASE",
            "REFUND_SUCCEEDED",
        }
        for event in events:
            assert event.trace_id and event.timestamp.tzinfo
            assert not set(event.summary).intersection(
                {"reason", "evidence_refs", "token", "authorization"}
            )
        assert session.get(AfterSalesCase, case["id"]).status == "REFUNDED"


def test_migration_roundtrip_preserves_m1_and_new_seed_idempotent(database):
    settings, _, factory = database
    config = Config(str(ROOT / "alembic.ini"))
    with factory() as session:
        before = session.scalar(select(func.count()).select_from(Order))
    command.downgrade(config, "0002_m1")
    command.upgrade(config, "head")
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Order)) == before
        assert session.scalar(text("SELECT version_num FROM alembic_version")) == "0005_m4"
        assert counts(factory, RefundJob, AfterSalesCase) == [0, 0]


@pytest.mark.parametrize("order,allowed", [("O-A106", True), ("O-A104", False), ("O-A112", False)])
def test_damage_special_category_and_contradictions(driver, order, allowed):
    response = driver.request(
        "/cases/drafts",
        {
            "order_id": order,
            "case_type": "DAMAGE_REFUND",
            "reason": "模拟损坏，需人工审核",
            "evidence_refs": ["EVIDENCE-A1"],
        },
    )
    assert response.status_code == (201 if allowed else 409)
    if allowed:
        assert response.json()["data"]["status"] == "DRAFT"
    else:
        assert response.json()["data"]["next_action"] == "CREATE_SUPPORT_TICKET"
    assert counts(driver.factory, RefundJob) == [0]


def test_tenant_b_independent_write_and_approval(driver):
    a = driver.draft(key="same-two-tenant-key")
    b = driver.draft(order="O-B101", actor="C-B1", key="same-two-tenant-key")
    assert a["id"] != b["id"] and b["policy_version"] == "POLICY-B-2026-10-v1"
    summary = driver.ok(
        f"/cases/{b['id']}/confirmation", {"expected_version": b["version"]}, "C-B1"
    )
    driver.ok(
        f"/confirmations/{summary['confirmation_id']}/confirm",
        {"payload_digest": summary["payload_digest"]},
        "C-B1",
    )
    b = driver.ok(
        f"/cases/{b['id']}/submit", {"expected_version": summary["summary"]["version"]}, "C-B1"
    )
    body = {
        "expected_version": b["version"],
        "decision": "APPROVE",
        "reason": "B租户审核",
        "return_required": True,
    }
    assert driver.request(f"/cases/{b['id']}/review", body, "E-A2").status_code == 404
    assert driver.ok(f"/cases/{b['id']}/review", body, "E-B2")["status"] == "AWAITING_RETURN"
    assert driver.get(f"/cases/{a['id']}", "C-B1").status_code == 404
    assert counts(driver.factory, AfterSalesCase, ReviewDecision, RefundJob) == [2, 1, 0]


def test_business_window_rechecked_at_approval(driver, database):
    case, _ = driver.submitted(driver.draft())
    with TestClient(
        create_app(database[0], clock=FixedClock(NOW + timedelta(days=6))),
        client=("127.0.0.1", 52001),
    ) as client:
        response = client.post(
            f"/api/v1/cases/{case['id']}/review",
            json={
                "expected_version": case["version"],
                "decision": "APPROVE",
                "reason": "审核",
                "return_required": True,
            },
            headers=driver.headers("E-A2", "late-approval-key"),
        )
    assert response.status_code == 409 and response.json()["code"] == "MANUAL_REVIEW_REQUIRED"
    assert counts(driver.factory, ReviewDecision, RefundJob) == [0, 0]


def test_execution_uses_approved_policy_snapshot(driver):
    driver.ready(damage=True)
    with driver.factory() as session, session.begin():
        session.get(Policy, "POLICY-A-2026-10-v1").status = "DRAFT"
    assert RefundWorker(driver.factory).run_once()["status"] == "REFUNDED"


def test_provider_call_outside_order_transaction(driver):
    case = driver.ready(damage=True)

    class LockProbe(SimulatedProvider):
        def submit(self, operation_key, amount_fen):
            with self.sessions() as session, session.begin():
                assert (
                    session.scalar(
                        select(Order)
                        .where(Order.id == case["order_id"])
                        .with_for_update(nowait=True)
                    )
                    is not None
                )
            return super().submit(operation_key, amount_fen)

    assert (
        RefundWorker(driver.factory, LockProbe(driver.factory)).run_once()["status"] == "REFUNDED"
    )


def test_local_bookkeeping_database_failure_rolls_back_and_recovers(driver):
    case = driver.ready(damage=True)

    def inject_constraint_failure(session, flush_context, instances):
        for row in session.new:
            if isinstance(row, RefundTransaction):
                row.status = "INVALID"

    event.listen(Session, "before_flush", inject_constraint_failure)
    try:
        with pytest.raises(IntegrityError):
            RefundWorker(driver.factory).run_once()
    finally:
        event.remove(Session, "before_flush", inject_constraint_failure)
    with driver.factory() as session:
        assert session.get(Order, case["order_id"]).refunded_amount_fen == 0
        assert session.get(AfterSalesCase, case["id"]).status == "REFUND_PENDING"
    assert counts(driver.factory, RefundTransaction, SimulatedProviderOperation) == [0, 1]
    due(driver.factory)
    assert RefundWorker(driver.factory).run_once()["status"] == "REFUNDED"
    assert counts(driver.factory, RefundTransaction, SimulatedProviderOperation) == [1, 1]


def test_expired_workers_simultaneous_provider_submits_deduplicate(driver):
    driver.ready(damage=True)
    old, new = RefundWorker(driver.factory), RefundWorker(driver.factory)
    job_id, token_old = old.claim()
    key, amount, _ = old.prepare(job_id, token_old)
    due(driver.factory)
    job_new, token_new = new.claim()
    assert job_new == job_id
    assert new.prepare(job_new, token_new)[:2] == (key, amount)
    barrier = Barrier(2)

    def pay(worker):
        barrier.wait(timeout=10)
        return worker.provider.submit(key, amount)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(pay, [old, new]))
    assert results[0] == results[1]
    assert new.finish(job_id, token_new, results[1]) == "REFUNDED"
    assert old.finish(job_id, token_old, results[0]) == "STALE_LEASE"
    assert counts(driver.factory, RefundTransaction, SimulatedProviderOperation) == [1, 1]


@pytest.mark.parametrize(
    "endpoint,fields",
    [
        ("submit", {"confirmed_by": "C-A1"}),
        ("review", {"amount_fen": 1}),
        ("refund-reconcile", {"status": "REFUNDED"}),
        ("return-received", {"received_at": "2026-01-01"}),
    ],
)
def test_critical_write_parameters_cannot_be_forged(driver, endpoint, fields):
    case, _ = driver.submitted(driver.draft())
    body = {"expected_version": case["version"], **fields}
    if endpoint == "review":
        body.update(decision="APPROVE", reason="审核", return_required=True)
    response = driver.request(f"/cases/{case['id']}/{endpoint}", body, "E-A2")
    assert response.status_code == 422 and response.json()["data"] == {}
    assert counts(driver.factory, ReviewDecision, RefundJob) == [0, 0]


def test_submitted_case_cannot_edit_cancel_or_skip_review(driver):
    case, _ = driver.submitted(driver.draft())
    for endpoint in ["cancel", "refund-reconcile"]:
        response = driver.request(
            f"/cases/{case['id']}/{endpoint}",
            {"expected_version": case["version"]},
            "E-A2" if endpoint == "refund-reconcile" else "C-A1",
        )
        assert response.status_code == 409
    response = driver.request(
        f"/cases/{case['id']}/draft",
        {"expected_version": case["version"], "reason": "改原因"},
        method="PATCH",
    )
    assert response.status_code == 409
    response = driver.request(
        f"/cases/{case['id']}/return-received", {"expected_version": case["version"]}, "E-A3"
    )
    assert response.status_code == 409
    assert counts(driver.factory, RefundJob) == [0]


def test_denied_write_audit_without_business_mutation(driver):
    case = driver.draft()
    response = driver.request(
        f"/cases/{case['id']}/review",
        {
            "expected_version": 1,
            "decision": "APPROVE",
            "reason": "不该记录的私人正文",
            "return_required": True,
        },
    )
    assert response.status_code == 403
    with driver.factory() as session:
        row = session.scalar(select(AuditEvent).where(AuditEvent.result == "FORBIDDEN"))
        assert row.actor_id == "C-A1" and row.summary == {"method": "POST"}
        assert session.get(AfterSalesCase, case["id"]).status == "DRAFT"


def test_concurrent_approvals_one_decision(driver):
    case, _ = driver.submitted(driver.draft())
    from app.write_schemas import ReviewInput

    args = ReviewInput(
        expected_version=case["version"],
        decision="APPROVE",
        reason="并发审核",
        return_required=True,
    )
    barrier = Barrier(2)

    def execute(i):
        barrier.wait(timeout=10)
        with driver.factory() as session:
            try:
                data = WriteService(session, "E-A2", FixedClock(NOW), f"review-{i}").review(
                    case["id"], args, f"concurrent-review-{i}"
                )
                session.commit()
                return data["status"]
            except BusinessError as exc:
                session.rollback()
                return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(execute, range(2)))
    assert sorted(results) == ["AWAITING_RETURN", "VERSION_CONFLICT"]
    assert counts(driver.factory, ReviewDecision) == [1]


def test_confirmation_uses_clock_after_acquiring_business_locks(driver):
    summary = driver.summary(driver.draft())
    from app.write_schemas import ConfirmInput

    class AdvancingClock:
        calls = 0

        def now(self, session):
            self.calls += 1
            return NOW if self.calls == 1 else NOW + timedelta(seconds=900)

    with driver.factory() as session:
        service = WriteService(session, "C-A1", AdvancingClock(), "clock-after-lock")
        with pytest.raises(BusinessError, match="CONFIRMATION_EXPIRED"):
            service.confirm(
                summary["confirmation_id"],
                ConfirmInput(payload_digest=summary["payload_digest"]),
                "after-lock-clock-key",
            )
        session.rollback()
    with driver.factory() as session:
        assert session.get(Confirmation, summary["confirmation_id"]).confirmed_at is None
