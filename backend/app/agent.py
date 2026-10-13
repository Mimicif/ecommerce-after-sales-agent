"""One LangGraph agent, PostgreSQL worker and bounded, auditable tool execution."""

import json
import re
import time
from datetime import UTC, datetime, timedelta
from typing import TypedDict
from uuid import uuid4

from langgraph.graph import END, START, StateGraph
from langsmith import tracing_context
from pydantic import ValidationError
from sqlalchemy import and_, or_, select

from app.agent_checkpoint import PostgresRunSaver
from app.agent_schemas import FinalAnswer
from app.agent_store import event, fenced, redact, run_view
from app.agent_tools import AgentTools, definitions, normalized_call, tool_message
from app.config import ROOT
from app.errors import BusinessError
from app.grounding import grounded_text, observed_facts, positive_status_text, verified
from app.models import AgentInvocation, AgentRun, ChatMessage, Conversation
from app.writes import WriteService, identifier, payload_digest

PROMPT = (ROOT / "backend/app/prompts/system_m4.txt").read_text(encoding="utf-8")


class AgentState(TypedDict):
    messages: list[dict]
    round: int
    decision: dict
    errors: int
    cases: list[str]
    tickets: list[str]
    citations: list[str]
    observations: list[dict]
    response: dict
    status: str
    repair: bool


class AgentWorker:
    def __init__(
        self, sessions, model, clock, *, crash_after_tool=False, read_only=False, tool_fault=None
    ):
        self.sessions, self.model, self.clock = sessions, model, clock
        self.crash_after_tool = crash_after_tool
        self.read_only, self.tool_fault = read_only, tool_fault

    def claim(self):
        now = datetime.now(UTC)
        with self.sessions() as session, session.begin():
            run = session.scalar(
                select(AgentRun)
                .where(
                    or_(
                        AgentRun.status == "QUEUED",
                        and_(AgentRun.status == "RUNNING", AgentRun.lease_until <= now),
                    )
                )
                .order_by(AgentRun.created_at)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if run is None:
                return None
            run.status, run.lease_token = "RUNNING", uuid4().hex
            run.lease_until = now + timedelta(seconds=15)
            if run.deadline_at is None:
                run.deadline_at = now + timedelta(seconds=45)
            if run.provider is None:
                run.provider, run.model = self.model.provider, self.model.model_id
            event(
                session,
                run,
                "RUNNING",
                {"provider": run.provider, "model": run.model, "resumed": run.model_calls > 0},
            )
            return run.id, run.lease_token

    def renew(self, run_id, token):
        with self.sessions() as session, session.begin():
            run = fenced(session, run_id, token)
            run.lease_until = min(run.deadline_at, datetime.now(UTC) + timedelta(seconds=15))

    def model_node(self, run_id, token, state):
        self.renew(run_id, token)
        step = str(state["round"])
        with self.sessions() as session, session.begin():
            run = fenced(session, run_id, token)
            if (run.provider, run.model) != (self.model.provider, self.model.model_id):
                raise BusinessError("MODEL_RESUME_MISMATCH", 409)
            messages = [
                {
                    "role": "system",
                    "content": PROMPT
                    + "\n本次可信action="
                    + run.action
                    + "\n客户选择的目标订单="
                    + (run.target_order_id or "未选择；写入时须补选订单"),
                },
                *state["messages"],
            ]
            digest = payload_digest({"messages": messages})
            key = (run_id, "MODEL", step)
            invocation = session.get(AgentInvocation, key)
            if invocation and invocation.request_digest != digest:
                raise BusinessError("RUN_REPLAY_CONFLICT", 409)
            if invocation and invocation.result is not None:
                return {"decision": invocation.result}
            if run.model_calls >= 8:
                raise BusinessError("RUN_BUDGET_EXCEEDED", 409)
            run.model_calls += 1
            if invocation is None:
                session.add(
                    AgentInvocation(
                        run_id=run_id, kind="MODEL", step=step, request_digest=digest, result=None
                    )
                )
            timeout = min(10.0, (run.deadline_at - datetime.now(UTC)).total_seconds())
        started = time.monotonic()
        offered = definitions()
        if self.read_only:
            offered = [
                tool
                for tool in offered
                if tool["function"]["name"]
                not in {"create_case_draft", "submit_case", "create_support_ticket"}
            ]
        if state.get("repair"):
            offered = []
        result = self.model.complete(messages, offered, timeout)
        result = {**result, "calls": [normalized_call(call) for call in result["calls"]]}
        with self.sessions() as session, session.begin():
            run = fenced(session, run_id, token)
            invocation = session.get(AgentInvocation, key)
            invocation.result = redact(result)
            event(
                session,
                run,
                "MODEL_RESULT",
                {
                    "round": state["round"],
                    "model": result["model"],
                    "usage": result["usage"],
                    "latency_ms": round((time.monotonic() - started) * 1000),
                    "tool_names": [call["name"] for call in result["calls"]],
                    "input_ref": {"message_id": run.input_message_id, "round": state["round"]},
                    "output_ref": {"run_id": run.id, "kind": "MODEL", "step": step},
                },
            )
        return {"decision": result}

    def tools_node(self, run_id, token, state):
        if state.get("repair"):
            raise BusinessError("MODEL_RESPONSE_INVALID", 503)
        self.renew(run_id, token)
        calls = state["decision"]["calls"]
        assistant = {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": call["id"],
                    "type": "function",
                    "function": {
                        "name": call["name"],
                        "arguments": json.dumps(call["arguments"], ensure_ascii=False),
                    },
                }
                for call in calls
            ],
        }
        messages = [*state["messages"], assistant]
        cases, tickets, citations = (
            set(state["cases"]),
            set(state["tickets"]),
            set(state["citations"]),
        )
        errors = state["errors"]
        observations = list(state["observations"])
        created_draft = False
        for index, call in enumerate(calls):
            if created_draft:
                result = {"ok": False, "code": "WAITING_FOR_CUSTOMER", "data": {}}
            else:
                result = AgentTools(
                    self.sessions, run_id, token, self.clock, fault=self.tool_fault
                ).call(call, f"{state['round']}:{index}")
            if self.crash_after_tool:
                # Test-only process-loss seam: durable effect exists, graph node not checkpointed.
                raise SimulatedAgentCrash()
            messages.append(tool_message(call, result))
            if not result["ok"]:
                if result["code"] == "POLICY_UNAVAILABLE" and not result.get("retryable"):
                    messages.append(
                        {
                            "role": "system",
                            "content": (
                                "后端已返回不可重试的POLICY_UNAVAILABLE。本run不要再次search_policy，"
                                "换query也无效。不能补造政策或创建售后草稿。"
                                "若本次可信action为CREATE_TICKET且目标已授权，可按客户明确诉求直接创建"
                                "MANUAL_AFTER_SALES工单；CONSULT则说明政策不可用并询问客户是否转人工。"
                            ),
                        }
                    )
                errors += 1
                if errors > 1:
                    raise BusinessError("TOOL_CORRECTION_EXHAUSTED", 409)
            else:
                data = result["data"]
                observations.extend(observed_facts(call["name"], call["arguments"], data))
                if call["name"] in {"get_case", "create_case_draft", "submit_case"}:
                    cases.add(data["id"])
                if call["name"] in {"get_support_ticket", "create_support_ticket"}:
                    tickets.add(data["id"])
                if call["name"] == "search_policy":
                    citations.update(item["citation"] for item in data.get("clauses", []))
                created_draft = call["name"] == "create_case_draft"
        update = {
            "messages": messages,
            "round": state["round"] + 1,
            "errors": errors,
            "cases": sorted(cases),
            "tickets": sorted(tickets),
            "citations": sorted(citations),
            "observations": observations,
        }
        if created_draft:
            update["decision"] = {
                "calls": [],
                "content": json.dumps(
                    {
                        "answer": "草稿已创建，请通过独立客户接口生成确认摘要并确认后再提交。",
                        "needs_input": True,
                        "citations": sorted(citations),
                    },
                    ensure_ascii=False,
                ),
            }
            update["status"] = "WAITING_FOR_USER"
        return update

    def respond_node(self, run_id, token, state):
        self.renew(run_id, token)
        try:
            answer = FinalAnswer.model_validate_json(state["decision"]["content"])
        except (ValidationError, ValueError):
            return self.repair_final(run_id, token, state, "MODEL_RESPONSE_INVALID")
        if set(answer.citations) - set(state["citations"]):
            return self.repair_final(run_id, token, state, "CITATION_UNVERIFIED")
        if any(not verified(claim.model_dump(), state["observations"]) for claim in answer.facts):
            return self.repair_final(run_id, token, state, "FACT_UNVERIFIED")
        if not grounded_text(answer.answer, [c.model_dump() for c in answer.facts]):
            return self.repair_final(run_id, token, state, "FACT_UNVERIFIED")
        with self.sessions() as session, session.begin():
            run = fenced(session, run_id, token)
            writer = WriteService(session, run.actor_id, self.clock, run_id)
            cards = [writer.get_case(case_id) for case_id in state["cases"]]
            tickets = [writer.get_ticket(ticket_id) for ticket_id in state["tickets"]]
        # Free text may describe only observed states. Amount/state cards remain authoritative.
        states = {card["status"] for card in cards}
        positive = positive_status_text(answer.answer)
        guards = [
            (r"退款成功|已退款|已退[回款]|钱已到账", {"REFUNDED"}),
            (
                r"审核通过|已批准",
                {"AWAITING_RETURN", "READY_TO_REFUND", "REFUND_PENDING", "REFUNDED"},
            ),
            (r"已收货", {"READY_TO_REFUND", "REFUND_PENDING", "REFUNDED"}),
            (
                r"提交成功|已提交",
                {
                    "PENDING_REVIEW",
                    "AWAITING_RETURN",
                    "READY_TO_REFUND",
                    "REFUND_PENDING",
                    "REFUNDED",
                    "REJECTED",
                },
            ),
        ]
        if any(
            re.search(pattern, positive) and not states.intersection(allowed)
            for pattern, allowed in guards
        ):
            return self.repair_final(run_id, token, state, "UNVERIFIED_STATUS_CLAIM")
        return {
            "response": {
                "answer": redact(answer.answer),
                "citations": answer.citations,
                "cases": cards,
                "tickets": tickets,
                "simulated": True,
                "facts": [claim.model_dump() for claim in answer.facts],
            },
            "status": "WAITING_FOR_USER" if answer.needs_input else "COMPLETED",
        }

    def repair_final(self, run_id, token, state, code):
        if state.get("repair") or not getattr(self.model, "final_repair", False):
            raise BusinessError(code, 409 if code != "MODEL_RESPONSE_INVALID" else 503)
        with self.sessions() as session, session.begin():
            run = fenced(session, run_id, token)
            event(
                session,
                run,
                "FINAL_REPAIR",
                {"error_code": code, "remaining_model_budget": 8 - run.model_calls},
            )
        # No business tools during repair. Supply only already authorized observations/citations.
        instruction = (
            "最终输出校验失败："
            + code
            + "。仅输出四字段JSON。按以下已观察事实回答，不推算新金额/截止日期，不执行任何工具："
            + json.dumps(
                {"facts": state["observations"], "citations": state["citations"]},
                ensure_ascii=False,
            )
        )
        return {
            "repair": True,
            "round": state["round"] + 1,
            "status": "REPAIRING",
            "messages": [*state["messages"], {"role": "system", "content": instruction}],
        }

    def graph(self, run_id, token):
        graph = StateGraph(AgentState)
        graph.add_node("model", lambda state: self.model_node(run_id, token, state))
        graph.add_node("tools", lambda state: self.tools_node(run_id, token, state))
        graph.add_node("respond", lambda state: self.respond_node(run_id, token, state))
        graph.add_edge(START, "model")
        graph.add_conditional_edges(
            "model", lambda state: "tools" if state["decision"]["calls"] else "respond"
        )
        graph.add_conditional_edges(
            "tools",
            lambda state: "respond" if state.get("status") == "WAITING_FOR_USER" else "model",
        )
        graph.add_conditional_edges(
            "respond", lambda state: "model" if state["status"] == "REPAIRING" else END
        )
        return graph.compile(checkpointer=PostgresRunSaver(self.sessions, run_id, token))

    def finish(self, run_id, token, status, response=None, code=None):
        with self.sessions() as session, session.begin():
            candidate = session.get(AgentRun, run_id)
            # Match HTTP lock order: conversation before run.
            conversation = session.scalar(
                select(Conversation)
                .where(Conversation.id == candidate.conversation_id)
                .with_for_update()
            )
            run = session.scalar(
                select(AgentRun)
                .where(AgentRun.id == run_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if run.status != "RUNNING" or run.lease_token != token:
                return
            if run.lease_until <= datetime.now(UTC):
                return
            run.status, run.error_code, run.response = status, code, response
            run.completed_at = datetime.now(UTC)
            run.lease_token = run.lease_until = None
            if response:
                # Append authoritative cards to memory so a later turn can identify the draft.
                content = (
                    response["answer"]
                    + "\n服务端事实（上下文，勿仿写为最终输出格式）："
                    + json.dumps(
                        {"cases": response["cases"], "tickets": response["tickets"]},
                        ensure_ascii=False,
                    )
                )
                session.add(
                    ChatMessage(
                        id=identifier("MSG"),
                        conversation_id=conversation.id,
                        seq=conversation.next_seq,
                        role="assistant",
                        run_id=run_id,
                        content=content,
                        created_at=run.completed_at,
                    )
                )
                conversation.next_seq += 1
            event(session, run, status, {"error_code": code, "response": response})

    def run_once(self):
        claim = self.claim()
        if claim is None:
            return {"processed": False}
        run_id, token = claim
        try:
            self.renew(run_id, token)
            graph = self.graph(run_id, token)
            config = {"configurable": {"thread_id": run_id}, "recursion_limit": 40}
            with self.sessions() as session:
                run = session.get(AgentRun, run_id)
                incoming = session.get(ChatMessage, run.input_message_id)
                rows = session.scalars(
                    select(ChatMessage)
                    .where(
                        ChatMessage.conversation_id == run.conversation_id,
                        ChatMessage.seq <= incoming.seq,
                    )
                    .order_by(ChatMessage.seq.desc())
                    .limit(12)
                ).all()
                initial = {
                    "messages": [
                        {"role": row.role, "content": row.content} for row in reversed(rows)
                    ],
                    "round": 0,
                    "decision": {},
                    "errors": 0,
                    "cases": [],
                    "tickets": [],
                    "citations": [],
                    "observations": [],
                    "response": {},
                    "status": "",
                    "repair": False,
                }
            with tracing_context(enabled=False):
                saved = graph.get_state(config)
                output = graph.invoke(None if saved.values else initial, config, durability="sync")
            self.finish(run_id, token, output["status"], output["response"])
        except BusinessError as exc:
            self.finish(run_id, token, "FAILED", code=exc.code)
        except SimulatedAgentCrash:
            raise
        except Exception as exc:
            # Provider/graph/database exception text can include sensitive values.
            try:
                with self.sessions() as session, session.begin():
                    run = fenced(session, run_id, token)
                    event(
                        session,
                        run,
                        "INTERNAL_ERROR_CATEGORY",
                        {"exception_type": type(exc).__name__},
                    )
            except Exception:
                # Diagnostic persistence must not mask the original safe error.
                pass
            self.finish(run_id, token, "FAILED", code="RUN_INTERNAL_ERROR")
        with self.sessions() as session:
            return {"processed": True, **run_view(session.get(AgentRun, run_id))}


class SimulatedAgentCrash(Exception):
    pass
