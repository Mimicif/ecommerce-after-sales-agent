from typing import Literal

from pydantic import Field, model_validator

from app.schemas import CaseType, Input, ResourceId


class VersionInput(Input):
    expected_version: int = Field(ge=1)


class DraftInput(Input):
    order_id: ResourceId
    case_type: CaseType
    reason: str = Field(min_length=1, max_length=2000)
    evidence_refs: list[ResourceId] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def unique_evidence(self):
        if len(set(self.evidence_refs)) != len(self.evidence_refs):
            raise ValueError("Duplicate evidence")
        return self


class EditDraftInput(VersionInput):
    reason: str = Field(min_length=1, max_length=2000)
    evidence_refs: list[ResourceId] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def unique_evidence(self):
        if len(set(self.evidence_refs)) != len(self.evidence_refs):
            raise ValueError("Duplicate evidence")
        return self


class ConfirmInput(Input):
    payload_digest: str = Field(pattern=r"^[a-f0-9]{64}$")


class ReviewInput(VersionInput):
    decision: Literal["APPROVE", "REJECT"]
    reason: str = Field(min_length=1, max_length=2000)
    return_required: bool


class TicketInput(Input):
    order_id: ResourceId
    category: Literal["LOGISTICS", "MANUAL_AFTER_SALES"]
    summary: str = Field(min_length=1, max_length=2000)
