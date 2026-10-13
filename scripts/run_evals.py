"""Run real PostgreSQL scenarios and persist every trial, including failures."""

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.agent_store import redact  # noqa: E402
from app.evaluation import json_default, summary, trial  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", choices=["dev", "holdout", "holdout-v2"], default="dev")
    parser.add_argument("--baseline", choices=["B0", "B1", "B2", "all"], default="all")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--cases", default="")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    if not 1 <= args.repeats <= 10:
        parser.error("repeats must be 1..10")
    dataset = (
        ROOT
        / "evals"
        / {
            "dev": "scenarios.jsonl",
            "holdout": "holdout_v1.jsonl",
            "holdout-v2": "holdout_v2.jsonl",
        }[args.dataset]
    )
    sha = hashlib.sha256(dataset.read_bytes()).hexdigest()
    if args.dataset != "dev" and args.live:
        freeze_path = (
            ROOT
            / "evals"
            / ("holdout_freeze.json" if args.dataset == "holdout" else "holdout_v2_freeze.json")
        )
        freeze = json.loads(freeze_path.read_text(encoding="utf-8")) if freeze_path.exists() else {}
        if freeze.get("sha256") != sha:
            parser.error("Holdout human review/freeze is required before live execution")
        if any(
            hashlib.sha256((ROOT / path).read_bytes()).hexdigest() != frozen_hash
            for path, frozen_hash in freeze.get("implementation_sha256", {}).items()
        ):
            parser.error("Frozen holdout implementation changed; create a new reviewed evaluation")
    scenarios = [
        json.loads(line)
        for line in dataset.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    contracts = json.loads((ROOT / "evals/request_contracts.json").read_text(encoding="utf-8"))
    if args.cases:
        selected = set(args.cases.split(","))
        if selected - {s["case_id"] for s in scenarios}:
            parser.error("Unknown case IDs")
        scenarios = [s for s in scenarios if s["case_id"] in selected]
    destination = Path(args.output).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    if (destination / "trials.jsonl").exists():
        parser.error(
            "Output already contains trials; use a new directory to preserve previous attempts"
        )
    manifest = {
        "eval_version": "eval-v2-m4",
        "dataset_sha256": sha,
        "dataset": args.dataset,
        "git_commit": None,
        "git_state": "unborn/uncommitted",
        "fixture_version": "fixtures-v1",
        "policy_schema_version": "policy-schema-v1",
        "prompt_version": "prompt-v5-m4",
        "tool_schema_version": "tools-v2-m4",
        "retrieval_version": "keyword_v1",
        "schema_version": "0005_m4",
        "prompt_sha256": hashlib.sha256(
            (ROOT / "backend/app/prompts/system_m4.txt").read_bytes()
        ).hexdigest(),
        "request_contract_sha256": hashlib.sha256(
            (ROOT / "evals/request_contracts.json").read_bytes()
        ).hexdigest(),
        "fixtures_sha256": hashlib.sha256((ROOT / "data/fixtures.json").read_bytes()).hexdigest(),
        "seed": None,
        "repeats": args.repeats,
        "transport": "ASGI TestClient + real PostgreSQL + live external model",
        "model_official_version": "DeepSeek-V4.1-Flash",
        "model_alias_immutable": False,
        "price_source": "https://api-docs.deepseek.com/quick_start/pricing/",
        "price_verified_date": "2026-10-12",
        "fact_metric_scope": (
            "Structured final assertions grounded in successful tools; "
            "bounded free-text checks; no exhaustive semantic judging"
        ),
        "latency_scope": (
            "Active task time across turns; excludes schema setup and human waiting; "
            "includes tools, model and confirmation card"
        ),
        "tuning_exposure": (
            "dev36 + first holdout-v1 failures for v5; holdout-v2 not used in prompt tuning"
        ),
        "selection": args.cases or "all",
    }
    (destination / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    results = []
    for scenario in scenarios:
        fault_contract = any(f["target"] == "llm" for f in scenario.get("faults", []))
        if scenario["level"] != "agent":
            baselines, repeats = ["SHARED"], 1
        elif fault_contract:
            baselines, repeats = ["B2"], 1
        else:
            baselines = ["B0", "B1", "B2"] if args.baseline == "all" else [args.baseline]
            baselines = [
                b
                for b in baselines
                if b != "B1"
                or scenario.get("readonly_comparison")
                or scenario["case_id"] in contracts["readonly_cases"]
            ]
            if not args.live:
                baselines = [b for b in baselines if b == "B0"]
            repeats = args.repeats
        for baseline in baselines:
            for repeat in range(repeats):
                result = trial(scenario, baseline, contracts, live=args.live)
                result["repeat_index"] = repeat
                trace = destination / f"{scenario['case_id']}_{baseline}_{repeat}.json"
                trace.write_text(
                    json.dumps(redact(result), ensure_ascii=False, indent=2, default=json_default)
                    + "\n",
                    encoding="utf-8",
                )
                result["trace_path"] = str(trace)
                results.append(result)
                with (destination / "trials.jsonl").open("a", encoding="utf-8") as stream:
                    stream.write(
                        json.dumps(redact(result), ensure_ascii=False, default=json_default) + "\n"
                    )
                (destination / "summary.json").write_text(
                    json.dumps(summary(results), ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                print(
                    f"{scenario['case_id']} {baseline} repeat={repeat} "
                    f"{'PASS' if result['score']['success'] else 'FAIL'} "
                    f"{result['evidence']['latency_ms']}ms",
                    flush=True,
                )


if __name__ == "__main__":
    main()
