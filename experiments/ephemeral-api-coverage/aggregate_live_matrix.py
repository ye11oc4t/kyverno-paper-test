#!/usr/bin/env python3
import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE / "results" / "2026-09-19-live-matrix"
PRODUCTS = ("kyverno", "gatekeeper", "kubewarden")
FAMILIES = ("privileged", "escalation", "capabilities")
INSTALLS = range(1, 4)
REPEATS = range(1, 6)


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def admitted(status: int) -> bool:
    return 200 <= status < 300


def executed(state: str) -> bool:
    return state in {"Running", "Terminated"}


def effect_observed(family: str, runtime: dict) -> bool:
    if not executed(runtime["state"]):
        return False
    if family == "escalation":
        return runtime["noNewPrivs"] == "0"
    try:
        cap_eff = int(runtime["capEff"], 16)
    except (TypeError, ValueError):
        return False
    if family == "privileged":
        return cap_eff != 0 and runtime["noNewPrivs"] == "0"
    return bool(cap_eff & (1 << 21))


rows = []
missing = []
for product in PRODUCTS:
    for install in INSTALLS:
        for family in FAMILIES:
            for repeat in REPEATS:
                path = ROOT / product / f"install-{install}" / family / f"repeat-{repeat}" / "summary.json"
                if not path.exists():
                    missing.append(path.relative_to(ROOT).as_posix())
                    continue
                summary = load(path)
                statuses = summary["httpStatus"]
                persisted = summary["persisted"]
                runtime = summary["runtime"]
                row = {
                    "product": product,
                    "install": install,
                    "family": family,
                    "repeat": repeat,
                    "ordinary_safe_http": statuses["ordinarySafe"],
                    "ordinary_safe_persisted": persisted["ordinarySafe"],
                    "ordinary_safe_runtime": runtime["ordinarySafe"]["state"],
                    "ordinary_violation_http": statuses["ordinaryViolation"],
                    "ordinary_violation_denied": not admitted(statuses["ordinaryViolation"]),
                    "ordinary_violation_persisted": persisted["ordinaryViolation"],
                    "ephemeral_safe_http": statuses["ephemeralSafe"],
                    "ephemeral_safe_persisted": persisted["ephemeralSafe"],
                    "ephemeral_safe_runtime": runtime["ephemeralSafe"]["state"],
                    "ephemeral_violation_http": statuses["ephemeralViolation"],
                    "ephemeral_violation_admitted": admitted(statuses["ephemeralViolation"]),
                    "ephemeral_violation_persisted": persisted["ephemeralViolation"],
                    "ephemeral_violation_runtime": runtime["ephemeralViolation"]["state"],
                    "ephemeral_violation_cap_eff": runtime["ephemeralViolation"]["capEff"],
                    "ephemeral_violation_no_new_privs": runtime["ephemeralViolation"]["noNewPrivs"],
                    "runtime_effect_observed": effect_observed(family, runtime["ephemeralViolation"]),
                }
                rows.append(row)

if missing:
    raise SystemExit("missing result files:\n" + "\n".join(missing))

csv_path = ROOT / "aggregate.csv"
with csv_path.open("w", encoding="utf-8", newline="") as handle:
    writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)

groups = defaultdict(list)
for row in rows:
    groups[(row["product"], row["family"])].append(row)

group_results = []
for (product, family), group in sorted(groups.items()):
    trials = len(group)
    group_results.append(
        {
            "product": product,
            "family": family,
            "trials": trials,
            "independentInstalls": len({item["install"] for item in group}),
            "ordinarySafeAdmitted": sum(admitted(item["ordinary_safe_http"]) for item in group),
            "ordinarySafePersisted": sum(item["ordinary_safe_persisted"] for item in group),
            "ordinarySafeExecuted": sum(executed(item["ordinary_safe_runtime"]) for item in group),
            "ordinaryViolationDenied": sum(item["ordinary_violation_denied"] for item in group),
            "ordinaryViolationPersisted": sum(item["ordinary_violation_persisted"] for item in group),
            "ephemeralSafeAdmitted": sum(admitted(item["ephemeral_safe_http"]) for item in group),
            "ephemeralSafePersisted": sum(item["ephemeral_safe_persisted"] for item in group),
            "ephemeralSafeExecuted": sum(executed(item["ephemeral_safe_runtime"]) for item in group),
            "ephemeralViolationAdmitted": sum(item["ephemeral_violation_admitted"] for item in group),
            "ephemeralViolationPersisted": sum(item["ephemeral_violation_persisted"] for item in group),
            "ephemeralViolationExecuted": sum(executed(item["ephemeral_violation_runtime"]) for item in group),
            "runtimeEffectObserved": sum(item["runtime_effect_observed"] for item in group),
            "ordinaryViolationHttpStatuses": sorted({item["ordinary_violation_http"] for item in group}),
            "ephemeralViolationHttpStatuses": sorted({item["ephemeral_violation_http"] for item in group}),
        }
    )

aggregate = {
    "experiment": "persisted and executed ephemeral-container policy coverage",
    "date": "2026-09-19",
    "products": list(PRODUCTS),
    "policyFamilies": list(FAMILIES),
    "independentInstallsPerProduct": len(INSTALLS),
    "repeatsPerInstallAndFamily": len(REPEATS),
    "experimentUnits": len(rows),
    "apiRequests": len(rows) * 4,
    "groups": group_results,
}

verification_errors = []
for item in group_results:
    for field in (
        "ordinarySafeAdmitted",
        "ordinarySafePersisted",
        "ordinarySafeExecuted",
        "ordinaryViolationDenied",
        "ephemeralSafeAdmitted",
        "ephemeralSafePersisted",
        "ephemeralSafeExecuted",
        "ephemeralViolationAdmitted",
        "ephemeralViolationPersisted",
        "ephemeralViolationExecuted",
        "runtimeEffectObserved",
    ):
        if item[field] != item["trials"]:
            verification_errors.append(
                f"{item['product']}/{item['family']}: {field}={item[field]} of {item['trials']}"
            )
    if item["ordinaryViolationPersisted"] != 0:
        verification_errors.append(
            f"{item['product']}/{item['family']}: ordinaryViolationPersisted={item['ordinaryViolationPersisted']}"
        )
aggregate["verification"] = {
    "complete": not verification_errors,
    "errors": verification_errors,
}
if verification_errors:
    raise SystemExit("verification failed:\n" + "\n".join(verification_errors))

(ROOT / "aggregate.json").write_text(json.dumps(aggregate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

manifest = {}
for path in sorted(ROOT.rglob("*")):
    if not path.is_file() or path.name in {"aggregate.json", "aggregate.csv", "evidence-sha256.json", "LIVE-MATRIX-REPORT.ko.md"}:
        continue
    manifest[path.relative_to(ROOT).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
(ROOT / "evidence-sha256.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

table_lines = []
for item in group_results:
    table_lines.append(
        f"| {item['product']} | {item['family']} | {item['ordinaryViolationDenied']}/{item['trials']} | "
        f"{item['ephemeralViolationAdmitted']}/{item['trials']} | {item['ephemeralViolationPersisted']}/{item['trials']} | "
        f"{item['ephemeralViolationExecuted']}/{item['trials']} | {item['runtimeEffectObserved']}/{item['trials']} |"
    )

report = f"""# 실제 저장·실행 기반 본실험 결과

Kubernetes v1.35.8 kind 클러스터에서 Kyverno 1.19.1(차트 3.9.1), Gatekeeper 3.23.1, Kubewarden 1.37.2(차트 6.0.2)를 각각 세 번 독립 설치했다. 설치별로 privileged, allowPrivilegeEscalation, Linux capabilities 정책을 하나씩 격리하여 활성화하고 각 정책군을 다섯 번 반복했다. 총 {len(rows)}개 실험 단위에서 정상 일반 Pod, 위반 일반 Pod, 정상 임시 컨테이너, 위반 임시 컨테이너의 네 요청을 실제로 처리했으므로 API 요청은 {len(rows) * 4}건이다.

| 제품 | 정책군 | 일반 위반 거부 | 임시 위반 허용 | API 저장 | 컨테이너 실행 | 런타임 효과 관찰 |
|---|---|---:|---:|---:|---:|---:|
{chr(10).join(table_lines)}

모든 정상 일반 Pod와 정상 임시 컨테이너는 허용·저장·실행되었고, 모든 위반 일반 Pod는 정책 엔진에서 거부되어 저장되지 않았다. 반면 위반 임시 컨테이너는 모든 제품과 정책군 조합에서 허용되어 Pod 객체에 저장되고 컨테이너 런타임에 의해 실행되었다. privileged 사례는 0이 아닌 전체 유효 capability와 `NoNewPrivs=0`, allowPrivilegeEscalation 사례는 `NoNewPrivs=0`, capabilities 사례는 `SYS_ADMIN` 비트를 실제 프로세스 상태에서 확인했다.

각 반복의 요청 본문, HTTP 상태와 응답, API에서 다시 조회한 Pod 객체, 컨테이너 상태와 로그는 제품·설치·정책군·반복 디렉터리에 저장했다. `evidence-sha256.json`은 집계 산출물을 제외한 증거 파일의 SHA-256을 기록한다.
"""
(ROOT / "LIVE-MATRIX-REPORT.ko.md").write_text(report, encoding="utf-8")
print(json.dumps(aggregate, ensure_ascii=False, indent=2))
