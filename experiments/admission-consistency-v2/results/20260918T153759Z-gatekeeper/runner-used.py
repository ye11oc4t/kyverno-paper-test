#!/usr/bin/env python3
"""Benign multi-container conformance, with a fixed catalogue and isolated engines."""
import argparse
import copy
import importlib.util
import json
import pathlib
import random
import time

HERE = pathlib.Path(__file__).resolve().parent
BASE_FILE = HERE.parent / 'admission-consistency' / 'run.py'
module = importlib.util.spec_from_file_location('baseline', BASE_FILE)
base = importlib.util.module_from_spec(module)
module.loader.exec_module(base)
base.HERE = HERE
save, command, now, sha = base.save, base.command, base.now, base.sha
MODULE = 'registry://ghcr.io/kubewarden/policies/cel-policy@sha256:4ca1c0aef61b900a5360fc1ae5da2a1d0a7a667d486d4d1ae09069dc4253308a'


def catalogue():
    good = base.GOOD_IMAGE
    other = base.OTHER_IMAGE
    # Expectations are declared before execution, not produced by engine policies.
    patterns = [
        ('single-ok', [('study-a', good)], True, []),
        ('pair-ok', [('study-a', good), ('study-b', good)], True, []),
        ('edge-names-ok', [('study-0', good), ('study-a-b', good)], True, []),
        ('name-first', [('sample-a', good), ('study-b', good)], False, ['name']),
        ('name-last', [('study-a', good), ('sample-b', good)], False, ['name']),
        ('name-infix', [('x-study-a', good)], False, ['name']),
        ('name-no-separator', [('studya', good)], False, ['name']),
        ('image-first', [('study-a', other), ('study-b', good)], False, ['image']),
        ('image-last', [('study-a', good), ('study-b', other)], False, ['image']),
        ('both-single', [('sample-a', other)], False, ['name', 'image']),
        ('split-pair', [('sample-a', good), ('study-b', other)], False, ['name', 'image']),
    ]
    cases = []
    for route in ('regular', 'ephemeral'):
        for label, entries, allowed, rules in patterns:
            cases.append({'case': route + '-' + label, 'route': route, 'history': False,
                          'probes': [base.container(name, image) for name, image in entries],
                          'expected': 'ALLOW' if allowed else 'DENY', 'expectedRules': rules})
    for allowed in (True, False):
        cases.append({'case': 'ephemeral-history-' + ('ok' if allowed else 'reject'),
                      'route': 'ephemeral', 'history': True,
                      'probes': [base.container('study-next' if allowed else 'sample-next')],
                      'expected': 'ALLOW' if allowed else 'DENY', 'expectedRules': [] if allowed else ['name']})
    return cases


def kubewarden_policy():
    vap = base.policies('vap')[0]['spec']
    return {'apiVersion': 'policies.kubewarden.io/v1', 'kind': 'ClusterAdmissionPolicy',
            'metadata': {'name': 'study-conformance'}, 'spec': {
                'module': MODULE, 'policyServer': 'default', 'mutating': False, 'mode': 'protect',
                'failurePolicy': 'Fail', 'backgroundAudit': False,
                'namespaceSelector': vap['matchConstraints']['namespaceSelector'],
                'rules': vap['matchConstraints']['resourceRules'],
                'settings': {'validations': vap['validations']}}}


class Study(base.Study):
    def __init__(self, engine):
        super().__init__(engine)
        self.catalogue = catalogue()
        save(self.out / 'catalogue.json', self.catalogue)
        (self.out / 'runner-used.py').write_bytes(pathlib.Path(__file__).read_bytes())
        (self.out / 'base-runner-used.py').write_bytes(BASE_FILE.read_bytes())
        self.order = list(self.catalogue)
        random.Random(20260919).shuffle(self.order)
        save(self.out / 'execution-order.json', [c['case'] for c in self.order])

    def install_engine(self):
        if self.engine != 'kubewarden':
            return super().install_engine()
        chart = base.CACHE / 'v2-vendor/admission-controller-6.0.2.tgz'
        self.log('Installing Kubewarden chart 6.0.2 / app v1.37.2')
        result = command([base.CACHE / 'bin/helm', '--kubeconfig', self.kubeconfig,
                          'install', 'study-kubewarden', chart, '-n', 'kubewarden', '--create-namespace',
                          '--wait', '--timeout', '240s'], check=False)
        (self.out / 'engine-install.log').write_text(result.stdout + result.stderr)
        if result.returncode:
            raise RuntimeError('Kubewarden Helm installation failed')
        policy = kubewarden_policy()
        save(self.out / 'policy-0.json', policy)
        self.apply(policy)
        attempts = []
        for _ in range(180):
            r = self.k('create', '--dry-run=server', '-f', '-',
                       data=json.dumps(base.pod('readiness-canary', base.container('canary'))), check=False)
            attempts.append({'time': now(), 'exitCode': r.returncode, 'stderr': r.stderr})
            if r.returncode and 'study-name:' in r.stderr:
                save(self.out / 'readiness.json', attempts)
                self.log('Kubewarden policy propagation confirmed')
                return
            time.sleep(1)
        save(self.out / 'readiness.json', attempts)
        raise RuntimeError('Kubewarden policy readiness not established')

    def freeze(self):
        images = json.loads(command(['docker', 'image', 'inspect', base.GOOD_IMAGE, base.OTHER_IMAGE]).stdout)
        if len({i['Id'] for i in images}) != 1:
            raise RuntimeError('Study aliases differ in content')
        files = ['runner-used.py', 'base-runner-used.py', 'catalogue.json', 'execution-order.json']
        files += [p.name for p in sorted(self.out.glob('policy-*.json')) if 'registration' not in p.name]
        save(self.out / 'frozen-inputs.json', {'frozenAt': now(), 'engine': self.engine,
            'files': {name: sha(self.out / name) for name in files}, 'cases': 24, 'repeats': 1,
            'shuffleSeed': 20260919, 'images': [{'id': i['Id'], 'tags': i['RepoTags']} for i in images],
            'downloads': json.loads((HERE / 'downloads.json').read_text()),
            'kubewardenModule': MODULE if self.engine == 'kubewarden' else None})

    def ephemeral_body(self, name, current, probes):
        return {'apiVersion': 'v1', 'kind': 'Pod', 'metadata': {'name': name, 'namespace': base.NS,
                'resourceVersion': current['metadata']['resourceVersion']},
                'spec': {'ephemeralContainers': copy.deepcopy(current['spec'].get('ephemeralContainers', [])) + probes}}

    def submit(self, route, name, body):
        if route == 'regular':
            return self.k('create', '-f', '-', '-o', 'json', data=json.dumps(body), check=False)
        return self.k('replace', '--raw', f'/api/v1/namespaces/{base.NS}/pods/{name}/ephemeralcontainers',
                      '-f', '-', data=json.dumps(body), check=False)

    def cases(self):
        for case in self.order:
            name = 'v2-' + case['case']
            directory = self.out / 'cases' / case['case']
            directory.mkdir(parents=True)
            before = None
            if case['route'] == 'ephemeral':
                self.k('create', '-f', '-', data=json.dumps(base.pod(name, base.container('study-base'))))
                running, before = self.wait_running(name, 'containerStatuses', 'study-base')
                if not running:
                    raise RuntimeError('Base Pod did not start')
                if case['history']:
                    history = self.ephemeral_body(name, before, [base.container('study-history')])
                    save(directory / 'history-request.json', history)
                    r = self.submit('ephemeral', name, history)
                    (directory / 'history-response.log').write_text(r.stdout + r.stderr)
                    if r.returncode:
                        raise RuntimeError('Compliant history container was not accepted')
                    running, before = self.wait_running(name, 'ephemeralContainerStatuses', 'study-history')
                    if not running:
                        raise RuntimeError('Compliant history container did not start')
                body = self.ephemeral_body(name, before, case['probes'])
            else:
                body = base.pod(name, case['probes'][0])
                body['spec']['containers'] = case['probes']
            save(directory / 'before.json', before)
            save(directory / 'request.json', body)
            started = now()
            result = self.submit(case['route'], name, body)
            accepted = result.returncode == 0
            (directory / 'stdout.log').write_text(result.stdout)
            (directory / 'stderr.log').write_text(result.stderr)
            field = 'containers' if case['route'] == 'regular' else 'ephemeralContainers'
            statuses = 'containerStatuses' if case['route'] == 'regular' else 'ephemeralContainerStatuses'
            observation = self.read_pod(name)
            running_all = accepted
            if accepted:
                for probe in case['probes']:
                    running, observation = self.wait_running(name, statuses, probe['name'])
                    running_all = running_all and running
            actual = observation.get('spec', {}).get(field, []) if observation else []
            stored_all = all(any(c['name'] == p['name'] and c['image'] == p['image'] for c in actual) for p in case['probes'])
            stored_any = any(c['name'] == p['name'] for c in actual for p in case['probes'])
            old = before.get('spec', {}).get(field, []) if before else []
            unchanged_on_deny = actual == old and (observation is None if case['route'] == 'regular' else observation is not None)
            denial = not accepted and any('study-' + rule + ':' in result.stderr for rule in case['expectedRules'])
            matched = (accepted and stored_all and running_all) if case['expected'] == 'ALLOW' else (
                denial and not stored_any and unchanged_on_deny)
            save(directory / 'observation.json', observation)
            row = {'engine': self.engine, 'case': case['case'], 'pod': name, 'route': case['route'],
                   'expected': case['expected'], 'startedUtc': started, 'finishedUtc': now(),
                   'accepted': accepted, 'exitCode': result.returncode, 'storedAll': stored_all,
                   'storedAny': stored_any, 'runningAll': running_all, 'studyRuleDenial': denial,
                   'unchangedOnDeny': unchanged_on_deny, 'matchedExpectation': matched}
            self.rows.append(row)
            save(directory / 'result.json', row)
            save(self.out / 'results.json', self.rows)
            self.log(case['case'] + ': ' + ('MATCH' if matched else 'MISMATCH'))

    def capture(self):
        if not self.created:
            return
        audit = command(['docker', 'exec', self.name + '-control-plane', 'cat', '/var/log/kubernetes/study-audit.log'], check=False)
        (self.out / 'audit.jsonl').write_text(audit.stdout)
        save(self.out / 'audit-capture-status.json', {'exitCode': audit.returncode, 'stderr': audit.stderr})
        resources = ['pods', 'events']
        for resource in resources:
            r = self.k('get', resource, '-n', base.NS, '-o', 'json', check=False)
            if r.returncode == 0:
                save(self.out / ('final-' + resource + '.json'), json.loads(r.stdout))
        policy_resource = {'vap': 'validatingadmissionpolicies', 'kyverno': 'validatingpolicies.policies.kyverno.io',
                           'gatekeeper': self.constraint_resource or 'constrainttemplates',
                           'kubewarden': 'clusteradmissionpolicies.policies.kubewarden.io'}[self.engine]
        for filename, resource in [('final-policies.json', policy_resource), ('validatingwebhooks.json', 'validatingwebhookconfigurations')]:
            r = self.k('get', resource, '-o', 'json', check=False)
            if r.returncode == 0:
                save(self.out / filename, json.loads(r.stdout))
        if self.engine != 'vap':
            namespace = {'kyverno': 'kyverno', 'gatekeeper': 'gatekeeper-system', 'kubewarden': 'kubewarden'}[self.engine]
            for resource in ('pods', 'events', 'deployments'):
                r = self.k('get', resource, '-n', namespace, '-o', 'json', check=False)
                if r.returncode == 0:
                    save(self.out / ('engine-' + resource + '.json'), json.loads(r.stdout))
            deployments = json.loads(self.k('get', 'deployments', '-n', namespace, '-o', 'json').stdout)
            for dep in deployments['items']:
                depname = dep['metadata']['name']
                r = self.k('logs', '-n', namespace, 'deployment/' + depname, '--all-containers=true', '--tail=1500', check=False)
                (self.out / (depname + '.log')).write_text(r.stdout + r.stderr)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--engine', required=True, choices=['vap', 'kyverno', 'gatekeeper', 'kubewarden'])
    study = Study(parser.parse_args().engine)
    error = None
    try:
        study.create_cluster()
        study.install_engine()
        study.freeze()
        study.cases()
    except (Exception, KeyboardInterrupt) as exc:
        error = str(exc) or 'Interrupted'
        study.log('ERROR: ' + error)
    finally:
        try:
            study.capture()
        except Exception as exc:
            error = (error or '') + '; capture: ' + str(exc)
        study.finish(error)
        study.cleanup()
    study.log('Evidence: ' + str(study.out))
    raise SystemExit(1 if error or len(study.rows) != 24 or not all(r['matchedExpectation'] for r in study.rows) else 0)


if __name__ == '__main__':
    main()
