from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

CaseType = Literal["RETURN_REFUND", "DAMAGE_REFUND"]
Intent = Literal["RETURN_REFUND", "DAMAGE_REFUND", "LOGISTICS"]
ResourceId = Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[A-Z0-9-]+$")]
Fen = Annotated[int, Field(ge=0, strict=True)]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)


class ListOrdersInput(Input):
    cursor: ResourceId | None = None
    limit: int = Field(default=20, ge=1, le=20)


class OrderInput(Input):
    order_id: ResourceId


class PolicyInput(OrderInput):
    intent: Intent
    query: str = Field(default="", max_length=500)
    top_k: int = Field(default=3, ge=1, le=6)


class PolicyQuery(Input):
    intent: Intent
    query: str = Field(default="", max_length=500)
    # HTTP query parameters arrive as strings; tool input remains strictly typed.
    top_k: int = Field(default=3, ge=1, le=6, strict=False)


class EligibilityInput(OrderInput):
    case_type: CaseType
    reason_code: Literal["CHANGE_OF_MIND", "DAMAGED", "OTHER"] = "OTHER"


class EligibilityBody(Input):
    case_type: CaseType
    reason_code: Literal["CHANGE_OF_MIND", "DAMAGED", "OTHER"] = "OTHER"


class Output(BaseModel):
    model_config = ConfigDict(extra="forbid")


class OrderView(Output):
    id: str
    product_category: Literal["STANDARD", "CUSTOM", "PERISHABLE"]
    status: Literal["DELIVERED", "IN_TRANSIT"]
    paid_amount_fen: Fen
    refunded_amount_fen: Fen
    delivered_at: datetime | None
    version: int = Field(ge=1)
    cases: list[dict] = Field(default_factory=list)


class OrderPage(Output):
    items: list[OrderView]
    next_cursor: str | None


class LogisticsEventView(Output):
    id: str
    occurred_at: datetime
    status: str
    description: str


class LogisticsView(Output):
    order_id: str
    order_status: str
    events: list[LogisticsEventView]
    events_truncated: bool
    last_updated_at: datetime | None
    possible_exception: bool | None
    manual_required: bool
    reason_codes: list[str]
    evaluated_at: datetime
    simulated: Literal[True] = True


class PolicyClause(Input):
    chunk_id: ResourceId
    intent: Literal["RETURN_REFUND", "DAMAGE_REFUND", "LOGISTICS", "ALL"]
    text: str = Field(min_length=1, max_length=4000)


class PolicyClauseView(Output):
    chunk_id: str
    intent: str
    text: str
    citation: str


class PolicyView(Output):
    order_id: str
    policy_version: str
    intent: Intent
    effective_from: datetime
    effective_to: datetime
    clauses: list[PolicyClauseView]
    retrieval_mode: Literal["keyword_v1"] = "keyword_v1"
    candidates: list[dict] = Field(default_factory=list)
    rule_summary: dict = Field(default_factory=dict)
    evaluated_at: datetime
    simulated: Literal[True] = True


class EligibilityView(Output):
    eligibility: Literal["eligible", "ineligible", "manual_required"]
    reason_codes: list[str]
    refundable_amount_fen: Fen
    policy_version: str | None
    order_version: int
    evaluated_at: datetime
    assessment_scope: Literal["READ_ONLY_PRECHECK"] = "READ_ONLY_PRECHECK"
    review_required: Literal[True] = True
