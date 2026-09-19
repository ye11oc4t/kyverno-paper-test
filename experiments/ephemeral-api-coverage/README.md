# Ephemeral API policy coverage experiment

The experiment was executed on 2026-09-19. Read [the Korean report](REPORT.ko.md) for the method, results, exclusions, and claim boundaries.

The canonical machine-readable result is [results/2026-09-19/aggregate.json](results/2026-09-19/aggregate.json). `run-api-cases.sh` sends the four API-only cases with a dedicated ServiceAccount. `aggregate_results.py` validates the 45 canonical runs and the three cause-isolation runs.

Privileged requests use `dryRun=All`. No privileged test container was persisted or executed.
