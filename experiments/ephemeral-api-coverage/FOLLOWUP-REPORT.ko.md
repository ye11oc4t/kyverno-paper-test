# Kubernetes 기본 통제·최소 수정·정책군 확장 후속 실험

## 결론

이번 후속 실험은 앞선 미탐을 Kubernetes가 원래 허용한 의도적 예외로 볼 수 있는지, 공개 정책의 연결만 고치면 정상 동작하는지, 그리고 문제가 `privileged` 정책 하나에만 한정되는지를 확인했다. 실제 API 요청 결과, Kubernetes의 내장 통제는 의도대로 작동했다. `pods/ephemeralcontainers` 수정 권한이 있는 주체도 Pod Security Admission의 Baseline 정책 아래에서는 `privileged: true`인 임시 컨테이너를 추가하지 못했고 HTTP 403을 받았다. 반대로 PSA를 `privileged`로 풀어 둔 네임스페이스에서도 해당 하위 API 권한이 없는 주체는 RBAC에서 HTTP 403으로 차단됐다.

따라서 Kubernetes가 임시 컨테이너를 무조건 정책 예외로 취급한다고 해석할 수 없다. Kubernetes는 누가 하위 API를 호출할 수 있는지를 RBAC로 제한하고, 호출이 허용된 뒤에는 admission이 새 임시 컨테이너의 내용을 검사하는 구조다. 두 기본 통제를 운영자가 모두 느슨하게 설정하면 추가가 허용되는 것도 설계의 일부다. 문제가 되는 조건은 운영자가 디버깅을 위해 하위 API 권한을 부여하고 내장 PSA 대신 Kyverno·Gatekeeper·Kubewarden의 공개 보안 정책이 같은 보장을 제공한다고 의존했을 때다. 고정한 공개 정책은 일반 Pod에서는 보장을 집행하면서 바로 그 합법적인 하위 API 요청에서는 같은 값을 놓쳤다.

`privileged` 정책의 제품별 최소 수정도 실제 저장 요청으로 검증했다. Kyverno에는 `pods/ephemeralcontainers` 매칭을 추가했고, Gatekeeper에는 일반 Pod UPDATE 생략을 유지하면서 임시 컨테이너 하위 API만 검사하도록 예외를 넣었고, Kubewarden에는 같은 하위 API의 UPDATE 라우팅을 추가했다. 세 수정본 모두 안전한 임시 컨테이너를 HTTP 200으로 받아 실제 `Running` 상태로 만들었고, 이어 보낸 `privileged: true` 임시 컨테이너는 각각 400·403·400으로 거부해 Pod에 저장하지 않았다. 그러므로 임시 컨테이너 전체를 금지해야만 해결되는 문제가 아니며, 정상 디버깅 기능을 유지하면서 위험한 내용만 차단할 수 있다.

정책군 확장 실험에서는 `allowPrivilegeEscalation: true`와 `capabilities.add: [SYS_ADMIN]`을 각각 검사했다. 세 제품 모두 일반 Pod의 두 위반은 정책 고유 메시지로 거부했지만, 기존 Pod에 같은 값을 가진 임시 컨테이너를 추가하는 요청은 모두 HTTP 200으로 허용했다. 허용 응답 객체에 `true`와 `SYS_ADMIN`이 그대로 남았으므로, 허용 뒤 안전한 값으로 자동 교정됐다는 설명도 성립하지 않는다. 총 여섯 개의 제품·정책군 조합에서 같은 최종 유효 적용 범위 미탐이 나왔다.

이 확장 결과는 `privileged` 정책 하나의 오타보다 넓은 문제를 보여 준다. 다만 실행은 각 조합당 한 번의 독립 설치에서 수행한 범위 확인 실험이다. 앞선 `privileged` 기준 실험처럼 제품별 3개 설치와 설치당 5회 반복을 수행한 정식 반복 결과와 같은 통계적 무게를 부여하지 않는다.

## Kubernetes 기본 통제 대조군

첫 번째 대조군은 Baseline PSA가 적용된 네임스페이스였다. 전용 ServiceAccount에는 `pods/ephemeralcontainers`의 patch·update 권한을 실제로 부여했다. 안전한 임시 컨테이너는 HTTP 200으로 저장됐지만, 같은 요청에 `privileged: true`인 두 번째 임시 컨테이너를 추가하자 API 서버가 `violates PodSecurity "baseline:latest"`라는 메시지와 함께 HTTP 403을 반환했다. 위반 컨테이너는 Pod에 저장되지 않았다. 이 결과는 PSA가 일반 Pod 생성뿐 아니라 임시 컨테이너 하위 API의 새 내용도 검사한다는 실제 대조값이다.

두 번째 대조군은 PSA를 `privileged`로 둔 대신 ServiceAccount에서 하위 API 수정 권한을 제거했다. `kubectl auth can-i update pods --subresource=ephemeralcontainers`는 `no`였고, 실제 privileged 임시 컨테이너 요청도 `cannot patch resource "pods/ephemeralcontainers"`라는 RBAC 메시지와 함께 HTTP 403으로 거부됐다. 이 경우에도 Pod는 바뀌지 않았다.

| 대조군 | 하위 API RBAC | 콘텐츠 정책 | 안전한 추가 | privileged 추가 | 저장 여부 |
|---|---|---|---:|---:|---|
| PSA Baseline | 허용 | Kubernetes PSA | 200 | 403 | 위반 미저장 |
| RBAC 차단 | 거부 | PSA privileged | 미실행 | 403 | 위반 미저장 |

이 두 결과는 제3자 도구의 허용을 Kubernetes 설계 자체의 실패로 확대하면 안 된다는 뜻이다. Kubernetes가 제공한 두 통제 지점은 작동했다. 논문의 중심은 “Kubernetes에는 통제가 없다”가 아니라 “공개 정책 묶음이 Kubernetes가 제공한 admission 지점에 동일한 보안을 끝까지 연결하지 못했다”가 되어야 한다.

## privileged 정책 최소 수정의 실제 동작

| 제품 | 최소 수정 | 안전한 임시 컨테이너 | privileged 임시 컨테이너 | 최종 Pod |
|---|---|---:|---:|---|
| Kyverno 1.19.1 | CEL `resourceRules`에 하위 API 추가 | 200, Running | 400 | 위반 미저장 |
| Gatekeeper 3.23.1 | 임시 컨테이너 UPDATE를 검사하도록 조건 수정 | 200, Running | 403 | 위반 미저장 |
| Kubewarden 1.37.2 | 정책 규칙에 하위 API UPDATE 추가 | 200, Running | 400 | 위반 미저장 |

Kyverno의 정책식은 처음부터 `spec.ephemeralContainers`를 읽었다. 빠진 것은 요청을 그 식으로 보내는 `resourceRules`였다. 따라서 경로 하나를 추가한 뒤에는 일반 Pod 판정과 안전한 임시 컨테이너 판정이 유지되면서 위반 요청만 거부됐다. 이는 엔진 능력 부족이 아니라 공개 CEL 정책의 API 연결 범위 누락이라는 해석을 지지한다.

Gatekeeper는 반대 층에서 실패했다. 웹훅은 하위 API 요청을 받고 정책도 임시 컨테이너를 수집했지만, 과거 일반 Pod의 보안 필드가 UPDATE로 바뀌지 않는다는 가정 때문에 모든 UPDATE를 먼저 허용했다. `request.subResource`가 `ephemeralcontainers`일 때만 그 생략을 적용하지 않도록 바꾸자 원하는 판정이 나왔다. 일반 Pod의 불필요한 UPDATE 검사를 전부 켤 필요는 없었다.

Kubewarden의 privileged 모듈은 `skip_ephemeral_containers: false`일 때 임시 컨테이너를 검사할 수 있었지만 공개 정책 객체가 Pod CREATE만 모듈로 보냈다. 하위 API UPDATE 규칙을 추가하자 모듈의 기존 거부 메시지인 `Privileged ephemeral container is not allowed`가 반환됐다. 설정 이름과 실제 요청 라우팅 사이의 불일치가 충분 원인이었다.

## privilege escalation·capability 정책군 확장

| 제품 | 일반 APE=true | 임시 APE=true | 일반 SYS_ADMIN | 임시 SYS_ADMIN |
|---|---:|---:|---:|---:|
| Kyverno | 400 | 200 | 400 | 200 |
| Gatekeeper | 403 | 200 | 403 | 200 |
| Kubewarden | 400 | 200 | 400 | 200 |

표의 APE는 `allowPrivilegeEscalation`의 약자다. 이 값이 `true`이면 컨테이너 안의 프로세스가 setuid 실행 파일 같은 경로를 통해 현재보다 높은 권한을 얻을 수 있다. `SYS_ADMIN`은 Linux capability 중 범위가 매우 넓은 권한으로, 마운트와 여러 커널 관리 동작에 관여한다. 둘 다 곧바로 노드 장악을 뜻하지는 않지만, 보안 기준이 명시적으로 제한하는 값이며 컨테이너 탈출이나 다른 취약점의 영향을 키울 수 있다.

각 단계에서 안전한 일반 Pod와 안전한 임시 컨테이너는 허용됐다. 일반 위반은 Kyverno의 `disallow-privilege-escalation`·`disallow-capabilities-strict`, Gatekeeper의 `psp-allow-privilege-escalation-container`·`psp-capabilities-restricted`, Kubewarden의 `no-privilege-escalation`·`drop-capabilities` 메시지로 거부됐다. 따라서 정책이 비활성 상태였거나 모든 요청을 허용한 결과가 아니다. 같은 정책이 일반 컨테이너에는 작동했지만 하위 API를 통한 임시 컨테이너에서만 보장을 잃었다.

원인 분리 결과는 제품마다 달랐다. Kyverno의 두 CEL 정책에 하위 API 매칭만 추가하자 두 임시 위반이 400으로 바뀌었다. Gatekeeper의 두 정책에서 임시 컨테이너 UPDATE를 검사하도록 단축 조건만 바꾸자 두 위반이 403으로 바뀌었다. 두 제품에서는 앞서 privileged 정책에서 확인한 원인이 다른 정책군에도 그대로 반복됐다.

Kubewarden은 `no-privilege-escalation`과 `drop-capabilities`에 하위 API UPDATE 라우팅을 추가한 뒤에도 두 위반을 계속 HTTP 200으로 허용했다. 응답 객체에도 `allowPrivilegeEscalation: true`와 `SYS_ADMIN`이 남았다. 따라서 이 두 모듈에서는 라우팅 누락만 고쳐서는 충분하지 않으며, 모듈이 일반 컨테이너와 초기화 컨테이너뿐 아니라 `ephemeralContainers` 배열도 순회하도록 바꿔야 한다. Kubewarden의 privileged 모듈과 달리 이 두 모듈에는 객체 순회 누락이라는 두 번째 층의 문제가 있다.

| 제품 | 확장 정책에 적용한 원인 분리 변경 | APE 결과 | capability 결과 | 해석 |
|---|---|---:|---:|---|
| Kyverno | 하위 API 라우팅 추가 | 400 | 400 | 라우팅 수정으로 충분 |
| Gatekeeper | 임시 컨테이너 UPDATE 검사 | 403 | 403 | UPDATE 분기 수정으로 충분 |
| Kubewarden | 하위 API 라우팅만 추가 | 200 | 200 | 모듈 순회 수정도 필요 |

## 왜 이런 결함이 생겼는가

일반 Pod가 만들어진 뒤에는 `spec.containers`의 보안 설정을 마음대로 바꿀 수 없다는 오래된 전제 자체는 맞다. 그래서 여러 정책이 Pod CREATE를 중심으로 등록되거나 UPDATE를 통째로 건너뛰도록 작성됐다. 임시 컨테이너는 이미 존재하는 Pod에 `pods/ephemeralcontainers`라는 별도 하위 API의 UPDATE 요청으로 새 컨테이너 정의를 추가한다. 기존 컨테이너의 불변 필드를 수정하는 UPDATE와 새 임시 컨테이너를 넣는 UPDATE가 같은 연산 이름을 쓰면서, 과거 최적화가 새로운 합법적 변경 경로를 보안 예외로 만들었다.

이 결함은 세 층으로 나뉜다. 첫째는 웹훅 또는 정책의 리소스 규칙이 하위 API 요청을 받지 않는 라우팅 누락이다. 둘째는 요청을 받은 뒤 UPDATE라는 이유만으로 평가를 생략하는 연산 분기다. 셋째는 정책 모듈이 Pod 객체를 읽으면서 `containers`와 `initContainers`만 순회하고 `ephemeralContainers`를 빼는 객체 순회 누락이다. Kyverno의 현재 CEL 정책은 첫째, Gatekeeper 공개 PSS 정책은 둘째, Kubewarden 정책군은 첫째와 일부 모듈의 셋째를 보여 줬다.

## 사용자에게 생기는 문제와 완화 방법

공격자가 이 경로를 쓰려면 대상 네임스페이스에서 `pods/ephemeralcontainers`를 patch 또는 update할 RBAC 권한이 필요하다. 그러나 이 권한은 운영·장애 대응 인력에게 현실적으로 부여될 수 있고, 공격자뿐 아니라 정상 사용자의 실수도 같은 결과를 만든다. 정책 도구가 일반 Pod의 위험 설정을 막는 모습을 보고 동일 보장을 기대한 관리자는 기존 민감한 Pod 안에 위험한 임시 컨테이너가 추가되는 것을 놓칠 수 있다. 앞선 실제 실행 실험에서는 privileged 임시 컨테이너가 저장되어 containerd에서 실행됐고 UID 0과 넓은 유효 capability가 관찰됐다.

즉시 가능한 완화는 하위 API 권한을 별도 RBAC 역할로 좁히고, 가능한 네임스페이스에는 PSA Baseline 또는 Restricted를 적용하는 것이다. 제3자 정책을 사용할 때는 일반 `pods`뿐 아니라 `pods/ephemeralcontainers`와 UPDATE가 실제 ValidatingWebhookConfiguration 또는 정책 매칭 규칙에 들어 있는지 확인해야 한다. 정책식은 `spec.containers`, `spec.initContainers`, `spec.ephemeralContainers`를 모두 같은 보안 의미로 순회해야 하며, UPDATE 생략 조건은 일반 Pod의 불변 필드 변경에만 적용하고 임시 컨테이너 하위 API는 평가해야 한다.

## 주장 범위와 남은 실험

`privileged` 기준 실험은 제품별 3개 독립 설치에서 설치당 5회 반복한 dry-run 결과와 제품별 한 번의 실제 실행 결과를 가진다. 이번 Kubernetes 기본 통제, 수정본 실제 실행, 정책군 확장은 각 조건당 한 번 수행했다. 후속 결과는 설계 해석과 결함 범위를 강하게 보완하지만, 여러 Kubernetes 버전이나 관리형 배포판에 대한 재현율을 제공하지 않는다.

논문 본문에 필요한 핵심 대조와 원인 분리는 현재 충족됐다. 다음 우선순위는 같은 정책군 확장 실험을 제품별 여러 독립 설치에서 반복해 표본을 맞추는 것이다. 그다음은 최신 버전과 직전 주요 버전을 비교해 회귀 시점을 좁히는 실험이다. Polaris 같은 네 번째 도구는 외적 타당성을 늘리지만, 현재 세 도구의 인과관계를 밝히는 데 필수는 아니다. 관리형 Kubernetes와 HA 환경은 전파 지연·failurePolicy 같은 운영 조건을 다루는 별도 연구 질문으로 분리하는 편이 타당하다.

## 결과 파일

- `results/2026-09-19-kubernetes-controls/`: PSA와 RBAC 실제 대조군
- `results/2026-09-19-live-fixes/`: privileged 정책 최소 수정 뒤 실제 저장·실행 판정
- `results/2026-09-19-policy-families/`: 두 추가 정책군의 기준 결과와 원인 분리 결과
- `results/2026-09-19-followup-aggregate.json`: 모든 후속 결과의 검증된 집계
- `run-kubernetes-controls.sh`: Kubernetes 기본 통제 실행기
- `run-live-fixed-case.sh`: 수정된 privileged 정책의 실제 요청 실행기
- `run-policy-family-cases.sh`: privilege escalation·capability 공통 dry-run 실행기
- `aggregate_followup_results.py`: 상태 코드, 응답 값, 정책 메시지를 검증하는 집계기
