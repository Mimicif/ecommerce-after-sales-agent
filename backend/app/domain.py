"""Pure domain calculations. Text, reason codes and evidence never grant permissions."""

from datetime import datetime

from app.clock import utc
from app.policy import PolicyRules
from app.schemas import CaseType, EligibilityView, OrderView

DOMAIN_VERSION = "domain-v1-m1"
LOGISTICS_INACTIVITY_SECONDS = 48 * 60 * 60


def assess_eligibility(
    order: OrderView, case_type: CaseType, rules: PolicyRules, policy_version: str, now: datetime
) -> EligibilityView:
    now = utc(now)
    amount = order.paid_amount_fen - order.refunded_amount_fen

    def outcome(state, *reasons):
        return EligibilityView(
            eligibility=state,
            reason_codes=list(reasons),
            refundable_amount_fen=max(amount, 0),
            policy_version=policy_version,
            order_version=order.version,
            evaluated_at=now,
        )

    if amount < 0:
        return outcome("manual_required", "INVALID_BALANCE")
    if order.paid_amount_fen == 0:
        return outcome("ineligible", "NO_REFUNDABLE_AMOUNT")
    if amount == 0:
        return outcome("ineligible", "ALREADY_REFUNDED")
    if order.refunded_amount_fen > 0:
        return outcome("manual_required", "PARTIAL_REFUND_HISTORY")
    if order.status != "DELIVERED":
        state = "manual_required" if case_type == "DAMAGE_REFUND" else "ineligible"
        return outcome(state, "ORDER_NOT_DELIVERED")
    if order.delivered_at is None:
        return outcome("manual_required", "DELIVERY_TIME_MISSING")
    age = (now - utc(order.delivered_at)).total_seconds()
    if age < 0:
        return outcome("manual_required", "DELIVERY_TIME_IN_FUTURE")
    if case_type == "DAMAGE_REFUND":
        return outcome("manual_required", "DAMAGE_REQUIRES_MANUAL_REVIEW")
    if order.product_category != "STANDARD":
        return outcome("manual_required", "CATEGORY_REQUIRES_MANUAL_REVIEW")
    if age > rules.standard_return_window_seconds:
        return outcome("ineligible", "RETURN_WINDOW_EXCEEDED")
    return outcome("eligible", "RETURN_RULES_SATISFIED")
