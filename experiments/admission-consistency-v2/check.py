#!/usr/bin/env python3
"""Re-derive v2 outcomes from raw API audit records and object observations."""
import hashlib
import json
import pathlib

HERE = pathlib.Path(__file__).resolve().parent

def read(path):
    return json.loads(path.read_text())

def projection(containers):
    return [(c['name'], c['image']) for c in containers or []]

summaries = []
for directory in sorted((HERE / 'results').glob('*')):
    if not (directory / 'summary.json').exists():
        continue
    original = read(directory / 'summary.json')
    if original.get('mode') == 'offline':
        continue
    if original['status'] == 'ERROR':
        summaries.append({'run': directory.name, 'engine': original['engine'], 'status': 'EXECUTION_ERROR',
                          'executions': original['executions'], 'error': original['error']})
        continue
    catalogue = {c['case']: c for c in read(directory / 'catalogue.json')}
    frozen = read(directory / 'frozen-inputs.json')
    hashes = all(hashlib.sha256((directory / f).read_bytes()).hexdigest() == digest for f, digest in frozen['files'].items())
    rows = read(directory / 'results.json')
    events = [json.loads(line) for line in (directory / 'audit.jsonl').read_text().splitlines() if line.strip()]
    checks = []
    for row in rows:
        case = catalogue[row['case']]
        casedir = directory / 'cases' / row['case']
        request, before, after = [read(casedir / f) for f in ('request.json', 'before.json', 'observation.json')]
        field = 'containers' if case['route'] == 'regular' else 'ephemeralContainers'
        statuses = 'containerStatuses' if case['route'] == 'regular' else 'ephemeralContainerStatuses'
        submitted = request['spec'][field]
        old = before['spec'].get(field, []) if before else []
        actual = after['spec'].get(field, []) if after else []
        fixture_ok = projection(submitted) == projection(old + case['probes'])
        matches = [e for e in events if e.get('stage') == 'ResponseComplete'
                   and e.get('objectRef', {}).get('name') == row['pod']
                   and e.get('objectRef', {}).get('namespace') == 'study-consistency'
                   and e.get('verb') == ('create' if case['route'] == 'regular' else 'update')
                   and e.get('objectRef', {}).get('subresource', '') == ('' if case['route'] == 'regular' else 'ephemeralcontainers')
                   and 'dryRun=' not in e.get('requestURI', '')
                   and projection(e.get('requestObject', {}).get('spec', {}).get(field, [])) == projection(submitted)]
        api_ok = len(matches) == 1
        accepted = api_ok and 200 <= matches[0].get('responseStatus', {}).get('code', 0) < 300
        api_ok = api_ok and accepted == row['accepted'] and accepted == (row['exitCode'] == 0)
        stored = all(pair in projection(actual) for pair in projection(case['probes']))
        started = bool(after) and all(any(s['name'] == p['name'] and 'running' in s.get('state', {})
                            for s in after.get('status', {}).get(statuses, [])) for p in case['probes'])
        no_new = not any(c['name'] == p['name'] for c in actual for p in case['probes'])
        same_uid = bool(before and after and before['metadata']['uid'] == after['metadata']['uid'])
        deny_preserved = after is None if case['route'] == 'regular' else same_uid and before['spec'] == after['spec']
        history_preserved = not case['history'] or (same_uid and all(c in actual for c in old))
        message = matches[0].get('responseStatus', {}).get('message', '') if len(matches) == 1 else ''
        stderr = (casedir / 'stderr.log').read_text()
        rule_denial = any('study-' + rule + ':' in message and 'study-' + rule + ':' in stderr for rule in case['expectedRules'])
        outcome_ok = (accepted and stored and started and history_preserved) if case['expected'] == 'ALLOW' else (
            not accepted and rule_denial and no_new and deny_preserved and history_preserved)
        checks.append({'case': row['case'], 'fixture': fixture_ok, 'audit': api_ok, 'outcome': outcome_ok,
                       'auditIDs': [e['auditID'] for e in matches],
                       'policyEvaluationEvidence': 'UNKNOWN' if accepted else ('EXPLICIT_RULE_DENIAL' if rule_denial else 'UNKNOWN')})
    complete = len(rows) == 24 and {r['case'] for r in rows} == set(catalogue)
    detail = {'run': directory.name, 'engine': original['engine'], 'executions': len(rows),
              'complete': complete, 'frozenHashesAgree': hashes,
              'matchedFixtures': sum(c['fixture'] for c in checks), 'matchedAudit': sum(c['audit'] for c in checks),
              'matchedOutcomes': sum(c['outcome'] for c in checks),
              'accepted': sum(r['accepted'] for r in rows), 'ruleDenials': sum(r['studyRuleDenial'] for r in rows),
              'status': 'PASS' if hashes and complete and all(c['fixture'] and c['audit'] and c['outcome'] for c in checks) else 'REVIEW_REQUIRED'}
    (directory / 'crosscheck.json').write_text(json.dumps({'summary': detail, 'cases': checks}, indent=2) + '\n')
    summaries.append(detail)
(HERE / 'results/crosscheck.json').write_text(json.dumps(summaries, indent=2) + '\n')
print(json.dumps(summaries, indent=2))
raise SystemExit(1 if any(s['status'] == 'REVIEW_REQUIRED' for s in summaries) else 0)
