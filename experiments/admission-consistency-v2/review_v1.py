#!/usr/bin/env python3
"""Read-only reanalysis of v1 diversity and inference scope."""
import json
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
SOURCE = HERE.parent / 'admission-consistency/results'
primary = [r for r in json.loads((SOURCE / 'crosscheck.json').read_text())['runs'] if r['status'] == 'PASS']
review = []
for run in primary:
    directory = SOURCE / run['run']
    rows = json.loads((directory / 'results.json').read_text())
    settings = set()
    for row in rows:
        request = json.loads((directory / 'cases' / row['pod'] / 'request.json').read_text())
        field = 'containers' if row['route'] == 'regular' else 'ephemeralContainers'
        probes = request['spec'][field]
        settings.add(json.dumps({'route': row['route'], 'containers': probes}, sort_keys=True))
    review.append({'run': run['run'], 'engine': run['engine'], 'executions': len(rows),
                   'logicalCaseLabels': len({r['case'] for r in rows}),
                   'distinctContainerSettingsIncludingRoute': len(settings),
                   'clusters': 1, 'policyFamily': 'CEL' if run['engine'] in ('vap', 'kyverno') else 'Rego',
                   'publicPolicyLibrarySampled': False})
(HERE / 'v1-reanalysis.json').write_text(json.dumps(review, indent=2) + '\n')
print(json.dumps(review, indent=2))
