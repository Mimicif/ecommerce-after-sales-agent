"""Conversation authorization and durable run leases; all times here use real UTC."""

import re
from datetime import UTC, datetime

from sqlalchemy import select

from app.errors import BusinessError
from app.models import AgentRun, ChatMessage, Conversation, RunEvent, User
from app.writes import WriteService, identifier, payload_digest

ACTIVE = ("QUEUED", "RUNNING")
PROMPT_VERSION = "prompt-v5-m4"
TOOL_VERSION = "tools-v2-m4"


def redact(value):
    if isinstance(value, str):
        value = re.sub(r"(?i)(?:sk-|Bearer\s+)[A-Za-z0-9_\-\.]{8,}", "[REDACTED]", value)
        value = re.sub(r"(?i)(?:api[_ -]?key|password|密钥)\s*[:=]\s*\S+", "[REDACTED]", value)
        value = re.sub(r"(?<!\d)1[3-9]\d{9}(?!\d)", "[PHONE]", value)
        return re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[EMAIL]", value)
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, dict):
        return {key: redact(item) for key, item in value.items()}
    return value


def event(session, run, kind, data):
    session.add(
        RunEvent(
            run_id=run.id,
            seq=run.next_event_seq,
            kind=kind,
            data=redact(data),
            created_at=datetime.now(UTC),
        )
    )
    run.next_event_seq += 1


def run_view(run):
    return {
        "run_id": run.id,
        "conversation_id": run.conversation_id,
        "status": run.status,
        "action": run.action,
        "target_order_id": run.target_order_id,
        "provider": run.provider,
        "model": run.model,
        "prompt_version": run.prompt_version,
        "tool_version": run.tool_version,
        "model_calls": run.model_calls,
        "tool_calls": run.tool_calls,
        "error_code": run.error_code,
        "response": run.response,
        "created_at": run.created_at.isoformat(),
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
    }


class ConversationService:
    def __init__(self, session, actor_id, clock, trace_id):
        self.session = session
        self.writer = WriteService(session, actor_id, clock, trace_id)
        self.writer.role("customer", "support")
        self.actor = self.writer.actor

    def conversation(self, conversation_id, *, lock=False, owner=False):
        query = select(Conversation).where(
            Conversation.id == conversation_id, Conversation.tenant_id == self.actor.tenant_id
        )
        if owner or "support" not in self.actor.roles:
            query = query.where(Conversation.owner_id == self.actor.id)
        if lock:
            query = query.with_for_update().execution_options(populate_existing=True)
        conversation = self.session.scalar(query)
        if conversation is None:
            raise BusinessError("RESOURCE_NOT_FOUND", 404)
        return conversation

    def create(self, args, key):
        def write():
            conversation = Conversation(
                id=identifier("CONV"),
                tenant_id=self.actor.tenant_id,
                owner_id=self.actor.id,
                next_seq=1,
                created_at=datetime.now(UTC),
            )
            self.session.add(conversation)
            return {"conversation_id": conversation.id}

        return self.writer.mutate("create_conversation", key, args, write)

    def message(self, conversation_id, args):
        conversation = self.conversation(conversation_id, lock=True, owner=True)
        digest = payload_digest(args.model_dump(mode="json"))
        previous = self.session.scalar(
            select(ChatMessage).where(
                ChatMessage.conversation_id == conversation.id,
                ChatMessage.client_message_id == args.client_message_id,
            )
        )
        if previous:
            if previous.request_digest != digest:
                raise BusinessError("IDEMPOTENCY_CONFLICT", 409)
            return run_view(self.session.get(AgentRun, previous.run_id))
        if self.session.scalar(
            select(AgentRun.id).where(
                AgentRun.conversation_id == conversation.id, AgentRun.status.in_(ACTIVE)
            )
        ):
            raise BusinessError("RUN_ACTIVE", 409)
        if args.target_order_id is not None:
            self.writer.order(args.target_order_id)
        now, run_id, message_id = datetime.now(UTC), identifier("RUN"), identifier("MSG")
        self.session.add(
            ChatMessage(
                id=message_id,
                conversation_id=conversation.id,
                seq=conversation.next_seq,
                role="user",
                client_message_id=args.client_message_id,
                request_digest=digest,
                run_id=run_id,
                content=redact(args.content),
                created_at=now,
            )
        )
        conversation.next_seq += 1
        self.session.flush()
        run = AgentRun(
            id=run_id,
            tenant_id=self.actor.tenant_id,
            conversation_id=conversation.id,
            actor_id=self.actor.id,
            input_message_id=message_id,
            action=args.action,
            target_order_id=args.target_order_id,
            status="QUEUED",
            prompt_version=PROMPT_VERSION,
            tool_version=TOOL_VERSION,
            model_calls=0,
            tool_calls=0,
            next_event_seq=1,
            created_at=now,
        )
        self.session.add(run)
        self.session.flush()
        event(self.session, run, "QUEUED", {"action": args.action})
        return run_view(run)

    def run(self, run_id):
        run = self.session.get(AgentRun, run_id)
        if run is None:
            raise BusinessError("RESOURCE_NOT_FOUND", 404)
        self.conversation(run.conversation_id)
        return run

    def events(self, run_id, after, limit):
        self.run(run_id)
        rows = self.session.scalars(
            select(RunEvent)
            .where(RunEvent.run_id == run_id, RunEvent.seq > after)
            .order_by(RunEvent.seq)
            .limit(limit)
        ).all()
        return {
            "items": [
                {
                    "seq": row.seq,
                    "kind": row.kind,
                    "data": row.data,
                    "created_at": row.created_at.isoformat(),
                }
                for row in rows
            ],
            "next_cursor": rows[-1].seq if rows else after,
        }

    def messages(self, conversation_id):
        self.conversation(conversation_id)
        rows = self.session.scalars(
            select(ChatMessage)
            .where(ChatMessage.conversation_id == conversation_id)
            .order_by(ChatMessage.seq.desc())
            .limit(50)
        ).all()
        return {
            "items": [
                {
                    "message_id": row.id,
                    "seq": row.seq,
                    "role": row.role,
                    "content": row.content,
                    "run_id": row.run_id,
                }
                for row in reversed(rows)
            ]
        }

    def cancel(self, run_id):
        current = self.run(run_id)
        self.conversation(current.conversation_id, lock=True, owner=True)
        run = self.session.scalar(
            select(AgentRun)
            .where(AgentRun.id == run_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if run.status in ACTIVE:
            run.status, run.completed_at = "CANCELLED", datetime.now(UTC)
            run.lease_until = run.lease_token = None
            event(self.session, run, "CANCELLED", {})
        return run_view(run)


def fenced(session, run_id, token, *, deadline=True):
    run = session.scalar(
        select(AgentRun)
        .where(AgentRun.id == run_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    now = datetime.now(UTC)
    if (
        run is None
        or run.status != "RUNNING"
        or run.lease_token != token
        or run.lease_until is None
        or run.lease_until <= now
    ):
        raise BusinessError("RUN_LEASE_LOST", 409)
    if deadline and run.deadline_at <= now:
        raise BusinessError("RUN_BUDGET_EXCEEDED", 409)
    actor = session.get(User, run.actor_id)
    conversation = session.get(Conversation, run.conversation_id)
    if (
        actor is None
        or actor.tenant_id != run.tenant_id
        or not {"customer", "support"}.intersection(actor.roles)
        or conversation.owner_id != actor.id
    ):
        raise BusinessError("FORBIDDEN", 403)
    return run
