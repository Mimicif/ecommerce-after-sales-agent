import argparse
import time

import uvicorn
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import make_url

from app.config import ROOT, Settings


def validate_reset(settings, target):
    url = make_url(settings.database_url.get_secret_value())
    if not settings.dev_mode or settings.database_schema != "public" or target != url.database:
        raise ValueError("Reset requires DEV_MODE, public schema and an exact target match")
    if target not in {"after_sales_dev", "after_sales_test"}:
        raise ValueError("Reset only permits the named local demo/test databases")


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("serve")
    sub.add_parser("index-policies")
    agent_worker = sub.add_parser("agent-worker")
    agent_worker.add_argument("--max-runs", type=int, choices=range(1, 101), default=10)
    agent_worker.add_argument("--watch", action="store_true")
    agent_worker.add_argument("--poll-seconds", type=float, default=1.0)
    reset = sub.add_parser("reset")
    reset.add_argument("--target", required=True)
    worker = sub.add_parser("refund-worker")
    worker.add_argument("--max-jobs", type=int, choices=range(1, 101), default=10)
    worker.add_argument("--watch", action="store_true")
    worker.add_argument("--poll-seconds", type=float, default=1.0)
    worker.add_argument(
        "--fault",
        choices=["success", "timeout_before", "timeout_after", "unavailable"],
        default="success",
    )
    args = parser.parse_args()
    if hasattr(args, "poll_seconds") and not 0.1 <= args.poll_seconds <= 30:
        parser.error("poll-seconds must be 0.1..30")
    settings = Settings()
    if args.action == "serve":
        uvicorn.run(
            "app.main:create_app",
            factory=True,
            host="127.0.0.1",
            port=8000,
            proxy_headers=False,
            access_log=False,
        )
    elif args.action == "index-policies":
        from app.db import make_engine, make_session_factory
        from app.retrieval import rebuild_index

        if not settings.dev_mode:
            raise ValueError("Local indexing requires DEV_MODE")
        engine = make_engine(settings)
        try:
            with make_session_factory(engine)() as session, session.begin():
                print({"indexed_chunks": rebuild_index(session)})
        finally:
            engine.dispose()
    elif args.action == "agent-worker":
        from app.agent import AgentWorker
        from app.agent_model import DeepSeekModel
        from app.clock import FixtureClock, SystemClock
        from app.db import make_engine, make_session_factory

        engine = make_engine(settings)
        try:
            model = DeepSeekModel(settings)
            clock = FixtureClock() if settings.business_clock_mode == "fixture" else SystemClock()
            worker = AgentWorker(make_session_factory(engine), model, clock)
            processed = 0
            while args.watch or processed < args.max_runs:
                outcome = worker.run_once()
                if outcome["processed"] or not args.watch:
                    print(
                        {
                            key: outcome.get(key)
                            for key in (
                                "processed",
                                "run_id",
                                "status",
                                "error_code",
                                "model_calls",
                                "tool_calls",
                            )
                        }
                    )
                if not outcome["processed"]:
                    if not args.watch:
                        break
                    time.sleep(args.poll_seconds)
                else:
                    processed += 1
        finally:
            engine.dispose()
    elif args.action == "refund-worker":
        if not settings.dev_mode:
            raise ValueError("Simulated refunds require local DEV_MODE")
        from app.db import make_engine, make_session_factory
        from app.refunds import RefundWorker, SimulatedProvider

        engine = make_engine(settings)
        try:
            factory = make_session_factory(engine)
            worker = RefundWorker(factory, SimulatedProvider(factory, fault=args.fault))
            processed = 0
            while args.watch or processed < args.max_jobs:
                outcome = worker.run_once()
                if outcome["processed"] or not args.watch:
                    print(outcome, flush=True)
                if not outcome["processed"]:
                    if not args.watch:
                        break
                    time.sleep(args.poll_seconds)
                else:
                    processed += 1
        finally:
            engine.dispose()
    else:
        validate_reset(settings, args.target)
        config = Config(str(ROOT / "alembic.ini"))
        command.downgrade(config, "base")
        command.upgrade(config, "head")
        # Reset CLI arguments must not be forwarded to the seed parser.
        from app.db import make_engine, make_session_factory
        from app.seed import import_seed

        engine = make_engine(settings)
        try:
            with make_session_factory(engine)() as session, session.begin():
                print(import_seed(session))
        finally:
            engine.dispose()


if __name__ == "__main__":
    main()
