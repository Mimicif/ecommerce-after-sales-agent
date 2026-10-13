"""Durable local simulation. Provider transactions are separate from local bookkeeping."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from pydantic import ValidationError
from sqlalchemy import or_, select

from app.models import (
    AfterSalesCase,
    Order,
    RefundJob,
    RefundTransaction,
    ReviewDecision,
    SimulatedProviderOperation,
)
from app.policy import PolicyRules
from app.writes import advisory_lock, audit, identifier


class ProviderFailure(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class ProviderResult:
    operation_key: str
    provider_operation_id: str
    amount_fen: int
    status: str
    provider_reference: str


def provider_result(row):
    return ProviderResult(**{key: getattr(row, key) for key in ProviderResult.__dataclass_fields__})


class SimulatedProvider:
    def __init__(self, sessions, *, fault="success"):
        if fault not in {"success", "timeout_before", "timeout_after", "unavailable"}:
            raise ValueError("Unknown trusted simulation fault")
        self.sessions, self.fault = sessions, fault

    def query(self, operation_key):
        if self.fault == "unavailable":
            raise ProviderFailure("PROVIDER_UNAVAILABLE")
        with self.sessions() as session:
            row = session.get(SimulatedProviderOperation, operation_key)
            return provider_result(row) if row else None

    def submit(self, operation_key, amount_fen):
        if self.fault in {"timeout_before", "unavailable"}:
            raise ProviderFailure(
                "PROVIDER_TIMEOUT" if self.fault == "timeout_before" else "PROVIDER_UNAVAILABLE"
            )
        with self.sessions() as session, session.begin():
            advisory_lock(session, "provider:" + operation_key)
            row = session.get(SimulatedProviderOperation, operation_key)
            if row is None:
                row = SimulatedProviderOperation(
                    operation_key=operation_key,
                    provider_operation_id=identifier("SIM-PAY"),
                    amount_fen=amount_fen,
                    status="SUCCEEDED",
                    provider_reference=identifier("SIM-REF"),
                    created_at=datetime.now(UTC),
                )
                session.add(row)
                session.flush()
            if row.amount_fen != amount_fen:
                raise ProviderFailure("PROVIDER_AMOUNT_CONFLICT")
            result = provider_result(row)
        if self.fault == "timeout_after":
            raise ProviderFailure("PROVIDER_TIMEOUT")
        return result


class SimulatedCrash(Exception):
    """Test-only abrupt exit after provider commit, before local transaction."""


class RefundWorker:
    MAX_ATTEMPTS = 3
    LEASE_SECONDS = 30
    RETRY_SECONDS = 5

    def __init__(self, sessions, provider=None, *, now=None):
        self.sessions = sessions
        self.provider = provider or SimulatedProvider(sessions)
        self.now = now or (lambda: datetime.now(UTC))

    def claim(self):
        now, token = self.now(), uuid4().hex
        with self.sessions() as session, session.begin():
            job = session.scalar(
                select(RefundJob)
                .where(
                    RefundJob.status.in_(["QUEUED", "RETRY", "RUNNING"]),
                    RefundJob.next_attempt_at <= now,
                    or_(RefundJob.lease_until.is_(None), RefundJob.lease_until <= now),
                )
                .order_by(RefundJob.next_attempt_at, RefundJob.id)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            if not job:
                return None
            job.status, job.lease_token = "RUNNING", token
            job.lease_until = now + timedelta(seconds=self.LEASE_SECONDS)
            job.attempts += 1
            return job.id, token

    def locked(self, session, job_id, token):
        row = session.get(RefundJob, job_id)
        if not row:
            return None
        order_id = session.scalar(
            select(AfterSalesCase.order_id).where(AfterSalesCase.id == row.case_id)
        )
        order = session.scalar(select(Order).where(Order.id == order_id).with_for_update())
        case = session.scalar(
            select(AfterSalesCase).where(AfterSalesCase.id == row.case_id).with_for_update()
        )
        job = session.scalar(
            select(RefundJob)
            .where(RefundJob.id == job_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if (
            job.status != "RUNNING"
            or job.lease_token != token
            or not job.lease_until
            or job.lease_until <= self.now()
        ):
            return None
        return order, case, job

    @staticmethod
    def release(job):
        job.lease_token, job.lease_until = None, None

    def log(self, session, case, action, code="OK"):
        audit(
            session,
            "REFUND-WORKER",
            case.tenant_id,
            action,
            case.id,
            uuid4().hex,
            {
                "status": case.status,
                "version": case.version,
                "amount_fen": case.requested_amount_fen,
            },
            result=code,
        )

    def manual(self, session, case, job, code):
        case.status, case.version = "MANUAL_INTERVENTION", case.version + 1
        job.status, job.last_error, job.case_version = "MANUAL", code, case.version
        self.release(job)
        self.log(session, case, "REFUND_MANUAL", code)

    @staticmethod
    def authorized(session, order, case, job):
        review = session.scalar(select(ReviewDecision).where(ReviewDecision.case_id == case.id))
        try:
            rules = PolicyRules.model_validate(case.rules_snapshot)
        except ValidationError:
            return False
        return (
            case.status in {"READY_TO_REFUND", "REFUND_PENDING"}
            and case.version == job.case_version
            and review is not None
            and review.decision == "APPROVE"
            and review.reviewer_id != case.created_by
            and (case.case_type != "RETURN_REFUND" or review.return_required)
            and (not review.return_required or case.received_at is not None)
            and rules.all_refunds_require_review
            and order.tenant_id == case.tenant_id
            and order.status == "DELIVERED"
            and order.delivered_at is not None
            and (case.case_type != "RETURN_REFUND" or order.product_category == "STANDARD")
            and order.version == case.order_version
            and order.refunded_amount_fen == 0
            and order.paid_amount_fen == case.requested_amount_fen == job.amount_fen
            and job.operation_key == "SIM-REFUND:" + case.id
        )

    def prepare(self, job_id, token):
        with self.sessions() as session, session.begin():
            locked = self.locked(session, job_id, token)
            if not locked:
                return None
            order, case, job = locked
            if not self.authorized(session, order, case, job):
                self.manual(session, case, job, "REFUND_GUARD_FAILED")
                return None
            if case.status == "READY_TO_REFUND":
                case.status, case.version = "REFUND_PENDING", case.version + 1
                job.case_version = case.version
                self.log(session, case, "REFUND_PENDING")
            return job.operation_key, job.amount_fen, job.attempts

    def failure(self, job_id, token, code):
        with self.sessions() as session, session.begin():
            locked = self.locked(session, job_id, token)
            if not locked:
                return "STALE_LEASE"
            _, case, job = locked
            if job.attempts >= self.MAX_ATTEMPTS or code == "PROVIDER_AMOUNT_CONFLICT":
                self.manual(session, case, job, code)
                return "MANUAL_INTERVENTION"
            job.status, job.last_error = "RETRY", code
            job.next_attempt_at = self.now() + timedelta(seconds=self.RETRY_SECONDS)
            self.release(job)
            self.log(session, case, "REFUND_RETRY", code)
            return "REFUND_PENDING"

    def finish(self, job_id, token, result):
        with self.sessions() as session, session.begin():
            locked = self.locked(session, job_id, token)
            if not locked:
                return "STALE_LEASE"
            order, case, job = locked
            if (
                not self.authorized(session, order, case, job)
                or result.operation_key != job.operation_key
                or result.amount_fen != job.amount_fen
                or result.status != "SUCCEEDED"
            ):
                self.manual(session, case, job, "PROVIDER_RESULT_CONFLICT")
                return "MANUAL_INTERVENTION"
            # Order and case locks serialize all bookkeeping. Unique keys are a second guard.
            previous = session.scalar(
                select(RefundTransaction).where(RefundTransaction.case_id == case.id)
            )
            if previous is not None:
                self.manual(session, case, job, "LEDGER_STATE_CONFLICT")
                return "MANUAL_INTERVENTION"
            session.add(
                RefundTransaction(
                    provider_operation_id=result.provider_operation_id,
                    case_id=case.id,
                    operation_key=result.operation_key,
                    amount_fen=result.amount_fen,
                    status=result.status,
                    provider_reference=result.provider_reference,
                    created_at=self.now(),
                )
            )
            order.refunded_amount_fen += result.amount_fen
            order.version += 1
            case.status, case.version = "REFUNDED", case.version + 1
            job.status, job.case_version, job.last_error = "DONE", case.version, None
            self.release(job)
            self.log(session, case, "REFUND_SUCCEEDED")
            return "REFUNDED"

    def run_once(self, *, crash_after_provider=False):
        claimed = self.claim()
        if not claimed:
            return {"processed": False, "status": "IDLE", "simulated": True}
        job_id, token = claimed
        prepared = self.prepare(job_id, token)
        if not prepared:
            return {"processed": True, "status": "GUARD_BLOCKED_OR_STALE", "simulated": True}
        operation_key, amount, attempts = prepared
        try:
            result = self.provider.query(operation_key)
            if result is None:
                if attempts > self.MAX_ATTEMPTS:
                    raise ProviderFailure("PROVIDER_RETRY_EXHAUSTED")
                result = self.provider.submit(operation_key, amount)
        except ProviderFailure as exc:
            status = self.failure(job_id, token, exc.code)
        else:
            if crash_after_provider:
                raise SimulatedCrash()
            status = self.finish(job_id, token, result)
        return {"processed": True, "status": status, "simulated": True}
