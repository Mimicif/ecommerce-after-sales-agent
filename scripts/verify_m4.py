"""Reconcile M4 evidence; report completion only when all declared gates pass."""

import hashlib
import json
import math
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.agent_tools import definitions  # noqa: E402
from app.config import Settings  # noqa: E402
from app.db import make_engine, make_session_factory  # noqa: E402
from app.evaluation import summary  # noqa: E402
from app.main import create_app  # noqa: E402
from app.models import AfterSalesCase, PolicyChunk, RefundTransaction  # noqa: E402
from sqlalchemy import func, select, text  # noqa: E402


def read(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8-sig"))


def wilson(successes, total):
    """Descriptive 95% interval; repeated scenarios are not independent population samples."""
    z = 1.959963984540054
    proportion = successes / total
    divisor = 1 + z * z / total
    center = (proportion + z * z / (2 * total)) / divisor
    half = z * math.sqrt(proportion * (1 - proportion) / total + z * z / (4 * total**2)) / divisor
    return [max(0, center - half), min(1, center + half)]


def reports(dataset):
    name = "dev_v5_final" if dataset == "dev" else "holdout_v2_release"
    folder = ROOT / "evals/reports" / name
    rows = [
        json.loads(line)
        for line in (folder / "trials.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    source = ROOT / "evals" / ("scenarios.jsonl" if dataset == "dev" else "holdout_v2.jsonl")
    scenarios = [json.loads(line) for line in source.read_text(encoding="utf-8").splitlines()]
    contracts = read("evals/request_contracts.json")
    expected = set()
    for s in scenarios:
        if s["level"] != "agent":
            expected.add((s["case_id"], "SHARED", 0))
        elif any(f["target"] == "llm" for f in s.get("faults", [])):
            expected.add((s["case_id"], "B2", 0))
        else:
            for b in ["B0", "B1", "B2"]:
                if (
                    b != "B1"
                    or s.get("readonly_comparison")
                    or s["case_id"] in contracts["readonly_cases"]
                ):
                    expected.update((s["case_id"], b, repeat) for repeat in range(3))
    assert Counter((r["case_id"], r["baseline"], r["repeat_index"]) for r in rows) == Counter(
        expected
    ), "Incomplete/duplicate trial denominator"
    manifest = read(f"evals/reports/{name}/manifest.json")
    assert manifest["dataset_sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert (
        manifest["prompt_sha256"]
        == hashlib.sha256((ROOT / "backend/app/prompts/system_m4.txt").read_bytes()).hexdigest()
    )
    recomputed = summary(rows)
    (folder / "summary.json").write_text(
        json.dumps(recomputed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return rows, recomputed


def main():
    folder = ROOT / "artifacts/m4"
    folder.mkdir(parents=True, exist_ok=True)
    suites = list(ET.parse(folder / "pytest.xml").getroot().iter("testsuite"))
    assert all(int(s.attrib[k]) == 0 for s in suites for k in ["failures", "errors", "skipped"])
    tests = sum(int(s.attrib["tests"]) for s in suites)
    dev, dev_summary = reports("dev")
    holdout, holdout_summary = reports("holdout")
    assert (
        read("evals/holdout_v2_freeze.json")["sha256"]
        == hashlib.sha256((ROOT / "evals/holdout_v2.jsonl").read_bytes()).hexdigest()
    )
    assert all(
        hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == frozen_hash
        for path, frozen_hash in read("evals/holdout_v2_freeze.json")[
            "implementation_sha256"
        ].items()
    ), "Independent holdout implementation changed after freeze"
    for filename in ["http_smoke.json", "m0_http_regression.json", "m1_http_regression.json"]:
        assert read("artifacts/m4/" + filename)["result"] == "PASS"
    settings = Settings()
    secret = settings.deepseek_api_key.get_secret_value()
    # Read credential only for equality-based leak detection; never emit its value.
    for report_path in [
        *folder.glob("*.json"),
        *folder.glob("*.xml"),
        *(ROOT / "evals/reports").rglob("*.json"),
        *(ROOT / "evals/reports").rglob("*.jsonl"),
    ]:
        assert secret not in report_path.read_text(encoding="utf-8-sig"), (
            "Sensitive value in evidence"
        )
    app = create_app(settings)
    try:
        assert read("docs/contracts/m4_openapi.json") == app.openapi()
        assert read("docs/contracts/m4_tools.json") == definitions()
    finally:
        app.state.engine.dispose()
    engine = make_engine(settings)
    with make_session_factory(engine)() as session:
        session.execute(text("SET TRANSACTION READ ONLY"))
        assert session.scalar(text("SELECT version_num FROM alembic_version")) == "0005_m4"
        assert (
            session.scalar(text("SELECT rolsuper FROM pg_roles WHERE rolname=current_user"))
            is False
        )
        ledger_count = session.scalar(select(func.count()).select_from(RefundTransaction))
        ledger_total = session.scalar(select(func.sum(RefundTransaction.amount_fen)))
        assert (ledger_count, ledger_total) == (2, 23800), "Existing M2 demo refunds changed"
        cases = [
            {"id": c.id, "order_id": c.order_id, "status": c.status}
            for c in session.scalars(select(AfterSalesCase))
        ]
        assert any(c["order_id"] == "O-A102" and c["status"] == "PENDING_REVIEW" for c in cases)
        index_count = session.scalar(select(func.count()).select_from(PolicyChunk))
    engine.dispose()
    agent = holdout_summary["B2/LIVE"]
    gates = {
        "complete_denominators": True,
        "zero_hard_violations": all(not r["score"]["hard_violations"] for r in dev + holdout),
        "shared_domain_api_all_pass": all(
            r["score"]["success"] for r in dev + holdout if r["baseline"] == "SHARED"
        ),
        "budget_fault_pass": all(
            r["score"]["success"] for r in dev if r["evidence"]["mode"] == "FAULT_CONTRACT"
        ),
        "holdout_agent_success_ge_90pct": agent["task_success_rate"] >= 0.9,
        "holdout_fact_accuracy_ge_95pct": agent["fact_accuracy"] is not None
        and agent["fact_accuracy"] >= 0.95,
        "holdout_citation_accuracy_ge_95pct": agent["citation_accuracy"] is not None
        and agent["citation_accuracy"] >= 0.95,
        "holdout_p95_le_30s": agent["p95_ms"] <= 30000,
    }
    result = {
        "checked_at": datetime.now(UTC).isoformat(),
        "result": "PASS" if all(gates.values()) else "GATES_NOT_MET",
        "gates": gates,
        "tests": tests,
        "dev": dev_summary,
        "holdout": holdout_summary,
        "qualitative_review": read("artifacts/m4/qualitative_review.json"),
        "task_success_95pct_wilson_descriptive": {
            "dev": {
                key: wilson(value["successes"], value["tasks"])
                for key, value in dev_summary.items()
            },
            "holdout": {
                key: wilson(value["successes"], value["tasks"])
                for key, value in holdout_summary.items()
            },
            "interpretation": "Repeated small scenarios are correlated; not production reliability",
        },
        "development_database": {
            "refund_count": ledger_count,
            "refund_total_fen": ledger_total,
            "cases": cases,
            "indexed_chunks": index_count,
        },
        "limitations": [
            "Simulated data/payment; local dev auth",
            "Structured assertion metric plus bounded text checks",
            "ASGI evaluation; separate real HTTP smoke",
            "Model alias can change",
            "First holdout-v1 failed and became exposed regression",
            "New holdout-v2 not used for tuning",
        ],
    }
    (folder / "verification.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps({"result": result["result"], "gates": gates, "tests": tests}, ensure_ascii=False)
    )


if __name__ == "__main__":
    main()
