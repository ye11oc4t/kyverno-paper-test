#!/usr/bin/env python3
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results" / "2026-09-19"

CANONICAL_RUNS = {
    "kyverno": [
        "run-1", "run-1-r2", "run-1-r3", "run-1-r4", "run-1-r5",
        "run-2", "run-2-r2", "run-2-r3", "run-2-r4", "run-2-r5",
        "run-3", "run-3-r2", "run-3-r3", "run-3-r4", "run-3-r5",
    ],
    "gatekeeper": [
        *(f"run-1-stable-r{i}" for i in range(1, 6)),
        *(f"run-2-stable-r{i}" for i in range(1, 6)),
        *(f"run-3-stable-r{i}" for i in range(1, 6)),
    ],
    "kubewarden": [
        "run-1", "run-1-r2", "run-1-r3", "run-1-r4", "run-1-r5",
        "run-2", "run-2-r2", "run-2-r3", "run-2-r4", "run-2-r5",
        "run-3", "run-3-r2", "run-3-r3", "run-3-r4", "run-3-r5",
    ],
}

TARGET_MARKERS = {
    "kyverno": "disallow-privileged-containers",
    "gatekeeper": "privileged-container",
    "kubewarden": "no-privileged-pod",
}

ABLATIONS = {
    "kyverno": ("kyverno-ablation/before-routing-fix", "kyverno-ablation/after-routing-fix"),
    "gatekeeper": ("gatekeeper-ablation/before-update-fix", "gatekeeper-ablation/after-update-fix"),
    "kubewarden": ("kubewarden-ablation/before-routing-fix", "kubewarden-ablation/after-routing-fix"),
}


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def allowed(status: int) -> bool:
    return 200 <= status < 300


def validate_run(product: str, run_name: str):
    run = RESULTS / product / run_name
    summary = load_json(run / "summary.json")
    statuses = summary["httpStatus"]
    expected = (
        allowed(statuses["C0"])
        and not allowed(statuses["C1"])
        and allowed(statuses["C2"])
        and allowed(statuses["C3"])
    )
    rbac = summary["rbac"]["podsCreate"] and summary["rbac"]["ephemeralUpdate"]
    c1_body = (run / "cases" / "C1" / "response.json").read_text(encoding="utf-8").lower()
    target_denial = TARGET_MARKERS[product].lower() in c1_body
    before = load_json(run / "evidence" / "baseline-before.json")
    after = load_json(run / "evidence" / "baseline-after.json")
    unchanged = (
        before["metadata"]["resourceVersion"] == after["metadata"]["resourceVersion"]
        and not before["spec"].get("ephemeralContainers")
        and not after["spec"].get("ephemeralContainers")
    )
    return {
        "run": run_name,
        "httpStatus": statuses,
        "rbacValid": rbac,
        "targetPolicyDeniedC1": target_denial,
        "baselineUnchanged": unchanged,
        "expectedMissPattern": expected,
        "valid": expected and rbac and target_denial and unchanged,
    }


aggregate = {
    "date": "2026-09-19",
    "primaryPhase": "privileged ephemeral container admission",
    "products": {},
    "ablations": {},
    "excluded": {
        "gatekeeperWarmup": {
            "runs": ["run-1", "run-1-r2", "run-1-r3", "run-1-r4", "run-1-r5"],
            "reason": "The native ValidatingAdmissionPolicyBinding became active after the first request, changing the C1 denial path and status from webhook 403 to native VAP 422. Stable measurements were repeated after binding readiness.",
        }
    },
}

for product, run_names in CANONICAL_RUNS.items():
    runs = [validate_run(product, run_name) for run_name in run_names]
    aggregate["products"][product] = {
        "installations": 3,
        "repetitionsPerInstallation": 5,
        "validRuns": sum(run["valid"] for run in runs),
        "totalRuns": len(runs),
        "allExpectedMissPattern": all(run["expectedMissPattern"] for run in runs),
        "allValid": all(run["valid"] for run in runs),
        "uniqueHttpStatusPatterns": sorted({
            f'C0={run["httpStatus"]["C0"]},C1={run["httpStatus"]["C1"]},C2={run["httpStatus"]["C2"]},C3={run["httpStatus"]["C3"]}'
            for run in runs
        }),
        "runs": runs,
    }

for product, (before_name, after_name) in ABLATIONS.items():
    before = load_json(RESULTS / before_name / "summary.json")["httpStatus"]
    after = load_json(RESULTS / after_name / "summary.json")["httpStatus"]
    aggregate["ablations"][product] = {
        "before": before,
        "after": after,
        "c3ChangedFromAllowToDeny": allowed(before["C3"]) and not allowed(after["C3"]),
    }

legacy = load_json(RESULTS / "kyverno-clusterpolicy" / "comparison" / "summary.json")["httpStatus"]
aggregate["kyvernoClusterPolicyComparison"] = {
    "httpStatus": legacy,
    "c3Denied": not allowed(legacy["C3"]),
}

if not all(v["allValid"] for v in aggregate["products"].values()):
    raise SystemExit("one or more canonical runs are invalid")
if not all(v["c3ChangedFromAllowToDeny"] for v in aggregate["ablations"].values()):
    raise SystemExit("one or more ablations did not reverse C3")

(RESULTS / "aggregate.json").write_text(
    json.dumps(aggregate, ensure_ascii=False, indent=2) + "\n",
    encoding="utf-8",
)
print(json.dumps({
    "products": {
        k: {
            "validRuns": v["validRuns"],
            "totalRuns": v["totalRuns"],
            "patterns": v["uniqueHttpStatusPatterns"],
        }
        for k, v in aggregate["products"].items()
    },
    "ablations": aggregate["ablations"],
    "kyvernoClusterPolicyComparison": aggregate["kyvernoClusterPolicyComparison"],
}, ensure_ascii=False, indent=2))
