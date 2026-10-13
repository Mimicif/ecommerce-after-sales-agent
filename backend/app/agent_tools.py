import json

from pydantic import ValidationError

from app.agent_schemas import CaseInput, SubmitCaseInput, TicketReadInput
from app.agent_store import TOOL_VERSION, event, fenced, redact
from app.errors import BusinessError
from app.models import AgentInvocation
from app.tools import CONTRACTS, ReadTools
from app.write_schemas import DraftInput, TicketInput, VersionInput
from app.writes import WriteService, payload_digest

AGENT_CONTRACTS = {
    **CONTRACTS,
    "create_case_draft": (DraftInput, "创建草稿，必须明确申请；未确认、未提交、未审批。"),
    "get_case": (CaseInput, "读取申请的实际状态、版本及金额。"),
    "submit_case": (SubmitCaseInput, "仅提交已通过独立客户确认接口确认的当前版本申请。"),
    "create_support_ticket": (TicketInput, "明确要求转人工时创建物流或售后人工工单。"),
    "get_support_ticket": (TicketReadInput, "读取人工工单的实际状态。"),
}
WRITE_ACTIONS = {
    "create_case_draft": "APPLY_AFTER_SALES",
    "submit_case": "SUBMIT_CONFIRMED",
    "create_support_ticket": "CREATE_TICKET",
}


def definitions():
    return [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": schema.model_json_schema(),
            },
        }
        for name, (schema, description) in AGENT_CONTRACTS.items()
    ]


def validated(call):
    name, arguments = call.get("name"), call.get("arguments")
    if name not in AGENT_CONTRACTS or not isinstance(arguments, dict):
        return None
    try:
        return AGENT_CONTRACTS[name][0].model_validate(arguments)
    except ValidationError:
        return None


def normalized_call(call):
    args = validated(call)
    # Invalid extras and malformed strings may contain secrets: never save those values.
    return {
        "id": call["id"],
        "name": call["name"] if call["name"] in AGENT_CONTRACTS else "INVALID_TOOL",
        "arguments": redact(args.model_dump(mode="json")) if args else None,
    }


class AgentTools:
    def __init__(self, sessions, run_id, token, clock, *, fault=None):
        self.sessions, self.run_id, self.token, self.clock = sessions, run_id, token, clock
        self.fault = fault

    def call(self, call, step):
        name, args = call["name"], validated(call)
        request = {"name": name, "arguments": args.model_dump(mode="json") if args else None}
        digest = payload_digest(request)
        with self.sessions() as session, session.begin():
            run = fenced(session, self.run_id, self.token)
            key = (run.id, "TOOL", step)
            previous = session.get(AgentInvocation, key)
            if previous:
                if previous.request_digest != digest:
                    raise BusinessError("RUN_REPLAY_CONFLICT", 409)
                return previous.result
            if run.tool_calls >= 12:
                raise BusinessError("RUN_BUDGET_EXCEEDED", 409)
            run.tool_calls += 1
            code, data, retryable = "OK", {}, False
            try:
                if args is None:
                    raise BusinessError("INVALID_ARGUMENT", 422)
                if self.fault:
                    self.fault.before(name)
                if name in WRITE_ACTIONS and run.action != WRITE_ACTIONS[name]:
                    raise BusinessError("ACTION_NOT_AUTHORIZED", 403)
                # Business failure rolls back only this tool's state, preserving its error event.
                with session.begin_nested():
                    writer = WriteService(session, run.actor_id, self.clock, run.id)
                    if name in WRITE_ACTIONS:
                        target = (
                            writer.get_case(args.case_id)["order_id"]
                            if name == "submit_case"
                            else args.order_id
                        )
                        if run.target_order_id is None:
                            raise BusinessError("TARGET_ORDER_REQUIRED", 422)
                        if target != run.target_order_id:
                            raise BusinessError("TARGET_ORDER_MISMATCH", 409)
                    if name in CONTRACTS:
                        result = ReadTools(
                            self.sessions, actor_id=run.actor_id, clock=self.clock
                        ).call(name, args.model_dump(mode="json"))
                        code, data = result["code"], result["data"]
                        retryable = result["retryable"]
                    elif name == "get_case":
                        data = writer.get_case(args.case_id)
                    elif name == "get_support_ticket":
                        data = writer.get_ticket(args.ticket_id)
                    elif name == "create_case_draft":
                        data = writer.draft(args, f"AGENT:{run.id}:{step}")
                    elif name == "create_support_ticket":
                        data = writer.ticket(args, f"AGENT:{run.id}:{step}")
                    else:
                        data = writer.submit(
                            args.case_id,
                            VersionInput(expected_version=args.expected_version),
                            f"AGENT:{run.id}:{step}",
                        )
            except BusinessError as exc:
                code, data = exc.code, exc.data
                retryable = exc.retryable
            fenced(session, self.run_id, self.token)
            result = {
                "ok": code == "OK",
                "code": code,
                "data": redact(data),
                "tool_version": TOOL_VERSION,
                "retryable": retryable,
                "trace_id": run.id,
            }
            session.add(
                AgentInvocation(
                    run_id=run.id, kind="TOOL", step=step, request_digest=digest, result=result
                )
            )
            event(
                session,
                run,
                "TOOL_RESULT",
                {
                    "step": step,
                    "name": name,
                    "arguments": redact(request["arguments"]),
                    "result": result,
                },
            )
            session.flush()
            return result


def tool_message(call, result):
    return {
        "role": "tool",
        "tool_call_id": call["id"],
        "content": json.dumps(result, ensure_ascii=False),
    }
