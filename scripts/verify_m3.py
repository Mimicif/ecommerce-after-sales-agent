"""Read-only reconciliation of M3 offline, live, schema and simulated business evidence."""

import hashlib
import json
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.agent_tools import definitions  # noqa: E402
from app.config import Settings  # noqa: E402
from app.db import make_engine, make_session_factory  # noqa: E402
from app.main import create_app  # noqa: E402
from app.models import (  # noqa: E402
    AfterSalesCase,
    AgentInvocation,
    AgentRun,
    GraphCheckpoint,
    RefundJob,
    RefundTransaction,
    RunEvent,
)
from sqlalchemy import func, select, text  # noqa: E402


def main():
    folder = ROOT / "artifacts/m3"
    suites = list(ET.parse(folder / "pytest.xml").getroot().iter("testsuite"))
    assert all(int(s.attrib[key]) == 0 for s in suites for key in ["failures", "errors", "skipped"])
    tests = sum(int(s.attrib["tests"]) for s in suites)
    by_file = Counter(t.attrib["classname"] for s in suites for t in s.findall("testcase"))
    live = json.loads((folder / "live_clean.json").read_text(encoding="utf-8"))
    assert live["ok"] and live["mode"] == "LIVE" and all(live["checks"].values())
    initial = json.loads((folder / "live_initial_failure.json").read_text(encoding="utf-8"))
    assert initial["runs"][-1]["error_code"] == "MODEL_RESPONSE_INVALID"
    for name in ["m0_http_regression.json", "m1_http_regression.json", "m2_http_regression.json"]:
        assert json.loads((folder / name).read_text(encoding="utf-8"))["result"] == "PASS"
    settings = Settings()
    secret = settings.deepseek_api_key.get_secret_value()
    for path in [
        *folder.glob("*.json"),
        *folder.glob("*.xml"),
        *(ROOT / "docs/contracts").glob("m3*.json"),
    ]:
        assert secret not in path.read_text(encoding="utf-8"), "Sensitive value in evidence"
    app = create_app(settings)
    try:
        assert (
            json.loads((ROOT / "docs/contracts/m3_openapi.json").read_text(encoding="utf-8"))
            == app.openapi()
        )
        assert (
            json.loads((ROOT / "docs/contracts/m3_tools.json").read_text(encoding="utf-8"))
            == definitions()
        )
    finally:
        app.state.engine.dispose()
    engine = make_engine(settings)
    usage = Counter()
    runs_summary = []
    try:
        with make_session_factory(engine)() as session:
            session.execute(text("SET TRANSACTION READ ONLY"))
            assert session.scalar(text("SELECT version_num FROM alembic_version")) == "0004_m3"
            assert (
                session.scalar(text("SELECT rolsuper FROM pg_roles WHERE rolname=current_user"))
                is False
            )
            runs = list(
                session.scalars(
                    select(AgentRun)
                    .where(AgentRun.provider == "deepseek")
                    .order_by(AgentRun.created_at)
                )
            )
            for run in runs:
                assert run.model_calls <= 8 and run.tool_calls <= 12
                assert run.status not in {"QUEUED", "RUNNING"}
                assert (
                    session.scalar(
                        select(func.count())
                        .select_from(GraphCheckpoint)
                        .where(GraphCheckpoint.run_id == run.id)
                    )
                    > 0
                )
                events = list(
                    session.scalars(
                        select(RunEvent).where(RunEvent.run_id == run.id).order_by(RunEvent.seq)
                    )
                )
                assert [row.seq for row in events] == list(range(1, len(events) + 1))
                invocations = list(
                    session.scalars(
                        select(AgentInvocation).where(
                            AgentInvocation.run_id == run.id, AgentInvocation.kind == "MODEL"
                        )
                    )
                )
                for invocation in invocations:
                    if invocation.result:
                        assert "reasoning_content" not in invocation.result
                        assert secret not in json.dumps(invocation.result)
                        usage.update(invocation.result["usage"])
                runs_summary.append(
                    {
                        "run_id": run.id,
                        "status": run.status,
                        "error_code": run.error_code,
                        "model_calls": run.model_calls,
                        "tool_calls": run.tool_calls,
                    }
                )
            submitted = []
            for order_id in ["O-A102", "O-A108"]:
                case = session.scalar(
                    select(AfterSalesCase).where(AfterSalesCase.order_id == order_id)
                )
                assert case.status == "PENDING_REVIEW"
                assert (
                    session.scalar(
                        select(func.count())
                        .select_from(RefundJob)
                        .where(RefundJob.case_id == case.id)
                    )
                    == 0
                )
                assert (
                    session.scalar(
                        select(func.count())
                        .select_from(RefundTransaction)
                        .where(RefundTransaction.case_id == case.id)
                    )
                    == 0
                )
                submitted.append(
                    {
                        "case_id": case.id,
                        "order_id": order_id,
                        "status": case.status,
                        "requested_amount_fen": case.requested_amount_fen,
                    }
                )
            total = session.scalar(select(func.sum(RefundTransaction.amount_fen)))
            assert total == 23800
    finally:
        engine.dispose()
    probe_usage = {
        "prompt_tokens": 1729,
        "completion_tokens": 48,
        "total_tokens": 1777,
        "prompt_cache_hit_tokens": 0,
        "prompt_cache_miss_tokens": 1729,
    }
    cost_usage = usage + Counter(probe_usage)
    low = (
        cost_usage["prompt_cache_hit_tokens"] * 0.003
        + cost_usage["prompt_cache_miss_tokens"] * 0.15
        + cost_usage["completion_tokens"] * 0.6
    ) / 1_000_000
    report = {
        "result": "PASS",
        "checked_at": datetime.now(UTC).isoformat(),
        "versions": {
            "app": "0.4.0",
            "api": "api-v1-m3",
            "schema": "0004_m3",
            "tools": "tools-v1-m3",
            "prompt": "prompt-v1-m3",
            "domain": "domain-v1-m2",
            "fixtures": "fixtures-v1",
            "policy_schema": "policy-schema-v1",
        },
        "offline": {
            "mode": "FAKE scripted / real PostgreSQL",
            "passed": tests,
            "failed": 0,
            "skipped": 0,
            "by_file": dict(by_file),
            "duration_seconds": sum(float(s.attrib["time"]) for s in suites),
        },
        "live": {
            "provider": "deepseek",
            "model_id": "deepseek-flash",
            "official_model_version": "DeepSeek-V4.1-Flash",
            "checks": live["checks"],
            "runs": runs_summary,
            "usage": dict(usage),
            "capability_probe_usage": probe_usage,
            "probe_source": "Executed adapter probe; tool get_order; console metadata recorded",
            "estimated_cost_usd_range_including_probe": [round(low, 8), round(low * 2, 8)],
            "price_source": "https://api-docs.deepseek.com/quick_start/pricing/",
            "cost_note": "Official off-peak/peak token estimate; not a billing receipt",
        },
        "business": {
            "agent_submitted_cases": submitted,
            "preserved_m2_refund_total_fen": total,
            "real_payment": False,
        },
        "packages": {
            p: version(p)
            for p in [
                "langgraph",
                "langgraph-checkpoint",
                "langchain-core",
                "httpx",
                "fastapi",
                "sqlalchemy",
                "psycopg",
                "pytest",
            ]
        },
        "source_sha256": {
            name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
            for name in [
                "uv.lock",
                "backend/app/prompts/system_m3.txt",
                "data/fixtures.json",
                "data/policy.json",
                "evals/scenarios.jsonl",
            ]
        },
        "limitations": [
            "M4 full scenario evaluations, Chinese retrieval ranking, M5 UI and M6 pending",
            "Single root LangGraph namespace, JSON-only checkpoints",
            "Current backend cards are authoritative; free-text semantics need M4 evaluation",
            "Local dev sessions and simulated payment only",
            "A business write can succeed before a final model response fails; read resource truth",
        ],
    }
    (folder / "verification.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "result": "PASS",
                "offline_passed": tests,
                "live_runs": len(runs_summary),
                "estimated_cost_usd_range": report["live"][
                    "estimated_cost_usd_range_including_probe"
                ],
            }
        )
    )


if __name__ == "__main__":
    main()
