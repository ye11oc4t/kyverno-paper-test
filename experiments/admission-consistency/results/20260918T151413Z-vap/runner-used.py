#!/usr/bin/env python3
"""Bounded, benign policy conformance study on fresh local kind clusters."""
import argparse
import csv
import hashlib
import json
import pathlib
import platform
import subprocess
import time
from datetime import datetime, timezone

HERE = pathlib.Path(__file__).resolve().parent
CACHE = pathlib.Path('/root/.cache/kyverno-paper-study')
KIND = str(CACHE / 'bin/kind')
KUBECTL = str(CACHE / 'bin/kubectl')
NODE_IMAGE = 'kindest/node:v1.35.8@sha256:07b2536e30b803ed61d1677a79df6115f798ce64c80f9e22f6ed45afd09323c0'
GOOD_IMAGE = 'study.local/approved/pause:3.10'
OTHER_IMAGE = 'study.local/alternate/pause:3.10'
NS = 'study-consistency'


def now():
    return datetime.now(timezone.utc).isoformat()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def command(args, *, data=None, check=True, timeout=600):
    result = subprocess.run([str(x) for x in args], input=data, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    if check and result.returncode:
        raise RuntimeError(f'{args[0]} failed ({result.returncode}): {result.stderr[-2500:]}')
    return result


def expression(predicate):
    return (f'object.spec.containers.all(c, {predicate}) && '
            f'(!has(object.spec.initContainers) || object.spec.initContainers.all(c, {predicate})) && '
            f'(!has(object.spec.ephemeralContainers) || object.spec.ephemeralContainers.all(c, {predicate}))')


def policies(engine):
    validations = [
        {'expression': expression("c.name.startsWith('study-')"), 'message': 'study-name: name must start with study-'},
        {'expression': expression(f"c.image == '{GOOD_IMAGE}'"), 'message': 'study-image: image must be the approved study alias'},
    ]
    match = {'resourceRules': [{'apiGroups': [''], 'apiVersions': ['v1'],
                               'operations': ['CREATE', 'UPDATE'], 'resources': ['pods', 'pods/ephemeralcontainers']}],
             'namespaceSelector': {'matchLabels': {'study.example/pilot': 'true'}}}
    if engine == 'vap':
        return [
            {'apiVersion': 'admissionregistration.k8s.io/v1', 'kind': 'ValidatingAdmissionPolicy',
             'metadata': {'name': 'study-conformance'}, 'spec': {'failurePolicy': 'Fail', 'matchConstraints': match, 'validations': validations}},
            {'apiVersion': 'admissionregistration.k8s.io/v1', 'kind': 'ValidatingAdmissionPolicyBinding',
             'metadata': {'name': 'study-conformance'}, 'spec': {'policyName': 'study-conformance', 'validationActions': ['Deny']}},
        ]
    if engine == 'kyverno':
        return [{'apiVersion': 'policies.kyverno.io/v1', 'kind': 'ValidatingPolicy',
                 'metadata': {'name': 'study-conformance'},
                 'spec': {'validationActions': ['Deny'], 'failurePolicy': 'Fail',
                          'matchConstraints': match, 'validations': validations}}]
    rego = '''package studyconformance
containers[c] { c := input.review.object.spec.containers[_] }
containers[c] { c := input.review.object.spec.initContainers[_] }
containers[c] { c := input.review.object.spec.ephemeralContainers[_] }
violation[{"msg": "study-name: name must start with study-"}] {
  c := containers[_]
  not startswith(c.name, "study-")
}
violation[{"msg": "study-image: image must be the approved study alias"}] {
  c := containers[_]
  c.image != "study.local/approved/pause:3.10"
}
'''
    return [
        {'apiVersion': 'templates.gatekeeper.sh/v1', 'kind': 'ConstraintTemplate',
         'metadata': {'name': 'studyconformance'},
         'spec': {'crd': {'spec': {'names': {'kind': 'StudyConformance'}, 'validation': {'openAPIV3Schema': {'type': 'object'}}}},
                  'targets': [{'target': 'admission.k8s.gatekeeper.sh', 'rego': rego}]}},
        {'apiVersion': 'constraints.gatekeeper.sh/v1beta1', 'kind': 'StudyConformance',
         'metadata': {'name': 'study-conformance'},
         'spec': {'enforcementAction': 'deny', 'match': {'kinds': [{'apiGroups': [''], 'kinds': ['Pod']}], 'namespaces': [NS]}}},
    ]


def container(name='study-probe', image=GOOD_IMAGE):
    return {'name': name, 'image': image, 'imagePullPolicy': 'Never',
            'securityContext': {'runAsNonRoot': True, 'runAsUser': 1000, 'runAsGroup': 1000,
                                'allowPrivilegeEscalation': False, 'readOnlyRootFilesystem': True,
                                'capabilities': {'drop': ['ALL']}, 'seccompProfile': {'type': 'RuntimeDefault'}}}


def pod(name, probe):
    return {'apiVersion': 'v1', 'kind': 'Pod', 'metadata': {'name': name, 'namespace': NS},
            'spec': {'automountServiceAccountToken': False, 'restartPolicy': 'Never',
                     'terminationGracePeriodSeconds': 0, 'containers': [probe]}}


class Study:
    def __init__(self, engine):
        self.engine = engine
        self.run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + engine
        self.name = 'paper-consistency-' + self.run_id.lower()
        self.work = CACHE / self.run_id
        self.work.mkdir(parents=True, exist_ok=False)
        self.out = HERE / 'results' / self.run_id
        self.out.mkdir(parents=True, exist_ok=False)
        self.kubeconfig = self.work / 'kubeconfig'
        self.rows = []
        self.created = False

    def log(self, message):
        print(f'{now()} [{self.engine}] {message}', flush=True)

    def k(self, *args, **kwargs):
        return command([KUBECTL, '--kubeconfig', self.kubeconfig, '--context', 'kind-' + self.name, *args], **kwargs)

    def apply(self, obj):
        return self.k('apply', '-f', '-', data=json.dumps(obj))

    def read_pod(self, name):
        r = self.k('get', 'pod', name, '-n', NS, '-o', 'json', check=False)
        return json.loads(r.stdout) if r.returncode == 0 else None

    def wait_running(self, name, field, target):
        last = None
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            last = self.read_pod(name)
            if last:
                for status in last.get('status', {}).get(field, []):
                    if status['name'] == target and 'running' in status.get('state', {}):
                        return True, last
            time.sleep(1)
        return False, last

    def create_cluster(self):
        if self.name in command([KIND, 'get', 'clusters']).stdout.splitlines():
            raise RuntimeError('Refusing to reuse an existing cluster')
        audit = {'apiVersion': 'audit.k8s.io/v1', 'kind': 'Policy',
                 'omitStages': ['RequestReceived'], 'rules': [
                     {'level': 'RequestResponse', 'namespaces': [NS],
                      'verbs': ['create', 'update', 'patch'], 'resources': [{'group': '', 'resources': ['pods', 'pods/ephemeralcontainers']}]},
                     {'level': 'None'}]}
        audit_path = self.work / 'audit-policy.json'
        save(audit_path, audit)
        patch = {'kind': 'ClusterConfiguration',
                 'apiServer': {'extraArgs': {'audit-log-path': '/var/log/kubernetes/study-audit.log',
                                            'audit-policy-file': '/etc/kubernetes/policies/study-audit.json'},
                               'extraVolumes': [{'name': 'study-audit-policy', 'hostPath': '/etc/kubernetes/policies', 'mountPath': '/etc/kubernetes/policies', 'readOnly': True, 'pathType': 'DirectoryOrCreate'},
                                                {'name': 'study-audit-log', 'hostPath': '/var/log/kubernetes', 'mountPath': '/var/log/kubernetes', 'readOnly': False, 'pathType': 'DirectoryOrCreate'}]}}
        config = {'kind': 'Cluster', 'apiVersion': 'kind.x-k8s.io/v1alpha4',
                  'nodes': [{'role': 'control-plane', 'kubeadmConfigPatches': [json.dumps(patch)],
                             'extraMounts': [{'hostPath': str(audit_path), 'containerPath': '/etc/kubernetes/policies/study-audit.json', 'readOnly': True}]}]}
        save(self.work / 'kind-config.json', config)
        save(self.out / 'kind-config.json', config)
        save(self.out / 'audit-policy.json', audit)
        self.log('Creating isolated Kubernetes v1.35.8 cluster')
        r = command([KIND, 'create', 'cluster', '--name', self.name, '--config', self.work / 'kind-config.json',
                     '--image', NODE_IMAGE, '--kubeconfig', self.kubeconfig, '--wait', '120s'], check=False)
        (self.out / 'cluster-create.log').write_text(r.stdout + r.stderr)
        self.created = self.name in command([KIND, 'get', 'clusters']).stdout.splitlines()
        if r.returncode:
            raise RuntimeError('Cluster creation failed; see cluster-create.log')
        archive = self.work / 'study-images.tar'
        # Docker's containerd image store can export incomplete multi-platform indexes.
        # Keep only the host architecture before importing into the local kind node.
        command(['docker', 'image', 'save', '--platform', 'linux/amd64', '-o', archive, GOOD_IMAGE, OTHER_IMAGE])
        command([KIND, 'load', 'image-archive', archive, '--name', self.name])
        save(self.out / 'kubernetes-version.json', json.loads(self.k('version', '-o', 'json').stdout))
        self.apply({'apiVersion': 'v1', 'kind': 'Namespace', 'metadata': {'name': NS, 'labels': {
            'study.example/pilot': 'true', 'pod-security.kubernetes.io/enforce': 'restricted',
            'pod-security.kubernetes.io/enforce-version': 'v1.35'}}})
        self.k('create', '-f', '-', data=json.dumps(pod('study-audit-canary', container())))
        audit_ready = False
        for _ in range(10):
            check = command(['docker', 'exec', self.name + '-control-plane', 'cat', '/var/log/kubernetes/study-audit.log'], check=False)
            if check.returncode == 0 and 'study-audit-canary' in check.stdout:
                audit_ready = True
                break
            time.sleep(1)
        save(self.out / 'audit-readiness.json', {'confirmed': audit_ready, 'checkedUtc': now()})
        self.k('delete', 'pod', 'study-audit-canary', '-n', NS, '--wait=false')
        if not audit_ready:
            raise RuntimeError('Audit evidence gate failed before policy installation')

    def install_engine(self):
        if self.engine != 'vap':
            vendor = CACHE / 'vendor' / ('kyverno-v1.19.1.yaml' if self.engine == 'kyverno' else 'gatekeeper-v3.23.1.yaml')
            self.log('Installing pinned ' + self.engine)
            r = self.k('create', '-f', str(vendor), check=False)
            (self.out / 'engine-install.log').write_text(r.stdout + r.stderr)
            if r.returncode:
                raise RuntimeError('Engine installation failed')
            namespace = 'kyverno' if self.engine == 'kyverno' else 'gatekeeper-system'
            deployments = json.loads(self.k('get', 'deployments', '-n', namespace, '-o', 'json').stdout)
            for deployment in deployments['items']:
                self.log('Waiting for ' + deployment['metadata']['name'])
                self.k('rollout', 'status', 'deployment/' + deployment['metadata']['name'], '-n', namespace, '--timeout=240s')
        for i, policy in enumerate(policies(self.engine)):
            save(self.out / f'policy-{i}.json', policy)
            self.apply(policy)
            if self.engine == 'gatekeeper' and i == 0:
                self.k('wait', '--for=condition=Established', 'crd/studyconformances.constraints.gatekeeper.sh', '--timeout=60s')
        # Propagation gate is a regular-Pod dry-run only, outside the measured cases.
        canary = pod('readiness-canary', container(name='canary'))
        attempts = []
        for _ in range(60):
            r = self.k('create', '--dry-run=server', '-f', '-', data=json.dumps(canary), check=False)
            attempts.append({'time': now(), 'exitCode': r.returncode, 'stderr': r.stderr})
            if r.returncode and 'study-name:' in r.stderr:
                save(self.out / 'readiness.json', attempts)
                self.log('Policy propagation confirmed with a benign name canary')
                return
            time.sleep(1)
        save(self.out / 'readiness.json', attempts)
        raise RuntimeError('Policy readiness not established')

    def freeze(self):
        (self.out / 'runner-used.py').write_bytes(pathlib.Path(__file__).read_bytes())
        (self.out / 'expectations-used.csv').write_bytes((HERE / 'expectations.csv').read_bytes())
        image_records = json.loads(command(['docker', 'image', 'inspect', GOOD_IMAGE, OTHER_IMAGE]).stdout)
        if len({x['Id'] for x in image_records}) != 1:
            raise RuntimeError('Study aliases must contain identical benign image bytes')
        save(self.out / 'frozen-inputs.json', {'frozenAt': now(), 'host': 'KSYBOB', 'wsl': platform.platform(),
            'engine': self.engine, 'cluster': self.name, 'nodeImage': NODE_IMAGE,
            'runnerSha256': sha(pathlib.Path(__file__)), 'prepareSha256': sha(HERE / 'prepare.sh'),
            'expectationsSha256': sha(HERE / 'expectations.csv'),
            'policies': [{'file': p.name, 'sha256': sha(p)} for p in sorted(self.out.glob('policy-*.json'))],
            'vendor': [{'file': p.name, 'sha256': sha(p)} for p in sorted((CACHE / 'vendor').glob('*.yaml'))],
            'images': [{'alias': alias, 'imageId': image['Id'], 'repoDigests': image.get('RepoDigests', [])}
                       for alias, image in zip([GOOD_IMAGE, OTHER_IMAGE], image_records)],
            'expected': 'Compliant inputs allowed; noncompliant inputs rejected with the corresponding study rule message.',
            'uniqueCases': 8, 'repeats': 3, 'readinessCanaryExcluded': True})

    def cases(self):
        for iteration in range(1, 4):
            for rule in ('name', 'image'):
                for route in ('regular', 'ephemeral'):
                    for compliant in (True, False):
                        case_id = f'{rule}-{route}-' + ('ok' if compliant else 'reject')
                        name = f'r{iteration}-{case_id}'
                        probe = container(name='study-probe' if compliant or rule != 'name' else 'sample-probe',
                                          image=GOOD_IMAGE if compliant or rule != 'image' else OTHER_IMAGE)
                        case_dir = self.out / 'cases' / name
                        case_dir.mkdir(parents=True)
                        started = now()
                        if route == 'ephemeral':
                            base = pod(name, container(name='study-base'))
                            self.k('create', '-f', '-', data=json.dumps(base))
                            base_running, current = self.wait_running(name, 'containerStatuses', 'study-base')
                            if not base_running:
                                save(case_dir / 'base-observation.json', current)
                                raise RuntimeError('Compliant base Pod did not start')
                            save(case_dir / 'base-observation.json', current)
                            body = {'apiVersion': 'v1', 'kind': 'Pod', 'metadata': {'name': name, 'namespace': NS,
                                    'resourceVersion': current['metadata']['resourceVersion']}, 'spec': {'ephemeralContainers': [probe]}}
                            save(case_dir / 'request.json', body)
                            result = self.k('replace', '--raw', f'/api/v1/namespaces/{NS}/pods/{name}/ephemeralcontainers',
                                            '-f', '-', data=json.dumps(body), check=False)
                        else:
                            body = pod(name, probe)
                            save(case_dir / 'request.json', body)
                            result = self.k('create', '-f', '-', '-o', 'json', data=json.dumps(body), check=False)
                        (case_dir / 'stdout.log').write_text(result.stdout)
                        (case_dir / 'stderr.log').write_text(result.stderr)
                        accepted = result.returncode == 0
                        rejected_by_rule = not accepted and f'study-{rule}:' in result.stderr
                        running = False
                        observation = self.read_pod(name)
                        if accepted:
                            running, observation = self.wait_running(name, 'ephemeralContainerStatuses' if route == 'ephemeral' else 'containerStatuses', probe['name'])
                        save(case_dir / 'observation.json', observation)
                        field = 'ephemeralContainers' if route == 'ephemeral' else 'containers'
                        stored = bool(observation and any(c['name'] == probe['name'] and c['image'] == probe['image']
                                                          for c in observation.get('spec', {}).get(field, [])))
                        matched = (accepted and stored and running) if compliant else (rejected_by_rule and not stored)
                        row = {'engine': self.engine, 'iteration': iteration, 'case': case_id, 'pod': name,
                               'startedUtc': started, 'finishedUtc': now(), 'rule': rule, 'route': route,
                               'expected': 'ALLOW' if compliant else 'DENY', 'accepted': accepted,
                               'rejectedByStudyRule': rejected_by_rule, 'stored': stored, 'running': running,
                               'matchedExpectation': matched, 'exitCode': result.returncode}
                        self.rows.append(row)
                        save(case_dir / 'result.json', row)
                        save(self.out / 'results.json', self.rows)
                        self.log(f'{name}: {"MATCH" if matched else "MISMATCH"}; accepted={accepted}; stored={stored}; running={running}')

    def capture(self):
        if not self.created:
            return
        node = self.name + '-control-plane'
        audit = command(['docker', 'exec', node, 'cat', '/var/log/kubernetes/study-audit.log'], check=False)
        (self.out / 'audit.jsonl').write_text(audit.stdout)
        save(self.out / 'audit-capture-status.json', {'exitCode': audit.returncode, 'stderr': audit.stderr})
        for kind in ('pods', 'events'):
            r = self.k('get', kind, '-n', NS, '-o', 'json', check=False)
            if r.returncode == 0:
                save(self.out / f'final-{kind}.json', json.loads(r.stdout))
        r = self.k('get', 'validatingwebhookconfigurations', '-o', 'json', check=False)
        if r.returncode == 0:
            save(self.out / 'validatingwebhooks.json', json.loads(r.stdout))
        resource = {'vap': 'validatingadmissionpolicies.admissionregistration.k8s.io',
                    'kyverno': 'validatingpolicies.policies.kyverno.io',
                    'gatekeeper': 'studyconformances.constraints.gatekeeper.sh'}[self.engine]
        r = self.k('get', resource, '-o', 'json', check=False)
        if r.returncode == 0:
            save(self.out / 'final-policies.json', json.loads(r.stdout))
        if self.engine != 'vap':
            ns = 'kyverno' if self.engine == 'kyverno' else 'gatekeeper-system'
            r = self.k('get', 'pods', '-n', ns, '-o', 'json', check=False)
            if r.returncode == 0:
                save(self.out / 'engine-pods.json', json.loads(r.stdout))
            deployment = 'kyverno-admission-controller' if self.engine == 'kyverno' else 'gatekeeper-controller-manager'
            r = self.k('logs', '-n', ns, 'deployment/' + deployment, '--all-containers=true', '--tail=2000', check=False)
            (self.out / 'engine.log').write_text(r.stdout + r.stderr)

    def finish(self, error):
        if self.rows:
            with (self.out / 'results.csv').open('w', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=list(self.rows[0]))
                writer.writeheader()
                writer.writerows(self.rows)
        complete = len(self.rows) == 24
        save(self.out / 'summary.json', {'engine': self.engine, 'finishedUtc': now(), 'cluster': self.name,
            'status': 'ERROR' if error else ('PASS' if complete and all(r['matchedExpectation'] for r in self.rows) else 'MISMATCH'),
            'error': error, 'executions': len(self.rows), 'matched': sum(r['matchedExpectation'] for r in self.rows),
            'uniqueCases': len({r['case'] for r in self.rows}), 'runtimeScope': 'benign pause process startup only'})

    def cleanup(self):
        if self.created:
            node = self.name + '-control-plane'
            label = command(['docker', 'inspect', '--format', '{{index .Config.Labels "io.x-k8s.kind.cluster"}}', node]).stdout.strip()
            if label != self.name or not self.name.startswith('paper-consistency-'):
                raise RuntimeError('Cleanup identity guard failed')
            r = command([KIND, 'delete', 'cluster', '--name', self.name, '--kubeconfig', self.kubeconfig])
            (self.out / 'cleanup.log').write_text(r.stdout + r.stderr)
            self.log('Removed this run\'s isolated cluster')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--engine', required=True, choices=['vap', 'kyverno', 'gatekeeper'])
    args = parser.parse_args()
    study = Study(args.engine)
    error = None
    try:
        study.create_cluster()
        study.install_engine()
        study.freeze()
        study.cases()
    except Exception as exc:
        error = str(exc)
        study.log('ERROR: ' + error)
    except KeyboardInterrupt:
        error = 'Operator interrupted this run'
        study.log(error)
    finally:
        try:
            study.capture()
        except Exception as exc:
            error = (error or '') + '; capture: ' + str(exc)
        study.finish(error)
        study.cleanup()
    study.log('Evidence: ' + str(study.out))
    raise SystemExit(1 if error or not all(r['matchedExpectation'] for r in study.rows) else 0)


if __name__ == '__main__':
    main()
