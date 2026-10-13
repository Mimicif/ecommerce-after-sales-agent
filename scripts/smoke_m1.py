"""Live M1 HTTP verification for the trusted fixture-clock demo. No token persistence."""

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
    with httpx.Client(base_url="http://127.0.0.1:8000", timeout=10, trust_env=False) as client:
        assert client.get("/api/v1/health").status_code == 200
        assert client.get("/openapi.json").json()["info"]["version"] in {
            "0.2.0",
            "0.3.0",
            "0.4.0",
            "0.5.0",
        }
        checks.append("m1_api_and_database_ready")
        login = client.post("/api/v1/dev/sessions", json={"user_id": "C-A1"})
        assert login.status_code == 201
        headers = {"Authorization": "Bearer " + login.json()["data"]["access_token"]}
        response = client.post(
            "/api/v1/orders/O-A102/eligibility",
            headers=headers,
            json={"case_type": "RETURN_REFUND"},
        )
        assert response.status_code == 200
        eligibility = response.json()["data"]
        if eligibility["eligibility"] == "manual_required":
            # M3's real Agent demo has created an active O-A102 application.
            assert eligibility["reason_codes"] == ["ACTIVE_CASE_EXISTS"]
            checks.append("active_m3_application_blocks_another_application")
        else:
            assert eligibility["eligibility"] == "eligible"
        assert datetime.fromisoformat(eligibility["evaluated_at"]) == datetime(
            2026, 10, 11, 2, tzinfo=UTC
        )
        assert eligibility["refundable_amount_fen"] == 39900 and eligibility["review_required"]
        checks.append("fixture_clock_and_standard_return_precheck")
        damage = client.post(
            "/api/v1/orders/O-A103/eligibility",
            headers=headers,
            json={"case_type": "DAMAGE_REFUND"},
        ).json()["data"]
        order = client.get("/api/v1/orders/O-A103", headers=headers).json()["data"]
        if order["refunded_amount_fen"] == order["paid_amount_fen"]:
            # M2's successful demo legitimately changes this fixture's business state.
            assert damage["eligibility"] == "ineligible"
            assert damage["reason_codes"] == ["ALREADY_REFUNDED"]
            checks.append("completed_m2_refund_is_ineligible_for_another_damage_request")
        else:
            assert damage["eligibility"] == "manual_required"
            assert "RETURN_WINDOW_EXCEEDED" not in damage["reason_codes"]
            checks.append("damage_outside_return_window_is_manual")
        logistics = client.get("/api/v1/orders/O-A104/logistics", headers=headers).json()["data"]
        missing = client.get("/api/v1/orders/O-A113/logistics", headers=headers).json()["data"]
        assert logistics["possible_exception"] is True and logistics["manual_required"]
        assert missing["possible_exception"] is None and missing["manual_required"]
        checks.append("logistics_exception_and_unknown_are_distinct")
        policy = client.get(
            "/api/v1/orders/O-A101/policy",
            headers=headers,
            params={"intent": "RETURN_REFUND", "top_k": 6},
        ).json()["data"]
        assert policy["policy_version"] == "POLICY-A-2026-10-v1"
        assert {c["chunk_id"] for c in policy["clauses"]} == {
            "A-RETURN-01",
            "A-RETURN-02",
            "A-CONFIRM-01",
            "A-REFUND-01",
        }
        assert policy["retrieval_mode"] in {"metadata_only", "keyword_v1"}
        checks.append("current_tenant_policy_with_citations")
        for order in ("O-A108", "O-B101"):
            assert (
                client.get(f"/api/v1/orders/{order}/logistics", headers=headers).status_code == 404
            )
            assert (
                client.get(
                    f"/api/v1/orders/{order}/policy",
                    headers=headers,
                    params={"intent": "RETURN_REFUND"},
                ).status_code
                == 404
            )
            assert (
                client.post(
                    f"/api/v1/orders/{order}/eligibility",
                    headers=headers,
                    json={"case_type": "RETURN_REFUND"},
                ).status_code
                == 404
            )
        checks.append("new_endpoints_preserve_customer_and_tenant_isolation")
        assert (
            client.post(
                "/api/v1/orders/O-A101/eligibility",
                headers=headers,
                json={"case_type": "RETURN_REFUND", "now": "2099"},
            ).status_code
            == 422
        )
        checks.append("client_clock_override_rejected")
    report = {
        "checked_at_utc": datetime.now(UTC).isoformat(),
        "result": "PASS",
        "api_version": "api-v1-m1",
        "scope": "Live HTTP and PostgreSQL; no LLM",
        "business_clock": "fixture",
        "checks": checks,
    }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
