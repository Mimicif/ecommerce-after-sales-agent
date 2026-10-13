import hashlib
import json

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import BusinessError
from app.models import Policy
from app.schemas import Intent, PolicyClause


def content_digest(rules: dict, clauses: list) -> str:
    payload = json.dumps(
        {"rules": rules, "clauses": clauses},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class PolicyRules(BaseModel):
    # Known safety flags must agree with domain rules. Unknown rule keys fail closed.
    model_config = ConfigDict(extra="forbid", strict=True)
    standard_return_window_seconds: int = Field(gt=0)
    all_refunds_require_review: bool
    window_end_inclusive: bool = True
    eligible_order_status: list[str] = ["DELIVERED"]
    automatic_standard_categories: list[str] = ["STANDARD"]
    excluded_categories_require_manual: list[str] = ["CUSTOM", "PERISHABLE"]
    logistics_inactivity_seconds: int = 172800
    logistics_threshold_comparator: str = ">"
    customer_confirmation_ttl_seconds: int = 900
    standard_returns_require_warehouse_receipt: bool = True
    damaged_items_require_description_and_evidence: bool = True
    damage_decision_requires_manual_review: bool = True
    refund_mode: str = "FULL_REMAINING_SINGLE_ITEM"
    partial_refund_history_requires_manual: bool = True

    @model_validator(mode="after")
    def safety_constraints(self):
        if (
            not all(
                (
                    self.all_refunds_require_review,
                    self.window_end_inclusive,
                    self.standard_returns_require_warehouse_receipt,
                    self.damaged_items_require_description_and_evidence,
                    self.damage_decision_requires_manual_review,
                    self.partial_refund_history_requires_manual,
                )
            )
            or self.eligible_order_status != ["DELIVERED"]
            or self.automatic_standard_categories != ["STANDARD"]
            or set(self.excluded_categories_require_manual) != {"CUSTOM", "PERISHABLE"}
            or self.logistics_inactivity_seconds != 172800
            or self.logistics_threshold_comparator != ">"
            or self.customer_confirmation_ttl_seconds != 900
            or self.refund_mode != "FULL_REMAINING_SINGLE_ITEM"
        ):
            raise ValueError("Policy conflicts with accepted safety rules")
        return self


def unavailable(reason: str):
    return BusinessError(
        "POLICY_UNAVAILABLE", 503, data={"reason_codes": [reason], "next_action": "MANUAL_REVIEW"}
    )


def current_policy(session: Session, tenant_id: str, intent: Intent, now):
    # Tenant, status and time filters happen in SQL before clause text is read.
    rows = session.scalars(
        select(Policy)
        .where(
            Policy.tenant_id == tenant_id,
            Policy.status == "PUBLISHED",
            Policy.effective_from <= now,
            Policy.effective_to > now,
        )
        .limit(2)
    ).all()
    if not rows:
        raise unavailable("POLICY_NOT_FOUND")
    if len(rows) != 1:
        raise unavailable("POLICY_CONFLICT")
    policy = rows[0]
    if not policy.clauses:
        raise unavailable("POLICY_TEXT_MISSING")
    if policy.content_digest != content_digest(policy.rules, policy.clauses):
        raise unavailable("POLICY_CONTENT_CHANGED")
    try:
        rules = PolicyRules.model_validate(policy.rules)
        clauses = [PolicyClause.model_validate(clause) for clause in policy.clauses]
    except ValidationError:
        raise unavailable("POLICY_CONTENT_INVALID") from None
    if len({c.chunk_id for c in clauses}) != len(clauses):
        raise unavailable("POLICY_CONTENT_INVALID")
    if not any(c.intent == intent for c in clauses):
        raise unavailable("POLICY_INTENT_MISSING")
    return policy, rules, [c for c in clauses if c.intent in {intent, "ALL"}]
