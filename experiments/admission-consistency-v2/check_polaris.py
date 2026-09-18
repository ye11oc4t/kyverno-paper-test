#!/usr/bin/env python3
"""Require actual per-rule results; a score/exit code alone is insufficient."""
import hashlib
import json
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
def read(p):
    return json.loads(p.read_text())
summaries = []
for directory in sorted((HERE / 'results').glob('polaris-*')):
    if (directory / 'disposition.json').exists():
        summaries.append({'run': directory.name, 'status': 'EXCLUDED_NO_EVALUATED_OBJECTS', **read(directory / 'disposition.json')})
        continue
    frozen = read(directory / 'frozen-inputs.json')
    hashes = all(hashlib.sha256((directory / name).read_bytes()).hexdigest() == frozen[key] for name, key in
                 [('config.json', 'configSha256'), ('catalogue.json', 'catalogueSha256'), ('runner-used.py', 'runnerSha256')])
    catalogue = read(directory / 'catalogue.json')
    rows = {r['case']: r for r in read(directory / 'results.json')}
    checks = []
    for case in catalogue:
        casedir = directory / case['case']
        result = read(casedir / 'stdout.json')
        items = result.get('Results', [])
        rules = items[0].get('PodResult', {}).get('Results', {}) if len(items) == 1 else {}
        evaluated = len(items) == 1 and set(rules) == {'study-name', 'study-image'}
        expected_rule_status = {f'study-{rule}': rule not in case['expectedRules'] for rule in ('name', 'image')}
        outcomes = evaluated and all(rules[key].get('Success') == allowed for key, allowed in expected_rule_status.items())
        request = read(casedir / 'input.yaml')
        field = 'containers' if case['route'] == 'regular' else 'ephemeralContainers'
        actual = request['spec'][field]
        probes = actual[1:] if case['history'] else actual
        fixture = probes == case['probes']
        exit_agrees = rows[case['case']]['exitCode'] == (0 if case['expected'] == 'ALLOW' else 3)
        checks.append({'case': case['case'], 'evaluated': evaluated, 'ruleOutcomes': outcomes,
                       'fixture': fixture, 'exitCode': exit_agrees})
    detail = {'run': directory.name, 'tool': 'Polaris 10.2.5', 'mode': 'offline', 'cases': len(checks),
              'evaluatedObjects': sum(c['evaluated'] for c in checks), 'evaluatedRules': 2 * sum(c['evaluated'] for c in checks),
              'matchedCases': sum(all(c[k] for k in ('evaluated', 'ruleOutcomes', 'fixture', 'exitCode')) for c in checks),
              'frozenHashesAgree': hashes, 'admissionEvidence': 'NOT_APPLICABLE',
              'status': 'PASS_OFFLINE' if hashes and len(checks) == 24 and
                        all(all(c[k] for k in ('evaluated', 'ruleOutcomes', 'fixture', 'exitCode')) for c in checks) else 'REVIEW_REQUIRED'}
    (directory / 'crosscheck.json').write_text(json.dumps({'summary': detail, 'cases': checks}, indent=2) + '\n')
    summaries.append(detail)
(HERE / 'results/offline-crosscheck.json').write_text(json.dumps(summaries, indent=2) + '\n')
print(json.dumps(summaries, indent=2))
raise SystemExit(1 if any(s['status'] == 'REVIEW_REQUIRED' for s in summaries) else 0)
