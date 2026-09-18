#!/usr/bin/env python3
"""Cross-check raw case artifacts against specifications and audit evidence."""
import csv
import hashlib
import json
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
expected = {r['case']: r for r in csv.DictReader((HERE / 'expectations.csv').open())}
summaries = []
for directory in sorted((HERE / 'results').iterdir()):
    if not directory.is_dir() or not (directory / 'summary.json').exists():
        continue
    run = json.loads((directory / 'summary.json').read_text())
    if (directory / 'disposition.json').exists():
        summaries.append({'run': directory.name, 'engine': run['engine'], 'status': 'EXCLUDED_FROM_PRIMARY_ANALYSIS',
                          'completedExecutions': run['executions'], **json.loads((directory / 'disposition.json').read_text())})
        continue
    if run['status'] == 'ERROR':
        summaries.append({'run': directory.name, 'engine': run['engine'], 'status': 'SETUP_OR_EXECUTION_ERROR',
                          'completedExecutions': run['executions'], 'error': run['error']})
        continue
    rows = json.loads((directory / 'results.json').read_text())
    frozen = json.loads((directory / 'frozen-inputs.json').read_text())
    hashes_agree = all(hashlib.sha256((directory / filename).read_bytes()).hexdigest() == frozen[key]
                       for filename, key in [('runner-used.py', 'runnerSha256'),
                                             ('expectations-used.csv', 'expectationsSha256')])
    expectations_unchanged = ((directory / 'expectations-used.csv').read_bytes() ==
                              (HERE / 'expectations.csv').read_bytes())
    events = []
    for line in (directory / 'audit.jsonl').read_text().splitlines():
        if line.strip():
            events.append(json.loads(line))
    validations = []
    for row in rows:
        contract = expected[row['case']]
        should_allow = contract['expected'] == 'ALLOW'
        matches = [e for e in events
                   if e.get('stage') == 'ResponseComplete'
                   and e.get('objectRef', {}).get('namespace') == 'study-consistency'
                   and e.get('objectRef', {}).get('name') == row['pod']
                   and e.get('verb') == ('create' if row['route'] == 'regular' else 'update')
                   and e.get('objectRef', {}).get('subresource', '') == ('' if row['route'] == 'regular' else 'ephemeralcontainers')
                   and 'dryRun=' not in e.get('requestURI', '')]
        response_codes = [e.get('responseStatus', {}).get('code') for e in matches]
        audit_agrees = len(matches) == 1 and ((200 <= response_codes[0] < 300) == row['accepted'])
        case_dir = directory / 'cases' / row['pod']
        submitted = json.loads((case_dir / 'request.json').read_text())
        observation = json.loads((case_dir / 'observation.json').read_text())
        field = 'containers' if row['route'] == 'regular' else 'ephemeralContainers'
        statuses = 'containerStatuses' if row['route'] == 'regular' else 'ephemeralContainerStatuses'
        probes = submitted['spec'][field]
        probe = probes[0]
        expected_name = 'sample-probe' if row['rule'] == 'name' and not should_allow else 'study-probe'
        expected_image = ('study.local/alternate/pause:3.10' if row['rule'] == 'image' and not should_allow
                          else 'study.local/approved/pause:3.10')
        fixture_agrees = (len(probes) == 1 and probe['name'] == expected_name and probe['image'] == expected_image
                          and contract['rule'] == row['rule'] and contract['route'] == row['route']
                          and contract['expected'] == row['expected'])
        raw_stored = bool(observation and any(c['name'] == probe['name'] and c['image'] == probe['image']
                                              for c in observation.get('spec', {}).get(field, [])))
        raw_running = bool(observation and any(c['name'] == probe['name'] and 'running' in c.get('state', {})
                                               for c in observation.get('status', {}).get(statuses, [])))
        raw_denial = row['exitCode'] != 0 and f"study-{row['rule']}:" in (case_dir / 'stderr.log').read_text()
        observation_agrees = (raw_stored == row['stored'] and raw_running == row['running']
                              and raw_denial == row['rejectedByStudyRule']
                              and (row['exitCode'] == 0) == row['accepted'])
        audit_input_agrees = len(matches) == 1 and any(
            c.get('name') == probe['name'] and c.get('image') == probe['image']
            for c in matches[0].get('requestObject', {}).get('spec', {}).get(field, []))
        audit_denial_agrees = should_allow or (len(matches) == 1 and
            f"study-{row['rule']}:" in matches[0].get('responseStatus', {}).get('message', ''))
        outcome_agrees = ((row['accepted'] and row['stored'] and row['running']) if should_allow
                          else (not row['accepted'] and row['rejectedByStudyRule'] and not row['stored']))
        # Do not infer successful policy invocation solely from an allowed API response.
        validations.append({'iteration': row['iteration'], 'case': row['case'],
                            'contractMatches': outcome_agrees, 'apiAuditAgrees': audit_agrees,
                            'fixtureAgrees': fixture_agrees, 'rawObservationAgrees': observation_agrees,
                            'auditInputAgrees': audit_input_agrees, 'auditDenialAgrees': audit_denial_agrees,
                            'auditIds': [e['auditID'] for e in matches], 'responseCodes': response_codes,
                            'policyEvaluationEvidence': 'EXPLICIT_RULE_DENIAL' if row['rejectedByStudyRule'] else 'UNKNOWN'})
    seen = {(r['iteration'], r['case']) for r in rows}
    required = {(n, case) for n in (1, 2, 3) for case in expected}
    complete = len(rows) == 24 and seen == required
    consistent = all(len({(r['accepted'], r['stored'], r['running'], r['rejectedByStudyRule'])
                          for r in rows if r['case'] == case}) == 1 for case in expected)
    detail = {'run': directory.name, 'engine': run['engine'], 'executions': len(rows),
              'complete': complete, 'uniqueCases': len({r['case'] for r in rows}),
              'matchedContract': sum(v['contractMatches'] for v in validations),
              'matchedAudit': sum(v['apiAuditAgrees'] for v in validations),
              'matchedRawEvidence': sum(all(v[key] for key in ('fixtureAgrees', 'rawObservationAgrees',
                                                               'auditInputAgrees', 'auditDenialAgrees')) for v in validations),
              'frozenHashesAgree': hashes_agree, 'expectationsUnchanged': expectations_unchanged,
              'consistentAcrossRepeats': consistent,
              'allowed': sum(r['accepted'] for r in rows),
              'explicitStudyRuleDenials': sum(r['rejectedByStudyRule'] for r in rows),
              'benignContainersStarted': sum(r['running'] for r in rows),
              'status': 'PASS' if complete and consistent and hashes_agree and expectations_unchanged and
                        all(all(v[key] for key in ('contractMatches', 'apiAuditAgrees', 'fixtureAgrees',
                                                  'rawObservationAgrees', 'auditInputAgrees', 'auditDenialAgrees'))
                            for v in validations) else 'REVIEW_REQUIRED'}
    (directory / 'evidence-crosscheck.json').write_text(json.dumps({'summary': detail, 'cases': validations}, indent=2) + '\n')
    summaries.append(detail)
output = {'scope': 'Custom benign rules; not an assessment of all built-in security policies or exploitability.', 'runs': summaries}
(HERE / 'results' / 'crosscheck.json').write_text(json.dumps(output, indent=2) + '\n')
print(json.dumps(output, indent=2))
raise SystemExit(1 if any(r['status'] == 'REVIEW_REQUIRED' for r in summaries) else 0)
