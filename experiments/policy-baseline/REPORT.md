# KSYBOB policy baseline result

**PASS: 36 of 36 assertions matched the predefined policy decisions.** The same twelve cases were evaluated three times and produced identical assertion results, reasons, and messages.

- Host: KSYBOB, Windows 10.0.26200.0, PowerShell 7.6.5.
- Run start: 2026-09-18 14:43:48 UTC (23:43:48 Korea Standard Time).
- Engine: official Kyverno CLI 1.19.1, commit `40ec788d48bb28d83dbf85538e962a59db9d45c6`.
- Mode: local offline policy evaluation; all three CLI executions exited with code 0.

| Experiment policy | Cases per run | Expected policy pass | Expected policy fail | Assertions matched across 3 runs |
| --- | ---: | ---: | ---: | ---: |
| Disallow privileged mode in regular containers | 4 | 2 | 2 | 12/12 |
| Require explicit container-level runAsNonRoot: true | 4 | 1 | 3 | 12/12 |
| Require registry.example.com/ image prefix | 4 | 1 | 3 | 12/12 |
| Total | 12 | 4 | 8 | 36/36 |

Each policy used a normal case, an explicit violation, a missing-field case, and a two-container case with one violation. An expected policy failure is a successful test assertion when Kyverno reports that failure. This baseline observed no disagreement with its expectations; it does not establish a general detection rate outside these synthetic cases.

The repository did not supply a paper or research hypothesis. These results establish a small reproducible policy-logic baseline, not a paper reproduction or an admission performance result. The policies intentionally target regular containers only; the non-root contract does not model Pod-level inheritance. The missing-image input is an incomplete offline fixture. See the [design and limitations](README.md).

## Evidence

- [Machine, versions, input hashes and run metadata](results/20260918T144348Z-KSYBOB/summary.json)
- [All 36 expected-decision assertions](results/20260918T144348Z-KSYBOB/assertions.csv)
- Raw CLI output: [run 1](results/20260918T144348Z-KSYBOB/run-1.stdout.log), [run 2](results/20260918T144348Z-KSYBOB/run-2.stdout.log), [run 3](results/20260918T144348Z-KSYBOB/run-3.stdout.log).

The raw stderr files contain no diagnostics. Archive SHA256 was verified before extracting the CLI, and the executed binary SHA256 is recorded in the metadata. Source manifests and expectations were fixed before the recorded runs.
