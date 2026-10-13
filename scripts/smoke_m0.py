"""Live HTTP verification. Never prints or saves bearer tokens."""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    checks = []
    with httpx.Client(
        base_url="http://127.0.0.1:8000/api/v1", timeout=10, trust_env=False
    ) as client:
        response = client.get("/health")
        assert response.status_code == 200 and response.json()["data"]["database"] == "reachable"
        checks.append("health_database_reachable")
        for user, own, denied in (
            ("C-A1", "O-A101", ["O-B101", "O-A108"]),
            ("C-B1", "O-B101", ["O-A101"]),
        ):
            login = client.post("/dev/sessions", json={"user_id": user})
            assert login.status_code == 201
            headers = {"Authorization": "Bearer " + login.json()["data"]["access_token"]}
            assert client.get(f"/orders/{own}", headers=headers).status_code == 200
            for order in denied:
                response = client.get(f"/orders/{order}", headers=headers)
                assert (
                    response.status_code == 404 and response.json()["code"] == "RESOURCE_NOT_FOUND"
                )
            checks.append(f"{user}_order_scope")
        assert client.get("/orders").status_code == 401
        checks.append("unauthenticated_request_blocked")
    report = {
        "checked_at_utc": datetime.now(UTC).isoformat(),
        "result": "PASS",
        "scope": "Live local HTTP and real PostgreSQL; no LLM",
        "checks": checks,
        "api_version": "api-v1-m0",
    }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
