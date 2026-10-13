"""Launch a disposable real PostgreSQL + live-model browser acceptance environment.

Only the UUID schema created here is removed. Existing development state is untouched.
No credentials or browser storage/headers are included in the evidence reports.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from app.config import Settings  # noqa: E402
from app.db import make_engine, make_session_factory  # noqa: E402
from app.models import (  # noqa: E402
    AfterSalesCase,
    AgentRun,
    Order,
    RefundTransaction,
    RunEvent,
    SimulatedProviderOperation,
)
from app.seed import import_seed  # noqa: E402
from sqlalchemy import func, select, text  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402


def snapshot(engine):
    with make_session_factory(engine)() as session:
        return {
            "refund_count": session.scalar(select(func.count()).select_from(RefundTransaction)),
            "refund_sum_fen": session.scalar(
                select(func.coalesce(func.sum(RefundTransaction.amount_fen), 0))
            ),
            "orders": [
                [o.id, o.version, o.refunded_amount_fen]
                for o in session.scalars(select(Order).order_by(Order.id))
            ],
            "cases": [
                [c.id, c.status, c.version]
                for c in session.scalars(select(AfterSalesCase).order_by(AfterSalesCase.id))
            ],
        }


def ready(url, process):
    for _ in range(100):
        if process.poll() is not None:
            raise RuntimeError("Local browser server exited; inspect its local log")
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                if response.status == 200:
                    return
        except OSError:
            time.sleep(0.2)
    raise RuntimeError("Local browser server did not become ready")


def main():
    artifacts = Path(os.environ.get("BROWSER_ARTIFACT_DIR", ROOT / "artifacts/m5")).resolve()
    artifacts.mkdir(parents=True, exist_ok=True)
    base = Settings()
    if not base.dev_mode or not base.deepseek_api_key:
        raise RuntimeError("Browser acceptance requires DEV_MODE and a configured live model")
    development = make_engine(
        base.model_copy(
            update={
                "database_url": type(base.database_url)(
                    os.environ.get("DEVELOPMENT_DATABASE_URL", base.database_url.get_secret_value())
                )
            }
        )
    )
    before = snapshot(development)
    schema = "m5_browser_" + uuid4().hex
    test_url = make_url(base.database_url.get_secret_value())
    requested_database = os.environ.get("BROWSER_DATABASE", "after_sales_test")
    if requested_database != "after_sales_test" and not re.fullmatch(
        r"after_sales_m6_[a-f0-9]{32}", requested_database
    ):
        raise RuntimeError("Browser tests only permit disposable databases")
    test_url = test_url.set(database=requested_database)
    os.environ.update(
        DATABASE_URL=test_url.render_as_string(hide_password=False),
        DATABASE_SCHEMA="public",
        BUSINESS_CLOCK_MODE="fixture",
        DEV_MODE="true",
        PYTHONPATH=str(ROOT / "backend"),
        PYTHONUNBUFFERED="1",
    )
    admin = make_engine(Settings())
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    os.environ["DATABASE_SCHEMA"] = schema
    engine = make_engine(Settings())
    processes = []
    logs = []
    migrated = False
    try:
        command.upgrade(Config(str(ROOT / "alembic.ini")), "head")
        migrated = True
        with make_session_factory(engine)() as session, session.begin():
            import_seed(session)
        api_port = os.environ.get("BROWSER_API_PORT", "8105")
        web_port = os.environ.get("BROWSER_WEB_PORT", "5174")
        if not api_port.isdecimal() or not web_port.isdecimal():
            raise RuntimeError("Invalid loopback browser ports")
        environment = dict(
            os.environ,
            API_TARGET=f"http://127.0.0.1:{api_port}",
            BROWSER_BASE_URL=f"http://127.0.0.1:{web_port}",
            BROWSER_ARTIFACT_DIR=str(artifacts),
        )
        node_command = shutil.which("node")
        if not node_command:
            raise RuntimeError("Node.js must be on PATH")
        node = Path(node_command)
        vite_args = [str(node), "node_modules/vite/bin/vite.js"]
        if os.environ.get("BROWSER_PRODUCTION") == "true":
            vite_args.append("preview")
        vite_args.extend(["--port", web_port])
        for name, args, cwd, url in [
            (
                "api",
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "app.main:create_app",
                    "--factory",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    api_port,
                    "--no-proxy-headers",
                    "--no-access-log",
                ],
                ROOT,
                f"http://127.0.0.1:{api_port}/api/v1/health",
            ),
            (
                "web",
                vite_args,
                ROOT / "frontend",
                f"http://127.0.0.1:{web_port}",
            ),
        ]:
            (ROOT / ".runtime").mkdir(exist_ok=True)
            log = (ROOT / f".runtime/m5-{name}.log").open("w", encoding="utf-8")
            logs.append(log)
            process = subprocess.Popen(
                args,
                cwd=cwd,
                env=environment,
                stdout=log,
                stderr=log,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            processes.append(process)
            ready(url, process)
        result = subprocess.run(
            [str(node), "node_modules/@playwright/test/cli.js", "test"],
            cwd=ROOT / "frontend",
            env=environment,
        )
        if result.returncode:
            raise RuntimeError("Browser workflow failed; milestone remains unaccepted")
        with make_session_factory(engine)() as session:
            cases = session.scalars(select(AfterSalesCase)).all()
            ledgers = session.scalars(select(RefundTransaction)).all()
            providers = session.scalars(select(SimulatedProviderOperation)).all()
            runs = session.scalars(select(AgentRun)).all()
            assert len(cases) == len(ledgers) == len(providers) == 3
            assert all(c.status == "REFUNDED" for c in cases)
            assert sum(t.amount_fen for t in ledgers) == 64700
            assert len({t.case_id for t in ledgers}) == 3
            live_runs = [r for r in runs if r.model is not None]
            assert len(live_runs) == 5 and all(r.model == "deepseek-flash" for r in live_runs)
            assert all(r.status in {"COMPLETED", "WAITING_FOR_USER", "CANCELLED"} for r in runs)
            assert sum(r.status == "CANCELLED" for r in runs) == 2
            evidence = {
                "status": "PASS",
                "real_postgresql": True,
                "live_model": True,
                "runs": len(runs),
                "live_runs": len(live_runs),
                "refunds": len(ledgers),
                "provider_operations": len(providers),
                "total_fen": sum(t.amount_fen for t in ledgers),
                "schema_isolated": True,
                "development_unchanged": before == snapshot(development),
            }
            assert evidence["development_unchanged"]
            (artifacts / "browser_database.json").write_text(
                json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            print(json.dumps(evidence, ensure_ascii=False))
    finally:
        try:
            if migrated:
                export_trace(engine, artifacts)
        finally:
            for process in reversed(processes):
                if process.poll() is None:
                    subprocess.run(
                        ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    process.wait(timeout=10)
            for log in logs:
                log.close()
            engine.dispose()
            if not re.fullmatch(r"m5_browser_[a-f0-9]{32}", schema):
                raise RuntimeError("Invalid cleanup target")
            with admin.begin() as connection:
                connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            admin.dispose()
            development.dispose()


def export_trace(engine, artifacts):
    with make_session_factory(engine)() as session:
        trace = [
            {
                "run_id": r.id,
                "status": r.status,
                "action": r.action,
                "model": r.model,
                "model_calls": r.model_calls,
                "tool_calls": r.tool_calls,
                "error_code": r.error_code,
                "events": [
                    {"seq": e.seq, "kind": e.kind, "data": e.data}
                    for e in session.scalars(
                        select(RunEvent).where(RunEvent.run_id == r.id).order_by(RunEvent.seq)
                    )
                ],
            }
            for r in session.scalars(select(AgentRun).order_by(AgentRun.created_at))
        ]
        (artifacts / "browser_trace.json").write_text(
            json.dumps(trace, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )


if __name__ == "__main__":
    main()
