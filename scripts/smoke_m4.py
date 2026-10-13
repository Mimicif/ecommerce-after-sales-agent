"""Real network HTTP M4 read/authorization regression, preserving demo business data."""

import json
from pathlib import Path

import httpx


def main():
    checks = []
    with httpx.Client(base_url="http://127.0.0.1:8000", timeout=10, trust_env=False) as client:
        assert client.get("/openapi.json").json()["info"]["version"] == "0.5.0"
        assert client.get("/api/v1/health").is_success

        def auth(actor):
            response = client.post("/api/v1/dev/sessions", json={"user_id": actor})
            assert response.status_code == 201
            return {"Authorization": "Bearer " + response.json()["data"]["access_token"]}

        a, b = auth("C-A1"), auth("C-B1")
        for headers, order, chunk in [(a, "O-A101", "A-RETURN-02"), (b, "O-B101", "B-RETURN-01")]:
            response = client.get(
                f"/api/v1/orders/{order}/policy",
                headers=headers,
                params={"intent": "RETURN_REFUND", "query": "定制易腐商品", "top_k": 1},
            )
            assert response.is_success, response.status_code
            data = response.json()["data"]
            assert data["retrieval_mode"] == "keyword_v1"
            assert [c["chunk_id"] for c in data["clauses"]] == [chunk]
            assert sum(c["selected"] for c in data["candidates"]) == 1
        checks.append("chinese_ranking_and_tenant_filter")
        for headers, order in [(a, "O-B101"), (b, "O-A101"), (a, "O-A108")]:
            for suffix in ["", "/policy?intent=RETURN_REFUND", "/logistics"]:
                assert (
                    client.get(f"/api/v1/orders/{order}{suffix}", headers=headers).status_code
                    == 404
                )
        checks.append("cross_tenant_and_customer_404")
        assert (
            client.get("/api/v1/orders/O-A102", headers=a).json()["data"]["cases"][0]["status"]
            == "PENDING_REVIEW"
        )
        checks.append("existing_pending_case_discoverable_by_authorized_customer")
        assert (
            client.get(
                "/api/v1/orders/O-A101/policy",
                headers=a,
                params={"intent": "RETURN_REFUND", "top_k": 7},
            ).status_code
            == 422
        )
        checks.append("invalid_top_k_rejected")
    output = {"result": "PASS", "mode": "REAL_HTTP", "checks": checks, "business_mutations": 0}
    path = Path("artifacts/m4/http_smoke.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False))


if __name__ == "__main__":
    main()
