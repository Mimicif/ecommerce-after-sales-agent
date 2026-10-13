"""Reconcile actual M5 acceptance artifacts; preserve all historical M4 evidence."""

import hashlib
import json
import sys
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.agent_tools import definitions  # noqa: E402
from app.main import create_app  # noqa: E402


def read(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8-sig"))


def digest(path):
    return hashlib.sha256((ROOT / path).read_bytes()).hexdigest()


def main():
    app = create_app()
    try:
        contract = app.openapi()
        assert contract["info"]["version"] == "0.6.0"
        assert contract == read("docs/contracts/m5_openapi.json")
        for path in [
            "/me",
            "/cases",
            "/tickets",
            "/conversations",
            "/orders/{order_id}/evidence",
            "/cases/{case_id}/timeline",
        ]:
            assert "get" in contract["paths"]["/api/v1" + path]
        assert definitions() == read("docs/contracts/m4_tools.json")
        frozen = read("evals/holdout_v2_freeze.json")["implementation_sha256"]
        assert all(digest(path) == expected for path, expected in frozen.items())
        suites = list(ET.parse(ROOT / "artifacts/m5/pytest.xml").getroot().iter("testsuite"))
        tests = sum(int(s.attrib["tests"]) for s in suites)
        assert tests == 308 and all(
            int(s.attrib["failures"]) == int(s.attrib["errors"]) == 0 for s in suites
        )
        browser = read("artifacts/m5/browser_results.json")
        assert browser["stats"]["expected"] == 2
        assert (
            browser["stats"]["unexpected"]
            == browser["stats"]["skipped"]
            == browser["stats"]["flaky"]
            == 0
        )
        database = read("artifacts/m5/browser_database.json")
        assert database["status"] == "PASS" and database["development_unchanged"]
        assert database["live_runs"] == 5 and database["runs"] == 7
        assert database["refunds"] == database["provider_operations"] == 3
        assert database["total_fen"] == 64700 and database["real_postgresql"]
        recovery = read("artifacts/m5/browser_recovery.json")
        assert recovery["status"] == "PASS" and all(
            value is True for value in recovery.values() if isinstance(value, bool)
        )
        workflows = read("artifacts/m5/browser_workflows.json")
        assert workflows["status"] == "PASS" and len(workflows["scenarios"]) == 3
        trace = read("artifacts/m5/browser_trace.json")
        assert len(trace) == 7
        allowed = {t["function"]["name"] for t in definitions()}
        assert all(
            e["data"]["name"] in allowed
            for r in trace
            for e in r["events"]
            if e["kind"] == "TOOL_RESULT"
        )
        package = read("frontend/package.json")
        locked = read("frontend/package-lock.json")["packages"][""]
        assert package["version"] == locked["version"] == "0.6.0"
        assert package["dependencies"] == locked["dependencies"]
        assert package["devDependencies"] == locked["devDependencies"]
        for source in (ROOT / "frontend/src").rglob("*"):
            if source.is_file():
                content = source.read_text(encoding="utf-8")
                assert "DEEPSEEK_API_KEY" not in content and "api.deepseek.com" not in content
        assert (ROOT / "frontend/dist/index.html").exists()
        report = {
            "status": "PASS",
            "checked_at": datetime.now(UTC).isoformat(),
            "api_version": "api-v1-m5",
            "application_version": "0.6.0",
            "schema_version": "0005_m4",
            "pytest_passed": tests,
            "browser_passed": 2,
            "live_runs": 5,
            "simulated_refunds": 3,
            "total_fen": 64700,
            "development_unchanged": True,
            "m4_frozen_implementation_unchanged": True,
            "tool_count": len(allowed),
            "source_sha256": {
                p: digest(p)
                for p in [
                    "backend/app/workspace.py",
                    "backend/app/main.py",
                    "backend/app/cli.py",
                    "frontend/src/App.tsx",
                    "frontend/src/api.ts",
                    "frontend/src/styles.css",
                    "frontend/package-lock.json",
                ]
            },
        }
        (ROOT / "artifacts/m5/verification.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(json.dumps(report, ensure_ascii=False))
    finally:
        app.state.engine.dispose()


if __name__ == "__main__":
    main()
