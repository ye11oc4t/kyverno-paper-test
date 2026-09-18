# Benign admission consistency pilot

Read the [Korean results and interpretation](REPORT.ko.md) for the measured scope, outcomes, and excluded setup attempts.

This implements the [research protocol](../../research/ephemeral-policy-consistency/PROTOCOL.ko.md) for two custom conformance rules: container names start with `study-`, and image references equal the approved study alias. Both image aliases contain the same benign Kubernetes pause image. The fixtures run without added capabilities, privilege escalation, writable root filesystems, or mounted SA credentials.

The comparison covers regular Pod creation and adding an Ephemeral Container. Each engine receives eight distinct cases, repeated three times. Every measured Ephemeral Container request has its own compliant base Pod; base creation, audit canaries, and readiness canaries are setup checks and are excluded from case counts.

The engine policies are deliberately specified to cover both container types. They are study-authored policies, not a sample of all published security policies. A successful result supports conformance for these rules under the recorded configuration; it does not establish universal security coverage or exploitability.

## Environment and reproduction

The tested host is KSYBOB with Ubuntu 24.04 on WSL2 and Docker 29.8.0. The scripts use a fixed task cache at `/root/.cache/kyverno-paper-study` and create uniquely named local kind clusters. They refuse to reuse an existing cluster, use a dedicated kubeconfig, and remove only the cluster created by that run after capturing evidence. Run one engine at a time.

From the repository root inside that Linux environment:

```sh
bash experiments/admission-consistency/prepare.sh
python3 experiments/admission-consistency/run.py --engine vap
python3 experiments/admission-consistency/run.py --engine kyverno
python3 experiments/admission-consistency/run.py --engine gatekeeper
python3 experiments/admission-consistency/summarize.py
```

The preparation script pins kind v0.33.0, kubectl and Kubernetes v1.35.8, Kyverno v1.19.1, Gatekeeper v3.23.1, and the pause image content. Release binaries/manifests are checksum checked; node and pause image content use digests. Linux amd64 image export is explicit to avoid exporting an incomplete multi-platform index from Docker's containerd image store. This pilot uses Kubernetes 1.35, within Kyverno 1.19's documented compatibility range. [Kyverno supported versions](https://kyverno.io/docs/installation/releases/)

## Evidence

Every run has its own UTC-stamped directory. `frozen-inputs.json` records source hashes, policy hashes, image identities, and versions before measured cases. `expectations.csv` specifies the eight contracts. `runner-used.py` and `expectations-used.csv` preserve the exact source and expectations used by completed measurement runs.

For each request, the runner stores the submitted object, CLI response, exit code, object observation, and normalized result. The postprocessor checks the original fixture and stored/runtime observations against the normalized rows and case specification, verifies frozen source/expectation hashes, and correlates request fields, response codes, and denial messages with API audit records. This is a separate evidence check by the same author, not an independent reviewer validation. Audit readiness is checked before installing a policy. The restricted Pod Security Admission profile remains enabled in the study namespace; any unrelated rejection is an experiment error, not a successful study-rule denial.

The raw evidence distinguishes request acceptance, explicit study-rule rejection, object persistence, and benign process startup. It does not equate an allowed API response with direct proof that each policy expression was evaluated: such invocation evidence remains `UNKNOWN` unless separately established. Explicit denial messages identify the rejecting study rule. VAP is evaluated inside the API server, while the other engines use their respective admission integrations.

`results/crosscheck.json` lists every attempt, including setup failures and excluded pilots. An excluded run's `disposition.json` explains why it is not part of the primary comparison, without rewriting its original observations. Setup failures, including image import, audit configuration, webhook connection readiness, and an incorrect generated-resource name in the harness, are recorded separately from policy findings. Policy registration retries only specific webhook transport failures during setup; measured requests are never retried.

The Kyverno run used its CEL `ValidatingPolicy` API; it does not cover the legacy `ClusterPolicy` implementation. Its recorded status reports insufficient permissions for background reporting despite the observed admission decisions matching expectations. Gatekeeper uses the official manifest's default webhook failure policy. Background reporting, audit-controller health, and behavior during webhook communication failures are outside the measured claims.

## Primary references

- [Ephemeral Containers](https://kubernetes.io/docs/concepts/workloads/pods/ephemeral-containers/)
- [Dynamic Admission Control](https://kubernetes.io/docs/reference/access-authn-authz/extensible-admission-controllers/)
- [ValidatingAdmissionPolicy](https://kubernetes.io/docs/reference/access-authn-authz/validating-admission-policy/)
- [kind audit configuration](https://kind.sigs.k8s.io/docs/user/auditing/)
- [Kyverno installation](https://kyverno.io/docs/installation/installation/)
- [Gatekeeper installation](https://open-policy-agent.github.io/gatekeeper/website/docs/install/)
