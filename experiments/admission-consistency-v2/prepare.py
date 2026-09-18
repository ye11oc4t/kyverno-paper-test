#!/usr/bin/env python3
"""Download pinned official study tools without modifying system installations."""
import hashlib
import io
import json
import pathlib
import tarfile
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
CACHE = pathlib.Path('/root/.cache/kyverno-paper-study')
VENDOR = CACHE / 'v2-vendor'
VENDOR.mkdir(parents=True, exist_ok=True)
records = []

def fetch(url, filename, digest=None):
    data = urllib.request.urlopen(url, timeout=120).read()
    actual = hashlib.sha256(data).hexdigest()
    if digest and actual != digest:
        raise RuntimeError('Checksum mismatch: ' + filename)
    (VENDOR / filename).write_bytes(data)
    records.append({'url': url, 'file': filename, 'sha256': actual, 'expectedSha256': digest})
    return data

helm_url = 'https://get.helm.sh/helm-v4.3.0-linux-amd64.tar.gz'
helm_hash = '86584a54def73570558f66f5111cc53dfed56689637ae32c1201205d494f54fb'
helm = fetch(helm_url, 'helm-v4.3.0-linux-amd64.tar.gz', helm_hash)
polaris_base = 'https://github.com/FairwindsOps/polaris/releases/download/v10.2.5/'
polaris_hash = '21c979f649e9600ad41d907d188c6e01b2c7ae4dc0cdbf4df392120c950e1fca'
polaris = fetch(polaris_base + 'polaris_10.2.5_linux_amd64.tar.gz', 'polaris_10.2.5_linux_amd64.tar.gz', polaris_hash)
for archive, member, executable in [(helm, 'linux-amd64/helm', 'helm'), (polaris, 'polaris', 'polaris')]:
    with tarfile.open(fileobj=io.BytesIO(archive), mode='r:gz') as tar:
        path = CACHE / 'bin' / executable
        path.write_bytes(tar.extractfile(member).read())
        path.chmod(0o755)
fetch('https://github.com/kubewarden/helm-charts/releases/download/admission-controller-6.0.2/admission-controller-6.0.2.tgz',
      'admission-controller-6.0.2.tgz', 'd74a3112f43a73d46a69d934eb04c3fe0568bfc6b994c00dad719c480013a982')
fetch('https://github.com/kubewarden/policies/releases/download/cel-policy/v1.6.4/policy.wasm',
      'cel-policy-1.6.4.wasm', 'fb66785aef219286e953ca59cf038f52f3774801c1e19a7b1aca31d261f37c74')
(HERE / 'downloads.json').write_text(json.dumps(records, indent=2) + '\n')
print(json.dumps(records, indent=2))
