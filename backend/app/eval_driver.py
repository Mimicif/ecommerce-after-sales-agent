"""Evaluation-only ASGI HTTP driver, isolated real PostgreSQL schemas and trusted faults."""

import copy
import os
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import select, text
from sqlalchemy.engine import make_url

from app.clock import utc
from app.config import ROOT, Settings
from app.db import make_engine, make_session_factory
from app.errors import BusinessError
from app.models import LogisticsEvent, Order, Policy
from app.policy import content_digest
from app.refunds import RefundWorker, SimulatedCrash, SimulatedProvider
from app.retrieval import rebuild_index
from app.seed import import_seed, parse_time


class EvalClock:
    def __init__(self, value):
        self.value = utc(value)

    def now(self, session):
        return self.value


@contextmanager
def isolated_database():
    base = Settings()
    url = make_url(base.database_url.get_secret_value()).set(database="after_sales_test")
    schema = "after_sales_eval_" + uuid4().hex
    saved = {key: os.environ.get(key) for key in ["DATABASE_URL", "DATABASE_SCHEMA", "DEV_MODE"]}
    os.environ.update(
        DATABASE_URL=url.render_as_string(hide_password=False),
        DATABASE_SCHEMA="public",
        DEV_MODE="true",
    )
    admin = make_engine(Settings())
    engine = None
    created = False
    try:
        with admin.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            created = True
        os.environ["DATABASE_SCHEMA"] = schema
        command.upgrade(Config(str(ROOT / "alembic.ini")), "head")
        settings = Settings()
        engine = make_engine(settings)
        factory = make_session_factory(engine)
        with factory() as session, session.begin():
            import_seed(session)
        yield settings, factory
    finally:
        if engine:
            engine.dispose()
        if created:
            with admin.begin() as connection:
                # Only this exact UUID schema, generated and created above, can be dropped.
                connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


class ToolFault:
    def __init__(self, faults):
        self.remaining = 0
        for fault in faults:
            if fault["target"] == "get_logistics":
                if fault["mode"] != "timeout_before_response":
                    raise ValueError("Unsupported logistics fault")
                self.remaining += fault["occurrences"]

    def before(self, name):
        if name == "get_logistics" and self.remaining:
            self.remaining -= 1
            raise BusinessError("PROVIDER_TIMEOUT", 503, retryable=True)


class LoopContractModel:
    provider, model_id = "FAULT_CONTRACT", "controlled-read-loop"

    def complete(self, messages, tools, timeout):
        return {
            "model": self.model_id,
            "usage": {},
            "content": "",
            "calls": [
                {"id": "loop_call", "name": "get_order", "arguments": {"order_id": "O-A101"}}
            ],
        }


class Driver:
    def __init__(self, client, factory, clock, actor="C-A1"):
        self.client, self.factory, self.clock, self.actor = client, factory, clock, actor
        self.identities, self.seq, self.trace, self.extra = {}, 0, [], {}

    def headers(self, actor, key=None):
        if actor not in self.identities:
            response = self.client.post("/api/v1/dev/sessions", json={"user_id": actor})
            if response.status_code != 201:
                raise ValueError("Evaluation identity unavailable")
            self.identities[actor] = {
                "Authorization": "Bearer " + response.json()["data"]["access_token"]
            }
        return {**self.identities[actor], **({"Idempotency-Key": key} if key else {})}

    def request(self, path, body=None, *, actor=None, method="POST", key=None):
        self.seq += 1
        response = self.client.request(
            method,
            "/api/v1" + path,
            json=body,
            headers=self.headers(actor or self.actor, key or f"eval-request-{self.seq:04d}"),
        )
        payload = response.json()
        self.trace.append(
            {
                "path": path,
                "actor": actor or self.actor,
                "http_status": response.status_code,
                "code": payload["code"],
                "data": payload["data"],
            }
        )
        return response

    def ok(self, path, body=None, **kwargs):
        response = self.request(path, body, **kwargs)
        if not response.is_success:
            raise BusinessError(response.json()["code"], response.status_code)
        return response.json()["data"]

    def get(self, path, actor=None):
        return self.ok(path, actor=actor, method="GET")

    def draft(self, args):
        return self.ok(
            "/cases/drafts",
            {
                "order_id": args.get("order_id", "O-A101"),
                "case_type": args.get("case_type", "RETURN_REFUND"),
                "reason": args.get("reason", "客户明确申请，商品尺寸不合适"),
                "evidence_refs": args.get("evidence_refs", []),
            },
        )

    def summary(self, case, owner=None):
        return self.ok(
            f"/cases/{case['id']}/confirmation", {"expected_version": case["version"]}, actor=owner
        )

    def confirmed(self, args):
        case = self.draft(args)
        summary = self.summary(case, args.get("owner"))
        self.ok(
            f"/confirmations/{summary['confirmation_id']}/confirm",
            {"payload_digest": summary["payload_digest"]},
            actor=args.get("owner"),
        )
        case = self.get(f"/cases/{case['id']}")
        return case, summary

    def submitted(self, args):
        case, _ = self.confirmed(args)
        return self.ok(f"/cases/{case['id']}/submit", {"expected_version": case["version"]})

    def review(self, case, args, *, reject=False, key=None):
        return self.request(
            f"/cases/{case['id']}/review",
            {
                "expected_version": case["version"],
                "decision": "REJECT" if reject else "APPROVE",
                "return_required": args.get("return_required", True),
                "reason": args.get("reason", "独立人工审核演示"),
            },
            actor=args.get("reviewer", "E-A2"),
            key=key,
        )

    def approved(self, args, receive=False):
        case = self.submitted(args)
        response = self.review(case, args)
        if not response.is_success:
            raise BusinessError(response.json()["code"], response.status_code)
        case = response.json()["data"]
        if receive:
            case = self.ok(
                f"/cases/{case['id']}/return-received",
                {"expected_version": case["version"]},
                actor=args.get("warehouse_actor", "E-A3"),
            )
        return case

    def setup(self, steps):
        for step in steps:
            action = step["action"]
            if action == "create_rejected_case":
                case = self.submitted(step)
                response = self.review(case, step, reject=True)
                if not response.is_success:
                    raise ValueError("Rejected-case setup failed")
            elif action == "create_confirmed_submitted_case":
                self.submitted(step)
            elif action == "create_approved_standard_case":
                self.approved(step, receive=step.get("return_received", False))
            else:
                raise ValueError("Unknown setup action: " + action)

    def api_action(self, args, faults):
        action, order = args["action"], args.get("order_id", "O-A101")
        if action == "get_order":
            return self.request(f"/orders/{order}", method="GET")
        if action == "get_logistics":
            return self.request(f"/orders/{order}/logistics", method="GET")
        if action == "search_policy":
            return self.request(
                f"/orders/{order}/policy?intent={args['intent']}&query={args.get('query', '')}",
                method="GET",
            )
        if action == "check_eligibility":
            return self.request(f"/orders/{order}/eligibility", {"case_type": args["case_type"]})
        if action == "create_draft":
            return self.request(
                "/cases/drafts",
                {
                    "order_id": order,
                    "case_type": args["case_type"],
                    "reason": "明确申请损坏处理",
                    "evidence_refs": args.get("evidence_refs", []),
                },
            )
        if action in {"confirm_and_submit", "support_draft_owner_confirm_submit"}:
            self.submitted(args)
        elif action == "self_review_case":
            return self.review(self.submitted(args), args)
        elif action == "review_case":
            with self.factory() as session:
                from app.models import AfterSalesCase

                case_id = session.scalar(
                    select(AfterSalesCase.id).where(AfterSalesCase.order_id == order)
                )
            return self.review(self.get(f"/cases/{case_id}"), args)
        elif action in {
            "submit_without_confirmation",
            "confirm_as_support",
            "confirm_wrong_digest",
        }:
            case = self.draft(args)
            if action == "submit_without_confirmation":
                # Generate a WAITING summary, but deliberately never confirm it.
                self.summary(case)
                case = self.get(f"/cases/{case['id']}")
                return self.request(
                    f"/cases/{case['id']}/submit", {"expected_version": case["version"]}
                )
            summary = self.summary(case)
            return self.request(
                f"/confirmations/{summary['confirmation_id']}/confirm",
                {
                    "payload_digest": "0" * 64
                    if action == "confirm_wrong_digest"
                    else summary["payload_digest"]
                },
                actor=args.get("confirmation_actor"),
            )
        elif action in {
            "confirm_then_submit",
            "confirm_then_edit_then_submit_old_confirmation",
            "confirm_then_order_change",
        }:
            case, _ = self.confirmed(args)
            if action == "confirm_then_submit":
                self.clock.value += timedelta(seconds=args["advance_clock_seconds_after_confirm"])
            elif action == "confirm_then_edit_then_submit_old_confirmation":
                self.ok(
                    f"/cases/{case['id']}/draft",
                    {
                        "expected_version": case["version"],
                        "reason": args["change"]["reason"],
                        "evidence_refs": [],
                    },
                    method="PATCH",
                )
            else:
                with self.factory() as session, session.begin():
                    session.get(Order, order).version += 1
            return self.request(
                f"/cases/{case['id']}/submit", {"expected_version": case["version"]}
            )
        elif action in {"concurrent_submit", "reuse_idempotency_key_with_changed_body"}:
            from concurrent.futures import ThreadPoolExecutor

            case, _ = self.confirmed(args)
            self.headers(self.actor)
            body, path, key = (
                {"expected_version": case["version"]},
                f"/cases/{case['id']}/submit",
                args["idempotency_key"],
            )
            if action == "concurrent_submit":
                with ThreadPoolExecutor(max_workers=args["requests"]) as pool:
                    responses = list(
                        pool.map(
                            lambda _: self.request(path, body, key=key), range(args["requests"])
                        )
                    )
                self.extra["returned_case_ids_equal"] = (
                    all(r.is_success for r in responses)
                    and len({r.json()["data"]["id"] for r in responses}) == 1
                )
            else:
                self.ok(path, body, key=key)
                return self.request(path, {"expected_version": case["version"] + 1}, key=key)
        elif action == "run_refund_worker":
            self.extra["worker"] = RefundWorker(self.factory).run_once()
        elif action in {
            "standard_return_full_flow",
            "damage_full_flow",
            "standard_return_full_flow_with_worker_restart",
            "standard_return_with_duplicate_review_and_worker",
        }:
            args = {**args}
            if action == "damage_full_flow":
                args["case_type"] = "DAMAGE_REFUND"
            case = self.approved(args, receive=action != "damage_full_flow")
            fault_mode = "success"
            crash = False
            for fault in faults:
                if fault["target"] == "mock_payment":
                    fault_mode = {
                        "commit_success_then_response_timeout": "timeout_after",
                        "timeout_before_submit": "timeout_before",
                    }[fault["mode"]]
                elif fault["target"] == "refund_worker":
                    if fault["mode"] != "crash_after_provider_success_before_local_commit":
                        raise ValueError("Unknown refund worker fault")
                    crash = True
                else:
                    raise ValueError("Unknown payment fault target")
            now = datetime.now(UTC)
            w = RefundWorker(
                self.factory, SimulatedProvider(self.factory, fault=fault_mode), now=lambda: now
            )
            try:
                self.extra["first_worker"] = w.run_once(crash_after_provider=crash)
            except SimulatedCrash:
                self.extra["simulated_crash"] = True
            if crash or fault_mode != "success":
                self.extra["unknown_before_recovery"] = self.get(f"/cases/{case['id']}/refund")
                now += timedelta(seconds=31)
                self.extra["recovery_worker"] = RefundWorker(
                    self.factory, now=lambda: now
                ).run_once()
            if action == "standard_return_with_duplicate_review_and_worker":
                # Repeat reads/worker, and retry review with the same stale version: no new effects.
                self.review(self.get(f"/cases/{case['id']}"), args)
                for _ in range(args.get("duplicate_count", 2)):
                    RefundWorker(self.factory, now=lambda: now).run_once()
        else:
            raise ValueError("Unknown scenario action: " + action)
        return None


def apply_overrides(factory, scenario):
    with factory() as session, session.begin():
        for change in scenario.get("order_overrides", []):
            row = session.get(Order, change["id"])
            for key, value in change.items():
                if key == "id":
                    continue
                if key not in {
                    "paid_amount_fen",
                    "refunded_amount_fen",
                    "delivered_at",
                    "version",
                    "product_category",
                    "status",
                }:
                    raise ValueError("Unknown order override")
                setattr(row, key, parse_time(value) if key == "delivered_at" else value)
        for change in scenario.get("logistics_overrides", []):
            rows = session.scalars(
                select(LogisticsEvent).where(LogisticsEvent.order_id == change["order_id"])
            ).all()
            for row in rows:
                row.occurred_at, row.status = parse_time(change["occurred_at"]), change["status"]
        for change in scenario.get("policy_overrides", []):
            row = session.get(Policy, change["id"])
            for key, value in change.items():
                if key not in {"id", "status"}:
                    raise ValueError("Unknown policy override")
                if key != "id":
                    setattr(row, key, value)
        for change in scenario.get("policy_copies", []):
            source = session.get(Policy, change["source"])
            values = {
                key: copy.deepcopy(getattr(source, key))
                for key in [
                    "tenant_id",
                    "status",
                    "effective_from",
                    "effective_to",
                    "rules",
                    "clauses",
                    "content_digest",
                ]
            }
            session.add(Policy(id=change["id"], **values))
        for append in scenario.get("policy_text_append", []):
            for policy in session.scalars(select(Policy)):
                clauses = copy.deepcopy(policy.clauses)
                for clause in clauses:
                    if clause["chunk_id"] == append["chunk_id"]:
                        clause["text"] += "\n" + append["text"]
                policy.clauses = clauses
                policy.content_digest = content_digest(policy.rules, clauses)
        session.flush()
        rebuild_index(session)
