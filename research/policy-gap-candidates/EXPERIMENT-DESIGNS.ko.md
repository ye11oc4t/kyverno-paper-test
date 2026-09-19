# 후보별 실험 설계

이 문서는 실행 계획만 정의한다. 현재 결과는 없으며, 아래의 “예상”은 소스 코드에서 도출한 가설이다.

## 공통 원칙

각 도구는 새 kind 클러스터에서 따로 설치한다. 같은 클러스터에 여러 정책 도구를 넣으면 한 도구의 거부가 다른 도구의 미탐을 가리기 때문이다. 버전은 `source-lock.json`에 고정한다. Kubernetes 내장 Pod Security Admission은 제품 실험 네임스페이스에서는 끄고, 별도 기준 클러스터에서만 사용한다.

모든 요청은 먼저 서버 측 dry-run으로 보낸다. dry-run은 API 서버와 admission 웹훅을 통과하지만 객체를 저장하지 않는 기능이다. 따라서 privileged 컨테이너를 실제로 실행하지 않고 허용·거부 판정을 볼 수 있다. 하위 API가 dry-run을 지원하지 않는 조합에서만 별도 로컬 클러스터에 `pause` 이미지를 사용해 저장 요청을 수행하며, 컨테이너 안에서 호스트 조작 명령은 실행하지 않는다.

각 사례에서 HTTP 응답, API 서버 감사 로그, 최종 ValidatingWebhookConfiguration, 정책 도구 로그, 정책 상태, 요청 전후 Pod JSON을 보존한다. 단순히 `kubectl` 종료 코드만 보지 않고 해당 정책 이름이 거부 원인에 나타났는지 확인한다.

## 설계 A: 임시 컨테이너 유효 적용 범위

세 핵심 도구의 API-only 요청, 제품별 설치 조건, 유효성 판정, 원인 분리 절차는 [상세 프로토콜](EPHEMERAL-API-EXPERIMENT.ko.md)에 고정한다.

### 연구 질문

공개 보안 정책이 일반 컨테이너 생성과 기존 Pod의 임시 컨테이너 추가에 같은 보장을 제공하는가. 미탐이 발생한다면 웹훅 등록, UPDATE 분기, 객체 순회 중 어느 층 때문인가.

### 비교 대상

- Kubernetes 내장 Pod Security Admission Restricted: 기준값
- Kyverno 1.19.1 + kyverno-policies 3.9.1 기본 `ValidatingPolicy`
- Gatekeeper 3.23.1 + 최신 gatekeeper-library PSS constraint
- Kubewarden 1.37.2 + recommended privileged/privilege-escalation/capabilities 정책, protect 모드
- Polaris 최신 소스 + 최신 chart, webhook 활성화

### 사례

1. 일반 컨테이너가 안전한 Pod를 만든다.
2. 같은 정책을 명백히 위반하는 일반 privileged Pod 생성 dry-run을 보낸다. 이것이 거부되지 않으면 설치가 잘못된 것이므로 해당 실행을 무효 처리한다.
3. 안전한 임시 컨테이너 추가 dry-run을 보낸다. 이것은 허용되어야 한다.
4. `securityContext.privileged: true`인 임시 컨테이너 추가 dry-run을 `pods/ephemeralcontainers`에 보낸다.
5. `allowPrivilegeEscalation: true`와 위험 capability를 가진 임시 컨테이너를 각각 추가한다.
6. 허용된 경우 웹훅 로그를 확인해 요청 자체가 도착하지 않았는지, 도착했지만 정책이 허용했는지 구분한다.

### 원인 분리 실험

Kyverno는 공개 정책 내용은 그대로 두고 resourceRules에 `pods/ephemeralcontainers`만 추가한다. 이때 거부되면 등록 층 결함이다. Gatekeeper는 웹훅을 그대로 두고 `UPDATE이면 허용` 조건만 제거하거나, `request.subResource == 'ephemeralcontainers'`일 때는 검사하도록 바꾼다. Kubewarden은 먼저 하위 API와 UPDATE만 등록해 privileged 모듈이 거부하는지 본 뒤, privilege-escalation과 capabilities 모듈의 임시 컨테이너 순회도 따로 보완한다. Polaris도 하위 API 등록만 보완한 상태와 실행기 순회까지 보완한 상태를 나눠 비교한다.

### 예상과 반증 조건

소스상 예상은 Kyverno·Kubewarden·Polaris는 기본 등록 단계에서 요청을 받지 않고, Gatekeeper는 요청을 받지만 UPDATE 조건으로 허용하는 것이다. Kubewarden privileged 모듈은 등록만 고치면 거부하지만 다른 일부 모듈은 계속 허용할 것으로 예상한다. Polaris는 등록만 고쳐도 실행기가 임시 컨테이너를 순회하지 않아 계속 허용할 것으로 예상한다.

각 제품의 공개 기본 정책이 사례 4와 5를 정책 고유 메시지로 거부하고 로그가 실제 평가를 증명하면 해당 제품에 대한 가설은 반증된다. 내장 PSA나 다른 웹훅이 대신 거부한 결과는 제품의 성공으로 세지 않는다.

## 설계 B: OCI 이미지 볼륨과 이미지 신뢰 정책

### 연구 질문

승인된 레지스트리만 허용하는 공개 정책이나 이미지 서명 정책이 `spec.volumes[].image.reference`로 가져오는 OCI 객체에도 같은 보장을 적용하는가.

Kubernetes 1.35 클러스터에서 이미지 볼륨과 해당 컨테이너 런타임 지원을 먼저 확인한다. 실행 이미지에는 승인된 레지스트리의 무해한 `pause` 또는 셸 이미지를 사용하고, 이미지 볼륨에는 `marker.txt` 하나만 든 테스트 OCI 아티팩트를 사용한다. 파일을 실행하지 않고 Pod가 허용되는지와 볼륨이 해결되는지만 기록한다.

Kyverno 공개 restrict-image-registries와 ImageValidatingPolicy, Gatekeeper allowedrepos, Kubewarden trusted-repos를 각각 별도 클러스터에서 거부 모드로 설정한다. 일반 컨테이너 이미지가 비승인 레지스트리일 때 거부되는 양성 대조, 컨테이너와 볼륨이 모두 승인된 레지스트리일 때 허용되는 음성 대조, 컨테이너는 승인됐지만 이미지 볼륨만 비승인 레지스트리인 본 사례를 비교한다.

본 사례가 허용되면 정책 로그에서 요청은 평가됐지만 `spec.volumes[].image.reference`가 수집되지 않았는지 확인한다. 그 뒤 각 정책에 이미지 볼륨 reference 한 줄만 추가해 같은 요청이 거부되는지 보는 원인 분리 실험을 설계한다. Kyverno ImageValidatingPolicy는 사용자 정의 imageExtractor를 추가한 상태와 기본 추출기를 비교한다.

클러스터나 런타임이 이미지 볼륨 자체를 거부하면 그 실행은 제품 미탐 근거로 사용하지 않는다. 제품 문서가 정책 범위를 명시적으로 “컨테이너 실행 이미지”로 한정하면 결과를 결함이 아니라 보장 범위 차이로 분류한다.

## 설계 C: PSS 버전·OS·user namespace 드리프트

### 연구 질문

PSS라고 표시한 공개 정책 묶음이 대상 Kubernetes 버전의 내장 Pod Security Admission과 같은 판정을 내리는가.

### 사례

첫째, Kubernetes 1.34 이상에서 probe 또는 lifecycle hook의 `host` 값을 넣은 Pod를 Baseline으로 검사한다. 내장 PSA가 거부하고 제3자 정책이 허용하면 버전 드리프트에 의한 미탐이다.

둘째, `spec.os.name: windows`인 Pod에 Linux 전용 seccomp, capability drop, allowPrivilegeEscalation 필드를 생략한다. Windows 노드가 없어도 서버 측 dry-run으로 admission 판정은 가능하다. 내장 PSS가 허용하고 제3자 정책이 거부하면 오탐이다.

셋째, 지원 버전에서 `hostUsers: false`인 Linux Pod를 만들고 PSS가 완화하는 runAsNonRoot/runAsUser 조건을 생략한다. 내장 PSS와 공개 정책의 판정 차이를 본다.

### 통제

같은 매니페스트를 PSS 버전 라벨을 고정한 내장 PSA, Kyverno PSS 차트, Gatekeeper PSS bundle에 보낸다. 제품이 PSS 호환을 주장하지 않는 Kubewarden 개별 PSP 대체 정책과 Polaris는 별도 “유사 보안 정책” 군으로 표시해 과도한 비교를 피한다.

## 설계 D: 감사 결과의 의미 보존

### 연구 질문

입장 시점에는 userInfo·operation·oldObject가 필요한 정책을 사후 감사가 pass, fail, unknown 중 무엇으로 표시하는가.

### 사례

1. 특정 사용자만 라벨을 설정할 수 있는 정책을 만든다.
2. admission 요청에서는 허용 사용자와 거부 사용자를 각각 보내 기준 판정을 얻는다.
3. 같은 최종 객체를 저장한 뒤 Gatekeeper와 Kubewarden 감사를 실행한다.
4. 사용자 정보가 없는 상태에서 pass 또는 fail로 단정하는지, 정책을 건너뛰는지, unknown/error로 표시하는지 기록한다.
5. CREATE 전용, UPDATE 전용, oldObject 차이에 의존하는 정책도 반복한다.

감사 결과가 입장 판정과 다르다는 사실만으로 버그라고 하지 않는다. 제품이 결과를 “검사 불가”로 명확히 표시하지 않고 준수 통계에 pass로 합산할 때 사용자 영향이 있는 것으로 판정한다.

## 설계 E: Pod resize 하위 API

### 연구 질문

CPU·메모리 최대값 또는 limit 필수 정책이 Pod 생성 뒤 `pods/resize` 변경에도 유지되는가.

안전한 범위의 요청과 제한으로 Pod를 만든 뒤, 서버 측 dry-run으로 조직 최대값을 넘는 CPU·메모리 값을 resize 하위 API에 보낸다. 일반 Pod 생성에서 같은 값이 거부되는지 양성 대조를 둔다. 웹훅 등록 목록, 호출 로그, 정책 결과를 함께 확인한다. 기능 게이트가 필요한 Kubernetes 버전에서는 실험 환경과 게이트 상태를 결과에 명시한다.

## 설계 F: Gatekeeper CONNECT 경로

### 연구 질문

기본 웹훅 목록에 적힌 `pods/exec`, `pods/attach`, `pods/portforward` 요청이 실제로 Gatekeeper에 도달하는가.

실제 셸 명령을 실행할 필요는 없다. CONNECT를 거부하는 식별 가능한 constraint를 만들고, 빈 명령 또는 즉시 종료 명령의 exec 요청을 보낸다. 기본 operations가 CREATE·UPDATE일 때와 CONNECT를 추가했을 때를 비교한다. 기본 상태에서 로그가 없고 CONNECT 추가 뒤 정책 고유 메시지로 거부되면 등록 불일치를 확인한 것이다.

## 설계 G: 정책 활성화 간격

무해한 ConfigMap만 사용한다. 정책 객체 생성 성공 시점부터 고유 위반 ConfigMap이 처음 거부되는 시점까지를 측정한다. 정책 상태가 Ready가 된 뒤 거부되는 대조 요청을 반드시 둔다. 즉시 요청이 허용되고 준비 후 요청이 거부된 라운드만 활성화 간격으로 센다. 자세한 판정 규칙은 `experiments/policy-activation-gap/PROTOCOL.ko.md`에 있다.

## 설계 H: 정책 엔진 네임스페이스와 커스텀 컨트롤러

엔진 네임스페이스 후보는 같은 안전한 위반 ConfigMap을 일반 네임스페이스와 엔진 네임스페이스에 dry-run으로 보내 기본 제외 범위를 확인한다. 결함 판정은 일반 사용자가 해당 네임스페이스에 쓰기 권한을 얻을 현실적인 RBAC 구성과 제품 문서의 경고 수준까지 포함한다.

컨트롤러 신원 후보는 direct Pod, Deployment가 만든 Pod, 간단한 테스트 CRD 컨트롤러가 만든 Pod를 비교한다. userInfo 기반 정책과 최종 Pod 필드 기반 정책을 분리해 원래 사용자 신원과 최종 객체 상태 중 무엇이 사라지는지 본다. 이 설계는 별도 컨트롤러 구현이 필요하므로 상위 후보 검증 뒤에 수행한다.

## 설계 I: 네이티브 사이드카의 자원 제한

### 연구 질문

`initContainers` 안에 있지만 Pod 수명 내내 실행되는 `restartPolicy: Always` 사이드카를 자원 request·limit 정책이 일반 실행 컨테이너처럼 검사하는가.

Kubernetes 1.33 이상에서 같은 이미지와 명령을 사용하는 두 Pod를 만든다. 첫 Pod는 자원 필드가 없는 컨테이너를 `containers`에 두고, 둘째 Pod는 같은 컨테이너를 `initContainers`에 두면서 `restartPolicy: Always`로 설정한다. 실제 부하를 만들지 않는 `pause` 계열 이미지를 사용하고 서버 측 dry-run 판정만 비교한다.

Polaris에서는 네 가지 기본 자원 검사의 결과와 webhook 판정을 기록한다. Kubewarden에서는 container-resources 정책을 `ignoreValues: true`처럼 필드 존재를 요구하는 설정으로 두고 판정한다. 일반 컨테이너는 실패하지만 네이티브 사이드카는 통과하면 배열 제외에 의한 미탐이다. 정책 순회에 initContainers만 추가한 뒤 같은 요청이 거부되는지 확인하는 수정 대조를 설계한다.

일반적인 일회성 init container도 함께 보내 네이티브 사이드카만 특별 취급해야 하는지, 모든 init container에 자원 정책을 적용해야 하는지 결과를 분리한다. 제품 문서가 init container를 의도적으로 제외했다고 명확히 밝히면 기술적 미탐과 문서화된 범위 한계를 나눠 보고한다.

## 설계 J: Pod 전체 자원 예산

Kubernetes 1.35에서 `spec.resources`에 충분한 CPU·메모리 request와 limit을 지정하고 개별 컨테이너의 resources는 비운 Pod를 만든다. 같은 총량을 개별 컨테이너에 적은 Pod, Pod 전체와 컨테이너 어디에도 값을 적지 않은 Pod를 대조한다. Kyverno, Gatekeeper, Kubewarden, Polaris가 세 사례를 어떻게 판정하는지 기록하되, 조직 정책 목표가 Pod 전체 상한인지 컨테이너별 회계인지 두 가지 기대값을 따로 둔다. 제품이 선언한 정책 의미와 충돌할 때만 오탐으로 센다.

## 설계 K: Static Pod의 정책 경계

일반 애플리케이션 노드와 격리된 일회용 테스트 노드에서만 수행하도록 설계한다. 같은 무해한 위반 Pod를 먼저 API 서버에 제출해 대상 정책이 거부하는지 확인한 뒤, kubelet의 staticPodPath에 같은 매니페스트를 둔다. 실행 중인 원본 컨테이너와 API 서버의 mirror Pod 상태를 별도로 기록한다. mirror Pod 등록이 admission에서 거부되어도 원본 Static Pod가 노드에서 실행되는지를 확인하는 경계 실험이며, 결과는 제품 취약점이 아니라 API 서버 admission의 적용 범위로 분류한다.

## 실행 순서 제안

1. 설계 A의 Kyverno와 Gatekeeper만 먼저 실행해 가장 강한 두 소스 예측을 검증한다.
2. 같은 설계를 Kubewarden과 Polaris로 확장해 세 층의 원인을 완성한다.
3. 설계 B로 새 이미지 입력 경로의 공통 미탐을 평가한다.
4. 설계 C로 PSS 미탐과 오탐을 함께 평가한다.
5. 설계 D, E, F, I를 수행한다.
6. 설계 G, H, J, K는 의미 범위나 운영 전제가 큰 후보이므로 마지막에 수행한다.

첫 두 제품에서 1순위 가설이 모두 반증되면 논문 중심 후보를 설계 B로 바꾼다. 한 제품에서만 재현되면 “모든 도구의 공통 결함”이라고 쓰지 않고, 여러 제품에서 반복되는 평가 방법의 맹점과 제품별 원인을 구분한다.
