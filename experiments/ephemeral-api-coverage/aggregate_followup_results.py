#!/usr/bin/env python3
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"
PRODUCTS = ("kyverno", "gatekeeper", "kubewarden")
FAMILIES = ("escalation", "capabilities")
POLICY_MARKERS = {
    "kyverno": {
        "fixed": "disallow-privileged-containers",
        "escalation": "disallow-privilege-escalation",
        "capabilities": "disallow-capabilities-strict",
    },
    "gatekeeper": {
        "fixed": "psp-privileged-container",
        "escalation": "psp-allow-privilege-escalation-container",
        "capabilities": "psp-capabilities-restricted",
    },
    "kubewarden": {
        "fixed": "Privileged ephemeral container is not allowed",
        "escalation": "privilege escalation enabled",
        "capabilities": "SYS_ADMIN",
    },
}


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


control_root = RESULTS / "2026-09-19-kubernetes-controls"
controls = read_json(control_root / "summary.json")
psa_message = read_json(control_root / "responses" / "PSA_PRIVILEGED.json")["message"]
rbac_message = read_json(control_root / "responses" / "RBAC_PRIVILEGED.json")["message"]
assert controls["psa"] == {
    "safeEphemeralHttp": 200,
    "privilegedEphemeralHttp": 403,
    "rbacCanUpdate": True,
    "privilegedStored": False,
}
assert controls["rbac"] == {
    "privilegedEphemeralHttp": 403,
    "rbacCanUpdate": False,
    "privilegedStored": False,
}
assert "violates PodSecurity" in psa_message and "debug-privileged" in psa_message
assert "cannot patch resource \"pods/ephemeralcontainers\"" in rbac_message

fixed_root = RESULTS / "2026-09-19-live-fixes"
fixed_results = []
for product in PRODUCTS:
    run = fixed_root / product
    summary = read_json(run / "summary.json")
    c3_message = read_json(run / "responses" / "C3.json")["message"]
    assert summary["product"] == product
    assert summary["httpStatus"]["ordinaryPrivilegedCreate"] >= 400
    assert summary["httpStatus"]["safeEphemeralUpdate"] == 200
    assert summary["httpStatus"]["privilegedEphemeralUpdate"] >= 400
    assert summary["pod"] == {
        "safeStored": True,
        "safeState": "Running",
        "privilegedStored": False,
    }
    assert POLICY_MARKERS[product]["fixed"] in c3_message
    fixed_results.append({**summary, "privilegedEphemeralDenyMessage": c3_message})

family_root = RESULTS / "2026-09-19-policy-families"
family_results = []
cause_isolation_results = []
for product in PRODUCTS:
    for family in FAMILIES:
        run = family_root / product / family / "run-1"
        summary = read_json(run / "summary.json")
        ordinary_message = read_json(run / "responses" / "ordinary-violation.json")["message"]
        assert summary["product"] == product and summary["family"] == family
        assert summary["httpStatus"] == {
            "ordinarySafe": 201,
            "ordinaryViolation": 400 if product != "gatekeeper" else 403,
            "ephemeralSafe": 200,
            "ephemeralViolation": 200,
        }
        assert summary["returnedViolationValue"]["ordinary"] is None
        expected = True if family == "escalation" else ["SYS_ADMIN"]
        assert summary["returnedViolationValue"]["ephemeral"] == expected
        assert POLICY_MARKERS[product][family] in ordinary_message
        family_results.append({**summary, "ordinaryDenyMessage": ordinary_message})

        fixed_run = family_root / product / family / "route-fix"
        fixed_summary = read_json(fixed_run / "summary.json")
        if product == "kyverno":
            fix_evidence = json.dumps(
                read_json(fixed_run / "evidence" / "kyverno-validating-policies.json")
            )
            assert "pods/ephemeralcontainers" in fix_evidence
        elif product == "gatekeeper":
            fix_evidence = json.dumps(
                read_json(fixed_run / "evidence" / "gatekeeper-constraint-templates.json")
            )
            assert "subResource" in fix_evidence and "ephemeralcontainers" in fix_evidence
        else:
            fix_evidence = json.dumps(
                read_json(fixed_run / "evidence" / "mutating-webhooks.json")
            )
            assert "pods/ephemeralcontainers" in fix_evidence
        assert fixed_summary["product"] == product and fixed_summary["family"] == family
        assert fixed_summary["httpStatus"]["ordinarySafe"] == 201
        assert fixed_summary["httpStatus"]["ordinaryViolation"] == (
            403 if product == "gatekeeper" else 400
        )
        assert fixed_summary["httpStatus"]["ephemeralSafe"] == 200
        if product in ("kyverno", "gatekeeper"):
            assert fixed_summary["httpStatus"]["ephemeralViolation"] == (
                403 if product == "gatekeeper" else 400
            )
            assert fixed_summary["returnedViolationValue"]["ephemeral"] is None
            fixed_message = read_json(
                fixed_run / "responses" / "ephemeral-violation.json"
            )["message"]
            assert POLICY_MARKERS[product][family] in fixed_message
        else:
            assert fixed_summary["httpStatus"]["ephemeralViolation"] == 200
            assert fixed_summary["returnedViolationValue"]["ephemeral"] == expected
            fixed_message = ""
        cause_isolation_results.append(
            {**fixed_summary, "ephemeralDenyMessage": fixed_message or None}
        )

aggregate = {
    "experiment": "Kubernetes-native controls, minimal live fixes, and policy-family generalization",
    "date": "2026-09-19",
    "kubernetesControls": {
        **controls,
        "psaDenyMessage": psa_message,
        "rbacDenyMessage": rbac_message,
    },
    "minimalFixes": fixed_results,
    "policyFamilies": family_results,
    "policyFamilyCauseIsolation": cause_isolation_results,
    "result": (
        "Kubernetes PSA and RBAC blocked the subresource as designed; each product's minimal fix "
        "preserved a safe ephemeral container and blocked a privileged one; all three public policy "
        "sets denied ordinary privilege-escalation and SYS_ADMIN violations but admitted the same "
        "values through pods/ephemeralcontainers. Routing or UPDATE-guard fixes were sufficient for "
        "Kyverno and Gatekeeper, while Kubewarden still admitted both violations after route-only fixes."
    ),
}
(RESULTS / "2026-09-19-followup-aggregate.json").write_text(
    json.dumps(aggregate, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
)
print(json.dumps(aggregate, indent=2, ensure_ascii=False))
