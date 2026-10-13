"""Deterministic business writes. The caller commits only after the operation succeeds."""

import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import select, text

from app.clock import utc
from app.domain import assess_eligibility
from app.errors import BusinessError
from app.models import (
    TERMINAL_CASES,
    AfterSalesCase,
    AuditEvent,
    Confirmation,
    Evidence,
    IdempotencyRecord,
    Order,
    RefundJob,
    RefundTransaction,
    ReviewDecision,
    SupportTicket,
    User,
)
from app.policy import current_policy
from app.reads import ReadService


def identifier(prefix):
    return prefix + "-" + uuid4().hex.upper()


def payload_digest(payload):
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def advisory_lock(session, scope):
    lock = int.from_bytes(hashlib.sha256(scope.encode()).digest()[:8], "big", signed=True)
    session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock})


def audit(session, actor_id, tenant_id, action, resource_id, trace_id, summary, result="OK"):
    session.add(
        AuditEvent(
            id=identifier("AUDIT"),
            actor_id=actor_id,
            tenant_id=tenant_id,
            action=action,
            resource_id=resource_id,
            result=result,
            timestamp=datetime.now(UTC),
            trace_id=trace_id,
            summary=summary,
        )
    )


def conflict(code="VERSION_CONFLICT", **data):
    raise BusinessError(code, 409, data=data)


class WriteService:
    def __init__(self, session, actor_id, clock, trace_id):
        self.session, self.clock, self.trace_id = session, clock, trace_id
        self.actor = session.get(User, actor_id)
        if self.actor is None:
            raise BusinessError("UNAUTHORIZED", 401)
        self.now = utc(clock.now(session))

    def role(self, *roles):
        if not set(roles).intersection(self.actor.roles):
            raise BusinessError("FORBIDDEN", 403)

    def order(self, order_id, *, lock=False):
        query = select(Order).where(Order.id == order_id, Order.tenant_id == self.actor.tenant_id)
        if "support" not in self.actor.roles:
            query = query.where(Order.customer_id == self.actor.customer_id)
        if lock:
            query = query.with_for_update().execution_options(populate_existing=True)
        order = self.session.scalar(query)
        if order is None:
            raise BusinessError("RESOURCE_NOT_FOUND", 404)
        if lock:
            self.now = utc(self.clock.now(self.session))
        return order

    def resource(self, model, resource_id):
        self.role("customer", "support", "reviewer", "warehouse")
        resource = self.session.scalar(
            select(model).where(model.id == resource_id, model.tenant_id == self.actor.tenant_id)
        )
        if resource is None:
            raise BusinessError("RESOURCE_NOT_FOUND", 404)
        order = self.session.get(Order, resource.order_id)
        if not set(self.actor.roles).intersection({"support", "reviewer", "warehouse"}):
            if order.customer_id != self.actor.customer_id:
                raise BusinessError("RESOURCE_NOT_FOUND", 404)
        return resource, order

    def case(self, case_id, *, lock=False, owner=False):
        case, order = self.resource(AfterSalesCase, case_id)
        if owner:
            self.role("customer")
            if self.actor.id != order.customer_id:
                raise BusinessError("RESOURCE_NOT_FOUND", 404)
        if lock:
            order = self.session.scalar(
                select(Order)
                .where(Order.id == order.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            case = self.session.scalar(
                select(AfterSalesCase)
                .where(AfterSalesCase.id == case_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            self.now = utc(self.clock.now(self.session))
        return case, order

    def mutate(self, operation, key, args, callback):
        if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9._:-]{8,128}", key):
            raise BusinessError("INVALID_ARGUMENT", 422)
        scope = (self.actor.tenant_id, self.actor.id, operation, key)
        advisory_lock(self.session, json.dumps(scope))
        digest = payload_digest(args.model_dump(mode="json"))
        stored = self.session.get(IdempotencyRecord, scope)
        if stored:
            if stored.request_digest != digest:
                conflict("IDEMPOTENCY_CONFLICT")
            return stored.response
        response = callback()
        self.session.flush()
        self.session.add(
            IdempotencyRecord(
                tenant_id=scope[0],
                actor_id=scope[1],
                operation=scope[2],
                client_key=scope[3],
                request_digest=digest,
                response=response,
                created_at=datetime.now(UTC),
            )
        )
        return response

    def log(self, action, case):
        audit(
            self.session,
            self.actor.id,
            case.tenant_id,
            action,
            case.id,
            self.trace_id,
            {
                "status": case.status,
                "version": case.version,
                "amount_fen": case.requested_amount_fen,
            },
        )

    @staticmethod
    def version(case, expected):
        if case.version != expected:
            conflict()

    @staticmethod
    def state(case, *states):
        if case.status not in states:
            conflict("INVALID_STATE_TRANSITION")

    def evidence(self, order, case_type, refs):
        if case_type == "DAMAGE_REFUND" and not refs:
            raise BusinessError(
                "INVALID_ARGUMENT", 422, data={"reason_codes": ["EVIDENCE_REQUIRED"]}
            )
        if refs:
            owned = set(
                self.session.scalars(
                    select(Evidence.id).where(
                        Evidence.id.in_(refs),
                        Evidence.tenant_id == order.tenant_id,
                        Evidence.owner_id == order.customer_id,
                    )
                ).all()
            )
            if owned != set(refs):
                raise BusinessError("RESOURCE_NOT_FOUND", 404)

    def calculate(self, order, case_type, refs):
        self.evidence(order, case_type, refs)
        policy, rules, _ = current_policy(self.session, order.tenant_id, case_type, self.now)
        view = assess_eligibility(
            ReadService.order_view(order), case_type, rules, policy.id, self.now
        )
        if case_type == "DAMAGE_REFUND":
            allowed = (
                order.status == "DELIVERED"
                and order.delivered_at is not None
                and order.delivered_at <= self.now
                and order.paid_amount_fen > 0
                and order.refunded_amount_fen == 0
            )
        else:
            allowed = view.eligibility == "eligible"
        if not allowed:
            conflict(
                "MANUAL_REVIEW_REQUIRED",
                reason_codes=view.reason_codes,
                next_action="CREATE_SUPPORT_TICKET",
            )
        return policy, rules, view.refundable_amount_fen

    def fresh(self, case, order):
        self.balance(case, order)
        policy, rules, amount = self.calculate(order, case.case_type, case.evidence_refs)
        if (
            case.order_version != order.version
            or case.requested_amount_fen != amount
            or case.policy_version != policy.id
            or case.policy_digest != policy.content_digest
        ):
            conflict(next_action="REGENERATE_CONFIRMATION")
        return policy, rules

    @staticmethod
    def view(case):
        return {
            "id": case.id,
            "order_id": case.order_id,
            "case_type": case.case_type,
            "status": case.status,
            "reason": case.reason,
            "evidence_refs": case.evidence_refs,
            "requested_amount_fen": case.requested_amount_fen,
            "policy_version": case.policy_version,
            "version": case.version,
            "order_version": case.order_version,
            "review_required": True,
            "simulated": True,
        }

    @staticmethod
    def summary(case):
        return {
            **WriteService.view(case),
            "policy_digest": case.policy_digest,
            "notice": "客户确认仅提交申请；退款须人工审核，普通退货须仓库收货。",
        }

    def get_case(self, case_id):
        return self.view(self.case(case_id)[0])

    def draft(self, args, key):
        self.role("customer", "support")
        self.order(args.order_id)

        def perform():
            order = self.order(args.order_id, lock=True)
            active = self.session.scalar(
                select(AfterSalesCase.id).where(
                    AfterSalesCase.order_id == order.id,
                    AfterSalesCase.status.not_in(TERMINAL_CASES),
                )
            )
            if active:
                conflict("ACTIVE_CASE_EXISTS")
            policy, rules, amount = self.calculate(order, args.case_type, args.evidence_refs)
            case = AfterSalesCase(
                id=identifier("CASE"),
                tenant_id=order.tenant_id,
                order_id=order.id,
                case_type=args.case_type,
                status="DRAFT",
                reason=args.reason,
                evidence_refs=args.evidence_refs,
                requested_amount_fen=amount,
                policy_version=policy.id,
                policy_digest=policy.content_digest,
                rules_snapshot=rules.model_dump(),
                order_version=order.version,
                version=1,
                created_by=self.actor.id,
                created_at=self.now,
            )
            self.session.add(case)
            self.session.flush()
            self.log("CREATE_DRAFT", case)
            return self.view(case)

        return self.mutate("draft", key, args, perform)

    def edit(self, case_id, args, key):
        self.role("customer", "support")
        self.order(self.case(case_id)[0].order_id)

        def perform():
            case, order = self.case(case_id, lock=True)
            self.version(case, args.expected_version)
            self.state(case, "DRAFT", "WAITING_FOR_USER")
            self.evidence(order, case.case_type, args.evidence_refs)
            case.reason, case.evidence_refs = args.reason, args.evidence_refs
            case.status, case.version = "DRAFT", case.version + 1
            self.log("EDIT_DRAFT", case)
            return self.view(case)

        return self.mutate("edit:" + case_id, key, args, perform)

    def confirmation(self, case_id, args, key):
        self.case(case_id, owner=True)

        def perform():
            case, order = self.case(case_id, lock=True, owner=True)
            self.version(case, args.expected_version)
            self.state(case, "DRAFT", "WAITING_FOR_USER")
            policy, rules, amount = self.calculate(order, case.case_type, case.evidence_refs)
            case.policy_version, case.policy_digest = policy.id, policy.content_digest
            case.rules_snapshot, case.requested_amount_fen = rules.model_dump(), amount
            case.order_version = order.version
            case.status, case.version = "WAITING_FOR_USER", case.version + 1
            payload = self.summary(case)
            confirmation = Confirmation(
                id=identifier("CONF"),
                case_id=case.id,
                case_version=case.version,
                payload_digest=payload_digest(payload),
                payload=payload,
                expires_at=self.now + timedelta(seconds=900),
            )
            self.session.add(confirmation)
            self.log("CREATE_CONFIRMATION", case)
            return {
                "confirmation_id": confirmation.id,
                "payload_digest": confirmation.payload_digest,
                "expires_at": confirmation.expires_at.isoformat(),
                "summary": payload,
            }

        return self.mutate("confirmation:" + case_id, key, args, perform)

    def confirm(self, confirmation_id, args, key):
        self.role("customer")
        conf = self.session.get(Confirmation, confirmation_id)
        if conf is None:
            raise BusinessError("RESOURCE_NOT_FOUND", 404)
        self.case(conf.case_id, owner=True)

        def perform():
            case, order = self.case(conf.case_id, lock=True, owner=True)
            self.state(case, "WAITING_FOR_USER")
            self.version(case, conf.case_version)
            if self.now >= conf.expires_at:
                conflict("CONFIRMATION_EXPIRED")
            self.fresh(case, order)
            if args.payload_digest != conf.payload_digest or conf.payload_digest != payload_digest(
                self.summary(case)
            ):
                conflict()
            conf.confirmed_by, conf.confirmed_at = self.actor.id, self.now
            self.log("CUSTOMER_CONFIRM", case)
            return {
                "confirmation_id": conf.id,
                "case_id": case.id,
                "case_version": case.version,
                "confirmed": True,
                "simulated": True,
            }

        return self.mutate("confirm:" + confirmation_id, key, args, perform)

    def submit(self, case_id, args, key):
        self.role("customer", "support")
        self.order(self.case(case_id)[0].order_id)

        def perform():
            case, order = self.case(case_id, lock=True)
            self.version(case, args.expected_version)
            self.state(case, "WAITING_FOR_USER")
            conf = self.session.scalar(
                select(Confirmation)
                .where(Confirmation.case_id == case.id, Confirmation.case_version == case.version)
                .order_by(Confirmation.expires_at.desc(), Confirmation.id)
                .limit(1)
                .with_for_update()
            )
            if not conf or not conf.confirmed_at or conf.confirmed_by != order.customer_id:
                conflict("CONFIRMATION_REQUIRED")
            if self.now >= conf.expires_at:
                conflict("CONFIRMATION_EXPIRED")
            if conf.consumed_at or conf.payload_digest != payload_digest(self.summary(case)):
                conflict()
            self.fresh(case, order)
            conf.consumed_at = self.now
            case.status, case.version = "PENDING_REVIEW", case.version + 1
            self.log("SUBMIT_CASE", case)
            return self.view(case)

        return self.mutate("submit:" + case_id, key, args, perform)

    def cancel(self, case_id, args, key):
        self.case(case_id, owner=True)

        def perform():
            case, _ = self.case(case_id, lock=True, owner=True)
            self.version(case, args.expected_version)
            self.state(case, "DRAFT", "WAITING_FOR_USER")
            case.status, case.version = "CANCELLED", case.version + 1
            self.log("CANCEL_CASE", case)
            return self.view(case)

        return self.mutate("cancel:" + case_id, key, args, perform)

    def job(self, case):
        self.session.add(
            RefundJob(
                id=identifier("JOB"),
                case_id=case.id,
                operation_key="SIM-REFUND:" + case.id,
                amount_fen=case.requested_amount_fen,
                case_version=case.version,
                status="QUEUED",
                attempts=0,
                next_attempt_at=datetime.now(UTC),
            )
        )

    def review(self, case_id, args, key):
        self.role("reviewer")
        self.case(case_id)
        if args.decision == "APPROVE" and self.case(case_id)[0].created_by == self.actor.id:
            raise BusinessError("FORBIDDEN", 403)

        def perform():
            case, order = self.case(case_id, lock=True)
            self.version(case, args.expected_version)
            self.state(case, "PENDING_REVIEW")
            if args.decision == "APPROVE":
                if case.case_type == "RETURN_REFUND" and not args.return_required:
                    conflict("INVALID_STATE_TRANSITION")
                _, rules = self.fresh(case, order)
                case.rules_snapshot = rules.model_dump()
                case.status = "AWAITING_RETURN" if args.return_required else "READY_TO_REFUND"
            else:
                case.status = "REJECTED"
            self.session.add(
                ReviewDecision(
                    id=identifier("REVIEW"),
                    case_id=case.id,
                    case_version=case.version,
                    reviewer_id=self.actor.id,
                    decision=args.decision,
                    return_required=args.return_required,
                    reason=args.reason,
                    created_at=self.now,
                )
            )
            case.version += 1
            if case.status == "READY_TO_REFUND":
                self.job(case)
            self.log("REVIEW_CASE", case)
            return self.view(case)

        return self.mutate("review:" + case_id, key, args, perform)

    def receive(self, case_id, args, key):
        self.role("warehouse")
        self.case(case_id)

        def perform():
            case, order = self.case(case_id, lock=True)
            self.version(case, args.expected_version)
            self.state(case, "AWAITING_RETURN")
            review = self.session.scalar(
                select(ReviewDecision).where(ReviewDecision.case_id == case.id)
            )
            if not review or review.decision != "APPROVE" or not review.return_required:
                conflict("INVALID_STATE_TRANSITION")
            self.balance(case, order)
            case.status, case.version, case.received_at = (
                "READY_TO_REFUND",
                case.version + 1,
                self.now,
            )
            self.job(case)
            self.log("RETURN_RECEIVED", case)
            return self.view(case)

        return self.mutate("receive:" + case_id, key, args, perform)

    @staticmethod
    def balance(case, order):
        if (
            order.version != case.order_version
            or order.refunded_amount_fen != 0
            or order.paid_amount_fen - order.refunded_amount_fen != case.requested_amount_fen
        ):
            conflict()

    def reconcile(self, case_id, args, key):
        self.role("reviewer")
        self.case(case_id)

        def perform():
            case, _ = self.case(case_id, lock=True)
            self.version(case, args.expected_version)
            self.state(case, "READY_TO_REFUND", "REFUND_PENDING", "MANUAL_INTERVENTION")
            job = self.session.scalar(
                select(RefundJob).where(RefundJob.case_id == case.id).with_for_update()
            )
            if not job:
                conflict("INVALID_STATE_TRANSITION")
            if job.lease_until and job.lease_until > datetime.now(UTC):
                conflict("INVALID_STATE_TRANSITION")
            if case.status == "MANUAL_INTERVENTION":
                case.status, case.version = "REFUND_PENDING", case.version + 1
                job.case_version = case.version
            job.status, job.attempts = "RETRY", 0
            job.next_attempt_at = datetime.now(UTC)
            job.lease_until, job.lease_token = None, None
            self.log("REQUEST_RECONCILE", case)
            return {
                "case_id": case.id,
                "status": case.status,
                "version": case.version,
                "reconcile_requested": True,
                "simulated": True,
            }

        return self.mutate("reconcile:" + case_id, key, args, perform)

    def refund(self, case_id):
        case, _ = self.case(case_id)
        ledger = self.session.scalar(
            select(RefundTransaction).where(RefundTransaction.case_id == case.id)
        )
        job = self.session.scalar(select(RefundJob).where(RefundJob.case_id == case.id))
        return {
            "case_id": case.id,
            "status": case.status,
            "simulated": True,
            "funds_state": "SUCCEEDED"
            if ledger and case.status == "REFUNDED"
            else (
                "UNKNOWN"
                if case.status in {"REFUND_PENDING", "MANUAL_INTERVENTION"}
                else "NOT_EXECUTED"
            ),
            "transaction": {
                "provider_operation_id": ledger.provider_operation_id,
                "amount_fen": ledger.amount_fen,
                "status": ledger.status,
            }
            if ledger
            else None,
            "job": {"status": job.status, "attempts": job.attempts, "last_error": job.last_error}
            if job
            else None,
        }

    @staticmethod
    def ticket_view(ticket):
        return {
            "id": ticket.id,
            "order_id": ticket.order_id,
            "category": ticket.category,
            "summary": ticket.summary,
            "status": ticket.status,
            "simulated": True,
        }

    def ticket(self, args, key):
        self.role("customer", "support")
        order = self.order(args.order_id)

        def perform():
            ticket = SupportTicket(
                id=identifier("TICKET"),
                tenant_id=order.tenant_id,
                order_id=order.id,
                category=args.category,
                summary=args.summary,
                status="OPEN",
                created_by=self.actor.id,
                created_at=self.now,
            )
            self.session.add(ticket)
            audit(
                self.session,
                self.actor.id,
                order.tenant_id,
                "CREATE_TICKET",
                ticket.id,
                self.trace_id,
                {"category": ticket.category, "status": "OPEN"},
            )
            return self.ticket_view(ticket)

        return self.mutate("ticket", key, args, perform)

    def get_ticket(self, ticket_id):
        return self.ticket_view(self.resource(SupportTicket, ticket_id)[0])
