"""Small live DeepSeek acceptance through HTTP and a separate durable worker process."""

import argparse
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="artifacts/m3/live_http.json")
    parser.add_argument(
        "--fresh-customer",
        action="store_true",
        help="Additional clean return flow for C-A2 / O-A108",
    )
    args = parser.parse_args()
    report = {
        "mode": "LIVE",
        "provider": "deepseek",
        "model_id": "deepseek-flash",
        "checked_at": datetime.now(UTC).isoformat(),
        "runs": [],
        "checks": {},
    }
    env = {**os.environ, "PYTHONPATH": str(ROOT / "backend"), "BUSINESS_CLOCK_MODE": "fixture"}
    with httpx.Client(base_url="http://127.0.0.1:8000", timeout=15, trust_env=False) as client:
        assert client.get("/openapi.json").json()["info"]["version"] == "0.4.0"
        headers = {}
        for user in ("C-A1", "C-A2", "C-B1", "E-A1"):
            data = client.post("/api/v1/dev/sessions", json={"user_id": user}).json()["data"]
            headers[user] = {"Authorization": "Bearer " + data["access_token"]}

        def request(method, path, *, user="C-A1", body=None, key=None):
            response = client.request(
                method,
                "/api/v1/" + path,
                json=body,
                headers={**headers[user], **({"Idempotency-Key": key} if key else {})},
            )
            assert response.is_success, (response.status_code, response.json()["code"])
            return response.json()["data"]

        def conversation(label, user="C-A1"):
            return request(
                "POST", "conversations", user=user, body={}, key="m3-live-conversation-" + label
            )["conversation_id"]

        def run(conv, label, content, *, action="CONSULT", target=None, user="C-A1"):
            body = {
                "client_message_id": "m3-live-" + label,
                "content": content,
                "action": action,
                "target_order_id": target,
            }
            posted = request("POST", f"conversations/{conv}/messages", user=user, body=body)
            if posted["status"] == "FAILED":
                report.setdefault("previous_failures", []).append(posted)
                body["client_message_id"] += "-retry-1"
                posted = request("POST", f"conversations/{conv}/messages", user=user, body=body)
            run_id = posted["run_id"]
            duplicate = request("POST", f"conversations/{conv}/messages", user=user, body=body)
            assert duplicate["run_id"] == run_id
            if posted["status"] in {"QUEUED", "RUNNING"}:
                process = subprocess.run(
                    [sys.executable, "-m", "app.cli", "agent-worker", "--max-runs", "1"],
                    cwd=ROOT,
                    env=env,
                    capture_output=True,
                    timeout=65,
                )
                assert process.returncode == 0, "Worker process failed (raw logs omitted)"
            result = request("GET", f"runs/{run_id}", user=user)
            events = request("GET", f"runs/{run_id}/events", user=user)
            report["runs"].append({"label": label, **result, "events": events["items"]})
            # Save failures too, without token/key/provider raw output.
            save()
            assert result["status"] in {"COMPLETED", "WAITING_FOR_USER"}, (
                label,
                result["error_code"],
            )
            assert result["provider"] == "deepseek"
            other_customer = "C-A1" if user == "C-A2" else "C-A2"
            assert (
                client.get(f"/api/v1/runs/{run_id}", headers=headers[other_customer]).status_code
                == 404
            )
            if user != "C-B1":
                assert (
                    client.get(f"/api/v1/runs/{run_id}/events", headers=headers["C-B1"]).status_code
                    == 404
                )
            return result

        def save():
            destination = ROOT / args.output
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(
                json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )

        conv = conversation("return")
        clarify = run(
            conv, "clarify", "我想退货，还没有选择订单。请先查我有哪些订单，再让我选择，不要建单。"
        )
        assert clarify["status"] == "WAITING_FOR_USER"
        assert not clarify["response"]["cases"]
        report["checks"]["multiple_orders_clarified"] = True
        applied = run(
            conv,
            "draft",
            "我要申请订单 O-A102 的普通退货退款，原因是不喜欢，请创建草稿。",
            action="APPLY_AFTER_SALES",
            target="O-A102",
        )
        case = applied["response"]["cases"][0]
        assert applied["status"] == "WAITING_FOR_USER" and case["status"] == "DRAFT"
        assert case["requested_amount_fen"] == 39900
        summary = request(
            "POST",
            f"cases/{case['id']}/confirmation",
            body={"expected_version": case["version"]},
            key="m3-live-summary-" + case["id"],
        )
        request(
            "POST",
            f"confirmations/{summary['confirmation_id']}/confirm",
            body={"payload_digest": summary["payload_digest"]},
            key="m3-live-confirm-" + case["id"],
        )
        submitted = run(
            conv,
            "submit",
            f"已通过独立确认接口确认申请 {case['id']}，请读取最新版本并提交审核。",
            action="SUBMIT_CONFIRMED",
            target="O-A102",
        )
        assert submitted["response"]["cases"][0]["status"] == "PENDING_REVIEW"
        report["checks"]["draft_real_confirmation_submit"] = True
        logistics = run(
            conversation("logistics"),
            "logistics",
            "订单 O-A104 的包裹很久没有更新，请查物流和物流政策，明确请求创建物流人工工单。",
            action="CREATE_TICKET",
            target="O-A104",
        )
        assert logistics["response"]["tickets"][0]["status"] == "OPEN"
        report["checks"]["logistics_ticket"] = True
        damage = run(
            conversation("damage"),
            "damage",
            "订单 O-A106 到货外壳损坏，暂时没有证据引用。请告诉我需要补什么，先不建单。",
        )
        assert damage["status"] == "WAITING_FOR_USER" and not damage["response"]["cases"]
        report["checks"]["damage_evidence_clarified"] = True
        bconv = conversation("tenant-b", "C-B1")
        b = run(
            bconv, "tenant-b", "查询订单 O-B101 的退货资格和本店政策。先咨询，不建单。", user="C-B1"
        )
        assert not b["response"]["cases"]
        report["checks"]["tenant_isolation"] = True
        if args.fresh_customer:
            fresh_conv = conversation("fresh-customer", "C-A2")
            fresh = run(
                fresh_conv,
                "fresh-draft",
                "申请 O-A108 普通退货，原因尺寸不合适，请建草稿。",
                action="APPLY_AFTER_SALES",
                target="O-A108",
                user="C-A2",
            )
            fresh_case = fresh["response"]["cases"][0]
            assert fresh_case["status"] == "DRAFT" and fresh_case["requested_amount_fen"] == 9900
            fresh_summary = request(
                "POST",
                f"cases/{fresh_case['id']}/confirmation",
                user="C-A2",
                body={"expected_version": fresh_case["version"]},
                key="m3-live-summary-" + fresh_case["id"],
            )
            request(
                "POST",
                f"confirmations/{fresh_summary['confirmation_id']}/confirm",
                user="C-A2",
                body={"payload_digest": fresh_summary["payload_digest"]},
                key="m3-live-confirm-" + fresh_case["id"],
            )
            fresh_submit = run(
                fresh_conv,
                "fresh-submit",
                f"独立客户确认已完成，请读取 {fresh_case['id']} 最新版本并提交审核。",
                action="SUBMIT_CONFIRMED",
                target="O-A108",
                user="C-A2",
            )
            assert fresh_submit["response"]["cases"][0]["status"] == "PENDING_REVIEW"
            report["checks"]["clean_customer_confirmation_submit"] = True
        report["ok"] = True
        save()
    print(
        json.dumps(
            {"ok": True, "mode": "LIVE", "runs": len(report["runs"]), "checks": report["checks"]},
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
