"""Validate structured business assertions against observed tool facts, not an LLM judge."""

import re
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

FIELDS = {
    "ORDER": (
        "paid_amount_fen",
        "refunded_amount_fen",
        "delivered_at",
        "product_category",
        "status",
        "version",
    ),
    "LOGISTICS": ("possible_exception", "order_status", "last_updated_at", "evaluated_at"),
    "ELIGIBILITY": ("eligibility", "refundable_amount_fen", "policy_version", "evaluated_at"),
    "POLICY": (
        "standard_return_window_seconds",
        "customer_confirmation_ttl_seconds",
        "logistics_inactivity_seconds",
        "all_refunds_require_review",
        "evaluated_at",
    ),
    "CASE": ("status", "case_type", "requested_amount_fen", "version", "order_id"),
    "TICKET": ("status", "category", "order_id"),
}


def observed_facts(name, arguments, data):
    kind = {
        "get_order": "ORDER",
        "get_logistics": "LOGISTICS",
        "search_policy": "POLICY",
        "check_eligibility": "ELIGIBILITY",
        "get_case": "CASE",
        "create_case_draft": "CASE",
        "submit_case": "CASE",
        "get_support_ticket": "TICKET",
        "create_support_ticket": "TICKET",
    }.get(name)
    if kind is None:
        return []
    resource_id = (
        data.get("policy_version")
        if kind == "POLICY"
        else (data.get("id") if kind in {"ORDER", "CASE", "TICKET"} else arguments.get("order_id"))
    )
    source = (
        {**data.get("rule_summary", {}), "evaluated_at": data.get("evaluated_at")}
        if kind == "POLICY"
        else data
    )
    return [
        {"kind": kind, "resource_id": resource_id, "field": key, "value": source[key]}
        for key in FIELDS[kind]
        if key in source
    ]


def same_value(field, first, second):
    if field.endswith("_at") and isinstance(first, str) and isinstance(second, str):
        try:
            a, b = datetime.fromisoformat(first), datetime.fromisoformat(second)
            return a.utcoffset() is not None and b.utcoffset() is not None and a == b
        except ValueError:
            return False
    return type(first) is type(second) and first == second


def verified(claim, observations):
    return any(
        all(claim[key] == fact[key] for key in ("kind", "resource_id", "field"))
        and same_value(claim["field"], claim["value"], fact["value"])
        for fact in observations
    )


def positive_status_text(answer):
    """Bounded extraction of affirmative claims, excluding negations and future conditions."""
    value = re.sub(r"[“\"](?:模拟)?退款成功[”\"](?:不能|不代表)[^，。；\n]*", "", answer)
    value = re.sub(r"(?:尚未|未|没有|不能|不代表|不等于|≠)[^，。；\n]*", "", value)
    value = re.sub(r"已退款\s*0(?:\.0+)?\s*(?:元|分)", "", value)
    value = re.sub(r"(?:只有|仅当|如果|若|待)[^。；\n]*?(?:才|则)[^，。；\n]*", "", value)
    value = re.sub(r"[^，。；\n]*(?:后才|前不能)[^，。；\n]*", "", value)
    return re.sub(r"(?<!已)(?:审核通过|审批通过|批准|收货|对账成功)后[^，。；\n]*", "", value)


def grounded_text(answer, claims):
    """Check explicit Arabic money and calendar dates against declared grounded claims.

    This is deliberately bounded; natural language semantics still need task or human review.
    """
    amounts = {
        c["value"] for c in claims if c["field"].endswith("amount_fen") and type(c["value"]) is int
    }
    for number, unit in re.findall(r"(?<![A-Za-z\d.-])(\d+(?:\.\d{1,2})?)\s*(元|分)(?!钟)", answer):
        value = Decimal(number) * (100 if unit == "元" else 1)
        if value != value.to_integral_value() or int(value) not in amounts:
            return False
    dates = set()
    for claim in claims:
        if claim["field"].endswith("_at") and isinstance(claim["value"], str):
            try:
                parsed = datetime.fromisoformat(claim["value"])
                if parsed.utcoffset() is not None:
                    dates.add(parsed.date().isoformat())
                    dates.add(parsed.astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat())
            except ValueError:
                pass
    if any(date not in dates for date in re.findall(r"(?<!\d)\d{4}-\d{2}-\d{2}(?!\d)", answer)):
        return False
    return True
