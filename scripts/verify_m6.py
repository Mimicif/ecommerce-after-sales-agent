"""Read-only evidence checks for M6, with an optional final source ZIP check."""

import argparse
import hashlib
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from package_m6 import verify

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.agent_checkpoint import CHECKPOINT_VERSION  # noqa: E402
from app.agent_tools import definitions  # noqa: E402
from app.main import create_app  # noqa: E402


def read(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def main(package=None):
    app = create_app()
    try:
        assert app.openapi() == read("docs/contracts/m5_openapi.json")
        assert definitions() == read("docs/contracts/m4_tools.json")
    finally:
        app.state.engine.dispose()
    assert read("artifacts/m4/verification.json")["result"] == "PASS"
    assert all(read("artifacts/m4/verification.json")["gates"].values())
    assert read("artifacts/m5/verification.json")["status"] == "PASS"
    report = read("artifacts/m6/reproduction.json")
    assert report["status"] == "PASS" and report["fresh_database_removed"]
    required = {
        "python-install",
        "frontend-install",
        "production-build",
        "frontend-format",
        "fresh-migration",
        "schema-check",
        "seed-1",
        "seed-2",
        "pytest",
        "production-browser",
        "browser-recorder-install",
        "recording-inspection",
    }
    assert set(report["checks"]) == required
    assert all(c["exit_code"] == 0 for c in report["checks"].values())
    suites = ET.parse(ROOT / "artifacts/m6/pytest.xml").getroot().findall("testsuite")
    assert sum(int(s.get("tests", 0)) for s in suites) == 311
    assert all(int(s.get(k, 0)) == 0 for s in suites for k in ("failures", "errors", "skipped"))
    browser = read("artifacts/m6/browser_results.json")["stats"]
    assert browser["expected"] == 2
    assert all(browser[key] == 0 for key in ("unexpected", "flaky", "skipped"))
    database = read("artifacts/m6/browser_database.json")
    assert database["development_unchanged"] and database["live_model"]
    assert database["refunds"] == database["provider_operations"] == 3
    assert database["total_fen"] == 64700 and database["live_runs"] == 5
    recovery = read("artifacts/m6/browser_recovery.json")
    assert all(
        recovery[key]
        for key in (
            "backend_committed_before_network_abort",
            "same_message_replayed_without_duplicate",
            "explicit_repeated_utterance_creates_new_message",
            "untrusted_html_rendered_as_text",
            "keyboard_native_controls",
        )
    )
    demo = read("artifacts/m6/demo_metadata.json")
    assert 180 <= demo["duration_seconds"] <= 360
    assert (
        hashlib.sha256((ROOT / "artifacts/m6/demo.webm").read_bytes()).hexdigest() == demo["sha256"]
    )
    # Only handoff documentation, evidence, and the new read-only verifier can differ
    # from the exact package used for the clean installation.
    core = {}
    for name, expected in report["source_files"].items():
        if name.startswith(("docs/", "artifacts/")) or name in {"README.md", "PROJECT_STATUS.md"}:
            continue
        actual = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
        assert actual == expected, f"Tested source changed: {name}"
        core[name] = expected
    freeze = read("evals/holdout_v2_freeze.json")
    for name, expected in freeze["implementation_sha256"].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == expected
    assert (
        hashlib.sha256((ROOT / "evals/holdout_v2.jsonl").read_bytes()).hexdigest()
        == freeze["sha256"]
    )
    result = {
        "status": "PASS",
        "release": "0.6.0-local-m6",
        "backend_tests": 311,
        "checkpoint_version": CHECKPOINT_VERSION,
        "checkpoint_sha256": core["backend/app/agent_checkpoint.py"],
        "backend_regression": report["checks"]["pytest"],
        "browser_tests": 2,
        "fresh_physical_database": True,
        "clean_install": True,
        "production_preview": True,
        "development_unchanged": True,
        "tested_source_files_unchanged": len(core),
        "runtime_versions": report["versions"],
        "postgresql": report["postgresql"],
        "demo": demo,
        "historical_evaluations_preserved": True,
    }
    if package:
        manifest = verify(package)
        for name, expected in core.items():
            assert manifest["files"][name] == expected
        result["final_zip_sha256"] = hashlib.sha256(package.read_bytes()).hexdigest()
        destination = package.with_suffix(".verification.json")
    else:
        destination = ROOT / "artifacts/m6/verification.json"
    destination.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", type=Path)
    main(parser.parse_args().package)
