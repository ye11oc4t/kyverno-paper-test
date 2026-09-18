#!/usr/bin/env python3
"""Render manually reviewed coverage records; never execute a policy or cluster request."""
import csv
import hashlib
import json
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
CACHE = pathlib.Path('/root/.cache/kyverno-paper-study/coverage-survey')
lock = json.loads((HERE / 'source-lock.json').read_text())
sources = {(s['project'], s['path']): s for s in lock['sources']}
rows = []


def evidence(project, path, start, end, purpose):
    source = sources[(project, path)]
    assert 1 <= start <= end <= source['lines'], (path, start, end)
    return {'project': project, 'path': path, 'start': start, 'end': end,
            'purpose': purpose, 'url': source['url'] + f'#L{start}-L{end}'}


def add(id, project, family, name, artifact, contract, fields, assessment,
        mode, conditions, tests, followup, refs):
    rows.append(dict(id=id, project=project, family=family, name=name,
        artifactType=artifact, documentedContract=contract, sourceScope=fields,
        scopeAssessment=assessment, enforcementMode=mode,
        deploymentConditions=conditions, testDefinitionEvidence=tests,
        actualAdmissionGuarantee='UNKNOWN', testsExecutedInThisSurvey=False,
        remediationOrOpenQuestion=followup, evidence=refs))


def ky(name, parent='best-practices'):
    return f'{parent}/{name}'


p = ky('restrict-image-registries')
add('KY-IMG-CP', 'kyverno', 'image-origin', 'restrict-image-registries', 'catalog ClusterPolicy YAML',
    '운영자가 지정한 레지스트리에서 오는 컨테이너 이미지를 검증한다. 허용 목록 맞춤 설정을 요구한다.',
    'Pod spec의 일반·init·ephemeral 컨테이너 이미지 필드를 모두 명시한다.', 'SOURCE_SUPPORTED',
    '공개 YAML: Audit, background=true. Chainsaw 정의는 Enforce로 변경한다.',
    '지원 API/버전, 실제 webhook 선택 범위, 예외 및 autogen 결과를 배포별로 확인해야 한다.',
    'CLI 객체 테스트와 Chainsaw 테스트 정의가 있다. Chainsaw에는 Ephemeral Container 추가가 실패해야 한다는 단계도 있다. 종료 실패만 관측하는 정의이므로 거부 원인까지 증명하지는 않는다.',
    '테스트 존재를 인정하되 실제 실행 로그, 정책 평가 기록, 저장 결과를 연결하기 전에는 요청 보장을 확정하지 않는다.',
    [evidence('kyverno', p+'/restrict-image-registries.yaml',12,37,'계약·모드·필드'),
     evidence('kyverno', p+'/.kyverno-test/kyverno-test.yaml',1,26,'객체 테스트 정의'),
     evidence('kyverno', p+'/.chainsaw-test/chainsaw-test.yaml',13,53,'집행 변경 및 요청 경로 테스트 정의')])

p = ky('allowed-image-repos','other-vpol')
add('KY-IMG-VPOL', 'kyverno', 'image-origin', 'allowed-image-repos', 'catalog ValidatingPolicy v1alpha1 YAML',
    '모든 컨테이너 유형의 이미지 repository가 지정 목록에 속한다고 설명한다. 레지스트리 허용 목록과 동일한 의미는 아니다.',
    'allContainers가 일반·init·ephemeral을 합친다. matchConstraints와 평가식은 별도 요소다.', 'SOURCE_SUPPORTED',
    '공개 YAML: Warn와 Audit, background=false. Chainsaw 정의는 Deny로 변경한다.',
    '이 표본의 API는 v1alpha1이다. 기존 자체 정책의 v1 실행 결과를 호환성 또는 실제 요청 적용 증거로 사용하지 않는다.',
    'CLI 객체 테스트와 Chainsaw Pod/컨트롤러 apply 정의를 확인했다. 선택한 Chainsaw 정의만으로 별도 subresource 시험은 확인되지 않는다.',
    'allContainers 검사와 실제 요청 선택·집행을 각각 명시하고 지원 버전의 배포 산출물로 확인할 필요가 있다.',
    [evidence('kyverno',p+'/allowed-image-repos.yaml',1,39,'계약·API·평가·매칭'),
     evidence('kyverno',p+'/.kyverno-test/kyverno-test.yaml',1,54,'객체 테스트 정의'),
     evidence('kyverno',p+'/.chainsaw-test/chainsaw-test.yaml',15,41,'Deny 변경 및 apply 테스트')])

p = ky('require-ro-rootfs')
add('KY-RO', 'kyverno', 'read-only-rootfs', 'require-ro-rootfs', 'catalog ClusterPolicy YAML',
    '컨테이너가 읽기 전용 루트 파일시스템을 선언하도록 검증한다고 설명한다.',
    '이 공개 pattern의 명시적 검사 대상은 일반 컨테이너 목록이다.', 'SCOPE_CLARIFICATION_NEEDED',
    '공개 YAML: Audit, background=true. Chainsaw 정의는 Enforce로 변경한다.',
    '일반적인 containers라는 설명을 모든 유형·모든 요청 시점의 보장으로 확장할 근거가 부족하다.',
    'CLI 객체 테스트와 Chainsaw apply 정의를 확인했다. 이번에는 실행하지 않았다.',
    '설명에 보장하는 컨테이너 유형을 적고, 범위를 확대하려면 검사 대상과 호환성·회귀 근거를 함께 보완한다.',
    [evidence('kyverno',p+'/require-ro-rootfs.yaml',11,33,'문서 표현과 명시 필드'),
     evidence('kyverno',p+'/.kyverno-test/kyverno-test.yaml',1,24,'객체 테스트 정의'),
     evidence('kyverno',p+'/.chainsaw-test/chainsaw-test.yaml',9,48,'집행 변경 및 apply 정의')])

p = ky('require-labels')
add('KY-LABEL', 'kyverno', 'metadata-label', 'require-labels', 'catalog ClusterPolicy YAML',
    'Pod의 app.kubernetes.io/name 레이블에 값이 있도록 검증한다.',
    'metadata.labels를 검사한다. 컨테이너 유형별 검사의 평가 단위가 아니다.', 'NOT_APPLICABLE',
    '공개 YAML: Audit, background=true. Chainsaw 정의는 Enforce로 변경한다.',
    'Pod 매칭 및 생성된 컨트롤러 규칙의 범위를 구분해야 한다.',
    'CLI 객체 테스트와 Chainsaw Pod/컨트롤러 apply 정의가 있다.',
    'Ephemeral Container 필드가 없다는 이유로 누락 또는 실패로 채점하지 않는다.',
    [evidence('kyverno',p+'/require-labels.yaml',11,31,'객체 레이블 계약'),
     evidence('kyverno',p+'/.kyverno-test/kyverno-test.yaml',1,23,'객체 테스트 정의'),
     evidence('kyverno',p+'/.chainsaw-test/chainsaw-test.yaml',9,43,'apply 정의')])

p='library/general/allowedreposv2'
add('GK-IMG', 'gatekeeper', 'image-origin', 'K8sAllowedReposv2', 'ConstraintTemplate plus sample Constraint',
    '허용 이미지의 정확 일치 또는 끝 wildcard에 따른 prefix 일치를 정의한다.',
    'Rego가 일반·init·ephemeral 이미지 목록을 각각 검사한다.', 'SOURCE_SUPPORTED',
    '표본 Constraint의 enforcementAction은 생략되어 있다. 제품 문서의 기본값은 deny다.',
    'Template만으로 배포가 완성되지 않는다. 표본 Constraint는 default namespace의 Pod를 선택한다. webhook 및 예외는 별도 확인 대상이다.',
    'gator Suite에 세 컨테이너 유형의 위반을 기대하는 객체 테스트가 있다. 객체 판정 정의는 live subresource 요청 증거와 다르다.',
    '표본의 namespace 한정과 실제 설치된 Constraint 범위를 문서화한다.',
    [evidence('gatekeeper',p+'/template.yaml',8,62,'계약·세 유형 평가식'),
     evidence('gatekeeper',p+'/samples/repo-must-be-openpolicyagent/constraint.yaml',1,18,'매칭·매개변수'),
     evidence('gatekeeper',p+'/suite.yaml',1,57,'gator 객체 테스트')])

p='library/pod-security-policy/read-only-root-filesystem'
add('GK-RO', 'gatekeeper', 'read-only-rootfs', 'K8sPSPReadOnlyRootFilesystem', 'ConstraintTemplate plus sample Constraint',
    'Pod 컨테이너의 읽기 전용 루트 파일시스템을 요구하는 PSP 대응 정책이다.',
    'CEL과 Rego에서 세 컨테이너 유형을 참조한다. 연산에 따른 평가 조건과 이미지 예외도 존재한다.', 'CONDITIONAL',
    '표본 Constraint는 enforcementAction을 생략한다. 제품 문서 기본값은 deny다.',
    '요청 연산 조건, 이미지 예외, 선택된 평가 엔진과 webhook 연결을 포함해야 계약을 해석할 수 있다.',
    'Suite는 ephemeral 객체 판정, 연산 조건, 예외에 관한 사례를 포함한다. 실제 Admission 요청 실행 기록은 수집하지 않았다.',
    '필드 열거 여부만으로 전체 생명주기 보장을 판정하지 말고 연산 조건을 정책 설명 및 회귀 범위에 포함한다.',
    [evidence('gatekeeper',p+'/template.yaml',8,34,'계약·문서화된 예외'),
     evidence('gatekeeper',p+'/template.yaml',38,120,'평가 엔진·필드·연산 조건'),
     evidence('gatekeeper',p+'/samples/psp-readonlyrootfilesystem/constraint.yaml',1,12,'표본 Constraint'),
     evidence('gatekeeper',p+'/suite.yaml',1,51,'객체·연산·예외 테스트 정의')])

p='library/general/requiredlabels'
add('GK-LABEL', 'gatekeeper', 'metadata-label', 'K8sRequiredLabels', 'ConstraintTemplate plus sample Constraint',
    '지정 레이블과 선택적인 값 정규식 조건을 요구한다.',
    'CEL 및 Rego가 객체 metadata.labels를 검사한다. 표본 Constraint는 Namespace를 선택한다.', 'NOT_APPLICABLE',
    '표본 Constraint는 enforcementAction을 생략한다. 제품 문서 기본값은 deny다.',
    '일반 template의 재사용 가능성과 이 표본의 실제 대상 Namespace를 구분한다.',
    'gator Suite에 레이블 존재·값 검사 객체 사례가 있다.',
    'Pod 정책과 똑같은 대상의 실험으로 집계하지 않으며 컨테이너 유형 누락으로 채점하지 않는다.',
    [evidence('gatekeeper',p+'/template.yaml',8,77,'계약 및 metadata 평가'),
     evidence('gatekeeper',p+'/samples/all-must-have-owner/constraint.yaml',1,14,'Namespace 표본'),
     evidence('gatekeeper',p+'/suite.yaml',1,33,'객체 테스트 정의')])

p='policies/trusted-repos-policy'
add('KW-IMG', 'kubewarden', 'image-origin', 'trusted-repos-policy', 'Wasm policy module source and metadata',
    'registry·tag·image 조건을 설정으로 조합해 이미지 출처를 제한한다.',
    'PodSpec 추출 후 discover_images가 일반·init·ephemeral 이미지 목록을 합친다.', 'SOURCE_SUPPORTED',
    'module metadata는 배포된 정책의 mode를 확정하지 않는다. 제품 문서 기본값 protect, monitor는 관측 모드다.',
    'module·settings·AdmissionPolicy 계열 리소스·PolicyServer 및 최종 요청 규칙이 함께 필요하다. 소스 버전 표기는 2.1.5이며 배포 OCI digest는 검증하지 않았다.',
    'Rust의 이미지 수집 단위 테스트에 ephemeral 사례가 있다. e2e.bats는 kwctl 로컬 평가 정의이며 live Admission 실행 결과가 아니다.',
    '추출 가능한 필드와 최종 생성된 요청 규칙을 분리해 설명한다. 필터의 의미도 다른 프로젝트의 허용 목록과 통일되어 있지 않다.',
    [evidence('kubewarden',p+'/README.md',4,26,'문서 계약'),
     evidence('kubewarden',p+'/metadata.yml',1,36,'기본 규칙 및 소스 버전'),
     evidence('kubewarden',p+'/src/lib.rs',42,92,'리소스 추출 경로'),
     evidence('kubewarden',p+'/src/validation.rs',54,88,'세 유형 이미지 수집'),
     evidence('kubewarden',p+'/src/validation.rs',313,345,'ephemeral 단위 테스트'),
     evidence('kubewarden',p+'/e2e.bats',1,42,'kwctl 테스트 정의')])

p='policies/readonly-root-filesystem-psp-policy'
add('KW-RO', 'kubewarden', 'read-only-rootfs', 'readonly-root-filesystem-psp-policy', 'Wasm policy module source and metadata',
    '일반·init 컨테이너 검사를 명시한다. README의 ephemeral에는 securityContext가 없다는 제외 사유는 참조 API 정의와 일치하지 않는다.',
    'do_validate는 일반·init 컨테이너를 검사한다. 문서상 범위 제한과 그 제한을 설명하는 API 사실의 정확성을 별도로 평가한다.', 'SCOPE_CLARIFICATION_NEEDED',
    '배포 mode는 미수집. 제품 문서 기본 protect, monitor는 비차단 관측 모드다.',
    '소스 metadata 버전은 1.0.14이다. 실제 OCI 바이너리와 배포 연결은 검증하지 않았다.',
    'Rust 단위 테스트 정의가 있다. 수집한 e2e.bats는 dummy test여서 실제 평가 또는 Admission 근거로 셀 수 없다.',
    'API에 관한 설명을 수정하고 의도한 컨테이너 범위를 명시한다. 범위를 바꾸면 별도 호환성·회귀 근거가 필요하다. 현재 확정 사항은 문서의 API 전제 오류다.',
    [evidence('kubewarden',p+'/README.md',4,25,'명시적 범위 및 API 설명'),
     evidence('kubewarden',p+'/src/lib.rs',25,76,'실제 입력과 검사'),
     evidence('kubewarden',p+'/src/lib.rs',78,105,'단위 테스트 정의'),
     evidence('kubewarden',p+'/metadata.yml',1,30,'규칙·버전'),
     evidence('kubewarden',p+'/e2e.bats',1,5,'dummy test'),
     evidence('kubernetes-api','core/v1/types.go',5191,5194,'v0.35.8 API의 ephemeral SecurityContext')])

p='policies/labels-policy'
add('KW-LABEL', 'kubewarden', 'metadata-label', 'labels-policy', 'Wasm policy module source and metadata',
    '일반 Kubernetes 객체의 레이블 키 집합을 설정한 논리 조건으로 검증한다. 기본 metadata는 workload 대상이라고 명시한다.',
    '입력 객체의 metadata.labels 키를 추출한다. 컨테이너 유형별 필드 검사가 아니다.', 'NOT_APPLICABLE',
    '배포 mode는 미수집. 제품 문서 기본 protect, monitor는 관측 모드다.',
    'README의 generic object 설명과 workload 기본 매칭을 구분해야 한다. 레이블 이름 설정은 필요하다. 소스 metadata 버전 0.1.10.',
    'Rust 단위 테스트와 kwctl 기반 e2e.bats 정의가 있다. 파일명 e2e를 클러스터 실행으로 해석하지 않는다.',
    '값 정규식/이름 일치 정책과 동일한 계약이라고 취급하지 않는다.',
    [evidence('kubewarden',p+'/README.md',6,48,'대상과 설정 조건'),
     evidence('kubewarden',p+'/src/lib.rs',23,54,'레이블 키 평가'),
     evidence('kubewarden',p+'/metadata.yml',1,61,'기본 규칙·버전'),
     evidence('kubewarden',p+'/e2e.bats',1,27,'kwctl 테스트 정의')])

p='docs/customization/custom-checks.md'
add('PL-IMG', 'polaris', 'image-origin', 'imageRegistry custom-check example', 'official documentation custom-check example',
    '문서 예제는 특정 registry 패턴을 금지한다. 내장 허용 목록 정책이 아니다.',
    'target=Container. 해당 반복 코드는 일반·init 컨테이너를 대상으로 하며 문서의 세부 옵션도 두 유형을 설명한다.', 'CONDITIONAL',
    '예제 severity=warning. 문서상 danger가 webhook 거부 기준이며 warning은 차단 보장이 아니다.',
    'customChecks 정의뿐 아니라 checks 활성화·severity·컨트롤러 포함/제외·예외 및 webhook 설정이 필요하다.',
    '이 특정 예제의 전용 회귀 테스트는 선택한 자료에서 확인하지 못했다. UNKNOWN이며 저장소 전체 부재를 뜻하지 않는다.',
    '문서의 all Container specs라는 표현을 구체적인 입력 범위와 함께 읽어야 한다. 앞선 자체 PodSpec 정책 실험으로 이 예제의 보장을 대신하지 않는다.',
    [evidence('polaris',p,14,55,'예제·모드·target 옵션'),
     evidence('polaris','pkg/validator/schema.go',251,274,'Container 반복 범위'),
     evidence('polaris','docs/admission-controller.md',10,17,'거부 기준'),
     evidence('polaris','docs/admission-controller.md',41,47,'warning 의미')])

add('PL-RO', 'polaris', 'read-only-rootfs', 'notReadOnlyRootFilesystem', 'built-in check',
    '컨테이너 파일시스템의 읽기 전용 여부를 확인한다.',
    'target=Container, schemaTarget=PodSpec. 각 일반·init 컨테이너를 선택한 뒤 검사할 PodSpec을 재구성한다. YAML의 containers만 보고 init 부재로 판단하면 틀린다.', 'CONDITIONAL',
    '기본 severity=warning. 이 기본값 자체는 webhook 차단 약속이 아니다.',
    '활성 설정, severity, exemption, webhook과 mutation 사용 여부를 구분해야 한다. 이번 검토는 검사 범위이며 mutation 보장은 조사하지 않았다.',
    'Container 평가 helper의 Go 단위 테스트 구조는 확인했다. 이 check의 전용 전체 suite나 live subresource 실행 결과를 검토한 것은 아니다.',
    'schemaTarget과 target을 모두 문서화하고 컨테이너 유형별 범위를 명시한다.',
    [evidence('polaris','pkg/config/checks/notReadOnlyRootFilesystem.yaml',1,47,'check 정의'),
     evidence('polaris','pkg/config/default.yaml',23,39,'기본 warning'),
     evidence('polaris','pkg/validator/schema.go',251,274,'반복 대상'),
     evidence('polaris','pkg/validator/schema.go',341,364,'schemaTarget 변환'),
     evidence('polaris','pkg/validator/container_test.go',64,88,'단위 테스트 helper'),
     evidence('polaris','docs/admission-controller.md',10,17,'차단 기준')])

add('PL-LABEL', 'polaris', 'metadata-label', 'label/name templating example', 'official documentation templating example',
    '문서 예제는 app.kubernetes.io/name과 객체 이름의 일치를 보여 준다.',
    'target=Controller, metadata.labels 평가. 컨테이너 유형별 검사와 무관하다.', 'NOT_APPLICABLE',
    '예제 블록 자체에는 checks 활성화 및 severity가 없어 배포 집행을 확정할 수 없다.',
    '같은 이름의 내장 정책으로 임의 대응시키지 않는다. 별도 내장 metadataAndInstanceMismatched는 instance 키를 사용하고 기본 warning이다.',
    '문서 예제의 전용 테스트는 선택 자료에서 확인하지 못했다. 다른 instance 내장 check의 fixture를 이 예제의 시험 증거로 합치지 않았다.',
    '예제의 설명·검사 키와 실제 내장 check를 구별하고 대상 Controller의 의미를 함께 명시한다.',
    [evidence('polaris',p,115,141,'선정한 문서 예제'),
     evidence('polaris',p,37,55,'활성화 및 대상 설명'),
     evidence('polaris','pkg/config/checks/metadataAndInstanceMismatched.yaml',1,18,'다른 내장 check와 구분'),
     evidence('polaris','pkg/config/default.yaml',1,9,'다른 내장 check의 모드')])

references = [
    ('kyverno-cp-mode','https://kyverno.io/docs/policy-types/cluster-policy/validate/','Audit/Enforce의 의미'),
    ('kyverno-vpol','https://kyverno.io/docs/policy-types/validating-policy/','정책 API·평가 모드와 생성 기능의 구분'),
    ('gatekeeper-mode','https://open-policy-agent.github.io/gatekeeper/website/docs/violations/','enforcementAction 기본 deny 및 dryrun/warn'),
    ('kubewarden-mode','https://docs.kubewarden.io/reference/monitor-mode','protect 기본값과 monitor 의미'),
    ('kubernetes-vap','https://kubernetes.io/docs/reference/access-authn-authz/validating-admission-policy/','정책·binding과 action의 구분'),
    ('kubernetes-pss-map','https://kubernetes.io/docs/reference/access-authn-authz/psp-to-pod-security-standards/','PSS는 readOnlyRootFilesystem에 대해 no opinion'),
]
result = {
    'reviewDateKst': '2026-09-19', 'method': 'exploratory purposive manual source review; single reviewer',
    'sampleUnitCount': len(rows), 'sampleProjects': sorted({r['project'] for r in rows}),
    'sourceLockSha256': hashlib.sha256((HERE/'source-lock.json').read_bytes()).hexdigest(),
    'runtimeTestsPerformed': False, 'confirmedCommonProductDefect': False,
    'meaningOfFalse': '이번 근거로 입증하지 못했다는 뜻이며 결함이 없다는 증명이 아니다.',
    'documentationReferences': [dict(id=i,url=u,purpose=p,checkedDateKst='2026-09-19',
       revision='online documentation; not immutable') for i,u,p in references],
    'rows': rows,
}

# Integrity checks verify provenance and completeness, not the truth of manual judgments.
assert len(rows) == 13 and len({r['id'] for r in rows}) == 13
assert len(result['sampleProjects']) == 4
assert not lock['unavailableRequestedSources']
for s in lock['sources']:
    data = (CACHE/s['project']/s['commit']/s['path']).read_bytes()
    assert hashlib.sha256(data).hexdigest() == s['sha256'], s['path']
for r in rows:
    assert r['actualAdmissionGuarantee'] == 'UNKNOWN'
    assert r['testsExecutedInThisSurvey'] is False and len(r['evidence']) >= 3

(HERE/'coverage.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
columns = ['id','project','family','name','artifactType','documentedContract','sourceScope',
           'scopeAssessment','enforcementMode','deploymentConditions','testDefinitionEvidence',
           'actualAdmissionGuarantee','testsExecutedInThisSurvey','remediationOrOpenQuestion','evidenceUrls']
with (HERE/'coverage.csv').open('w',encoding='utf-8-sig',newline='') as f:
    writer = csv.DictWriter(f,fieldnames=columns)
    writer.writeheader()
    for r in rows:
        writer.writerow({**{k:r[k] for k in columns if k!='evidenceUrls'},
                         'evidenceUrls':' | '.join(e['url'] for e in r['evidence'])})
md = ['# 공개 정책 보장 범위 대조표', '',
      '수동 검토 원본은 review.py, 전체 조건·테스트 근거·보완 항목은 coverage.json / coverage.csv에 있다. 모든 행의 실제 Admission 보장은 UNKNOWN이고 이번에 정책 테스트를 실행하지 않았다.', '',
      'SOURCE_SUPPORTED는 소스 입력 범위 확인, CONDITIONAL은 설정·평가 조건부, SCOPE_CLARIFICATION_NEEDED는 범위 또는 설명 보완 필요, NOT_APPLICABLE은 컨테이너 유형별 비교 비대상을 뜻한다. 결함률 또는 제품 순위가 아니다.', '',
      '| ID / 정책 | 산출물 | 소스에서 확인한 범위 | 집행 모드 | 범위 판정 | 근거 |',
      '| --- | --- | --- | --- | --- | --- |']
for r in rows:
    refs = ' · '.join(f"[{i}]({e['url']})" for i,e in enumerate(r['evidence'],1))
    cells = [r['id']+' / '+r['name'],r['artifactType'],r['sourceScope'],r['enforcementMode'],r['scopeAssessment'],refs]
    md.append('| '+' | '.join(c.replace('|','\\|').replace('\n',' ') for c in cells)+' |')
(HERE/'MATRIX.ko.md').write_text('\n'.join(md)+'\n',encoding='utf-8')
validation = dict(sampleUnits=len(rows), sampledProjects=len(result['sampleProjects']),
    lockedSourcesChecked=len(sources), evidenceAnchorsChecked=sum(len(r['evidence']) for r in rows),
    missingSources=0, runtimeTestsPerformed=False, integrityChecks='passed',
    limitation='무결성 검사 통과는 수동 판정의 독립 검토나 정책 실행 검증이 아니다.')
(HERE/'integrity.json').write_text(json.dumps(validation,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(validation,ensure_ascii=False))
