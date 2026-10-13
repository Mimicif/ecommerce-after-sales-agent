"""Validate an extracted source release without copying private configuration.

Requires the project's locally installed PostgreSQL admin-password file. Creates
and drops only a generated after_sales_m6_UUID database, never dev/test databases.
The complete pytest suite uses isolated schemas in after_sales_test as designed.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.config import Settings  # noqa: E402
from package_m6 import digest, verify  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402


def run(args, cwd, env, label, report):
    print(f"M6: {label}", flush=True)
    started = time.monotonic()
    # Commands never contain passwords or tokens. Raw child output stays ignored locally.
    log = ROOT / ".runtime" / f"m6-{label}.log"
    with log.open("w", encoding="utf-8") as output:
        result = subprocess.run(
            args,
            cwd=cwd,
            env=env,
            stdout=output,
            stderr=output,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    report["checks"][label] = {
        "exit_code": result.returncode,
        "seconds": round(time.monotonic() - started, 3),
    }
    if result.returncode:
        raise RuntimeError(f"{label} failed; inspect ignored .runtime/m6-{label}.log locally")


def main(source, reuse_backend_report=None):
    import psycopg
    from psycopg import sql

    artifacts = ROOT / "artifacts/m6"
    artifacts.mkdir(parents=True, exist_ok=True)
    report_path = artifacts / "reproduction.json"
    if report_path.exists():
        raise RuntimeError("Existing M6 report preserved; archive it before another run")
    manifest = verify(source)
    stage = ROOT / ".runtime" / ("m6_workspace_" + uuid4().hex)
    stage.mkdir(parents=True)
    # verify() has validated every relative archive path before extraction.
    with zipfile.ZipFile(source) as archive:
        archive.extractall(stage)
    assert not (stage / ".env").exists()
    assert not (stage / ".venv").exists()
    assert not (stage / "frontend/node_modules").exists()
    base = Settings()
    url = make_url(base.database_url.get_secret_value())
    database = "after_sales_m6_" + uuid4().hex
    assert re.fullmatch(r"after_sales_m6_[a-f0-9]{32}", database)
    admin_password = (ROOT / ".runtime/admin-password").read_text().strip()
    admin = psycopg.connect(
        host=url.host,
        port=url.port,
        user="postgres",
        password=admin_password,
        dbname="postgres",
        autocommit=True,
    )
    report = {
        "status": "RUNNING",
        "source_zip_sha256": digest(source.read_bytes()),
        "source_files": manifest["files"],
        "workspace": stage.name,
        "fresh_physical_database": database,
        "checks": {},
    }
    environment = dict(
        os.environ,
        PYTHONPATH=str(stage / "backend"),
        DEV_MODE="true",
        BUSINESS_CLOCK_MODE="fixture",
        DATABASE_SCHEMA="public",
        DATABASE_URL=url.set(database=database).render_as_string(hide_password=False),
        TEST_DATABASE_URL=url.set(database="after_sales_test").render_as_string(
            hide_password=False
        ),
        DEVELOPMENT_DATABASE_URL=url.render_as_string(hide_password=False),
        BROWSER_DATABASE=database,
        BROWSER_API_PORT="8106",
        BROWSER_WEB_PORT="5175",
        BROWSER_PRODUCTION="true",
        DEMO_RECORD="true",
        BROWSER_ARTIFACT_DIR=str(stage / "artifacts/m6"),
        PLAYWRIGHT_BROWSERS_PATH=str(ROOT / ".runtime/playwright"),
    )
    if base.deepseek_api_key:
        environment["DEEPSEEK_API_KEY"] = base.deepseek_api_key.get_secret_value()
    environment["DEEPSEEK_MODEL"] = base.deepseek_model
    created = False
    try:
        admin.execute(
            sql.SQL("CREATE DATABASE {} OWNER {}").format(
                sql.Identifier(database), sql.Identifier(url.username)
            )
        )
        created = True
        python = stage / ".venv/Scripts/python.exe"
        run(
            [
                "uv",
                "sync",
                "--locked",
                "--python",
                "3.12",
                "--cache-dir",
                str(ROOT / ".runtime/uv-cache"),
            ],
            stage,
            environment,
            "python-install",
            report,
        )
        npm = shutil.which("npm.cmd")
        node = shutil.which("node")
        if not npm or not node:
            raise RuntimeError("Node.js and npm must be on PATH")
        run(
            [npm, "ci", "--cache", str(ROOT / ".runtime/npm-cache"), "--no-fund", "--no-audit"],
            stage / "frontend",
            environment,
            "frontend-install",
            report,
        )
        run([npm, "run", "build"], stage / "frontend", environment, "production-build", report)
        run(
            [node, "node_modules/@playwright/test/cli.js", "install", "ffmpeg"],
            stage / "frontend",
            environment,
            "browser-recorder-install",
            report,
        )
        run(
            [npm, "run", "format:check"], stage / "frontend", environment, "frontend-format", report
        )
        run(
            [str(python), "-m", "alembic", "upgrade", "head"],
            stage,
            environment,
            "fresh-migration",
            report,
        )
        run([str(python), "-m", "alembic", "check"], stage, environment, "schema-check", report)
        for number in (1, 2):
            run([str(python), "-m", "app.seed"], stage, environment, f"seed-{number}", report)
        if reuse_backend_report:
            previous = json.loads(reuse_backend_report.read_text(encoding="utf-8"))
            assert previous["status"] == "PASS"
            covered = {
                name: value
                for name, value in manifest["files"].items()
                if name.startswith(("backend/", "data/", "evals/"))
                or name in {"pyproject.toml", "uv.lock", "alembic.ini"}
            }
            old_covered = {
                name: value
                for name, value in previous["source_files"].items()
                if name.startswith(("backend/", "data/", "evals/"))
                or name in {"pyproject.toml", "uv.lock", "alembic.ini"}
            }
            assert covered == old_covered, "Backend or dependency changed; run full pytest"
            shutil.copyfile(reuse_backend_report.parent / "pytest.xml", artifacts / "pytest.xml")
            report["checks"]["pytest"] = {
                "exit_code": 0,
                "seconds": 0,
                "mode": "reused_after_source_hash_check",
                "evidence": str(reuse_backend_report.relative_to(ROOT)).replace("\\", "/"),
                "unchanged_source_files": len(covered),
                "original_seconds": previous["checks"]["pytest"]["seconds"],
            }
        else:
            run(
                [
                    str(python),
                    "-m",
                    "pytest",
                    "-q",
                    "--tb=short",
                    "--junitxml=" + str(artifacts / "pytest.xml"),
                ],
                stage,
                dict(environment, BUSINESS_CLOCK_MODE="system"),
                "pytest",
                report,
            )
        suites = ET.parse(artifacts / "pytest.xml").getroot().findall("testsuite")
        assert sum(int(s.get("tests", 0)) for s in suites) == 311
        assert all(int(s.get(k, 0)) == 0 for s in suites for k in ("failures", "errors", "skipped"))
        run(
            [str(python), str(stage / "scripts/browser_m5.py")],
            stage,
            environment,
            "production-browser",
            report,
        )
        browser = json.loads((stage / "artifacts/m6/browser_database.json").read_text())
        assert browser["status"] == "PASS" and browser["development_unchanged"]
        assert browser["refunds"] == browser["provider_operations"] == 3
        report["browser"] = browser
        run(
            [
                node,
                str(stage / "scripts/inspect_demo.mjs"),
                str(stage),
                str(stage / "frontend/test-results"),
            ],
            stage,
            environment,
            "recording-inspection",
            report,
        )
        # Record hardware/runtime versions through installed executables, no network guesses.
        report["versions"] = {}
        for name, args in {
            "python": [str(python), "--version"],
            "uv": ["uv", "--version"],
            "node": [node, "--version"],
            "npm": [npm, "--version"],
        }.items():
            report["versions"][name] = subprocess.check_output(args, text=True).strip()
        report["postgresql"] = admin.execute("SHOW server_version").fetchone()[0]
        report["status"] = "PASS"
    finally:
        for directory in (stage / "artifacts/m6", stage / "frontend/test-results"):
            if directory.exists():
                target = artifacts if directory.name == "m6" else artifacts / "recordings"
                shutil.copytree(directory, target, dirs_exist_ok=True)
        if created:
            # Generated name checked again before a destructive database operation.
            if not re.fullmatch(r"after_sales_m6_[a-f0-9]{32}", database):
                raise RuntimeError("Invalid database cleanup target")
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database)))
            report["fresh_database_removed"] = True
        admin.close()
        if report["status"] != "PASS":
            report["status"] = "FAIL"
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(json.dumps({"status": report["status"], "checks": report["checks"]}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source_zip", type=Path)
    parser.add_argument(
        "--reuse-backend-report",
        type=Path,
        help="Only for a frontend-only revision; all backend hashes must match",
    )
    args = parser.parse_args()
    main(
        args.source_zip.resolve(),
        args.reuse_backend_report.resolve() if args.reuse_backend_report else None,
    )
