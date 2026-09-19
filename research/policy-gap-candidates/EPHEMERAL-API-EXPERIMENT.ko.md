# 임시 컨테이너 정책 미탐 API 실험 설계

## 상태

이 문서는 실행 전 설계다. 아직 클러스터를 만들거나 요청을 보내지 않았으며 결과도 없다. 본 실험은 Kyverno, Gatekeeper, Kubewarden 세 도구를 핵심 비교 대상으로 삼는다. Polaris는 세 도구의 결과를 확인한 뒤 추가 재현 대상으로만 사용한다.

소스만 보면 세 도구에서 같은 최종 현상, 즉 일반 privileged Pod는 거부하면서 privileged 임시 컨테이너 추가는 허용하는 결과가 예상된다. 그러나 이것은 아직 관찰값이 아니다. 세 도구 모두에서 재현된다는 주장은 아래 실험의 C1과 C3 결과가 나온 뒤에만 한다.

## 연구 질문

공개 privileged·privilege escalation·capability 정책이 일반 Pod 생성과 기존 Pod의 임시 컨테이너 추가에 같은 보장을 제공하는가. 미탐이 있다면 웹훅 등록, UPDATE 처리, 객체 순회 중 어느 층에서 발생하는가.

세 도구에서 기대하는 보안 의미는 동일하다. `securityContext.privileged: true`인 컨테이너는 일반 컨테이너, 초기화 컨테이너, 임시 컨테이너 중 어디에 있든 거부되어야 한다. 임시 컨테이너라는 이유로 예외를 주려면 사용자가 명시적으로 예외를 설정해야 한다.

## 가설

귀무가설 H0는 세 도구의 공개 정책이 일반 privileged Pod와 privileged 임시 컨테이너를 모두 거부한다는 것이다.

대립가설은 다음과 같이 제품별로 나눈다.

- Kyverno H1-K: 정책식은 임시 컨테이너를 검사하지만 `pods/ephemeralcontainers`가 웹훅 규칙에 없어 요청이 정책식까지 도달하지 않는다.
- Gatekeeper H1-G: 웹훅은 요청을 받지만 공개 PSS 정책의 `UPDATE이면 허용` 조건 때문에 위반을 허용한다.
- Kubewarden H1-W: recommended policy 차트가 `pods`의 CREATE만 등록해 privileged 모듈에 요청이 도달하지 않는다. 일부 다른 모듈은 라우팅을 고쳐도 임시 컨테이너 배열을 읽지 않는다.

세 도구에서 같은 허용 결과가 나와도 공통 원인이라고 주장하지 않는다. 공통점은 최종 보장 실패이고 코드 원인은 도구별로 다르다.

| 도구 | 요청 전달 | 정책식 도달 후 예상 분기 | 검증할 층 |
|---|---|---|---|
| Kyverno | 하위 API가 웹훅 규칙에서 빠질 것으로 예상 | 정책식은 임시 컨테이너를 읽음 | 라우팅 |
| Gatekeeper | 하위 API와 UPDATE를 받을 것으로 예상 | UPDATE 단축 조건으로 허용할 것으로 예상 | 연산 분기 |
| Kubewarden | 공개 차트가 pods CREATE만 등록할 것으로 예상 | privileged 모듈은 임시 컨테이너를 읽음 | 라우팅 |

## 고정 버전과 독립 환경

각 도구는 Kubernetes v1.35.8 kind 클러스터에 하나씩만 설치한다. 같은 클러스터에 여러 정책 도구를 설치하지 않는다. 버전은 다음과 같이 고정한다.

- Kyverno v1.19.1, `kyverno-policies` chart 3.9.1
- Gatekeeper v3.23.1, gatekeeper-library commit `22a40962f83268769bcec5dfe55e44b5a85c392a`
- Kubewarden v1.37.2, controller commit `23657f51d11fbc75ecd94f69c32a89ee5901cfcf`

각 제품은 세 번의 새 클러스터 설치에서 반복한다. 정책 상태가 준비된 뒤 동일 dry-run 요청을 다섯 번 보내며, 다섯 응답이 일치하지 않으면 해당 설치를 비결정적 실행으로 표시하고 원인을 조사한다.

## 정책 구성과 독립 단계

한 요청이 여러 정책에 동시에 거부되어 원인 귀속이 흐려지지 않도록 정책군을 세 단계로 분리한다. 각 단계에서는 대상 정책 하나만 거부 모드로 둔다. 1차 논문 판정은 세 도구 모두에서 공개 정책과 원인이 가장 명확한 P 단계로 한다. E와 C 단계는 결함 범위가 한 정책에 한정되지 않는지 확인하는 확장 실험이다.

- P 단계: privileged 정책, 사례 C0부터 C3
- E 단계: privilege escalation 정책, 사례 C0·C2·C4·C5
- C 단계: capability 정책, 사례 C0·C2·C6·C7

각 단계가 끝나면 대상 정책을 삭제하고 API에서 웹훅 규칙과 정책 캐시가 정리된 것을 확인한 뒤 다음 정책을 설치한다. 정책 준비 직후의 활성화 간격이 결과에 섞이지 않도록 일반 컨테이너 양성 대조가 안정적으로 거부될 때까지 본 사례를 시작하지 않는다.

### Kyverno

`kyverno-policies`의 기본 정책 형식인 `ValidatingPolicy`를 유지하고 `validationFailureAction: Enforce`를 사용한다. 차트 렌더링 결과에서 `validationActions: [Deny]`인지 확인한다. 각 단계에서는 차트가 렌더링한 다음 공개 정책 중 하나만 설치하고 Ready인지 API로 확인한다.

- disallow-privileged-containers
- disallow-privilege-escalation
- disallow-capabilities-strict

이 가설은 Kyverno 전체와 과거 버전에 대한 주장이 아니라 v1.19.1 차트 3.9.1이 기본으로 만드는 CEL `ValidatingPolicy` 경로에 대한 주장이다. 과거 `ClusterPolicy`가 임시 컨테이너를 거부한 공개 재현 사례와 구분한다. P 단계가 끝난 뒤 같은 차트에서 정책 형식만 `ClusterPolicy`로 바꾼 비교군을 한 번 더 실행한다. 이 비교군은 현재 기본값의 결함 판정에는 포함하지 않고 정책 형식 전환이 적용 범위에 미친 영향을 설명하는 데만 사용한다.

### Gatekeeper

고정 commit의 공식 template과 constraint를 설치한다. constraint의 `enforcementAction`은 deny로 둔다. 각 단계에서는 다음 정책 중 하나만 설치한다.

- K8sPSPPrivilegedContainer
- K8sPSPAllowPrivilegeEscalationContainer
- K8sPSPCapabilities

ConstraintTemplate과 constraint가 모두 API에서 생성되고 status에 오류가 없으며, 해당 단계의 일반 위반 Pod가 정책 고유 메시지로 거부된 뒤에만 본 사례를 시작한다.

### Kubewarden

recommended policy 차트가 생성하는 객체를 사용하고 `defaultPolicyMode: protect`로 설정한다. `skip_ephemeral_containers: false`를 유지한다. 각 단계에서는 다음 정책 중 하나만 활성화하고 PolicyServer와 정책이 Active인지 API로 확인한다.

- no-privileged-pod
- no-privilege-escalation
- drop-capabilities

차트가 실제로 생성한 ClusterAdmissionPolicy를 그대로 기준 구성으로 사용한다. 사용자가 수정한 규칙을 기준 결과에 섞지 않는다.

## Kubernetes 내장 정책과 RBAC 통제

실험 네임스페이스에는 다음 Pod Security Admission 라벨을 설정해 내장 PSA가 제3자 도구의 결과를 가리지 않게 한다.

```yaml
pod-security.kubernetes.io/enforce: privileged
pod-security.kubernetes.io/audit: privileged
pod-security.kubernetes.io/warn: privileged
```

테스트 주체는 전용 ServiceAccount로 만든다. 권한은 Pod 생성·조회·삭제와 `pods/ephemeralcontainers`의 get·patch·update로 한정한다. `SelfSubjectAccessReview` API에서 다음 두 결과를 저장한다.

- `create` on `pods`: allowed
- `update` on `pods/ephemeralcontainers`: allowed

RBAC 403은 정책 거부로 세지 않는다. 내장 PSA, 이미지 정책, 할당량 등 대상 정책이 아닌 구성요소가 요청을 거부하면 해당 사례를 무효 처리한다.

## API-only 실행 방식

모든 조작과 증거 수집은 Kubernetes API로 수행한다. `kubectl`을 사용하더라도 REST API 클라이언트로만 취급하며 노드 셸이나 컨테이너 셸에 접속하지 않는다.

먼저 안전한 기준 Pod 하나를 실제로 생성한다. `registry.k8s.io/pause` 이미지만 사용하고 privileged, hostPath, host namespace를 사용하지 않는다. Pod가 API에 존재해야 임시 컨테이너 하위 API를 호출할 수 있다.

기준 Pod가 `Ready=True`가 될 때까지 Pod GET API로 확인한다. 이 조건을 만족하지 못하면 노드나 이미지 준비 문제와 admission 결과가 섞일 수 있으므로 실행을 시작하지 않는다.

일반 Pod 대조 요청은 다음 API에 `dryRun=All`을 붙인다.

```text
POST /api/v1/namespaces/policy-gap-test/pods?dryRun=All
```

임시 컨테이너 요청은 다음 하위 API에 `dryRun=All`을 붙인다.

```text
PATCH /api/v1/namespaces/policy-gap-test/pods/baseline/ephemeralcontainers?dryRun=All
Content-Type: application/strategic-merge-patch+json
```

예시 privileged 요청 본문은 다음과 같다. dry-run이므로 저장되거나 실행되지 않는다.

```json
{
  "spec": {
    "ephemeralContainers": [
      {
        "name": "debug-privileged",
        "image": "registry.k8s.io/pause:3.10",
        "securityContext": {
          "privileged": true
        }
      }
    ]
  }
}
```

Kubernetes API가 이 PATCH 형식을 지원하지 않는 환경에서는 기존 Pod를 GET한 뒤 전체 객체와 resourceVersion을 사용해 다음 API로 바꾼다.

```text
PUT /api/v1/namespaces/policy-gap-test/pods/baseline/ephemeralcontainers?dryRun=All
```

PATCH와 PUT을 서로 다른 실험 조건으로 섞지 않는다. 세 제품 모두 같은 방식을 사용한다.

각 반복에서 안전 입력과 위반 입력의 순서는 번갈아 바꾼다. 모든 요청은 dry-run이라 Pod를 바꾸지 않지만, 고정된 요청 순서와 정책 서버 준비 상태가 결합하는 효과를 확인하기 위해서다. 각 요청 직전에 기준 Pod의 `resourceVersion`과 `spec.ephemeralContainers`를 저장하고, 요청 뒤에도 값이 변하지 않았음을 확인한다.

## 사례 행렬

| ID | API 경로 | 입력 | 보안 기대값 |
|---|---|---|---|
| C0 | pods CREATE | 안전한 일반 컨테이너 | 허용 |
| C1 | pods CREATE | `privileged: true` 일반 컨테이너 | 거부 |
| C2 | pods/ephemeralcontainers UPDATE | 안전한 임시 컨테이너 | 허용 |
| C3 | pods/ephemeralcontainers UPDATE | `privileged: true` 임시 컨테이너 | 거부 |
| C4 | pods CREATE | `allowPrivilegeEscalation: true` 일반 컨테이너 | 거부 |
| C5 | pods/ephemeralcontainers UPDATE | `allowPrivilegeEscalation: true` 임시 컨테이너 | 거부 |
| C6 | pods CREATE | `capabilities.add: [SYS_ADMIN]` 일반 컨테이너 | 거부 |
| C7 | pods/ephemeralcontainers UPDATE | `capabilities.add: [SYS_ADMIN]` 임시 컨테이너 | 거부 |

C0과 C2는 정책이 안전한 입력을 무조건 막는 오탐이 없는지 확인한다. C1, C4, C6은 각 단계의 정책 설치와 거부 모드가 실제로 작동하는 양성 대조다. C3, C5, C7이 대응하는 본 사례다. 안전한 securityContext도 단계마다 최소 조건만 사용한다. 예를 들어 E 단계의 안전 입력은 `allowPrivilegeEscalation: false`, C 단계의 안전 입력은 위험 capability를 추가하지 않은 상태다.

## 실행 유효성 조건

다음 조건을 모두 만족한 설치만 결과에 포함한다.

1. 대상 정책과 정책 서버가 Ready 또는 Active다.
2. C0과 C2가 허용된다.
3. 현재 단계의 일반 컨테이너 양성 대조가 해당 제품의 정책 이름과 메시지로 거부된다.
4. 요청 주체가 `pods/ephemeralcontainers` update 권한을 가진다.
5. 내장 PSA와 다른 admission 도구가 본 사례를 대신 거부하지 않는다.
6. 웹훅 timeout, 연결 실패, `failurePolicy`에 따른 허용이 발생하지 않는다.
7. 차트 렌더링 산출물과 설치 뒤 실제 ValidatingWebhookConfiguration의 리소스·연산 규칙을 모두 보존했다.

P 단계에서 C1이 허용되면 제품이 임시 컨테이너만 놓쳤다고 말할 수 없으므로 해당 실행을 무효 처리한다. E 단계의 C4, C 단계의 C6에도 같은 규칙을 적용한다. 본 사례가 허용되더라도 웹훅 오류나 timeout이 있으면 정책 미탐으로 세지 않는다.

## 판정 기준

HTTP 2xx는 허용, admission 응답의 4xx와 대상 정책 메시지는 거부로 기록한다. 다음 조건을 만족하면 해당 제품에서 privileged 임시 컨테이너 미탐을 관찰한 것으로 판정한다.

```text
C0 = allow
C1 = deny by target policy
C2 = allow
C3 = allow
```

C5와 C7도 각각 C4와 C6이 정상 거부된 경우에만 독립 미탐으로 센다. 결과는 `deny`, `allow`, `invalid`, `masked`, `error` 다섯 상태로 저장한다. RBAC 거부와 PSA 거부를 제품 성공으로 세지 않는다.

## 원인 분리 실험

기준 결과를 얻은 다음 한 번에 한 층만 수정한다.

원인 분리 실험은 기준 공개 정책과 별도 결과 집합으로 저장한다. 수정본이 거부에 성공해도 기준 공개 정책의 성공으로 다시 분류하지 않는다.

### Kyverno 분리

정책식은 그대로 두고 `matchConstraints.resourceRules.resources`에 `pods/ephemeralcontainers`만 추가한다. C3이 allow에서 deny로 바뀌면 웹훅 등록 누락이 충분 원인이다. 계속 허용되면 요청 로그와 정책 평가 경로를 조사하며 등록 누락만으로 결론 내리지 않는다.

### Gatekeeper 분리

웹훅과 컨테이너 수집식은 그대로 두고 `UPDATE이면 허용` 조건에 `request.subResource != 'ephemeralcontainers'` 예외를 추가한다. C3이 allow에서 deny로 바뀌면 연산 단축 조건이 충분 원인이다. 정책 전체에서 UPDATE 생략을 제거한 결과도 보조 비교하되 실제 수정안으로 제안하지 않는다.

### Kubewarden 분리

첫 단계에서는 같은 privileged 모듈과 설정을 유지한 채 규칙에 `pods/ephemeralcontainers`와 UPDATE만 추가한다. C3이 deny로 바뀌면 privileged 정책의 원인은 라우팅이다.

두 번째 단계에서는 C5와 C7을 확인한다. 라우팅만 고친 뒤에도 허용되면 allow-privilege-escalation과 capabilities 모듈에 임시 컨테이너 순회만 추가한다. 그 뒤 deny로 바뀌면 객체 순회 누락이 추가 원인이다.

각 수정은 별도 설치에서 수행하거나 기준 정책으로 완전히 되돌린 뒤 수행한다. 여러 변경을 동시에 적용하지 않는다.

## 수집할 API 증거

각 요청마다 다음 자료를 원문으로 저장한다.

- 요청 URL, 메서드, Content-Type, 본문 SHA-256, 시각
- HTTP 상태 코드, 응답 body, Warning 헤더
- 요청 전후 기준 Pod JSON
- ValidatingWebhookConfiguration 전체 JSON
- Kyverno ValidatingPolicy와 status
- Gatekeeper ConstraintTemplate, constraint와 status
- Kubewarden ClusterAdmissionPolicy, PolicyServer와 status
- 정책 서버 Pod 로그의 요청 시각 전후 구간을 `pods/log` API로 조회한 결과
- SelfSubjectAccessReview 결과

API 서버 감사 로그를 사용할 수 있으면 admission webhook annotation을 보조 증거로 보존한다. 감사 로그가 없어도 API 결과와 웹훅 설정, 정책 서버 로그로 기본 판정은 가능하다.

## 예상 결과와 반증

소스에서 도출한 예상은 다음과 같다.

| 도구 | C1 일반 privileged | C3 임시 privileged | 예상 원인 |
|---|---|---|---|
| Kyverno | deny | allow | subresource 등록 누락 |
| Gatekeeper | deny | allow | UPDATE 전체 허용 |
| Kubewarden | deny | allow | CREATE-only pods 규칙 |

각 제품의 기준 공개 정책이 C3을 정책 고유 메시지로 거부하면 그 제품에 대한 가설은 반증된다. 세 제품이 모두 C3을 거부하면 현재 논문 중심 가설을 폐기한다. 두 제품에서만 재현되면 “공통 제품 결함” 대신 “여러 구현에서 반복되는 유효 적용 범위 결함”으로 범위를 줄인다.

Kyverno의 현재 CEL `ValidatingPolicy`가 C3을 허용하고 형식 비교군인 `ClusterPolicy`가 C3을 거부하면 차트의 정책 형식 전환에 따른 회귀 가능성을 별도 결과로 기록한다. 둘 다 허용하면 Kyverno의 더 넓은 라우팅 문제이고, 둘 다 거부하면 Kyverno 가설은 반증된다. 한 번의 비교만으로 과거 모든 Kyverno 버전을 일반화하지 않는다.

세 제품에서 모두 재현돼도 “정책 엔진이 임시 컨테이너를 표현할 수 없다”고 쓰지 않는다. 원인 분리 수정 뒤 거부되면 엔진 능력의 문제가 아니라 공개 정책을 실제 API 요청에 연결하는 과정의 문제다.

## 주장할 수 없는 것

이 실험은 실제 privileged 컨테이너 실행, 컨테이너 탈출, 노드 장악을 수행하거나 입증하지 않는다. dry-run admission 판정으로 정책 보장이 유지되는지만 확인한다. 공격 가능성은 `pods/ephemeralcontainers` RBAC 권한, 별도 PSA 존재, 대상 Pod와 노드 구성에 따라 달라진다.

## 안전성

모든 클러스터는 로컬 일회용 kind 환경을 사용한다. 위반 요청에는 `pause` 이미지만 사용하고 모두 dry-run으로 보낸다. 기준 Pod 외에는 객체를 저장하지 않으며 컨테이너 내부 명령, hostPath, host namespace, 노드 셸을 사용하지 않는다.

## 공식 기준과 소스 근거

- [Kubernetes 동적 Admission 문서](https://kubernetes.io/docs/reference/access-authn-authz/extensible-admission-controllers/): 웹훅 리소스 규칙과 dry-run 동작의 기준
- [Kubernetes Ephemeral Containers API](https://kubernetes.io/docs/reference/generated/kubernetes-api/v1.35/#replace-pod-ephemeralcontainers-v1-core): `pods/ephemeralcontainers` 교체 API와 `dryRun` 매개변수
- [Kubernetes Pod Security Standards](https://kubernetes.io/docs/concepts/security/pod-security-standards/): privileged, privilege escalation, capability 제한이 임시 컨테이너에도 적용된다는 보안 기대값
- [Kyverno 1.19.1 차트의 privileged CEL 정책](https://github.com/kyverno/kyverno/blob/40ec788d48bb28d83dbf85538e962a59db9d45c6/charts/kyverno-policies/templates/baseline/disallow-privileged-containers.cel.yaml#L24-L40): 표현식은 임시 컨테이너를 읽지만 리소스 규칙은 pods만 지정
- [Gatekeeper library privileged 정책](https://github.com/open-policy-agent/gatekeeper-library/blob/22a40962f83268769bcec5dfe55e44b5a85c392a/src/pod-security-policy/privileged-containers/src.cel#L1-L32): 임시 컨테이너를 수집한 뒤 UPDATE를 허용하는 조건
- [Kubewarden recommended privileged 정책](https://github.com/kubewarden/adm-controller/blob/23657f51d11fbc75ecd94f69c32a89ee5901cfcf/charts/admission-controller/templates/defaults/policies/_pod-privileged.tpl#L12-L34): pods CREATE만 등록한 공개 차트 규칙
