#!/usr/bin/env python3
"""Record a small, explicit source sample; not an ecosystem-wide vulnerability scan."""
import hashlib
import json
import pathlib
import urllib.request
from datetime import datetime, timezone
import yaml

HERE = pathlib.Path(__file__).resolve().parent
items = [
    ('Kyverno ClusterPolicy example', 'kyverno/policies', '2716f4a26a3c27590a1d6d960dee4ce043e4fa4a',
     'best-practices/restrict-image-registries/restrict-image-registries.yaml'),
    ('Kyverno ValidatingPolicy example', 'kyverno/policies', '2716f4a26a3c27590a1d6d960dee4ce043e4fa4a',
     'other-vpol/allowed-image-repos/allowed-image-repos.yaml'),
    ('Gatekeeper allowedrepos template', 'open-policy-agent/gatekeeper-library', '22a40962f83268769bcec5dfe55e44b5a85c392a',
     'library/general/allowedrepos/template.yaml'),
    ('Kubewarden CEL implementation README', 'kubewarden/policies', '062ce69867746d012276e1120017f1c0c7694e22',
     'policies/cel-policy/README.md'),
]
records = []
for label, repo, commit, path in items:
    url = f'https://raw.githubusercontent.com/{repo}/{commit}/{path}'
    data = urllib.request.urlopen(url, timeout=60).read()
    text = data.decode()
    record = {'label': label, 'repository': repo, 'commit': commit, 'path': path,
              'url': f'https://github.com/{repo}/blob/{commit}/{path}',
              'sha256': hashlib.sha256(data).hexdigest(), 'accessedUtc': datetime.now(timezone.utc).isoformat(),
              'scope': 'source inspection only; not a live test of this published policy'}
    if path.endswith('.yaml'):
        obj = yaml.safe_load(text)
        record.update({'kind': obj['kind'], 'apiVersion': obj['apiVersion'],
                       'containsEphemeralContainerFieldReference': 'ephemeralContainers' in text,
                       'validationFailureAction': obj['spec'].get('validationFailureAction'),
                       'validationActions': obj['spec'].get('validationActions')})
    records.append(record)
(HERE / 'source-review.json').write_text(json.dumps(records, indent=2) + '\n')
print(json.dumps(records, indent=2))
