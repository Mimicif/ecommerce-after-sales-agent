from datetime import UTC, datetime, timedelta

import pytest
from app.clock import FixedClock, SystemClock
from app.domain import assess_eligibility
from app.policy import PolicyRules
from app.schemas import OrderView
from pydantic import ValidationError

NOW = datetime(2026, 10, 11, 2, tzinfo=UTC)
RULES = PolicyRules(standard_return_window_seconds=604800, all_refunds_require_review=True)


def order(**changes):
    facts = dict(
        id="O-A101",
        product_category="STANDARD",
        status="DELIVERED",
        paid_amount_fen=14900,
        refunded_amount_fen=0,
        delivered_at=NOW - timedelta(days=2),
        version=1,
    )
    return OrderView(**(facts | changes))


@pytest.mark.parametrize(
    "age,state,reason",
    [
        (timedelta(0), "eligible", "RETURN_RULES_SATISFIED"),
        (timedelta(days=7), "eligible", "RETURN_RULES_SATISFIED"),
        (timedelta(days=7, seconds=1), "ineligible", "RETURN_WINDOW_EXCEEDED"),
        (timedelta(days=7, microseconds=1), "ineligible", "RETURN_WINDOW_EXCEEDED"),
        (timedelta(seconds=-1), "manual_required", "DELIVERY_TIME_IN_FUTURE"),
    ],
)
def test_return_window_includes_exact_seven_days(age, state, reason):
    result = assess_eligibility(order(delivered_at=NOW - age), "RETURN_REFUND", RULES, "A-v1", NOW)
    assert result.eligibility == state and reason in result.reason_codes
    assert result.refundable_amount_fen == 14900 and result.review_required is True


@pytest.mark.parametrize(
    "changes,state,reason,amount",
    [
        (
            {"status": "IN_TRANSIT", "delivered_at": None},
            "ineligible",
            "ORDER_NOT_DELIVERED",
            14900,
        ),
        ({"delivered_at": None}, "manual_required", "DELIVERY_TIME_MISSING", 14900),
        (
            {"product_category": "CUSTOM"},
            "manual_required",
            "CATEGORY_REQUIRES_MANUAL_REVIEW",
            14900,
        ),
        (
            {"product_category": "PERISHABLE"},
            "manual_required",
            "CATEGORY_REQUIRES_MANUAL_REVIEW",
            14900,
        ),
        ({"refunded_amount_fen": 14900}, "ineligible", "ALREADY_REFUNDED", 0),
        ({"refunded_amount_fen": 5000}, "manual_required", "PARTIAL_REFUND_HISTORY", 9900),
        ({"paid_amount_fen": 0}, "ineligible", "NO_REFUNDABLE_AMOUNT", 0),
    ],
)
def test_return_category_status_and_balance(changes, state, reason, amount):
    result = assess_eligibility(order(**changes), "RETURN_REFUND", RULES, "A-v1", NOW)
    assert result.eligibility == state and reason in result.reason_codes
    assert result.refundable_amount_fen == amount
    assert result.assessment_scope == "READ_ONLY_PRECHECK"


@pytest.mark.parametrize(
    "changes,reason",
    [
        ({"delivered_at": NOW - timedelta(days=10)}, "DAMAGE_REQUIRES_MANUAL_REVIEW"),
        ({"product_category": "CUSTOM"}, "DAMAGE_REQUIRES_MANUAL_REVIEW"),
        ({"product_category": "PERISHABLE"}, "DAMAGE_REQUIRES_MANUAL_REVIEW"),
        ({"status": "IN_TRANSIT", "delivered_at": None}, "ORDER_NOT_DELIVERED"),
    ],
)
def test_damage_never_uses_standard_window_to_refuse(changes, reason):
    result = assess_eligibility(order(**changes), "DAMAGE_REFUND", RULES, "A-v1", NOW)
    assert result.eligibility == "manual_required" and reason in result.reason_codes
    assert "RETURN_WINDOW_EXCEEDED" not in result.reason_codes


def test_timezone_conversion_and_real_clock():
    beijing = datetime.fromisoformat("2026-10-04T10:00:00+08:00")
    result = assess_eligibility(order(delivered_at=beijing), "RETURN_REFUND", RULES, "A-v1", NOW)
    assert result.eligibility == "eligible"
    assert FixedClock(datetime.fromisoformat("2026-10-11T10:00:00+08:00")).value == NOW
    with pytest.raises(ValueError):
        FixedClock(datetime(2026, 10, 11))
    before = datetime.now(UTC)
    assert before <= SystemClock().now(None) <= datetime.now(UTC)


@pytest.mark.parametrize(
    "changes",
    [
        {"all_refunds_require_review": False},
        {"window_end_inclusive": False},
        {"standard_return_window_seconds": True},
        {"standard_return_window_seconds": 0},
        {"logistics_threshold_comparator": ">="},
        {"logistics_inactivity_seconds": 3600},
        {"partial_refund_history_requires_manual": False},
        {"refund_mode": "AUTONOMOUS"},
    ],
)
def test_policy_cannot_relax_domain_safety(changes):
    with pytest.raises(ValidationError):
        PolicyRules.model_validate(
            {"standard_return_window_seconds": 604800, "all_refunds_require_review": True} | changes
        )
