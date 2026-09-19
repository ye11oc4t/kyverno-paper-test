# 임시 컨테이너 정책 유효 적용 범위 실험 결과

## 결론

Kyverno, Gatekeeper, Kubewarden의 선택한 공개 privileged 정책에서 같은 최종 미탐이 재현됐다. 세 도구 모두 일반 Pod 생성에 `securityContext.privileged: true`가 있으면 거부했지만, 기존 Pod에 같은 설정의 임시 컨테이너를 추가하는 `pods/ephemeralcontainers` 요청은 허용했다.

이 결과는 제품마다 3개의 새 Kubernetes 클러스터를 만들고 각 설치에서 같은 API 요청을 5회 반복한 총 45개의 정식 실행에서 모두 같았다. 모든 실행에서 테스트 ServiceAccount는 필요한 두 권한을 가지고 있었고, 안전한 일반 Pod와 안전한 임시 컨테이너 요청은 허용됐으며, 일반 privileged Pod는 대상 정책의 이름이나 메시지로 거부됐다. dry-run 전후 기준 Pod의 `resourceVersion`은 같았고 `spec.ephemeralContainers`도 저장되지 않았다.

후속 실제 실행 실험에서는 제품별 새 클러스터 한 개에서 `dryRun`을 제거했다. 세 도구 모두 일반 privileged Pod를 실제 거부하면서 privileged 임시 컨테이너 추가는 허용했고, 해당 컨테이너는 containerd ID를 받아 `Running` 상태에서 UID 0과 `CapEff 000001ffffffffff`로 실행됐다. 이 후속 결과와 한계는 [LIVE-REPORT.ko.md](LIVE-REPORT.ko.md)에 분리해 기록했다.

세 도구의 공통점은 최종 보장 실패이고 원인은 서로 다르다. Kyverno와 Kubewarden은 하위 API 요청이 정책식 또는 정책 모듈까지 전달되지 않았고, Gatekeeper는 요청을 받은 뒤 UPDATE 전체를 허용하는 조건 때문에 통과시켰다. 각 원인 후보 하나만 고친 분리 실험에서 세 도구 모두 C3이 허용에서 거부로 바뀌었다.

## 실행 환경

- 실행 시각: 2026-09-19 KST
- 호스트: `ksybob`의 WSL2 Ubuntu 24.04
- Kubernetes: kind, `kindest/node:v1.35.8`
- kind: v0.33.0
- kubectl: v1.35.8
- Helm: v3.22.0
- Docker Engine: 29.8.0
- Kyverno: chart 3.9.1, app v1.19.1
- Kyverno policies: chart 3.9.1, 기본 CEL `ValidatingPolicy`
- Gatekeeper: chart/app v3.23.1
- Gatekeeper library: commit `22a40962f83268769bcec5dfe55e44b5a85c392a`
- Kubewarden admission-controller: chart 6.0.2, app v1.37.2
- Kubewarden privileged module: `ghcr.io/kubewarden/policies/pod-privileged:v1.0.13`

각 제품은 다른 제품이 설치되지 않은 단일 노드 kind 클러스터에서 실행했다. 입장 판정과 무관한 Kyverno background·cleanup·reports controller, Gatekeeper 주기적 audit, Kubewarden audit scanner는 껐다. 모든 admission controller와 policy server는 1개 replica로 실행했다.

## 요청과 판정

실험 네임스페이스의 Pod Security Admission 수준은 `privileged`로 설정했다. 제3자 정책이 아니라 내장 PSA가 위반 요청을 막는 일을 피하기 위해서다. 테스트 ServiceAccount에는 `pods` create와 `pods/ephemeralcontainers` update 권한을 부여하고 SelfSubjectAccessReview로 실제 허용을 확인했다.

| 사례 | 요청 | 기대값 |
|---|---|---|
| C0 | 안전한 일반 Pod CREATE, `dryRun=All` | 허용 |
| C1 | privileged 일반 Pod CREATE, `dryRun=All` | 정책 거부 |
| C2 | 안전한 임시 컨테이너 PATCH, `dryRun=All` | 허용 |
| C3 | privileged 임시 컨테이너 PATCH, `dryRun=All` | 정책 거부 |

C0와 C1은 `POST /api/v1/namespaces/policy-gap-test/pods?dryRun=All`로 보냈다. C2와 C3은 `PATCH /api/v1/namespaces/policy-gap-test/pods/baseline/ephemeralcontainers?dryRun=All`로 보내고 Content-Type은 `application/strategic-merge-patch+json`으로 고정했다. 모든 위반 요청은 `registry.k8s.io/pause:3.10`을 사용한 dry-run이므로 privileged 컨테이너가 저장되거나 실행되지 않았다.

## 정식 반복 결과

| 제품 | 독립 설치 | 설치당 반복 | C0 | C1 | C2 | C3 | 미탐 패턴 |
|---|---:|---:|---|---|---|---|---|
| Kyverno | 3 | 5 | 201 × 15 | 400 × 15 | 200 × 15 | 200 × 15 | 15/15 |
| Gatekeeper | 3 | 5 | 201 × 15 | 422 × 15 | 200 × 15 | 200 × 15 | 15/15 |
| Kubewarden | 3 | 5 | 201 × 15 | 400 × 15 | 200 × 15 | 200 × 15 | 15/15 |

여기서 200과 201은 허용이다. 400과 422는 각각 대상 정책이 반환한 거부다. Gatekeeper의 C1은 생성된 Kubernetes ValidatingAdmissionPolicy가 거부했으며 메시지에 `gatekeeper-k8spspprivilegedcontainer`와 `psp-privileged-container`가 포함됐다. Kyverno와 Kubewarden의 C1 응답에도 각각 `disallow-privileged-containers`와 `no-privileged-pod`가 포함됐다.

C3의 200 응답 body에는 요청한 privileged 임시 컨테이너가 들어 있는 dry-run 결과 Pod가 반환됐다. 그러나 API에서 다시 조회한 실제 기준 Pod에는 임시 컨테이너가 없었고 모든 반복에서 요청 전후 `resourceVersion`도 같았다. 따라서 결과는 실제 실행 성공이 아니라 admission 허용 판정의 증거다.

## 제품별 원인

### Kyverno

차트가 설치한 CEL `ValidatingPolicy`는 `spec.ephemeralContainers`를 검사했지만 `matchConstraints.resourceRules.resources`에는 `pods`만 있었다. 실제 `kyverno-resource-validating-webhook-cfg`에도 `pods/ephemeralcontainers`가 없었다. 따라서 일반 Pod C1은 정책식에 도달해 거부됐지만 C3은 해당 웹훅으로 전달되지 않았다.

같은 정책식은 유지하고 리소스 규칙에 `pods/ephemeralcontainers`만 추가하자 C3이 200에서 400으로 바뀌었다. C0, C1, C2의 판정은 유지됐다. 이 변경 하나가 결과를 뒤집었으므로 현재 CEL 정책에서 라우팅 누락은 관찰한 미탐의 충분 원인이다.

같은 Kyverno 1.19.1과 정책 차트 3.9.1에서 정책 형식만 레거시 `ClusterPolicy`로 바꾼 비교군은 C3을 400으로 거부했다. 따라서 이 결과를 “Kyverno 엔진은 임시 컨테이너를 검사할 수 없다”로 해석하면 틀린다. 현재 차트의 기본 CEL `ValidatingPolicy` 경로와 레거시 정책 경로의 적용 범위 차이다.

### Gatekeeper

Gatekeeper의 `validation.gatekeeper.sh` 웹훅과 Gatekeeper가 생성한 네이티브 ValidatingAdmissionPolicy는 모두 `pods/ephemeralcontainers`와 UPDATE를 등록했다. 요청 미전달이 아니다. 정책은 일반·초기화·임시 컨테이너를 모두 합쳐 privileged 값을 찾은 다음에도 `request.operation == "UPDATE"`이면 허용했다.

CEL과 Rego의 UPDATE 조건에 `subResource != "ephemeralcontainers"`를 추가해 임시 컨테이너 UPDATE만 검사하게 만들자 C3이 200에서 422로 바뀌었다. C0, C1, C2는 그대로였다. 따라서 Gatekeeper에서 관찰한 미탐의 충분 원인은 오래된 “Pod 보안 필드는 UPDATE로 바뀌지 않는다”는 단축 조건이다.

첫 설치에서 Constraint가 웹훅에는 준비됐지만 네이티브 ValidatingAdmissionPolicyBinding은 아직 생성 중이었다. 이 준비 구간의 첫 C1은 웹훅이 403으로 거부했고 이후 C1은 네이티브 VAP가 422로 거부했다. 판정은 같았지만 집행 경로가 바뀌었으므로 이 5회는 정식 집계에서 제외하고 binding 준비 뒤 5회를 다시 측정했다. 두 번째와 세 번째 설치도 binding 준비를 기다린 뒤 측정했다.

### Kubewarden

공식 admission-controller 6.0.2 차트가 렌더링한 `no-privileged-pod`는 모듈 설정에서 `skip_ephemeral_containers: false`였지만, 리소스 규칙은 `pods`의 CREATE만 포함했다. 생성된 ValidatingWebhookConfiguration도 같았다. 모듈이 임시 컨테이너를 검사할 수 있어도 C3은 정책 서버에 전달되지 않았다.

같은 정책 객체와 모듈 설정을 유지하고 `pods/ephemeralcontainers`의 UPDATE 규칙 하나만 추가하자 C3이 200에서 400으로 바뀌었다. C0, C1, C2는 그대로였다. 따라서 Kubewarden privileged 정책의 관찰된 미탐에는 차트 라우팅 규칙이 충분 원인이다.

Kubewarden 통합 차트는 recommended 정책을 개별적으로 활성화하는 값이 없다. 다른 정책의 거부가 결과에 섞이지 않도록 차트를 `protect` 모드로 렌더링하고, 생성된 `kubewarden-defaults` ConfigMap에서 `pod-privileged.yaml`을 수정 없이 추출해 그것만 적용했다. 엔진과 기본 PolicyServer는 같은 공식 차트로 설치했다.

## 원인 분리 결과

| 제품 | 바꾼 항목 | 변경 전 C3 | 변경 후 C3 | 나머지 대조 사례 |
|---|---|---:|---:|---|
| Kyverno | `pods/ephemeralcontainers` 라우팅 추가 | 200 | 400 | 유지 |
| Gatekeeper | 임시 컨테이너 UPDATE를 검사하도록 단축 조건 수정 | 200 | 422 | 유지 |
| Kubewarden | `pods/ephemeralcontainers` UPDATE 라우팅 추가 | 200 | 400 | 유지 |

세 변경은 각각 한 층만 바꿨다. 이 결과는 세 제품에서 같은 최종 미탐이 우연히 관찰됐다는 것보다, 소스에서 지목한 서로 다른 원인이 실제 API 판정을 만들었다는 설명을 지지한다.

## 주장 범위와 한계

이번 실행은 상세 설계의 1차 판정인 privileged P 단계만 수행했다. privilege escalation E 단계와 capability C 단계는 아직 실행하지 않았다. 따라서 여러 정책군 전체에 같은 현상이 반복된다고 실험 결과로 주장할 수는 없다.

요청 순서를 반복마다 번갈아 배치한다는 설계와 달리 실제 실행기는 C0, C1, C2, C3 순서로 고정했다. 모든 요청이 dry-run이었고 실제 기준 Pod가 한 번도 바뀌지 않았으며 3개 독립 설치에서 같은 결과가 나왔기 때문에 현재 판정에 미친 영향은 작아 보인다. 그래도 순서 효과를 완전히 제거한 실험은 아니다.

로컬 단일 노드 kind와 단일 replica를 사용했으므로 관리형 Kubernetes, HA 복제본 사이의 전파 지연, 장애 시 failurePolicy 동작은 평가하지 않았다. 후속 실험에서 실제 privileged 임시 컨테이너의 저장과 실행, UID 0 및 유효 capability 적용까지 확인했지만 노드 장악이나 컨테이너 탈출은 시도하지 않았다. 실제 공격에는 별도의 `pods/ephemeralcontainers` RBAC 권한이 필요하고, 내장 Pod Security Admission이나 다른 admission 도구가 별도로 차단할 수 있다.

따라서 현재 증거가 지지하는 주장은 다음과 같다. “고정한 버전과 공개 privileged 정책 구성에서 Kyverno, Gatekeeper, Kubewarden은 일반 privileged Pod를 거부하면서 privileged 임시 컨테이너 추가를 허용하는 동일한 유효 적용 범위 미탐을 보였고, 제품별 단일 원인 수정으로 판정이 거부로 바뀌었다.” 이를 모든 Kubernetes 정책 도구나 모든 정책에 대한 주장으로 확대하지 않는다.

## 결과 파일

- `results/2026-09-19/aggregate.json`: 45개 정식 실행과 원인 분리 결과의 기계 판독 집계
- `results/2026-09-19/<product>/<run>/summary.json`: 실행별 상태 코드와 RBAC 결과
- 각 실행의 `cases/<case>/`: 요청 body, SHA-256, 시각, HTTP 상태, 응답 header와 body
- 각 정식 설치의 첫 실행 `evidence/`: 정책 객체, 웹훅, 상태, 로그, Helm 값
- `run-api-cases.sh`: ServiceAccount로 네 가지 API 사례를 보내는 공통 실행기
- `aggregate_results.py`: 정식 실행 유효성 검사와 집계 생성기
- `LIVE-REPORT.ko.md`: 제품별 한 번의 실제 저장·실행 후속 검증
- `results/2026-09-19-live-execution/aggregate.json`: 실제 실행 후속 결과 집계
- `run-live-case.sh`, `aggregate_live_results.py`: 실제 실행기와 증거 검증기
