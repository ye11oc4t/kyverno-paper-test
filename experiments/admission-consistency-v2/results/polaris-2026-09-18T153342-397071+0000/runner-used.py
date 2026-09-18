#!/usr/bin/env python3
"""Offline JSON Schema evaluation; never counted as live admission enforcement."""
import json
from run import HERE, base, catalogue, command, now, save, sha

out = HERE / 'results' / ('polaris-' + now().replace(':', '').replace('.', '-'))
out.mkdir(parents=True)
checks = {}
for rule, property_name, predicate in [('name', 'name', {'pattern': '^study-'}),
                                       ('image', 'image', {'const': base.GOOD_IMAGE})]:
    item = {'type': 'object', 'required': [property_name], 'properties': {property_name: {'type': 'string', **predicate}}}
    schema = {'type': 'object', 'required': ['containers'], 'properties': {
        key: {'type': 'array', 'items': item} for key in ('containers', 'initContainers', 'ephemeralContainers')}}
    checks['study-' + rule] = {'successMessage': 'Study conformance holds', 'failureMessage': 'study-' + rule + ': nonconforming',
                               'category': 'Reliability', 'target': 'PodSpec', 'schema': schema}
config = {'checks': {key: 'danger' for key in checks}, 'customChecks': checks}
save(out / 'config.json', config)
save(out / 'catalogue.json', catalogue())
(out / 'runner-used.py').write_bytes((HERE / 'polaris.py').read_bytes())
save(out / 'frozen-inputs.json', {'frozenAt': now(), 'configSha256': sha(out / 'config.json'),
     'catalogueSha256': sha(out / 'catalogue.json'), 'runnerSha256': sha(out / 'runner-used.py'),
     'version': '10.2.5', 'mode': 'offline hypothetical object, not an API request',
     'downloads': json.loads((HERE / 'downloads.json').read_text())})
rows = []
for case in catalogue():
    directory = out / case['case']
    directory.mkdir()
    obj = base.pod('offline-' + case['case'], base.container('study-base'))
    field = 'containers' if case['route'] == 'regular' else 'ephemeralContainers'
    obj['spec'][field] = ([base.container('study-history')] if case['history'] else []) + case['probes']
    save(directory / 'input.json', obj)
    result = command([base.CACHE / 'bin/polaris', 'audit', '--config', out / 'config.json',
                      '--audit-path', directory / 'input.json', '--format', 'json', '--set-exit-code-on-danger'], check=False)
    (directory / 'stdout.json').write_text(result.stdout)
    (directory / 'stderr.log').write_text(result.stderr)
    rows.append({'case': case['case'], 'expected': case['expected'], 'exitCode': result.returncode,
                 'matchedExitCode': result.returncode == (0 if case['expected'] == 'ALLOW' else 3)})
save(out / 'results.json', rows)
save(out / 'summary.json', {'tool': 'polaris', 'mode': 'offline', 'cases': 24,
                          'matchedExitCodes': sum(r['matchedExitCode'] for r in rows),
                          'status': 'RAW_REVIEW_REQUIRED', 'admissionEvidence': 'NOT_APPLICABLE'})
print(str(out), flush=True)
