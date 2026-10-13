"""Atomic, serialized import of the simulation dataset; never rewrites existing business data."""

import argparse
import hashlib
import json
from datetime import UTC, datetime

from sqlalchemy import select, text

from app.config import ROOT, Settings
from app.db import make_engine, make_session_factory
from app.models import Evidence, LogisticsEvent, Order, Policy, SeedImport, Tenant, User
from app.policy import content_digest


def parse_time(value):
    if value is None:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("Dataset timestamps must include a timezone")
    return parsed.astimezone(UTC)


def import_seed(session, data_dir=ROOT / "data"):
    fixtures_raw = (data_dir / "fixtures.json").read_bytes()
    policy_raw = (data_dir / "policy.json").read_bytes()
    fixture, policies = json.loads(fixtures_raw), json.loads(policy_raw)
    if fixture["simulated"] is not True or policies["simulated"] is not True:
        raise ValueError("Only explicitly simulated data may be imported")
    if fixture["currency"] != "CNY" or fixture["amount_unit"] != "fen":
        raise ValueError("Expected integer CNY fen")
    source_digest = hashlib.sha256(fixtures_raw + b"\0" + policy_raw).hexdigest()
    # Separate schemas can import independently; concurrent imports in one schema serialize.
    session.execute(text("SELECT pg_advisory_xact_lock(hashtext(current_schema()))"))
    previous = session.get(SeedImport, "base")
    if previous:
        if previous.source_digest != source_digest:
            raise ValueError("Dataset changed: explicitly reset a local demo database first")
        return "already_imported"
    for model in (Tenant, User, Order, LogisticsEvent, Evidence, Policy):
        if session.scalar(select(model).limit(1)) is not None:
            raise ValueError("Import requires an empty migrated database")
    tenant_ids = {t["id"] for t in fixture["tenants"]}
    users = {u["id"]: u for u in fixture["users"]}
    for u in users.values():
        if (
            u["tenant_id"] not in tenant_ids
            or not set(u["roles"]) <= {"customer", "support", "reviewer", "warehouse"}
            or not u["roles"]
        ):
            raise ValueError("Invalid fixture identity")
        if "customer" in u["roles"] and u.get("customer_id") != u["id"]:
            raise ValueError("Fixture customer identity mismatch")
    session.add_all(Tenant(**t) for t in fixture["tenants"])
    session.flush()
    session.add_all(User(**u) for u in fixture["users"])
    session.flush()
    for original in fixture["orders"]:
        row = dict(original)
        customer = users[row["customer_id"]]
        if "customer" not in customer["roles"] or customer["tenant_id"] != row["tenant_id"]:
            raise ValueError("Order owner must be a customer in the same tenant")
        for key in ("paid_amount_fen", "refunded_amount_fen", "version"):
            if type(row[key]) is not int:
                raise ValueError("Amounts and versions must be integers")
        row["delivered_at"] = parse_time(row["delivered_at"])
        session.add(Order(**row))
    session.flush()
    for original in fixture["logistics_events"]:
        row = dict(original)
        row["occurred_at"] = parse_time(row["occurred_at"])
        session.add(LogisticsEvent(**row))
    session.add_all(Evidence(**e) for e in fixture["evidence"])
    for original in policies["policies"]:
        row = dict(original)
        row["effective_from"] = parse_time(row["effective_from"])
        row["effective_to"] = parse_time(row["effective_to"])
        if not row["clauses"] or len({c["chunk_id"] for c in row["clauses"]}) != len(
            row["clauses"]
        ):
            raise ValueError("Policy clauses must exist and have unique IDs")
        row["content_digest"] = content_digest(row["rules"], row["clauses"])
        session.add(Policy(**row))
    session.add(
        SeedImport(
            id="base",
            source_digest=source_digest,
            fixture_version=fixture["fixture_version"],
            policy_schema_version=policies["policy_schema_version"],
            fixture_clock=parse_time(fixture["clock"]),
            imported_at=datetime.now(UTC),
        )
    )
    session.flush()
    from app.retrieval import rebuild_index

    rebuild_index(session)
    return "imported"


def main():
    parser = argparse.ArgumentParser()
    parser.parse_args()
    settings = Settings()
    if not settings.dev_mode:
        raise SystemExit("Seed import is only permitted in DEV_MODE")
    engine = make_engine(settings)
    try:
        with make_session_factory(engine)() as session, session.begin():
            status = import_seed(session)
        print(json.dumps({"status": status, "fixture_version": "fixtures-v1", "simulated": True}))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
