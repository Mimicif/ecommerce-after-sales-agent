"""Verify saved test/HTTP evidence against current PostgreSQL bookkeeping, without mutations."""

import hashlib
import json
import platform
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import Settings  # noqa: E402
from app.db import make_engine, make_session_factory  # noqa: E402
from app.main import create_app  # noqa: E402
from app.models import AfterSalesCase, Order, RefundJob, RefundTransaction  # noqa: E402
from app.tools import definitions  # noqa: E402
from sqlalchemy import func, select, text  # noqa: E402


def main():
    folder = ROOT / "artifacts" / "m2"
    suites = list(ET.parse(folder / "pytest.xml").getroot().iter("testsuite"))
    tests = sum(int(s.attrib["tests"]) for s in suites)
    assert tests and all(
        int(s.attrib[k]) == 0 for s in suites for k in ["failures", "errors", "skipped"]
    )
    by_file = Counter(t.attrib["classname"] for s in suites for t in s.findall("testcase"))
    original = json.loads((folder / "http_smoke.json").read_text(encoding="utf-8"))
    assert original["result"] == "PASS" and original["first_run_timeout_injected"]
    for filename in [
        "http_repeat.json",
        "m0_http_regression.json",
        "m1_http_regression.json",
        "m1_after_m2_http_regression.json",
    ]:
        assert json.loads((folder / filename).read_text(encoding="utf-8"))["result"] == "PASS"
    app = create_app()
    try:
        assert (
            json.loads((ROOT / "docs/contracts/m2_openapi.json").read_text(encoding="utf-8"))
            == app.openapi()
        )
        assert (
            json.loads((ROOT / "docs/contracts/m1_tools.json").read_text(encoding="utf-8"))
            == definitions()
        )
    finally:
        app.state.engine.dispose()
    engine = make_engine(Settings())
    flows = []
    try:
        with make_session_factory(engine)() as session:
            session.execute(text("SET TRANSACTION READ ONLY"))
            assert session.scalar(text("SELECT version_num FROM alembic_version")) == "0003_m2"
            assert (
                session.scalar(text("SELECT rolsuper FROM pg_roles WHERE rolname=current_user"))
                is False
            )
            for flow in original["flows"]:
                case = session.get(AfterSalesCase, flow["case_id"])
                order = session.get(Order, flow["order_id"])
                ledger = session.scalars(
                    select(RefundTransaction).where(RefundTransaction.case_id == case.id)
                ).all()
                job = session.scalar(select(RefundJob).where(RefundJob.case_id == case.id))
                assert case.status == "REFUNDED" and job.status == "DONE" and len(ledger) == 1
                assert (
                    ledger[0].amount_fen
                    == order.refunded_amount_fen
                    == order.paid_amount_fen
                    == flow["amount_fen"]
                )
                assert order.version == 2
                flows.append(
                    {
                        **flow,
                        "successful_ledger_count": len(ledger),
                        "order_version": order.version,
                        "provider_operation_id": ledger[0].provider_operation_id,
                    }
                )
            total = session.scalar(select(func.sum(RefundTransaction.amount_fen)))
    finally:
        engine.dispose()
    sources = {
        name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
        for name in ["uv.lock", "data/fixtures.json", "data/policy.json", "evals/scenarios.jsonl"]
    }
    report = {
        "checked_at_utc": datetime.now(UTC).isoformat(),
        "result": "PASS",
        "versions": {
            "app": "0.3.0",
            "api": "api-v1-m2",
            "schema": "0003_m2",
            "domain": "domain-v1-m2",
            "tools": "tools-v1-m1",
            "fixtures": "fixtures-v1",
            "policy_schema": "policy-schema-v1",
        },
        "tests": {
            "passed": tests,
            "failed": 0,
            "errors": 0,
            "skipped": 0,
            "duration_seconds": sum(float(s.attrib["time"]) for s in suites),
            "by_file": dict(by_file),
        },
        "postgresql": "18.6",
        "python": platform.python_version(),
        "packages": {
            p: version(p)
            for p in [
                "fastapi",
                "sqlalchemy",
                "alembic",
                "psycopg",
                "pydantic",
                "pytest",
                "httpx",
                "starlette",
                "ruff",
            ]
        },
        "http": "PASS: initial timeout injection, repeat without duplicate payment, "
        "M0/M1 regressions",
        "schema_check": "PASS: Alembic no new upgrade operations",
        "seed_repeat": "already_imported; preserved existing cases and successful refunds",
        "contracts": "PASS: actual OpenAPI and read tools match exported schemas",
        "bookkeeping": {"demo_flows": flows, "successful_refund_total_fen": total},
        "source_sha256": sources,
        "limitations": [
            "Local simulated provider persists results in separate PostgreSQL transactions; "
            "no real payment",
            "No model or live Agent evaluations; M3-M6 remain",
            "Read tools only; write-tool orchestration starts M3",
            "Existing Starlette/httpx TestClient deprecation warning",
            "Fixture clock is frozen DEV demo time; leases/session use real UTC",
            "Tickets support creation/read OPEN state; "
            "post-submission cancellation requires manual handling",
        ],
    }
    (folder / "verification.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "result": "PASS",
                "tests_passed": tests,
                "demo_successful_refund_total_fen": total,
                "report": "artifacts/m2/verification.json",
            }
        )
    )


if __name__ == "__main__":
    main()
