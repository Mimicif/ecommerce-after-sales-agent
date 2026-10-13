"""M5 authorized discovery and audit history; no new mutation or model tools."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.models import AfterSalesCase, AuditEvent, Conversation, Evidence, Order, SupportTicket
from app.schemas import ResourceId
from app.writes import WriteService


class PageQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cursor: ResourceId | None = None
    limit: int = Field(default=25, ge=1, le=50)


class CasePageQuery(PageQuery):
    status: (
        Literal[
            "DRAFT",
            "WAITING_FOR_USER",
            "PENDING_REVIEW",
            "AWAITING_RETURN",
            "READY_TO_REFUND",
            "REFUND_PENDING",
            "MANUAL_INTERVENTION",
            "REFUNDED",
            "REJECTED",
            "CANCELLED",
        ]
        | None
    ) = None


class WorkspaceService:
    def __init__(self, session, actor_id, clock, trace_id):
        self.session = session
        self.writer = WriteService(session, actor_id, clock, trace_id)
        self.actor = self.writer.actor

    def scoped(self, model):
        self.writer.role("customer", "support", "reviewer", "warehouse")
        query = (
            select(model)
            .join(Order, Order.id == model.order_id)
            .where(
                model.tenant_id == self.actor.tenant_id,
                Order.tenant_id == self.actor.tenant_id,
            )
        )
        if not {"support", "reviewer", "warehouse"}.intersection(self.actor.roles):
            query = query.where(Order.customer_id == self.actor.customer_id)
        return query

    def page(self, query, model, params, render):
        if params.cursor:
            query = query.where(model.id > params.cursor)
        rows = self.session.scalars(query.order_by(model.id).limit(params.limit + 1)).all()
        more = len(rows) > params.limit
        rows = rows[: params.limit]
        return {
            "items": [render(row) for row in rows],
            "next_cursor": rows[-1].id if more else None,
        }

    def cases(self, params):
        query = self.scoped(AfterSalesCase)
        if params.status:
            query = query.where(AfterSalesCase.status == params.status)
        return self.page(query, AfterSalesCase, params, WriteService.view)

    def tickets(self, params):
        return self.page(
            self.scoped(SupportTicket), SupportTicket, params, WriteService.ticket_view
        )

    def conversations(self, params):
        self.writer.role("customer", "support")
        query = select(Conversation).where(
            Conversation.tenant_id == self.actor.tenant_id, Conversation.owner_id == self.actor.id
        )
        return self.page(
            query,
            Conversation,
            params,
            lambda row: {
                "conversation_id": row.id,
                "created_at": row.created_at.isoformat(),
            },
        )

    def evidence(self, order_id):
        self.writer.role("customer", "support")
        order = self.writer.order(order_id)
        rows = self.session.scalars(
            select(Evidence)
            .where(
                Evidence.tenant_id == self.actor.tenant_id, Evidence.owner_id == order.customer_id
            )
            .order_by(Evidence.id)
        ).all()
        return {
            "items": [
                {"id": row.id, "kind": row.kind, "description": row.description} for row in rows
            ]
        }

    def timeline(self, case_id):
        case, _ = self.writer.case(case_id)
        rows = self.session.scalars(
            select(AuditEvent)
            .where(AuditEvent.tenant_id == self.actor.tenant_id, AuditEvent.resource_id == case.id)
            .order_by(AuditEvent.timestamp, AuditEvent.id)
        ).all()
        return {
            "items": [
                {
                    "id": row.id,
                    "action": row.action,
                    "result": row.result,
                    "occurred_at": row.timestamp.isoformat(),
                    "summary": row.summary,
                }
                for row in rows
            ]
        }
