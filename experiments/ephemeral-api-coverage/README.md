# Ephemeral API policy coverage experiment

The canonical study was executed on 2026-09-19 with persisted API objects and running containers. It covers Kyverno, Gatekeeper, and Kubewarden across privileged, privilege-escalation, and Linux-capability policy families.

`run-live-study.sh` creates three independent clusters per product, activates one policy family at a time, and runs five repetitions per installation and family. `run-live-matrix-case.sh` sends four real API requests per experiment unit: safe and violating ordinary Pods, followed by safe and violating ephemeral containers on separate baseline Pods. Every admitted case is checked by reading the stored Pod, waiting for the container runtime, and collecting the process security state.

The canonical machine-readable result is [results/2026-09-19-live-matrix/aggregate.json](results/2026-09-19-live-matrix/aggregate.json). The 135 experiment units contain 540 API requests. Run `aggregate_live_matrix.py` to verify completeness, control behavior, persistence, execution, and runtime effects, then regenerate the CSV, Korean report, and SHA-256 evidence manifest.

`run-native-controls-live.sh` executes the separate Kubernetes Pod Security Admission and RBAC controls. Its output is stored under [results/2026-09-19-live-native-controls](results/2026-09-19-live-native-controls).

The current paper is [../../paper/EPHEMERAL-POLICY-COVERAGE-REVISION.ko.md](../../paper/EPHEMERAL-POLICY-COVERAGE-REVISION.ko.md).
