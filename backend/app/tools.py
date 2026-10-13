"""Five read-only tool contracts. Caller supplies verified context outside model arguments."""

from uuid import uuid4

from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.clock import Clock
from app.errors import BusinessError
from app.reads import ReadService
from app.schemas import EligibilityInput, ListOrdersInput, OrderInput, PolicyInput

TOOL_SCHEMA_VERSION = "tools-v2-m4"
CONTRACTS = {
    "list_my_orders": (ListOrdersInput, "列出当前身份可访问的订单，最多20条，只读。"),
    "get_order": (OrderInput, "查询有权限的订单事实与整数分金额，不提交售后。"),
    "get_logistics": (OrderInput, "读取物流轨迹与可能异常信号；未知不代表丢件。"),
    "search_policy": (
        PolicyInput,
        "先过滤本租户有效政策和意图，再以中文query检索，默认top_k=3；返回真实引用。",
    ),
    "check_eligibility": (EligibilityInput, "只读检查申请规则；eligible不等于已提交或已批准退款。"),
}


def definitions():
    return [
        {"name": name, "description": description, "parameters": model.model_json_schema()}
        for name, (model, description) in CONTRACTS.items()
    ]


class ReadTools:
    def __init__(self, sessions, *, actor_id: str, clock: Clock):
        self.sessions, self.actor_id, self.clock = sessions, actor_id, clock

    def call(self, name: str, arguments: dict) -> dict:
        trace_id = uuid4().hex

        def response(ok, code, data, retryable=False):
            return {
                "ok": ok,
                "code": code,
                "data": data,
                "retryable": retryable,
                "trace_id": trace_id,
            }

        if not isinstance(name, str) or name not in CONTRACTS or not isinstance(arguments, dict):
            return response(False, "INVALID_ARGUMENT", {})
        try:
            args = CONTRACTS[name][0].model_validate(arguments)
        except ValidationError:
            return response(False, "INVALID_ARGUMENT", {})
        try:
            with self.sessions() as session:
                session.execute(text("SET TRANSACTION READ ONLY"))
                service = ReadService(session, self.actor_id, self.clock)
                if name == "list_my_orders":
                    data = service.list_orders(args)
                elif name == "get_order":
                    data = service.get_order(args.order_id)
                elif name == "get_logistics":
                    data = service.get_logistics(args.order_id)
                elif name == "search_policy":
                    data = service.search_policy(args)
                else:
                    data = service.check_eligibility(args)
                return response(True, "OK", data.model_dump(mode="json"))
        except BusinessError as exc:
            return response(False, exc.code, exc.data, exc.retryable)
        except SQLAlchemyError:
            # The isolated session closes and rolls back before a later retry.
            return response(False, "DATABASE_UNAVAILABLE", {}, True)
