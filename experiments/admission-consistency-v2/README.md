# Admission consistency review and expanded benign study

The [Korean report](REPORT.ko.md) explains the design correction and results. The [pre-execution plan](PLAN.ko.md) fixes the v2 scope. v1 data is preserved separately.

This is a bounded conformance study with harmless pause containers. Both image aliases have identical content. The two custom rules check a name prefix and an exact image alias. Each live engine receives the same 24 cases once: 11 cases on each of two routes, plus two cases with a pre-existing compliant ephemeral container. Cases test list ordering, multiple violations, preservation of previous state, and absence of partial persistence after denial. The fixed shuffle seed is 20260919. Expected outcomes are declared in the catalogue before execution.

Live targets: Kubernetes VAP v1.35.8, Kyverno v1.19.1 CEL ValidatingPolicy, Gatekeeper v3.23.1 Rego, and Kubewarden v1.37.2 (chart 6.0.2; CEL policy v1.6.4 pinned by OCI digest). Polaris v10.2.5 evaluates hypothetical complete objects offline, using explicit PodSpec JSON Schema checks. It is not counted as a fifth live admission controller. The CLI mode does not exercise Polaris's supported webhook deployment mode.

## Reproduction on the recorded KSYBOB WSL environment

First prepare the pinned v1 kind, kubectl, node image, and harmless image aliases:

```sh
bash experiments/admission-consistency/prepare.sh
python3 experiments/admission-consistency-v2/prepare.py
python3 experiments/admission-consistency-v2/review_v1.py
python3 experiments/admission-consistency-v2/run.py --engine kubewarden
python3 experiments/admission-consistency-v2/run.py --engine vap
python3 experiments/admission-consistency-v2/run.py --engine kyverno
python3 experiments/admission-consistency-v2/run.py --engine gatekeeper
python3 experiments/admission-consistency-v2/check.py
python3 experiments/admission-consistency-v2/polaris.py
python3 experiments/admission-consistency-v2/check_polaris.py
python3 experiments/admission-consistency-v2/review_sources.py
```

Run live engines sequentially. Every live run uses its own kind cluster and dedicated kubeconfig, preserves evidence, then removes that specific cluster using the v1 identity guard. The scripts require Python 3; only `review_sources.py` additionally needs PyYAML (6.0.1 on this host). Tools stay in the study cache. `downloads.json` records exact downloads/checksums. The chart's default recommended policies are not enabled; the namespace's restricted Pod Security Admission baseline stays active. No telemetry destination is configured by the study.

## Reading results

`results/crosscheck.json` covers live runs. The checker re-derives expected outcomes from audit response codes and stored observations, verifies every submitted probe against the frozen catalogue, checks pre-existing state on denial/history cases, and validates frozen input hashes. An allowed response still does not directly prove each policy expression was invoked; invocation evidence is `UNKNOWN`. The same author wrote the harness and reviewed its evidence.

`results/offline-crosscheck.json` covers Polaris separately. It requires exactly one evaluated object and both named rule results per case. It verifies individual rule success values as well as exit codes and frozen inputs. An initial `.json` input attempt produced no evaluated objects and was excluded; the `.yaml` attempt preserves actual evaluations. A score of 100 with an empty results list is not treated as a policy success.

The fixed source sample in `source-review.json` contains immutable commits, hashes and source URLs. Field references in source are not proof of live invocation or complete policy coverage. This sample is not an ecosystem-wide survey, and the published policies were not deployed by these tests. Kyverno legacy ClusterPolicy, runtime security capabilities, outages, exception semantics, admission mutation ordering and all public policy libraries are outside the live results.
