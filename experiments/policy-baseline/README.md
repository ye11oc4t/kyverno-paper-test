# Offline policy baseline

This is the first executable policy-logic baseline on KSYBOB. It is not a reproduction of a particular paper: no paper, research hypothesis, or target Kyverno version was supplied. The experiment asks whether three explicitly defined policies produce the expected results on twelve synthetic inputs, consistently over three sequential executions.

| Policy | Normal | Explicit violation | Missing field | One compliant and one violating container |
| --- | --- | --- | --- | --- |
| Disallow privileged mode | pass | fail | pass | fail |
| Require container-level runAsNonRoot: true | pass | fail | fail | fail |
| Require registry.example.com/ image prefix | pass | fail | fail | fail |

The expected decisions are fixed in `kyverno-test.yaml` files and tabulated in `expectations.csv`. A successful test assertion means the policy decision matched its expectation; it does not mean the input was allowed. Each repetition should therefore contain four expected policy passes and eight expected policy failures, with twelve successful assertions.

## Reproduce on Windows x64

Use PowerShell 7 from the repository root:

```powershell
./experiments/policy-baseline/install-cli.ps1
./experiments/policy-baseline/run.ps1 -Repeats 3
```

The installer downloads the official Kyverno v1.19.1 Windows x64 archive into the ignored `work/` directory and verifies its SHA256 against the release asset digest. It does not change PATH. The runner records the executable hash, input hashes, version, host, logs, individual assertions, and repeat consistency in a new timestamped results directory. CLI JSON arrays are embedded in progress output, so the runner extracts each array and checks all twelve unique expected identities as well as the CLI exit code.

## Interpretation limits

- These are offline CEL `ValidatingPolicy` tests, confined to `spec.containers` on Pods. They do not cover init/ephemeral containers, inherited Pod security context, controller autogeneration, or comprehensive Kubernetes Pod Security Standards. Requiring container-level non-root explicitly is this experiment's chosen contract, not a claim about all valid non-root configurations.
- Image names use example domains and are never pulled. The missing-image fixture is deliberately incomplete for policy-logic testing and is not a valid deployable Pod.
- No resources or policies are applied to a cluster. Kubernetes defaulting, admission webhook behavior, runtime execution, image provenance, and cluster integration are outside scope.
- Three repeated runs check observed consistency only; they do not establish universal correctness. Timings include CLI startup and file IO and are not an admission performance benchmark.

## Primary references

- [Kyverno CLI and test manifests](https://kyverno.io/docs/subprojects/kyverno-cli/#testing-validatingpolicies)
- [ValidatingPolicy](https://kyverno.io/docs/policy-types/validating-policy/)
- [Pinned v1.19.1 release](https://github.com/kyverno/kyverno/releases/tag/v1.19.1)
