from typing import Literal

from pydantic import Field

from app.schemas import ResourceId
from app.write_schemas import Input

Action = Literal["CONSULT", "APPLY_AFTER_SALES", "CREATE_TICKET", "SUBMIT_CONFIRMED"]


class ConversationInput(Input):
    pass


class MessageInput(Input):
    client_message_id: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")
    content: str = Field(min_length=1, max_length=4000)
    action: Action = "CONSULT"
    target_order_id: ResourceId | None = None


class CaseInput(Input):
    case_id: ResourceId


class SubmitCaseInput(CaseInput):
    expected_version: int = Field(ge=1)


class TicketReadInput(Input):
    ticket_id: ResourceId


class FactClaim(Input):
    kind: Literal["ORDER", "LOGISTICS", "ELIGIBILITY", "POLICY", "CASE", "TICKET"]
    # Published policy versions use a lowercase v suffix; tool resource IDs stay uppercase.
    resource_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9-]+$")
    field: str = Field(min_length=1, max_length=64)
    value: str | int | bool | None


class FinalAnswer(Input):
    answer: str = Field(min_length=1, max_length=3000)
    needs_input: bool
    citations: list[str] = Field(default_factory=list, max_length=20)
    facts: list[FactClaim] = Field(default_factory=list, max_length=30)
