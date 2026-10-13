"""Live HTTP + separate worker process; only operates on explicit local simulated fixtures."""

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]


def run_worker(fault):
    environment = {**os.environ, "PYTHONPATH": str(ROOT / "backend")}
    process = subprocess.run(
        [sys.executable, "-m", "app.cli", "refund-worker", "--fault", fault],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
    )
    # Never include raw process stderr or configuration in the saved evidence.
    assert process.returncode == 0, "Simulated worker process failed"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    checks, flows, identities = [], [], {}
    with httpx.Client(base_url="http://127.0.0.1:8000", timeout=15, trust_env=False) as client:
        assert client.get("/openapi.json").json()["info"]["version"] in {"0.3.0", "0.4.0"}
        assert client.get("/api/v1/health").status_code == 200

        def headers(actor, key=None):
            if actor not in identities:
                login = client.post("/api/v1/dev/sessions", json={"user_id": actor})
                assert login.status_code == 201
                identities[actor] = {
                    "Authorization": "Bearer " + login.json()["data"]["access_token"]
                }
            return {**identities[actor], **({"Idempotency-Key": key} if key else {})}

        def post(path, body, actor, key):
            response = client.post("/api/v1" + path, json=body, headers=headers(actor, key))
            assert response.status_code in {200, 201}, response.json()["code"]
            return response.json()["data"]

        for kind, order, amount in [
            ("RETURN_REFUND", "O-A101", 14900),
            ("DAMAGE_REFUND", "O-A103", 8900),
        ]:
            prefix = "m2-http-v1-" + kind
            case = post(
                "/cases/drafts",
                {
                    "order_id": order,
                    "case_type": kind,
                    "reason": "本地HTTP售后演示",
                    "evidence_refs": ["EVIDENCE-A1"] if kind == "DAMAGE_REFUND" else [],
                },
                "C-A1",
                prefix + "-draft",
            )
            assert case["status"] == "DRAFT" and case["requested_amount_fen"] == amount
            summary = post(
                f"/cases/{case['id']}/confirmation",
                {"expected_version": case["version"]},
                "C-A1",
                prefix + "-summary",
            )
            post(
                f"/confirmations/{summary['confirmation_id']}/confirm",
                {"payload_digest": summary["payload_digest"]},
                "C-A1",
                prefix + "-confirm",
            )
            body = {"expected_version": summary["summary"]["version"]}
            submitted = post(f"/cases/{case['id']}/submit", body, "C-A1", prefix + "-submit")
            assert submitted["status"] == "PENDING_REVIEW"
            assert (
                post(f"/cases/{case['id']}/submit", body, "C-A1", prefix + "-submit") == submitted
            )
            approved = post(
                f"/cases/{case['id']}/review",
                {
                    "expected_version": submitted["version"],
                    "decision": "APPROVE",
                    "reason": "人工演示审核",
                    "return_required": kind == "RETURN_REFUND",
                },
                "E-A2",
                prefix + "-review",
            )
            if kind == "RETURN_REFUND":
                assert approved["status"] == "AWAITING_RETURN"
                post(
                    f"/cases/{case['id']}/return-received",
                    {"expected_version": approved["version"]},
                    "E-A3",
                    prefix + "-receive",
                )
            else:
                assert approved["status"] == "READY_TO_REFUND"
            for actor in ["C-A2", "C-B1", "E-B2"]:
                assert (
                    client.get(f"/api/v1/cases/{case['id']}", headers=headers(actor)).status_code
                    == 404
                )
            flows.append(
                {"case_id": case["id"], "order_id": order, "case_type": kind, "amount_fen": amount}
            )
        checks.extend(
            [
                "standard_return_requires_warehouse",
                "damage_outside_window_requires_reviewer",
                "submission_replay_is_same_result",
                "case_customer_and_tenant_isolation",
            ]
        )

        before = [
            client.get(f"/api/v1/cases/{flow['case_id']}/refund", headers=headers("C-A1")).json()[
                "data"
            ]
            for flow in flows
        ]
        first_run = any(r["status"] != "REFUNDED" for r in before)
        if first_run:
            run_worker("timeout_after")
            for flow in flows:
                refund = client.get(
                    f"/api/v1/cases/{flow['case_id']}/refund", headers=headers("C-A1")
                ).json()["data"]
                assert refund["status"] == "REFUND_PENDING" and refund["funds_state"] == "UNKNOWN"
                assert refund["transaction"] is None
            checks.append("separate_worker_provider_success_timeout_remains_unknown")
            time.sleep(6)
        run_worker("success")
        run_worker("success")
        for flow in flows:
            refund = client.get(
                f"/api/v1/cases/{flow['case_id']}/refund", headers=headers("C-A1")
            ).json()["data"]
            order = client.get(
                f"/api/v1/orders/{flow['order_id']}", headers=headers("C-A1")
            ).json()["data"]
            assert refund["status"] == "REFUNDED" and refund["funds_state"] == "SUCCEEDED"
            assert (
                refund["transaction"]["amount_fen"]
                == order["refunded_amount_fen"]
                == flow["amount_fen"]
            )
            assert order["version"] == 2
            flow["final_status"] = "REFUNDED"
        checks.append("new_worker_query_recovery_and_repeated_execution_do_not_double_refund")

        b = post(
            "/cases/drafts",
            {"order_id": "O-B101", "case_type": "RETURN_REFUND", "reason": "B租户独立草稿"},
            "C-B1",
            "m2-http-v1-b-draft",
        )
        assert b["policy_version"] == "POLICY-B-2026-10-v1"
        assert client.get(f"/api/v1/cases/{b['id']}", headers=headers("E-A2")).status_code == 404
        post(
            f"/cases/{b['id']}/cancel",
            {"expected_version": b["version"]},
            "C-B1",
            "m2-http-v1-b-cancel",
        )
        ticket = post(
            "/tickets",
            {"order_id": "O-A104", "category": "LOGISTICS", "summary": "模拟物流异常需人工核验"},
            "C-A1",
            "m2-http-v1-logistics-ticket",
        )
        assert ticket["status"] == "OPEN"
        assert (
            client.get(f"/api/v1/tickets/{ticket['id']}", headers=headers("C-B1")).status_code
            == 404
        )
        checks.extend(
            ["tenant_b_separate_policy_draft_and_cancel", "logistics_ticket_does_not_create_refund"]
        )
    report = {
        "checked_at_utc": datetime.now(UTC).isoformat(),
        "result": "PASS",
        "api_version": "api-v1-m2",
        "schema_version": "0003_m2",
        "business_clock": "fixture",
        "simulated": True,
        "scope": "Real HTTP, PostgreSQL and separate simulated worker processes; no LLM",
        "first_run_timeout_injected": first_run,
        "checks": checks,
        "flows": flows,
    }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
