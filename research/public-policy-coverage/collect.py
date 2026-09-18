#!/usr/bin/env python3
"""Fetch only an explicit read-only documentation/source sample at fixed commits."""
import hashlib
import json
import pathlib
import urllib.request
from datetime import datetime, timezone

HERE = pathlib.Path(__file__).resolve().parent
CACHE = pathlib.Path('/root/.cache/kyverno-paper-study/coverage-survey')
REPOS = {
    'kyverno': ('kyverno/policies', '2716f4a26a3c27590a1d6d960dee4ce043e4fa4a'),
    'gatekeeper': ('open-policy-agent/gatekeeper-library', '22a40962f83268769bcec5dfe55e44b5a85c392a'),
    'kubewarden': ('kubewarden/policies', '062ce69867746d012276e1120017f1c0c7694e22'),
    'polaris': ('FairwindsOps/polaris', 'c84bb2ea3674ee7ec044584db8c9cc9e8d17bdd0'),
    'kubernetes-api': ('kubernetes/api', 'b65ac350d910ec0067b586c1a7cce7f79fa9bdf5'),
}
paths = {key: [] for key in REPOS}
for parent, name in [('best-practices', 'restrict-image-registries'), ('other-vpol', 'allowed-image-repos'),
                     ('best-practices', 'require-ro-rootfs'), ('best-practices', 'require-labels')]:
    prefix = f'{parent}/{name}'
    paths['kyverno'] += [f'{prefix}/{name}.yaml', f'{prefix}/.kyverno-test/kyverno-test.yaml',
                        f'{prefix}/.chainsaw-test/chainsaw-test.yaml']
for prefix, sample in [('library/general/allowedreposv2', 'repo-must-be-openpolicyagent'),
                       ('library/pod-security-policy/read-only-root-filesystem', 'psp-readonlyrootfilesystem'),
                       ('library/general/requiredlabels', 'all-must-have-owner')]:
    paths['gatekeeper'] += [f'{prefix}/template.yaml', f'{prefix}/suite.yaml', f'{prefix}/samples/{sample}/constraint.yaml']
for name in ['trusted-repos-policy', 'readonly-root-filesystem-psp-policy', 'labels-policy']:
    prefix = f'policies/{name}'
    paths['kubewarden'] += [f'{prefix}/{f}' for f in ['README.md', 'metadata.yml', 'src/lib.rs', 'src/settings.rs', 'e2e.bats', 'Cargo.toml']]
paths['kubewarden'] += ['policies/trusted-repos-policy/src/validating_resource.rs',
                       'policies/trusted-repos-policy/src/validation.rs']
paths['polaris'] += ['docs/customization/custom-checks.md', 'docs/admission-controller.md',
    'docs/customization/exemptions.md', 'docs/customization/configuration.md',
    'pkg/config/checks/notReadOnlyRootFilesystem.yaml', 'pkg/config/default.yaml',
    'pkg/kube/resource.go', 'pkg/config/checks.go']
paths['polaris'] += ['pkg/validator/custom.go', 'pkg/validator/schema.go',
    'pkg/validator/container_test.go', 'pkg/config/checks/metadataAndInstanceMismatched.yaml',
    'test/checks/metadataAndInstanceMismatched/success.yaml',
    'test/checks/metadataAndInstanceMismatched/failure.yaml']
paths['kubernetes-api'] += ['core/v1/types.go']

records = []
missing = []
for project, files in paths.items():
    repo, commit = REPOS[project]
    for path in files:
        url = f'https://raw.githubusercontent.com/{repo}/{commit}/{path}'
        local = CACHE / project / commit / path
        try:
            if local.exists():
                data = local.read_bytes()
            else:
                data = urllib.request.urlopen(url, timeout=60).read()
                local.parent.mkdir(parents=True, exist_ok=True)
                local.write_bytes(data)
        except Exception as exc:
            missing.append({'project': project, 'path': path, 'url': url, 'error': str(exc)})
            continue
        records.append({'project': project, 'repository': repo, 'commit': commit, 'path': path,
                        'url': f'https://github.com/{repo}/blob/{commit}/{path}',
                        'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data),
                        'lines': len(data.decode().splitlines())})
result = {'collectedUtc': datetime.now(timezone.utc).isoformat(), 'mode': 'read-only source review',
          'sources': records, 'unavailableRequestedSources': missing}
(HERE / 'source-lock.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps({'sources': len(records), 'missing': missing}, indent=2))
