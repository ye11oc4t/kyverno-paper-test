# Public policy coverage survey

Read-only, manually reviewed, exploratory survey of 13 official policy/example units across four projects. This is separate from the benign custom-policy admission experiments. No sampled security policies were deployed or executed in this survey.

- [Korean report](REPORT.ko.md)
- [Method and classification](METHOD.ko.md)
- [Coverage matrix](MATRIX.ko.md)
- [Full records](coverage.json) and [CSV](coverage.csv)
- [Fixed source revisions and hashes](source-lock.json)
- [Integrity verification](integrity.json)

`review.py` contains the manually authored judgments and evidence anchors. It renders the JSON, CSV and Markdown records; it is not an automatic vulnerability detector. `collect.py` fetches only the enumerated source files and records hashes. Full third-party source files remain in the local cache, outside this repository. Cache paths include the source commit.

Run in the KSYBOB WSL environment with Python 3 and network access for the first collection:

```bash
python3 collect.py
python3 review.py
```

The cache is `/root/.cache/kyverno-paper-study/coverage-survey`. Recollection updates the collection timestamp and source-lock hash; rerun the renderer afterward. The integrity checks verify source hashes, row counts and anchor bounds, not independent agreement with the manual findings. The 56 locked files include one Kubernetes API reference file; the policy sample still consists of four projects.

Kyverno and Gatekeeper policy-library commits are fixed snapshots. Kubewarden's monorepo snapshot was selected during the preceding CEL study; the sampled modules have their own source metadata versions, not the CEL module's version. Polaris is the v10.2.5 source snapshot; Kubernetes API is v0.35.8, corresponding to Kubernetes v1.35.8. The policy survey does not establish that any downloaded module binary matches these sources.
