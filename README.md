# Kyverno Paper Test

Shared Git project for running and validating Kyverno paper experiments across Codex hosts.

Current research: effective policy coverage across Kubernetes API routes, operations, object traversal, and public policy bundles. The strongest source-derived candidate is a persistent Ephemeral Container false negative across Kyverno, Gatekeeper, Kubewarden, and Polaris for different implementation reasons. Other high-value candidates include OCI image volumes omitted from image trust policies and native sidecars omitted from resource checks. No new experiment has been executed for these candidates yet.

- [Policy gap candidates, ranking, and source evidence (Korean)](research/policy-gap-candidates/REPORT.ko.md)
- [Candidate experiment designs only (Korean)](research/policy-gap-candidates/EXPERIMENT-DESIGNS.ko.md)

- [Revised research protocol (Korean)](research/ephemeral-policy-consistency/PROTOCOL.ko.md)
- [Admission consistency pilot: results and interpretation (Korean)](experiments/admission-consistency/REPORT.ko.md)
- [Admission consistency pilot: reproduction and evidence](experiments/admission-consistency/README.md)
- [Expanded study: design review, additional tools, and results (Korean)](experiments/admission-consistency-v2/REPORT.ko.md)
- [Public policy coverage: 13 official policies/examples, source review (Korean)](research/public-policy-coverage/REPORT.ko.md)

- [KSYBOB environment check](REMOTE_EXPERIMENT.md)
- [Offline policy baseline: design and reproduction](experiments/policy-baseline/README.md)
- [First policy baseline results](experiments/policy-baseline/REPORT.md)
