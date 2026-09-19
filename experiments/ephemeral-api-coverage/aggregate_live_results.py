#!/usr/bin/env python3
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE / "results" / "2026-09-19-live-execution"
PRODUCTS = ("kyverno", "gatekeeper", "kubewarden")


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


results = []
for product in PRODUCTS:
    run = ROOT / product / "run-1"
    summary = read_json(run / "summary.json")
    pod = read_json(run / "evidence" / "baseline-after.json")
    deny_response = read_json(run / "responses" / "C1.json")
    safe_log = (run / "evidence" / "safe-container.log").read_text(encoding="utf-8")
    privileged_log = (run / "evidence" / "privileged-container.log").read_text(encoding="utf-8")

    assert summary["httpStatus"]["ordinaryPrivilegedCreate"] >= 400
    assert summary["httpStatus"]["safeEphemeralUpdate"] == 200
    assert summary["httpStatus"]["privilegedEphemeralUpdate"] == 200
    assert summary["runtime"]["safeEphemeral"] == "Running"
    assert summary["runtime"]["privilegedEphemeral"] == "Running"
    assert summary["runtime"]["safeCapEff"] == "0000000000000000"
    assert summary["runtime"]["privilegedCapEff"] != "0000000000000000"
    assert "uid=65532" in safe_log and "LIVE_SAFE" in safe_log
    assert "uid=0(root)" in privileged_log and "LIVE_PRIVILEGED" in privileged_log

    specs = {item["name"]: item for item in pod["spec"]["ephemeralContainers"]}
    statuses = {item["name"]: item for item in pod["status"]["ephemeralContainerStatuses"]}
    assert specs["debug-safe"]["securityContext"]["privileged"] is False
    assert specs["debug-privileged"]["securityContext"]["privileged"] is True
    assert "running" in statuses["debug-safe"]["state"]
    assert "running" in statuses["debug-privileged"]["state"]
    assert statuses["debug-safe"]["containerID"].startswith("containerd://")
    assert statuses["debug-privileged"]["containerID"].startswith("containerd://")

    results.append(
        {
            **summary,
            "ordinaryPrivilegedDenyMessage": deny_response.get("message", ""),
            "runtimeEvidence": {
                name: {
                    "containerID": statuses[name]["containerID"],
                    "imageID": statuses[name]["imageID"],
                    "startedAt": statuses[name]["state"]["running"]["startedAt"],
                    "uid": statuses[name]["user"]["linux"]["uid"],
                }
                for name in ("debug-safe", "debug-privileged")
            },
        }
    )

aggregate = {
    "experiment": "persisted privileged ephemeral container execution",
    "date": "2026-09-19",
    "independentProductInstalls": 3,
    "result": "all three policies denied an ordinary privileged Pod but admitted and ran a privileged ephemeral container",
    "products": results,
}
(ROOT / "aggregate.json").write_text(
    json.dumps(aggregate, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
)
print(json.dumps(aggregate, indent=2, ensure_ascii=False))
