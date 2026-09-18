# Kubernetes 정책 도구 미탐·오탐 후보 조사

## 결론부터

지금 가장 문제가 큰 후보는 **정책식이 검사한다고 적혀 있어도 실제 Kubernetes 요청이 그 정책식까지 도달하지 않는 문제**다. 특히 이미 실행 중인 Pod에 임시 컨테이너를 추가하는 `pods/ephemeralcontainers` 하위 API에서 Kyverno, Gatekeeper, Kubewarden, Polaris가 서로 다른 이유로 같은 미탐을 만들 가능성이 소스에서 확인됐다.

여기서 하위 API 또는 서브리소스(subresource)는 이미 존재하는 객체의 일부만 바꾸는 별도 API 주소다. 임시 컨테이너는 일반적인 Pod 수정이 아니라 `pods/ephemeralcontainers`라는 주소로 추가된다. Kubernetes 웹훅 규칙에서 `pods`라고만 쓰면 이 주소까지 자동으로 포함되지 않는다. Kubernetes 공식 문서도 `*`는 하위 API를 포함하지 않고, `pods/*` 또는 `pods/ephemeralcontainers`를 별도로 써야 한다고 명시한다.

이 후보가 중요한 이유는 임시 컨테이너가 단순한 관찰 도구로 제한되지 않기 때문이다. `kubectl debug --profile=sysadmin`은 `privileged: true`인 임시 컨테이너를 만들 수 있다. `privileged`는 컨테이너 격리를 크게 풀어 주는 설정이다. 따라서 임시 컨테이너를 추가할 RBAC 권한을 가진 사용자나 탈취된 계정이 정책 검사를 우회하면, 기존 Pod 안에서 강한 권한을 가진 이미지를 실행할 수 있다. 모든 사용자가 자동으로 공격 가능한 것은 아니고, `pods/ephemeralcontainers` 갱신 권한이 있어야 한다. Kubernetes 내장 Pod Security Admission이 따로 활성화되어 있으면 이 미탐을 막을 수도 있다.

앞선 실험이 모두 기대값과 일치한 이유도 설명된다. 앞선 실험은 임시 컨테이너 하위 API까지 정확히 등록한 맞춤 정책으로 엔진의 표현 능력을 검사했다. 이번 소스 검토는 사용자가 실제로 설치하는 공개 정책과 기본 Helm 설정이 그 요청을 정책 엔진까지 전달하는지를 본다. 엔진이 검사할 수 있다는 사실과 배포된 정책이 실제 요청을 검사한다는 사실은 다르다.

## 1순위: 임시 컨테이너의 유효 적용 범위 불일치

이 문제는 세 층에서 발생한다. 첫째는 웹훅 등록 층이다. Kubernetes API 서버가 어떤 요청을 정책 도구로 보낼지 정하는 목록에서 하위 API가 빠진다. 둘째는 연산 분기 층이다. 요청이 도착해도 `UPDATE이면 검사 생략` 같은 조건이 실행된다. 셋째는 객체 순회 층이다. 정책 코드가 일반 컨테이너와 초기화 컨테이너만 훑고 임시 컨테이너 배열은 읽지 않는다. 공개 정책의 단위 테스트가 완성된 Pod JSON을 함수에 직접 넣는 방식이면 첫째와 둘째 층의 결함을 놓치기 쉽다.

### Kyverno

Kyverno 1.19.1의 `kyverno-policies` 차트 3.9.1은 기본 정책 형식을 CEL 기반 `ValidatingPolicy`로 바꿨다. 기본 PSS 정책의 검사식은 `spec.ephemeralContainers`까지 확인하지만, 매칭 대상은 `resources: [pods]`뿐이다. 일반 `ValidatingPolicy`의 자동 생성 코드는 이 한 개의 `pods` 규칙을 Deployment 같은 Pod 컨트롤러 규칙으로 바꿀 뿐, Pod 하위 API를 추가하지 않는다. 같은 Kyverno 소스의 회귀 테스트 주석도 CEL 정책에서 `pods`만 쓰면 `pods/ephemeralcontainers` 요청에 웹훅이 호출되지 않으며 명시적으로 하위 API를 넣어야 한다고 설명한다. 차트의 CEL 정책 17개 중 하위 API를 등록한 파일은 0개였고, 임시 컨테이너 필드를 읽는 차트 파일은 27개였다. 즉 검사식과 호출 범위가 서로 어긋난다.

- [차트 기본값: ValidatingPolicy](https://github.com/kyverno/kyverno/blob/40ec788d48bb28d83dbf85538e962a59db9d45c6/charts/kyverno-policies/values.yaml#L1-L16)
- [privileged 검사식은 임시 컨테이너를 읽지만 매칭은 pods뿐](https://github.com/kyverno/kyverno/blob/40ec788d48bb28d83dbf85538e962a59db9d45c6/charts/kyverno-policies/templates/baseline/disallow-privileged-containers.cel.yaml#L24-L40)
- [일반 ValidatingPolicy 자동 생성은 Pod 컨트롤러 규칙만 만듦](https://github.com/kyverno/kyverno/blob/40ec788d48bb28d83dbf85538e962a59db9d45c6/pkg/cel/policies/vpol/autogen/autogen.go#L19-L50)
- [자동 생성 대상은 정확히 resources: pods인 정책으로 한정됨](https://github.com/kyverno/kyverno/blob/40ec788d48bb28d83dbf85538e962a59db9d45c6/pkg/cel/autogen/support.go#L7-L41)
- [pods만으로 하위 API가 호출되지 않는다는 소스 주석과 테스트](https://github.com/kyverno/kyverno/blob/40ec788d48bb28d83dbf85538e962a59db9d45c6/pkg/controllers/webhook/validating_test.go#L800-L814)
- [전용 block-ephemeral 정책은 두 리소스를 명시하므로 필요한 설정을 프로젝트도 알고 있음](https://github.com/kyverno/policies/blob/2716f4a26a3c27590a1d6d960dee4ce043e4fa4a/other-vpol/block-ephemeral-containers/block-ephemeral-containers.yaml#L11-L20)

예상 미탐은 최신 차트 기본값을 사용하고, PSS 정책을 실제 거부 모드로 설정했으며, 별도 내장 PSA가 없는 경우다. 일반 privileged Pod는 거부하지만 기존 안전한 Pod에 privileged 임시 컨테이너를 추가하는 요청은 Kyverno 웹훅에 도달하지 않을 것으로 예상한다. 이 결과는 아직 클러스터에서 실행해 확인하지 않았다.

### Gatekeeper

Gatekeeper 3.23.1 기본 웹훅은 `pods/ephemeralcontainers`와 `UPDATE`를 등록하므로 요청 자체는 받는다. 문제는 최신 Gatekeeper 정책 라이브러리의 여러 PSS 정책이 Pod 보안 필드가 불변이라는 가정으로 모든 `UPDATE` 요청을 허용한다는 점이다. 예를 들어 privileged 정책은 임시 컨테이너 배열을 정확히 읽은 다음에도 `isUpdate || 위반 없음`으로 판정한다. 임시 컨테이너 추가는 바로 `UPDATE` 요청이므로 위반 목록이 있어도 참이 된다. privilege escalation과 capability 정책도 같은 구조다.

- [Gatekeeper 기본 웹훅의 ephemeralcontainers 등록](https://github.com/open-policy-agent/gatekeeper/blob/2d0b6ad97cf3a8b8436a00a1f4b07b3a56b92ca0/config/webhook/manifests.yaml#L57-L93)
- [privileged 정책: 임시 컨테이너를 찾고도 UPDATE면 허용](https://github.com/open-policy-agent/gatekeeper-library/blob/22a40962f83268769bcec5dfe55e44b5a85c392a/src/pod-security-policy/privileged-containers/src.cel#L1-L32)
- [privilege escalation 정책의 UPDATE 우회](https://github.com/open-policy-agent/gatekeeper-library/blob/22a40962f83268769bcec5dfe55e44b5a85c392a/src/pod-security-policy/allow-privilege-escalation/src.cel#L1-L33)
- [capability 정책의 UPDATE 우회](https://github.com/open-policy-agent/gatekeeper-library/blob/22a40962f83268769bcec5dfe55e44b5a85c392a/src/pod-security-policy/capabilities/src.cel#L1-L58)

이 패턴은 privileged, privilege escalation, capabilities, proc mount, read-only root filesystem, HostProcess 등 임시 컨테이너에 의미가 있는 여러 정책에 반복된다. 오래된 일반 Pod 필드가 수정되지 않는다는 가정은 맞지만, 새 하위 API가 같은 `UPDATE` 연산 이름을 사용하면서 가정이 깨졌다.

### Kubewarden

Kubewarden 1.37.2의 선택 설치형 recommended policy에서 privileged 정책 모듈 자체는 임시 컨테이너를 검사한다. 그러나 차트가 만드는 정책 규칙은 `pods`의 `CREATE`만 등록하고, 주석에는 실행 중인 Pod에 privileged 컨테이너를 추가할 수 없다고 적혀 있다. Kubernetes는 임시 컨테이너 하위 API로 바로 그 동작을 허용한다. 따라서 모듈의 올바른 검사 코드까지 요청이 도달하지 않는다.

- [recommended privileged 정책의 CREATE-only 규칙과 잘못된 불변 가정](https://github.com/kubewarden/kubewarden-controller/blob/23657f51d11fbc75ecd94f69c32a89ee5901cfcf/charts/admission-controller/templates/defaults/policies/_pod-privileged.tpl#L12-L34)
- [정책 모듈은 임시 컨테이너의 privileged 값을 검사함](https://github.com/kubewarden/policies/blob/fd4c5c98fa765d5ad3db1a89a7bc027ea0bc89ff/policies/pod-privileged-policy/src/lib.rs#L56-L90)

추가로 allow-privilege-escalation과 capabilities 모듈은 일반 컨테이너와 초기화 컨테이너만 순회한다. 라우팅 규칙을 보완해도 이 두 모듈은 임시 컨테이너를 놓칠 것으로 예상한다. 소스 전체 검색에서 init container를 다루는 정책 중 allow-privilege-escalation, capabilities, host-namespaces, read-only-root-filesystem, user-group 정책에는 임시 컨테이너 처리가 없었다.

### Polaris

Polaris 최신 차트의 기본 웹훅은 `pods`의 CREATE와 UPDATE만 등록하고 하위 API를 등록하지 않는다. 설령 사용자가 규칙을 수동 추가하더라도 내장 검사 실행기는 `InitContainers`와 `Containers`만 반복하며 `EphemeralContainers`를 반복하지 않는다. 따라서 privileged, privilege escalation, capability, root 사용자, 읽기 전용 루트 파일시스템 등 컨테이너 대상 내장 검사가 모두 임시 컨테이너를 놓칠 가능성이 높다.

- [Polaris 차트의 pods-only 기본 규칙](https://github.com/FairwindsOps/charts/blob/db94aff3c6d0f0ce0ed6f80f56f3b0b5135f819c/stable/polaris/values.yaml#L190-L228)
- [내장 검사 실행기가 initContainers와 containers만 순회](https://github.com/FairwindsOps/polaris/blob/c84bb2ea3674ee7ec044584db8c9cc9e8d17bdd0/pkg/validator/schema.go#L241-L274)

### 왜 이 후보가 가장 강한가

첫째, 일시적인 경쟁 상태가 아니라 설정을 바꾸기 전까지 계속 남는 미탐이다. 둘째, 네 제품에서 같은 최종 결과가 서로 다른 코드 원인으로 나타나므로 특정 구현의 사소한 버그보다 일반화하기 좋다. 셋째, Kubernetes PSS가 명시적으로 임시 컨테이너의 privileged, capability, seccomp 같은 필드를 제한하며, 공식 `kubectl debug`가 privileged 임시 컨테이너를 실제로 만들 수 있어 사용자 피해 경로가 구체적이다. 넷째, 기존 실험처럼 정책식만 검사하면 모두 정상으로 보일 수 있어 평가 방법 자체의 결함도 보여 준다.

논문 질문은 “정책 언어가 임시 컨테이너를 표현할 수 있는가”가 아니라 “공개 정책을 설치했을 때 Kubernetes의 실제 API 요청 경로 전체에서 동일한 보장이 유지되는가”가 되어야 한다.

## 다른 주요 후보

### 2순위: OCI 이미지 볼륨이 이미지 신뢰 정책 밖에 놓이는 문제

Kubernetes 1.35에서 기본 활성화된 이미지 볼륨(image volume)은 컨테이너 이미지나 OCI 아티팩트의 파일을 Pod 안에 읽기 전용 디렉터리로 붙이는 기능이다. 예를 들어 실행 이미지는 허용된 사내 레지스트리에서 가져오면서, `spec.volumes[].image.reference`에는 외부 레지스트리를 적을 수 있다. 실행 이미지 허용 목록만 보면 안전한 Pod처럼 보이지만 실제 Pod는 외부 OCI 내용도 내려받는다. 허용된 기본 이미지에 셸이나 언어 실행기가 있으면 이 볼륨의 스크립트·라이브러리·설정을 읽거나 불러올 수 있으므로, “승인된 레지스트리의 내용만 사용한다”는 공급망 보장이 약해진다.

Kyverno 공개 `restrict-image-registries` 정책은 일반·초기화·임시 컨테이너의 `image`만 합친다. Kyverno의 새 ImageValidatingPolicy 기본 이미지 추출기도 같은 세 배열만 제공한다. Gatekeeper의 allowedrepos와 Kubewarden의 trusted-repos도 정확히 같은 세 배열만 순회한다. 어느 코드도 `spec.volumes[].image.reference`를 읽지 않는다. 세 도구에서 같은 객체 순회 미탐이 예상된다.

- [Kubernetes 1.35 이미지 볼륨: OCI 객체를 가져오며 컨테이너 image처럼 동작](https://v1-35.docs.kubernetes.io/docs/concepts/storage/volumes/#image)
- [Kyverno 공개 레지스트리 정책은 세 컨테이너 배열만 검사](https://github.com/kyverno/policies/blob/2716f4a26a3c27590a1d6d960dee4ce043e4fa4a/best-practices-vpol/restrict-image-registries/restrict-image-registries.yaml#L23-L34)
- [Kyverno ImageValidatingPolicy 기본 추출기도 세 배열만 제공](https://github.com/kyverno/kyverno/blob/40ec788d48bb28d83dbf85538e962a59db9d45c6/pkg/cel/compiler/images.go#L14-L24)
- [Gatekeeper allowedrepos도 일반·초기화·임시 컨테이너만 검사](https://github.com/open-policy-agent/gatekeeper-library/blob/22a40962f83268769bcec5dfe55e44b5a85c392a/src/general/allowedrepos/src.rego#L1-L18)
- [Kubewarden trusted-repos의 이미지 발견 함수도 세 배열만 검사](https://github.com/kubewarden/policies/blob/fd4c5c98fa765d5ad3db1a89a7bc027ea0bc89ff/policies/trusted-repos-policy/src/validation.rs#L54-L88)

이 후보는 임시 컨테이너보다 공격 전제는 넓다. 별도 디버그 권한 없이 Pod 생성 권한만 있으면 된다. 반면 외부 내용을 실제 코드나 설정으로 사용해야 피해가 생기므로 영향 경로가 한 단계 더 필요하고, 컨테이너 런타임의 이미지 볼륨 지원도 필요하다. 따라서 현재는 2순위다. 이미지 볼륨을 명시적으로 정책 범위에서 제외한다고 문서화한 제품은 결함보다 보장 범위의 한계로 분류해야 한다.

### 3순위: PSS 버전과 실행 환경 의미의 드리프트

PSS는 고정된 한 벌의 규칙이 아니라 Kubernetes 버전에 따라 바뀐다. Kubernetes 1.34부터 probe와 lifecycle hook의 `host` 필드를 막는 Baseline 규칙이 추가됐다. 현재 Kyverno PSS 차트에는 해당 정책이 없다. 차트는 자신을 “Kubernetes Pod Security Standards implemented as Kyverno policies”라고 설명하고 Kubernetes 최소 버전만 `>=1.25`로 두므로, 1.34 이상 사용자가 현재 Baseline과 동일하다고 이해하면 지속적인 미탐이 된다. Gatekeeper 최신 라이브러리는 이 항목을 이미 포함한다.

반대 방향의 오탐도 있다. Kubernetes 1.25 이상 PSS Restricted는 Windows Pod에서 Linux 전용인 privilege escalation, seccomp, Linux capability 조건을 완화한다. Kyverno 차트와 Gatekeeper PSS 묶음의 해당 정책에는 `spec.os.name == windows` 예외가 보이지 않았다. Polaris의 같은 내장 검사도 Pod OS를 보지 않는다. 따라서 표준상 허용되는 Windows 워크로드를 차단하거나 위험으로 표시할 수 있다.

Kubernetes의 user namespace는 컨테이너 안의 root를 호스트의 root와 다른 ID로 매핑하는 격리 기능이다. `hostUsers: false`인 Pod에서는 PSS가 일부 runAsNonRoot/runAsUser 검사를 완화한다. Kyverno 차트, Gatekeeper 정책 로직, Polaris, Kubewarden 개별 정책에서 이 의미를 반영한 코드는 확인되지 않았다. 이 역시 최신 표준을 기대하는 사용자에게 오탐을 만들 수 있다.

이 후보는 보안 미탐과 가용성 오탐을 동시에 설명하지만, 모든 도구가 PSS 완전 호환을 동일한 강도로 약속하지는 않는다. 따라서 제품 간 결함이라고 단정하기보다 “버전 없는 표준 재구현의 구조적 드리프트”로 다뤄야 한다.

### 4순위: 사후 감사가 실제 입장 요청을 재현하지 못하면서 통과로 표시하는 문제

감사(audit)는 이미 저장된 객체를 나중에 다시 검사하는 기능이다. 저장된 객체에는 누가 요청했는지, CREATE인지 UPDATE인지, 변경 전 객체가 무엇인지가 남지 않는다. Gatekeeper 감사 코드는 저장 객체로 요청 비슷한 구조를 만들지만 operation, userInfo, oldObject를 채우지 않는다. 문서도 이 필드에 의존하는 정책은 감사할 수 없다고 명시한다.

Kubewarden 감사 스캐너는 더 적극적으로 가짜 요청을 만든다. 모든 객체의 연산을 CREATE로 놓고 userInfo와 oldObject를 비우며, GVR의 resource 자리에는 복수형 API 이름 대신 Kind 문자열을 넣는다. 정책 응답이 allowed이면 보고서 상태를 `pass`로 기록한다. 실제 입장 요청에서만 존재하는 정보가 필요한 정책이라면 “검사 불가”가 맞는데 “통과”로 보일 수 있다. 또한 wildcard 규칙과 CREATE가 없는 정책은 감사 대상에서 조용히 빠진다.

Kyverno의 기존 ClusterPolicy는 background 모드에서 userInfo 같은 변수를 금지해 이 문제를 일부 예방한다. 새 CEL 정책 유형에서도 같은 안전장치가 완전한지는 별도 검토가 필요하다. 이 후보의 핵심은 감사 결과에 `unknown/not auditable` 상태가 필요하다는 점이다.

### 5순위: `pods/resize`를 통한 자원 제한 정책 우회

`pods/resize`는 실행 중인 컨테이너의 CPU와 메모리 요청·제한을 바꾸는 하위 API다. Kyverno 소스의 resize 정책 예제도 이 API를 명시적으로 등록한다. Kubewarden container-resources 정책 메타데이터와 Polaris 기본 웹훅은 `pods`만 등록하며 `pods/resize`를 넣지 않는다. Kyverno CEL 정책도 일반적으로 하위 API를 자동 확장하지 않는다. Gatekeeper 기본 웹훅은 현재 `pods/resize`를 명시해 이 후보에서는 상대적으로 안전하다.

영향은 보안보다 비용·성능·서비스 안정성에 가깝다. 처음에는 제한을 만족한 Pod가 나중에 과도한 CPU·메모리 제한으로 바뀌거나, 조직이 정한 최대값 검사를 피할 수 있다. 기능 게이트와 Kubernetes 버전에 따라 재현 조건이 달라지므로 임시 컨테이너 후보보다 우선순위는 낮다.

### 6순위: Gatekeeper의 CONNECT 하위 API가 목록에는 있지만 동작에는 없는 문제

Gatekeeper 기본 웹훅은 `pods/exec`, `pods/attach`, `pods/portforward`를 resources 목록에 넣지만 operations는 CREATE와 UPDATE뿐이다. 이 API들은 CONNECT 연산을 사용하므로 기본 설정에서는 웹훅이 호출되지 않는다. 문서는 CONNECT를 별도로 활성화하라고 설명하지만, 매니페스트만 보면 보호하는 것처럼 오해하기 쉽다. 사용자 세션을 제한하려는 정책이 조용히 실행되지 않는 미탐 후보다.

### 7순위: 네이티브 사이드카가 자원 정책의 init container 예외에 숨는 문제

Kubernetes 네이티브 사이드카는 `containers`가 아니라 `initContainers` 배열에 들어가고 `restartPolicy: Always`를 사용한다. 이름은 초기화 컨테이너지만 시작 뒤 종료되지 않고 Pod 수명 내내 일반 컨테이너와 함께 실행된다. 이 기능은 Kubernetes 1.33부터 안정 기능이다.

Polaris의 CPU·메모리 request/limit 검사는 설정에서 `initContainer`를 명시적으로 제외한다. Kubewarden container-resources 정책의 `validatePodSpec` 함수도 `pod.Containers`만 순회하고 `InitContainers`를 읽지 않는다. 따라서 자원 request와 limit이 없는 장기 실행 사이드카가 두 도구에서 정상으로 보일 가능성이 있다. 일반 컨테이너에는 자원 제한이 있는데 같은 일을 하는 네이티브 사이드카에는 없어도 통과한다면 비용·노드 안정성 관점의 미탐이다.

- [Kubernetes 네이티브 사이드카는 initContainers 안에서 Pod 수명 내내 실행됨](https://kubernetes.io/docs/concepts/workloads/pods/sidecar-containers/)
- [Polaris CPU request 검사는 initContainer를 제외](https://github.com/FairwindsOps/polaris/blob/c84bb2ea3674ee7ec044584db8c9cc9e8d17bdd0/pkg/config/checks/cpuRequestsMissing.yaml#L1-L27)
- [Polaris memory limit 검사도 initContainer를 제외](https://github.com/FairwindsOps/polaris/blob/c84bb2ea3674ee7ec044584db8c9cc9e8d17bdd0/pkg/config/checks/memoryLimitsMissing.yaml#L1-L27)
- [Kubewarden 자원 정책은 regular containers만 순회](https://github.com/kubewarden/policies/blob/fd4c5c98fa765d5ad3db1a89a7bc027ea0bc89ff/policies/container-resources-policy/validate.go#L407-L423)

### 8순위: 정책 생성 성공과 실제 활성화 사이의 간격

Kyverno, Gatekeeper, Kubewarden은 정책 객체를 저장한 뒤 별도 컨트롤러가 컴파일·캐시 적재·웹훅 갱신을 수행한다. 정책 생성 API가 성공한 직후 워크로드를 연속 적용하면 준비 전 요청이 통과할 가능성이 있다. 다만 각 제품이 준비 상태를 제공하며 간격은 일시적이다. 지속적이고 기본 구성에서 발생하는 1순위 후보보다 사용자 영향과 논문 기여도가 낮다.

### 9순위: 정책 엔진 네임스페이스의 기본 제외

Kyverno와 Kubewarden은 교착 상태를 피하려고 자신의 설치 네임스페이스를 기본 웹훅 대상에서 제외한다. Gatekeeper도 시스템 네임스페이스 제외 구성을 사용한다. 해당 네임스페이스에 일반 워크로드를 만들 권한이 있으면 그곳이 정책 신뢰 구역이 된다. 의도된 안전장치이고 문서화된 설정이므로 제품 결함보다는 운영 위협 모델 후보에 가깝다.

### 10순위: 컨트롤러가 만든 Pod에서 원래 사용자 신원 소실

사용자가 Deployment나 커스텀 리소스를 만들면 실제 Pod 생성자는 사용자가 아니라 컨트롤러 ServiceAccount가 된다. Pod 정책이 request.userInfo만 보면 원래 사용자를 알 수 없다. 기본 Deployment는 자동 생성 규칙으로 보완할 수 있지만, 임의의 Operator나 CRD가 만드는 Pod는 부모 객체 구조를 도구가 모르면 빠진다. 사용자 기반 정책은 부모를 검사하면 Pod 최종 상태를 모르고, 자식 Pod를 검사하면 원래 사용자를 모르는 구조적 딜레마다.

### 11순위: Polaris의 소유자 객체 신뢰와 미지원 컨트롤러

Polaris 웹훅은 ownerReference가 있는 객체의 소유자와 자식이 일치한다고 판단하면 자식 검사를 건너뛴다. 또한 문서는 알려진 컨트롤러 유형만 기본 지원한다고 밝힌다. 웹훅이 임시 컨테이너 하위 API를 받도록 수정했을 때도 이 소유자 단축 경로가 자식 Pod의 새 필드를 숨기는지 확인할 필요가 있다. 현재는 정적 소스만으로 최종 판정을 내리지 않았다.

### 12순위: 오류와 미지원 대상을 준수로 오해하는 출력

Gatekeeper 감사 루프는 객체 평가 오류를 로그에 남기고 다음 객체로 넘어간다. Kubewarden은 건너뛴 정책과 오류 정책 개수를 따로 관리하지만 개별 객체의 의미를 사용자가 쉽게 구분하지 못할 수 있다. Polaris는 지원하지 않는 입력이나 결과가 없는 객체에서 빈 결과와 높은 점수처럼 보일 가능성이 있다. 도구마다 UI와 보고서 형식이 달라 실제 오인 가능성을 실험해야 한다.

### 13순위: Pod 전체 자원 예산과 컨테이너별 정책의 의미 충돌

Kubernetes 1.35부터 `spec.resources`에 CPU·메모리 request와 limit을 Pod 전체 예산으로 줄 수 있다. 개별 컨테이너에 같은 값을 반복하지 않아도 Pod 수준 경계 안에서 자원을 공유할 수 있다. 반면 Kyverno의 공개 require-requests-limits, Gatekeeper의 container resource 정책, Kubewarden container-resources, Polaris의 기본 검사는 개별 컨테이너 필드만 판정한다. Pod 전체에 명확한 상한이 있어도 “컨테이너 limit 없음”으로 거부하거나 경고할 수 있다.

다만 이 정책들은 개별 컨테이너 값을 요구한다고 설명하는 경우가 많다. 그래서 현재는 제품 오탐으로 단정하지 않고, 사용자가 “Pod의 자원 경계가 있는가”를 원했는지 “컨테이너별 회계가 필요한가”를 구분하지 않은 정책 이름과 문서의 의미 충돌 후보로 둔다.

- [Kubernetes Pod-level resources](https://kubernetes.io/docs/concepts/configuration/manage-resources-containers/#pod-level-resource-specification)
- [Kyverno 공개 정책은 각 컨테이너의 resources만 확인](https://github.com/kyverno/policies/blob/2716f4a26a3c27590a1d6d960dee4ce043e4fa4a/best-practices-vpol/require-pod-requests-limits/require-pod-requests-limits.yaml#L29-L43)
- [Gatekeeper containerresources도 컨테이너별 필드만 확인](https://github.com/open-policy-agent/gatekeeper-library/blob/22a40962f83268769bcec5dfe55e44b5a85c392a/src/general/containerresources/src.rego#L1-L30)

### 14순위: Static Pod가 admission 자체를 통과하지 않는 경계

Static Pod는 API 서버가 아니라 각 노드의 kubelet이 로컬 매니페스트를 읽어 실행한다. Kyverno·Gatekeeper·Kubewarden·Polaris 웹훅은 API 서버의 admission 요청에서 동작하므로 원본 Static Pod를 막을 수 없다. 노드 파일을 쓸 권한이 이미 필요해 공격 전제가 강하고 Kubernetes 구조상 모든 admission 도구에 같은 한계가 있으므로 제품 결함으로 보기는 어렵다. 다만 “클러스터의 모든 Pod가 정책을 통과한다”는 운영 가정의 예외로 문서화하고 실험으로 경계를 확인할 가치는 있다.

- [Kubernetes API 서버 우회 위험: Static Pod는 admission 실패 뒤에도 노드에서 계속 실행될 수 있음](https://kubernetes.io/docs/concepts/security/api-server-bypass-risks/)

### 15순위 이하의 추적 후보

다음 후보도 실험 설계 대상으로 남기되 현재 근거가 약하거나 명시된 제한이다.

1. Gatekeeper 기본 `failurePolicy: Ignore`로 정책 서버 장애·시간 초과 때 요청이 허용되는 fail-open 동작.
2. Kubewarden 감사 스캐너가 wildcard-only 정책과 CREATE가 없는 정책을 건너뛰는 현상.
3. Polaris DELETE 처리에서 `oldObject`를 파싱한 뒤 실제 GenericResource 생성에는 빈 `object`를 다시 사용하는 코드 경로.
4. 이미지 저장소 허용 목록의 문자열 prefix 비교와 이미지 이름 정규화 차이. 잘못된 구분자 설정에서 `trusted.example/app`과 비슷한 공격자 저장소가 허용될 수 있다.
5. 네임스페이스 라벨 변경 직후 캐시 지연으로 selector 기반 정책이 잠시 잘못 적용되는지 여부.
6. HA 환경에서 정책 갱신·삭제가 여러 정책 서버 복제본에 서로 다른 시점에 퍼지는지 여부.
7. 새로운 Kubernetes 하위 API가 추가될 때 정적 웹훅 목록과 공개 정책이 자동으로 갱신되지 않는 일반 문제.

## 반증하거나 낮춘 후보

맞춤 정책이 일반·초기화·임시 컨테이너를 모두 명시했을 때 Kyverno, Gatekeeper, Kubewarden은 앞선 실험에서 기대대로 동작했다. 따라서 “엔진이 임시 컨테이너를 원천적으로 처리하지 못한다”는 가설은 반증됐다. 문제는 공개 정책과 웹훅 등록의 합성 결과다.

Kyverno 1.19.1 웹훅 조립 코드에서 Fail 정책이 중복 추가되는 것처럼 보인 부분도 다시 전체 문맥과 테스트를 확인했으며 실제 현재 소스에는 한 번만 추가된다. 후보에서 제외한다.

PSS sysctl 허용 목록은 현재 Kyverno 차트가 Kubernetes 문서의 1.29 이후 목록과 일치했다. 이 항목은 현재 버전 드리프트의 증거가 아니다.

## 원인과 해결 방향

공통 원인은 정책의 의미를 한 파일만 보고 판단하는 개발·평가 방식이다. 실제 집행 범위는 `웹훅 등록 규칙 × 연산 분기 × 객체 변환 × 정책식 × 실행 모드`의 교집합이다. 어느 한 층에서 요청을 빼면 마지막 정책식이 완벽해도 미탐이 된다. Kubernetes가 새 하위 API와 새 PSS 의미를 추가할수록 정적 목록과 “Pod는 불변” 같은 오래된 가정이 깨진다.

해결은 첫째, 정책 컴파일 시 부모 리소스만 보고 끝내지 말고 정책이 참조하는 필드가 변경 가능한 모든 하위 API를 자동 등록하는 것이다. 자동 등록이 어렵다면 `ephemeralContainers를 읽지만 pods/ephemeralcontainers를 매칭하지 않음`과 같은 정적 린트 오류를 내야 한다. 둘째, UPDATE 전체를 건너뛰지 말고 oldObject와 object의 차이를 비교해 새로 추가된 임시 컨테이너만 검사해야 한다. 셋째, 컨테이너 집합을 각 정책이 직접 조합하지 말고 regular, init, ephemeral을 반환하는 공통 라이브러리로 제공해야 한다. 넷째, 테스트는 완성 객체를 함수에 넣는 단위 테스트 외에 실제 API 경로·연산·하위 API를 통과하는 종단 테스트를 포함해야 한다. 다섯째, 감사 결과에는 pass/fail 외에 요청 정보가 없어 판정할 수 없는 unknown 상태가 필요하다. 여섯째, PSS 재구현은 `restricted` 같은 이름만 쓰지 말고 Kubernetes 기준 버전을 고정하고 OS·user namespace 조건을 함께 시험해야 한다.

## 공식 기준

- [Kubernetes 동적 Admission 문서: `*`는 하위 API를 포함하지 않음](https://kubernetes.io/docs/reference/access-authn-authz/extensible-admission-controllers/)
- [Kubernetes Pod 문서: ephemeralContainers와 resize는 별도 하위 API](https://kubernetes.io/docs/concepts/workloads/pods/)
- [Kubernetes 디버깅 문서: sysadmin 프로필은 privileged 임시 컨테이너를 만듦](https://kubernetes.io/docs/tasks/debug/debug-application/debug-running-pod/)
- [Kubernetes PSS: 임시 컨테이너 필드, Windows 조건, v1.34 host 제한](https://kubernetes.io/docs/concepts/security/pod-security-standards/)
- [Kubernetes user namespace에서 완화되는 PSS 검사](https://kubernetes.io/docs/concepts/workloads/pods/user-namespaces/)
- [Kubernetes 1.35 image volume](https://v1-35.docs.kubernetes.io/docs/concepts/storage/volumes/#image)
- [Kubernetes native sidecar containers](https://kubernetes.io/docs/concepts/workloads/pods/sidecar-containers/)
- [Kubernetes Pod-level resources](https://kubernetes.io/docs/concepts/configuration/manage-resources-containers/#pod-level-resource-specification)
- [Kubernetes API server bypass risks](https://kubernetes.io/docs/concepts/security/api-server-bypass-risks/)
