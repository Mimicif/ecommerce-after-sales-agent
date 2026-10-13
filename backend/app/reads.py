from sqlalchemy import select
from sqlalchemy.orm import Session

from app.clock import Clock, utc
from app.domain import LOGISTICS_INACTIVITY_SECONDS, assess_eligibility
from app.errors import BusinessError
from app.models import TERMINAL_CASES, AfterSalesCase, LogisticsEvent, Order, User
from app.policy import current_policy
from app.schemas import (
    EligibilityInput,
    EligibilityView,
    ListOrdersInput,
    LogisticsEventView,
    LogisticsView,
    OrderPage,
    OrderView,
    PolicyClauseView,
    PolicyInput,
    PolicyView,
)


class ReadService:
    def __init__(self, session: Session, actor_id: str, clock: Clock):
        self.session = session
        self.clock = clock
        # Actor ID is provided by verified backend context, never tool input.
        self.actor = session.get(User, actor_id)
        if self.actor is None:
            raise BusinessError("UNAUTHORIZED", 401)

    def authorized_orders(self):
        query = select(Order).where(Order.tenant_id == self.actor.tenant_id)
        if "support" in self.actor.roles:
            return query
        if "customer" in self.actor.roles and self.actor.customer_id:
            return query.where(Order.customer_id == self.actor.customer_id)
        raise BusinessError("FORBIDDEN", 403)

    def require_order(self, order_id: str) -> Order:
        order = self.session.scalar(self.authorized_orders().where(Order.id == order_id))
        if order is None:
            raise BusinessError("RESOURCE_NOT_FOUND", 404)
        return order

    @staticmethod
    def order_view(order: Order) -> OrderView:
        return OrderView(
            **{key: getattr(order, key) for key in OrderView.model_fields if key != "cases"}
        )

    def list_orders(self, args: ListOrdersInput) -> OrderPage:
        query = self.authorized_orders()
        if args.cursor:
            query = query.where(Order.id > args.cursor)
        rows = self.session.scalars(query.order_by(Order.id).limit(args.limit + 1)).all()
        return OrderPage(
            items=[self.order_view(o) for o in rows[: args.limit]],
            next_cursor=rows[args.limit - 1].id if len(rows) > args.limit else None,
        )

    def get_order(self, order_id: str) -> OrderView:
        order = self.require_order(order_id)
        view = self.order_view(order)
        rows = self.session.scalars(
            select(AfterSalesCase)
            .where(AfterSalesCase.tenant_id == order.tenant_id, AfterSalesCase.order_id == order.id)
            .order_by(AfterSalesCase.created_at.desc(), AfterSalesCase.id)
            .limit(5)
        ).all()
        view.cases = [{"id": row.id, "status": row.status, "version": row.version} for row in rows]
        return view

    def load_logistics(self, order_id: str):
        return self.session.scalars(
            select(LogisticsEvent)
            .where(
                LogisticsEvent.order_id == order_id,
            )
            .order_by(LogisticsEvent.occurred_at.desc(), LogisticsEvent.id.desc())
            .limit(101)
        ).all()

    def get_logistics(self, order_id: str) -> LogisticsView:
        order = self.require_order(order_id)
        now = utc(self.clock.now(self.session))
        rows = self.load_logistics(order.id)
        latest = rows[0] if rows else None
        flag, manual, reasons = False, False, ["LOGISTICS_NORMAL"]
        if latest is None:
            flag, manual, reasons = None, True, ["LOGISTICS_NO_EVENTS"]
        elif latest.occurred_at > now:
            flag, manual, reasons = None, True, ["LOGISTICS_TIME_IN_FUTURE"]
        elif latest.status not in {"IN_TRANSIT", "EXCEPTION", "DELIVERED"}:
            flag, manual, reasons = None, True, ["LOGISTICS_DATA_INVALID"]
        elif latest.status == "EXCEPTION":
            flag, manual, reasons = True, True, ["LOGISTICS_REPORTED_EXCEPTION"]
        elif (
            order.status == "IN_TRANSIT"
            and (now - latest.occurred_at).total_seconds() > LOGISTICS_INACTIVITY_SECONDS
        ):
            flag, manual, reasons = True, True, ["LOGISTICS_INACTIVE"]
        return LogisticsView(
            order_id=order.id,
            order_status=order.status,
            events=[
                LogisticsEventView(
                    id=e.id,
                    occurred_at=utc(e.occurred_at),
                    status=e.status,
                    description=e.description,
                )
                for e in rows[:100]
            ],
            events_truncated=len(rows) > 100,
            last_updated_at=utc(latest.occurred_at) if latest else None,
            possible_exception=flag,
            manual_required=manual,
            reason_codes=reasons,
            evaluated_at=now,
        )

    def search_policy(self, args: PolicyInput) -> PolicyView:
        from app.retrieval import indexed_clauses, rank

        order = self.require_order(args.order_id)
        now = utc(self.clock.now(self.session))
        policy, rules, clauses = current_policy(self.session, order.tenant_id, args.intent, now)
        clauses = indexed_clauses(self.session, policy, clauses, args.intent)
        ranked, candidates = rank(clauses, args.query, args.intent, args.top_k)
        return PolicyView(
            order_id=order.id,
            policy_version=policy.id,
            intent=args.intent,
            effective_from=utc(policy.effective_from),
            effective_to=utc(policy.effective_to),
            evaluated_at=now,
            clauses=[
                PolicyClauseView(
                    chunk_id=c.chunk_id,
                    intent=c.intent,
                    text=c.text,
                    citation=f"模拟售后政策 {policy.id} / {c.chunk_id}",
                )
                for c, _ in ranked
            ],
            candidates=candidates,
            rule_summary={
                key: getattr(rules, key)
                for key in (
                    "standard_return_window_seconds",
                    "customer_confirmation_ttl_seconds",
                    "logistics_inactivity_seconds",
                    "all_refunds_require_review",
                )
            },
        )

    def check_eligibility(self, args: EligibilityInput) -> EligibilityView:
        order = self.require_order(args.order_id)
        now = utc(self.clock.now(self.session))
        active = self.session.scalar(
            select(AfterSalesCase).where(
                AfterSalesCase.order_id == order.id, AfterSalesCase.status.not_in(TERMINAL_CASES)
            )
        )
        if active:
            return EligibilityView(
                eligibility="manual_required",
                reason_codes=["ACTIVE_CASE_EXISTS"],
                refundable_amount_fen=order.paid_amount_fen - order.refunded_amount_fen,
                policy_version=active.policy_version,
                order_version=order.version,
                evaluated_at=now,
            )
        try:
            policy, rules, _ = current_policy(self.session, order.tenant_id, args.case_type, now)
        except BusinessError as exc:
            if exc.code != "POLICY_UNAVAILABLE":
                raise
            return EligibilityView(
                eligibility="manual_required",
                reason_codes=[exc.code, *exc.data["reason_codes"]],
                refundable_amount_fen=order.paid_amount_fen - order.refunded_amount_fen,
                policy_version=None,
                order_version=order.version,
                evaluated_at=now,
            )
        return assess_eligibility(self.order_view(order), args.case_type, rules, policy.id, now)
