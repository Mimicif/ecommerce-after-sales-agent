"""M4 contracts use real PG; scripted graph checks are explicitly not live scores."""

import json

import pytest
from app.agent_schemas import FactClaim
from app.clock import FixtureClock
from app.config import ROOT
from app.eval_score import EXPECTED_KEYS
from app.evaluation import requests_for, trial
from app.grounding import grounded_text, positive_status_text, same_value, verified
from app.models import PolicyChunk
from app.retrieval import rebuild_index
from app.tools import ReadTools
from sqlalchemy import select, text


def scenarios(name="scenarios.jsonl"):
    return [
        json.loads(line)
        for line in (ROOT / "evals" / name).read_text(encoding="utf-8").splitlines()
    ]


CONTRACTS = json.loads((ROOT / "evals/request_contracts.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "query,chunk",
    [
        ("不合适七天能退吗", "A-RETURN-01"),
        ("定制易腐商品", "A-RETURN-02"),
        ("摘要确认有效期15分钟", "A-CONFIRM-01"),
        ("退款审核仓库收货对账", "A-REFUND-01"),
    ],
)
def test_chinese_retrieval_relevant_first(database, query, chunk):
    tool = ReadTools(database[2], actor_id="C-A1", clock=FixtureClock())
    result = tool.call(
        "search_policy",
        {"order_id": "O-A101", "intent": "RETURN_REFUND", "query": query, "top_k": 1},
    )
    assert result["ok"], result
    assert result["data"]["clauses"][0]["chunk_id"] == chunk
    assert result["data"]["retrieval_mode"] == "keyword_v1"
    assert len(result["data"]["candidates"]) == 4
    assert all(
        c["chunk_id"].startswith("A-") and c["chunk_id"] != "A-OLD-01"
        for c in result["data"]["candidates"]
    )
    # Ranking cannot change the rule engine's complete policy snapshot.
    assert (
        tool.call("check_eligibility", {"order_id": "O-A101", "case_type": "RETURN_REFUND"})[
            "data"
        ]["eligibility"]
        == "eligible"
    )


def test_stale_index_fail_closed_then_trusted_rebuild(database):
    with database[2]() as session, session.begin():
        session.scalar(
            select(PolicyChunk).where(PolicyChunk.chunk_id == "A-RETURN-01")
        ).text = "错误索引文本"
    tool = ReadTools(database[2], actor_id="C-A1", clock=FixtureClock())
    result = tool.call("search_policy", {"order_id": "O-A101", "intent": "RETURN_REFUND"})
    assert result["code"] == "POLICY_UNAVAILABLE"
    assert result["data"]["reason_codes"] == ["POLICY_INDEX_STALE"]
    assert (
        tool.call("check_eligibility", {"order_id": "O-A101", "case_type": "RETURN_REFUND"})[
            "data"
        ]["eligibility"]
        == "eligible"
    )
    with database[2]() as session, session.begin():
        assert rebuild_index(session) > 0
    assert tool.call("search_policy", {"order_id": "O-A101", "intent": "RETURN_REFUND"})["ok"]


def test_policy_index_tenant_foreign_key(database):
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError), database[2]() as session, session.begin():
        session.add(
            PolicyChunk(
                policy_version="POLICY-A-2026-10-v1",
                tenant_id="TENANT-B",
                chunk_id="B-FORGED",
                intent="ALL",
                text="不能混入其他租户",
            )
        )
        session.flush()


@pytest.mark.parametrize("top_k", [0, 7, True, "3"])
def test_invalid_retrieval_parameter_rejected(database, top_k):
    result = ReadTools(database[2], actor_id="C-A1", clock=FixtureClock()).call(
        "search_policy", {"order_id": "O-A101", "intent": "RETURN_REFUND", "top_k": top_k}
    )
    assert result["code"] == "INVALID_ARGUMENT"


def test_fact_money_type_resource_and_timezone():
    observation = {
        "kind": "ORDER",
        "resource_id": "O-A101",
        "field": "paid_amount_fen",
        "value": 14900,
    }
    assert verified(observation, [observation])
    assert not verified({**observation, "resource_id": "O-A108"}, [observation])
    assert not verified({**observation, "value": "14900"}, [observation])
    assert not same_value("version", True, 1)
    assert same_value("delivered_at", "2026-10-09T02:00:00Z", "2026-10-09T10:00:00+08:00")
    assert not same_value("delivered_at", "2026-10-09T02:00:00", "2026-10-09T02:00:00Z")
    assert grounded_text("149.00元", [observation])
    assert not grounded_text("149.01元", [observation])
    assert not grounded_text("签收2026-10-08", [observation])
    assert FactClaim(
        kind="POLICY",
        resource_id="POLICY-A-2026-10-v1",
        field="all_refunds_require_review",
        value=True,
    )


@pytest.mark.parametrize(
    "answer,affirmative",
    [
        ("草稿≠已提交，需要确认。", False),
        ("已退款0元，尚未提交申请。", False),
        ("收货后才可报告模拟退款成功。", False),
        ("只有对账成功才能报告退款成功。", False),
        ("审核通过后才能退款成功；当前仍需审核。", False),
        ("已审核通过。退款成功。", True),
        ("当前退款成功，已提交。", True),
        ("若不成功则人工处理。当前退款成功。", True),
        ("只有对账成功才能报告退款成功，当前退款成功。", True),
        ("只有模拟支付对账成功，才能报告模拟退款成功。", False),
        ("只有在模拟支付对账成功之后，才能说模拟退款成功。", False),
        ("收货并审核通过、对账成功后才会显示退款成功。", False),
        ("因此“退款成功”不能仅凭申请就宣称，需对账。", False),
    ],
)
def test_status_guard_distinguishes_conditions_from_completed_state(answer, affirmative):
    value = positive_status_text(answer)
    assert any(term in value for term in ["已提交", "退款成功", "已审核通过"]) is affirmative


def test_all_oracles_supported_and_inputs_do_not_contain_oracle():
    for scenario in scenarios() + scenarios("holdout_v1.jsonl") + scenarios("holdout_v2.jsonl"):
        assert not set(scenario["expected"]) - EXPECTED_KEYS
        if scenario["level"] == "agent":
            requests = requests_for(scenario, CONTRACTS)
            assert not any("expected" in request for request in requests)
    assert len(scenarios()) == 36
    assert len(scenarios("holdout_v1.jsonl")) == 24
    assert len(scenarios("holdout_v2.jsonl")) == 24


def test_manual_consent_second_turn():
    for scenario in scenarios():
        if scenario["case_id"] in {"S15", "S16", "S18"}:
            first, second = requests_for(scenario, CONTRACTS)
            assert first["action"] == "CONSULT"
            assert second["action"] == "CREATE_TICKET" and "同意" in second["content"]


def test_offline_refuses_to_fabricate_live_agent_score():
    with pytest.raises(ValueError, match="Live model required"):
        trial(scenarios()[0], "B2", CONTRACTS)


@pytest.mark.parametrize("repair_calls,code", [(False, None), (True, "MODEL_RESPONSE_INVALID")])
def test_final_repair_has_no_business_tools_and_is_bounded(database, repair_calls, code):
    from app.agent import AgentWorker
    from app.agent_schemas import ConversationInput, MessageInput
    from app.agent_store import ConversationService
    from app.models import AfterSalesCase, RunEvent
    from sqlalchemy import func

    with database[2]() as session, session.begin():
        service = ConversationService(session, "C-A1", FixtureClock(), "repair-test")
        conversation = service.create(ConversationInput(), "repair-conversation")
        service.message(
            conversation["conversation_id"],
            MessageInput(
                client_message_id="repair-message",
                content="查询O-A101金额",
                action="APPLY_AFTER_SALES",
                target_order_id="O-A101",
            ),
        )

    class RepairModel:
        provider, model_id, final_repair = "FAKE", "offline-repair-contract", True
        calls = 0

        def complete(self, messages, tools, timeout):
            self.calls += 1
            base = {"model": self.model_id, "usage": {}, "calls": [], "content": ""}
            if self.calls == 1:
                return {
                    **base,
                    "calls": [
                        {"id": "read", "name": "get_order", "arguments": {"order_id": "O-A101"}}
                    ],
                }
            if self.calls == 2:
                return {**base, "content": "This malformed output must not be silently accepted"}
            assert self.calls == 3 and tools == []
            if repair_calls:
                return {
                    **base,
                    "calls": [
                        {
                            "id": "write",
                            "name": "create_case_draft",
                            "arguments": {
                                "order_id": "O-A101",
                                "case_type": "RETURN_REFUND",
                                "reason": "禁止修复阶段写入",
                            },
                        }
                    ],
                }
            return {
                **base,
                "content": json.dumps(
                    {
                        "answer": "实付149元。",
                        "needs_input": False,
                        "citations": [],
                        "facts": [
                            {
                                "kind": "ORDER",
                                "resource_id": "O-A101",
                                "field": "paid_amount_fen",
                                "value": 14900,
                            }
                        ],
                    }
                ),
            }

    result = AgentWorker(database[2], RepairModel(), FixtureClock()).run_once()
    assert result["error_code"] == code, result
    assert result["model_calls"] == 3
    assert result["status"] == ("FAILED" if repair_calls else "COMPLETED")
    with database[2]() as session:
        assert session.scalar(select(func.count()).select_from(AfterSalesCase)) == 0
        assert (
            session.scalar(
                select(func.count()).select_from(RunEvent).where(RunEvent.kind == "FINAL_REPAIR")
            )
            == 1
        )


def test_m4_migration_roundtrip_preserves_original_policy(database):
    from alembic import command
    from alembic.config import Config

    config = Config(str(ROOT / "alembic.ini"))
    with database[2]() as session:
        before = session.scalar(text("SELECT count(*) FROM policy_chunks"))
    command.downgrade(config, "0004_m3")
    command.upgrade(config, "head")
    with database[2]() as session:
        assert session.scalar(text("SELECT count(*) FROM policy_chunks")) == before
        assert session.scalar(text("SELECT version_num FROM alembic_version")) == "0005_m4"


@pytest.mark.parametrize(
    "scenario", [s for s in scenarios() if s["level"] != "agent"], ids=lambda s: s["case_id"]
)
def test_development_deterministic_scenario_contracts(scenario):
    result = trial(scenario, "SHARED", CONTRACTS)
    assert result["score"]["success"], result["score"]
