"""Isolated scenario runner. The oracle is used only after execution for scoring."""

import time
from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.agent import AgentWorker
from app.agent_model import DeepSeekModel
from app.agent_schemas import FinalAnswer
from app.eval_baseline import FormBaseline
from app.eval_driver import (
    Driver,
    EvalClock,
    LoopContractModel,
    ToolFault,
    apply_overrides,
    isolated_database,
)
from app.eval_score import score, snapshot
from app.grounding import observed_facts
from app.main import create_app
from app.models import AgentInvocation, RunEvent
from app.seed import parse_time


def requests_for(scenario, contracts):
    spec = scenario["input"]
    contract = contracts["requests"].get(scenario["case_id"], {})
    first = {
        "content": spec["message"],
        "action": spec.get("agent_action", contract.get("action", "CONSULT")),
    }
    target = spec.get("target_order_id", contract.get("target_order_id"))
    if target:
        first["target_order_id"] = target
    return [first, *contract.get("followups", [])]


def gather_run(factory, run, evidence):
    evidence["run_status"], evidence["error_code"] = run["status"], run["error_code"]
    response = run.get("response")
    if response:
        evidence["responses"].append(
            {**response, "needs_input": run["status"] == "WAITING_FOR_USER"}
        )
        evidence["citations"].extend(response.get("citations", []))
    with factory() as session:
        events = session.scalars(
            select(RunEvent).where(RunEvent.run_id == run["run_id"]).order_by(RunEvent.seq)
        ).all()
        evidence["events"].extend(
            {"run_id": run["run_id"], "seq": e.seq, "kind": e.kind, "data": e.data} for e in events
        )
        for event in events:
            if event.kind == "TOOL_RESULT" and event.data["result"]["ok"]:
                data = event.data["result"]["data"]
                evidence["business_data"].append(data)
                evidence["observations"].extend(
                    observed_facts(event.data["name"], event.data["arguments"], data)
                )
                if event.data["name"] == "search_policy":
                    evidence["retrieved"].extend(c["chunk_id"] for c in data["clauses"])
                    evidence["available_citations"].extend(c["citation"] for c in data["clauses"])
            if event.kind == "MODEL_RESULT":
                for key, value in event.data["usage"].items():
                    evidence["tokens"][key] = evidence["tokens"].get(key, 0) + value
        invocations = session.scalars(
            select(AgentInvocation).where(
                AgentInvocation.run_id == run["run_id"], AgentInvocation.kind == "MODEL"
            )
        ).all()
        for invocation in invocations:
            result = invocation.result
            if result and result["content"] and not result["calls"]:
                try:
                    final = FinalAnswer.model_validate_json(result["content"])
                except ValueError:
                    continue
                evidence["claims"].extend(c.model_dump() for c in final.facts)
                # Failed grounding/citation assertions stay in the denominator.
                if not response:
                    evidence["citations"].extend(final.citations)
        evidence["model_outputs"].extend({"step": i.step, "result": i.result} for i in invocations)


def trial(scenario, baseline, contracts, *, live=False):
    faults = scenario.get("faults", [])
    known = {
        ("get_logistics", "timeout_before_response"),
        ("mock_payment", "commit_success_then_response_timeout"),
        ("mock_payment", "timeout_before_submit"),
        ("refund_worker", "crash_after_provider_success_before_local_commit"),
        ("llm", "repeated_read_tool_calls_until_budget"),
    }
    if any((f["target"], f["mode"]) not in known or f["occurrences"] < 1 for f in faults):
        raise ValueError("Unsupported fault specification")
    contract_model = any(f["target"] == "llm" for f in faults)
    if scenario["level"] == "agent" and baseline != "B0" and not live and not contract_model:
        raise ValueError("Live model required; offline cannot fabricate Agent task results")
    evidence = {
        k: []
        for k in [
            "responses",
            "citations",
            "available_citations",
            "retrieved",
            "observations",
            "claims",
            "business_data",
            "events",
            "model_outputs",
        ]
    }
    evidence.update(tokens={}, extra={}, run_status=None, error_code=None)
    with isolated_database() as (settings, factory):
        clock = EvalClock(parse_time(scenario.get("override_now", "2026-10-11T10:00:00+08:00")))
        apply_overrides(factory, scenario)
        with TestClient(create_app(settings, clock=clock), client=("127.0.0.1", 51000)) as client:
            driver = Driver(client, factory, clock, scenario["actor"])
            driver.setup(scenario.get("setup_steps", []))
            started = time.monotonic()
            if scenario["level"] != "agent":
                response = driver.api_action(scenario["input"], faults)
                if response is not None:
                    payload = response.json()
                    evidence["last_http"] = {
                        "http_status": response.status_code,
                        "code": payload["code"],
                    }
                    if response.is_success:
                        data = payload["data"]
                        name = scenario["input"]["action"]
                        evidence["observations"].extend(
                            observed_facts(name, scenario["input"], data)
                        )
                        evidence["business_data"].append(data)
                evidence["claims"] = list(evidence["observations"])
                evidence["mode"] = "DETERMINISTIC_API"
            elif baseline == "B0":
                form = FormBaseline(driver, ToolFault(faults))
                for request in requests_for(scenario, contracts):
                    form.turn(request)
                evidence.update(
                    observations=form.observations,
                    claims=form.observations,
                    responses=form.responses,
                    citations=form.citations,
                    available_citations=form.citations,
                    retrieved=form.retrieved,
                    mode="FORM",
                )
            else:
                model = LoopContractModel() if contract_model else DeepSeekModel(settings)
                conversation = driver.ok("/conversations", {})
                fault = ToolFault(faults)
                for index, request in enumerate(requests_for(scenario, contracts)):
                    if baseline == "B1":
                        request = {"content": request["content"], "action": "CONSULT"}
                    driver.ok(
                        f"/conversations/{conversation['conversation_id']}/messages",
                        {"client_message_id": f"eval-message-{index:04d}", **request},
                    )
                    run = AgentWorker(
                        factory, model, clock, read_only=baseline == "B1", tool_fault=fault
                    ).run_once()
                    gather_run(factory, run, evidence)
                    # Simulate opening the real customer confirmation card, never consenting.
                    for case in (run.get("response") or {}).get("cases", []):
                        if case["status"] == "DRAFT":
                            driver.summary(case)
                    evidence.setdefault("runs", []).append(run)
                evidence["mode"] = "FAULT_CONTRACT" if contract_model else "LIVE"
                evidence["provider"], evidence["model_id"] = model.provider, model.model_id
                evidence["model_calls"] = sum(r["model_calls"] for r in evidence["runs"])
                evidence["tool_calls"] = sum(r["tool_calls"] for r in evidence["runs"])
                evidence["usage_reported_calls"] = sum(
                    e["kind"] == "MODEL_RESULT" for e in evidence["events"]
                )
            evidence["latency_ms"] = round((time.monotonic() - started) * 1000)
            evidence["extra"], evidence["http_trace"] = driver.extra, driver.trace
            db = snapshot(factory)
            result = score(scenario, evidence, db, factory, clock)
            # DB dump contains only simulated IDs/status/money, no secrets or full personal data.
            evidence["database"] = db
    return {
        "case_id": scenario["case_id"],
        "title": scenario["title"],
        "level": scenario["level"],
        "tags": scenario["tags"],
        "baseline": baseline,
        "timestamp": datetime.now(UTC).isoformat(),
        "score": result,
        "evidence": evidence,
    }


def json_default(value):
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError("Unsupported report value")


def summary(results):
    groups = {}
    for result in results:
        mode = result["evidence"]["mode"]
        key = result["baseline"] + "/" + mode
        groups.setdefault(key, []).append(result)
    output = {}
    for key, rows in groups.items():
        scores = [r["score"] for r in rows]
        timings = sorted(r["evidence"]["latency_ms"] for r in rows)
        import math

        tokens = {}
        for row in rows:
            for name, value in row["evidence"]["tokens"].items():
                tokens[name] = tokens.get(name, 0) + value
        hit = tokens.get("prompt_cache_hit_tokens", 0)
        miss = tokens.get("prompt_cache_miss_tokens", tokens.get("prompt_tokens", 0) - hit)
        completion = tokens.get("completion_tokens", 0)

        def rate(numerator, denominator):
            return numerator / denominator if denominator else None

        output[key] = {
            "tasks": len(rows),
            "successes": sum(s["success"] for s in scores),
            "task_success_rate": rate(sum(s["success"] for s in scores), len(rows)),
            "hard_violations": sum(len(s["hard_violations"]) for s in scores),
            "fact_correct": sum(s["fact_correct"] for s in scores),
            "fact_total": sum(s["fact_total"] for s in scores),
            "fact_accuracy": rate(
                sum(s["fact_correct"] for s in scores), sum(s["fact_total"] for s in scores)
            ),
            "citation_accuracy": rate(
                sum(s["citation_correct"] for s in scores), sum(s["citation_total"] for s in scores)
            ),
            "retrieval_coverage": rate(
                sum(s["retrieval_covered"] and s["retrieval_required"] for s in scores),
                sum(s["retrieval_required"] for s in scores),
            ),
            "p50_ms": timings[math.ceil(0.5 * len(timings)) - 1],
            "p95_ms": timings[math.ceil(0.95 * len(timings)) - 1],
            "tokens": tokens,
            "model_calls": sum(
                sum(run["model_calls"] for run in r["evidence"].get("runs", [])) for r in rows
            ),
            "tool_calls": sum(
                sum(run["tool_calls"] for run in r["evidence"].get("runs", [])) for r in rows
            ),
            "usage_reported_calls": sum(
                sum(e["kind"] == "MODEL_RESULT" for e in r["evidence"]["events"]) for r in rows
            ),
            "cost_scope": (
                "Recorded usage only; requests failing before usage persistence may still be billed"
            ),
            "estimated_cost_usd_range": [
                (hit * 0.003 + miss * 0.15 + completion * 0.60) / 1e6,
                (hit * 0.006 + miss * 0.30 + completion * 1.20) / 1e6,
            ]
            if tokens
            else None,
            "failures": [
                {
                    "case_id": r["case_id"],
                    "repeat_index": r["repeat_index"],
                    "failed_checks": [k for k, v in r["score"]["checks"].items() if not v],
                    "error_code": r["evidence"].get("error_code"),
                }
                for r in rows
                if not r["score"]["success"]
            ],
        }
    return output
