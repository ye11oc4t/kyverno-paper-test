# Kyverno Paper Test

Shared Git project for running and validating Kyverno paper experiments across Codex hosts.

Current research: effective policy coverage across Kubernetes API routes, operations, object traversal, and public policy bundles. Experiments reproduced Ephemeral Container false negatives across Kyverno, Gatekeeper, and Kubewarden, verified actual runtime execution, tested Kubernetes-native controls, and isolated fixes across privileged, privilege-escalation, and capability policies. Other high-value candidates include OCI image volumes omitted from image trust policies and native sidecars omitted from resource checks.

- [Policy gap candidates, ranking, and source evidence (Korean)](research/policy-gap-candidates/REPORT.ko.md)
- [Candidate experiment designs only (Korean)](research/policy-gap-candidates/EXPERIMENT-DESIGNS.ko.md)
- [Three-tool Ephemeral Container API-only experiment design (Korean)](research/policy-gap-candidates/EPHEMERAL-API-EXPERIMENT.ko.md)
- [Three-tool Ephemeral Container experiment results (Korean)](experiments/ephemeral-api-coverage/REPORT.ko.md)
- [Three-tool persisted runtime follow-up results (Korean)](experiments/ephemeral-api-coverage/LIVE-REPORT.ko.md)
- [Kubernetes controls, live fixes, and additional policy families (Korean)](experiments/ephemeral-api-coverage/FOLLOWUP-REPORT.ko.md)
- [Ephemeral Container policy coverage paper draft (Korean)](paper/EPHEMERAL-POLICY-COVERAGE-DRAFT.ko.md)

- [Revised research protocol (Korean)](research/ephemeral-policy-consistency/PROTOCOL.ko.md)
- [Admission consistency pilot: results and interpretation (Korean)](experiments/admission-consistency/REPORT.ko.md)
- [Admission consistency pilot: reproduction and evidence](experiments/admission-consistency/README.md)
- [Expanded study: design review, additional tools, and results (Korean)](experiments/admission-consistency-v2/REPORT.ko.md)
- [Public policy coverage: 13 official policies/examples, source review (Korean)](research/public-policy-coverage/REPORT.ko.md)

- [KSYBOB environment check](REMOTE_EXPERIMENT.md)
- [Offline policy baseline: design and reproduction](experiments/policy-baseline/README.md)
- [First policy baseline results](experiments/policy-baseline/REPORT.md)
