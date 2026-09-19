# Ephemeral API policy coverage experiment

The experiment was executed on 2026-09-19. Read [the Korean report](REPORT.ko.md) for the method, results, exclusions, and claim boundaries. A subsequent non-dry-run check persisted and ran one privileged ephemeral container under each product; see [the live execution report](LIVE-REPORT.ko.md).

The canonical machine-readable result is [results/2026-09-19/aggregate.json](results/2026-09-19/aggregate.json). `run-api-cases.sh` sends the four API-only cases with a dedicated ServiceAccount. `aggregate_results.py` validates the 45 canonical runs and the three cause-isolation runs.

The 45 canonical admission repetitions use `dryRun=All`. The separate live follow-up is stored under [results/2026-09-19-live-execution](results/2026-09-19-live-execution) and is validated by `aggregate_live_results.py`. Its payload only prints UID and effective Linux capabilities and then sleeps; it does not access the host or attempt an escape.
