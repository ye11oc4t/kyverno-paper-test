# Kubernetes 임시 컨테이너 하위 API에서 정책 유효 적용 범위의 실증 평가: Kyverno, Gatekeeper, Kubewarden 비교

**Empirical Evaluation of Effective Policy Coverage on the Kubernetes Ephemeral Containers Subresource: A Comparison of Kyverno, Gatekeeper, and Kubewarden**

저자 및 소속: 추후 기입

## 요약

본 연구는 Kubernetes 정책 도구의 공개 컨테이너 보안 정책이 일반 Pod 생성과 기존 Pod에 임시 컨테이너를 추가하는 요청에서 동일한 보장을 제공하는지 검증하고, 이를 위한 유효 적용 범위 판정 방식을 제안한다. Kyverno, Gatekeeper, Kubewarden의 공개 privileged 정책을 비교한 결과 세 도구 모두 일반 privileged Pod를 거부했지만 `pods/ephemeralcontainers` 하위 API를 통한 privileged 임시 컨테이너 추가는 제품별 3개 독립 설치와 설치당 5회 반복한 총 45회 실행에서 모두 허용하였다. 후속 실제 실행에서도 허용된 컨테이너는 UID 0과 `000001ffffffffff`의 유효 Linux capability를 가지고 실행되었다. 또한 privilege escalation 및 capability 정책으로 확장한 여섯 개의 제품·정책 조합에서도 일반 컨테이너 위반은 거부됐지만 같은 값을 가진 임시 컨테이너는 허용됐다. 반면 Kubernetes 내장 Pod Security Admission과 RBAC는 동일한 하위 API 요청을 정상적으로 차단했으며, 제품별 원인을 수정한 실험에서는 안전한 임시 컨테이너를 허용하면서 위험한 요청만 거부할 수 있었다. 이를 통해 Kubernetes 정책의 보장 여부를 판정할 때는 정책 객체나 검사식의 존재뿐 아니라 API 라우팅, 연산 분기, 객체 순회와 최종 admission 결과를 함께 확인할 필요가 있음을 확인하였다.

## I. 서론

Kubernetes(이하 K8s)는 API를 통해 워크로드와 권한, 네트워크 및 저장소 구성을 관리한다. 이 과정에서 admission controller는 API 서버가 객체를 저장하기 전에 요청을 검사하거나 변경하며, 위험한 설정을 차단하는 정책 집행 지점으로 사용된다[1]. 예를 들어 컨테이너의 privileged 모드, 프로세스의 권한 상승 허용, 과도한 Linux capability는 컨테이너 격리를 약화할 수 있으므로 K8s의 Pod Security Admission(이하 PSA)과 Kyverno, Gatekeeper, Kubewarden 같은 정책 도구가 이를 제한한다[2]. 이러한 정책은 워크로드의 배포 허용 여부를 직접 결정하므로 정책이 대상으로 삼는 모든 API 요청에서 일관된 보장을 제공해야 한다.

그러나 정책 객체가 존재하거나 일반 Pod를 정상적으로 차단한다는 사실만으로 관련된 모든 API 경로에서 동일한 정책이 적용된다고 단정할 수 없다. K8s에는 일반 리소스 API 외에도 `status`, `scale`, `ephemeralcontainers`와 같은 하위 API가 존재하며, admission webhook은 등록된 리소스와 연산에 해당하는 요청만 전달받는다[1]. 따라서 정책식이 올바른 보안 조건을 포함하더라도 하위 API가 웹훅 규칙에서 빠져 있거나 특정 연산을 평가하지 않으면 실제 요청은 검사식까지 도달하지 않을 수 있다. 이런 불일치는 정책이 설치되고 정상 동작하는 것처럼 보이면서 특정 경로의 위반만 허용하는 미탐을 만들 수 있다.

임시 컨테이너(Ephemeral Container)는 이미 실행 중인 Pod에 문제 진단용 컨테이너를 추가하는 K8s 기능이다. 임시 컨테이너는 일반 Pod CREATE가 아니라 `pods/ephemeralcontainers` 하위 API의 UPDATE 요청을 통해 추가되며, 실행 이미지와 `securityContext`를 가진 실제 컨테이너로 동작한다[3][4]. K8s Pod Security Standards(이하 PSS)는 일반 컨테이너와 초기화 컨테이너뿐 아니라 임시 컨테이너의 privileged, privilege escalation 및 capability 설정도 제한한다[2]. 따라서 임시 컨테이너가 진단 목적으로 사용된다는 사실은 해당 컨테이너를 보안 정책에서 제외해야 한다는 의미가 아니다.

본 연구는 공개 K8s 정책이 일반 컨테이너와 임시 컨테이너에 동일한 보안을 제공하는지 실증적으로 검증하고, 정책의 실제 유효 적용 범위를 판정하는 방식을 제안한다. 이를 위해 Kyverno, Gatekeeper, Kubewarden의 세 보안 정책군을 대상으로 일반 Pod CREATE와 임시 컨테이너 UPDATE에 동일한 위반값을 입력하고 API 판정을 비교하였다. 또한 PSA와 RBAC를 Kubernetes 내장 대조군으로 구성하고, 각 제품에서 하나의 원인만 수정한 분리 실험을 통해 관찰된 미탐이 Kubernetes의 의도된 허용인지 공개 정책의 연결 및 평가 문제인지 구분하였다.

## II. 관련 연구 및 문제 정의

### 2.1 Kubernetes admission 정책과 임시 컨테이너

K8s의 동적 admission은 API 요청의 그룹, 버전, 리소스, 하위 리소스와 연산을 기준으로 대상 웹훅을 선택한다[1]. 요청이 정책 엔진에 전달되면 정책은 객체의 필드를 평가하여 허용 또는 거부하거나 안전한 값으로 변경한다. 따라서 최종 정책 보장은 검사식 자체뿐 아니라 요청이 검사식까지 전달되는지, 정책이 요청 객체의 대상 필드를 순회하는지, 평가 결과가 API 서버의 최종 판정에 반영되는지에 의해 결정된다. 특히 일반 리소스와 하위 리소스는 같은 객체를 반환하더라도 admission 등록에서는 서로 다른 대상으로 취급될 수 있다.

임시 컨테이너는 이미 실행 중인 Pod의 기존 컨테이너를 수정하는 대신 Pod의 `spec.ephemeralContainers`에 새 컨테이너 정의를 추가한다[3]. 호출자는 일반 `pods` 수정 권한과 별도로 `pods/ephemeralcontainers`의 patch 또는 update 권한을 가져야 한다. 해당 권한이 있어도 admission controller는 새 임시 컨테이너의 보안 설정을 검사할 수 있으며, 실제로 PSA는 이 경로의 privileged 설정을 평가한다. 그러므로 RBAC는 누가 임시 컨테이너를 추가할 수 있는지를 통제하고 admission 정책은 허용된 사용자가 어떤 내용의 컨테이너를 추가할 수 있는지를 통제하는 서로 다른 계층이다.

### 2.2 정책 유효 적용 범위와 판정 조건

본 연구에서 정책 유효 적용 범위는 정책이 표현하는 보안 조건이 관련된 실제 API 경로에서 최종적으로 집행되는 범위를 의미한다. 정책이 일반 Pod의 위반을 차단해도 임시 컨테이너 하위 API의 동일한 위반을 허용한다면 해당 정책은 임시 컨테이너에 대해 유효하게 적용되지 않은 것으로 본다. 반대로 하위 API 요청을 전부 차단하는 경우에는 위험 요청의 미탐은 없지만 정상적인 진단 컨테이너까지 차단하는 오탐 또는 기능 제한이 발생할 수 있으므로 안전한 요청도 함께 평가해야 한다.

유효 적용 범위의 판정 조건은 네 단계로 구분하였다. 첫째, 웹훅이나 정책의 리소스 규칙이 하위 API 요청을 받는지 확인하는 API 라우팅 단계이다. 둘째, CREATE와 UPDATE 및 하위 리소스를 구분하는 연산 분기 단계이다. 셋째, 정책식이나 모듈이 `containers`, `initContainers`, `ephemeralContainers`의 대상 필드를 실제로 읽는 객체 순회 단계이다. 넷째, 실제 API 요청이 허용·거부·변경되는지를 확인하는 최종 집행 단계이다. 본 연구에서는 일반 컨테이너의 위반을 대상 정책이 거부하지만 동일한 임시 컨테이너 위반은 허용되고 위험 값이 응답 또는 저장 객체에 남는 경우를 미탐으로 정의하였다.

## III. 실험 설계

### 3.1 평가 대상 오픈소스 도구

평가 대상은 K8s admission 정책을 제공하고 공개 보안 정책을 배포하는 Kyverno, Gatekeeper, Kubewarden으로 선정하였다. 실험에는 Kyverno 애플리케이션 1.19.1과 `kyverno-policies` 차트 3.9.1의 기본 CEL `ValidatingPolicy`, Gatekeeper 3.23.1과 gatekeeper-library 커밋 `22a40962f83268769bcec5dfe55e44b5a85c392a`, Kubewarden 1.37.2와 admission-controller 차트 6.0.2의 recommended 정책을 사용하였다. 평가 정책은 privileged, privilege escalation, capability 세 정책군이며 각 제품은 다른 정책 도구가 설치되지 않은 별도의 단일 노드 kind 클러스터에서 실행하였다.

### 3.2 실험 조건 및 검증 방법

각 정책이 일반 컨테이너와 임시 컨테이너를 동일하게 판정하는지 비교하기 위해 표 1의 C0~C7 조건을 구성하였다. privileged 단계는 컨테이너에 호스트 수준에 가까운 권한을 부여하는 `securityContext.privileged: true`를 위반값으로 사용하였다. privilege escalation 단계는 실행 중인 프로세스가 현재보다 높은 권한을 얻도록 허용하는 `allowPrivilegeEscalation: true`를 사용하였다. capability 단계는 Linux의 root 권한을 기능 단위로 나눈 capability 중 범위가 넓은 `SYS_ADMIN`을 추가하였다. C0와 C2의 안전한 요청은 정상 입력의 오탐 여부를 확인하고, C1·C4·C6의 일반 컨테이너 위반은 정책이 활성화되어 실제 거부 모드로 동작하는지를 확인한다. C3·C5·C7은 동일한 보안 의미를 임시 컨테이너 하위 API에 적용한 본 실험 사례이다.

**표 1. 정책 유효 적용 범위 검증을 위한 실험 조건**

| 조건 | API 요청 | 컨테이너 설정 | 기대값 |
|---|---|---|---|
| C0 | Pod CREATE | 안전한 일반 컨테이너 | 허용 |
| C1 | Pod CREATE | `privileged: true` | 거부 |
| C2 | `pods/ephemeralcontainers` UPDATE | 안전한 임시 컨테이너 | 허용 |
| C3 | `pods/ephemeralcontainers` UPDATE | `privileged: true` | 거부 |
| C4 | Pod CREATE | `allowPrivilegeEscalation: true` | 거부 |
| C5 | `pods/ephemeralcontainers` UPDATE | `allowPrivilegeEscalation: true` | 거부 |
| C6 | Pod CREATE | `capabilities.add: [SYS_ADMIN]` | 거부 |
| C7 | `pods/ephemeralcontainers` UPDATE | `capabilities.add: [SYS_ADMIN]` | 거부 |

일반 Pod 사례는 `POST /api/v1/namespaces/{namespace}/pods`, 임시 컨테이너 사례는 `PATCH /api/v1/namespaces/{namespace}/pods/{name}/ephemeralcontainers`로 전송하였다. HTTP 2xx는 허용으로 판정하고 대상 정책의 이름 또는 고유 메시지가 포함된 4xx 응답은 정책 거부로 판정하였다. 허용 응답은 상태 코드만 확인하지 않고 반환된 Pod 객체에 요청한 위험 값이 남아 있는지도 확인하였다. privileged 기준 실험은 `dryRun=All`을 사용하여 반복 판정 중 객체가 변경되지 않게 했으며, 후속 실제 실행에서는 dry-run을 제거하여 저장과 런타임 실행 여부를 확인하였다.

제3자 정책 실험의 네임스페이스는 PSA 수준을 `privileged`로 설정해 내장 PSA가 결과를 대신 차단하지 않도록 하였다. 전용 ServiceAccount에는 `pods` create와 `pods/ephemeralcontainers` get·patch·update만 부여하고 SelfSubjectAccessReview로 실제 권한을 확인하였다. 별도의 Kubernetes 대조군에서는 첫째, 하위 API 권한을 부여한 상태에서 PSA Baseline이 위험한 내용을 차단하는지 확인하고, 둘째, PSA를 `privileged`로 둔 상태에서 하위 API 권한이 없는 주체를 RBAC가 차단하는지 확인하였다.

privileged 정책은 제품별 세 개의 새 클러스터에서 설치당 같은 네 사례를 다섯 번 반복하였다. 총 45회의 정식 실행에서 정책 준비 상태, 안전한 요청 허용, 일반 위반의 정책 고유 거부, 하위 API RBAC 허용, 요청 전후 기준 Pod 불변을 유효성 조건으로 확인하였다. 이후 제품별 새 클러스터 한 개에서 실제 요청을 보내 안전한 임시 컨테이너와 privileged 임시 컨테이너의 저장 및 실행 상태를 비교하였다. 실행된 컨테이너에서는 UID와 `/proc/self/status`의 `CapEff`만 측정하고 호스트 접근이나 컨테이너 탈출은 수행하지 않았다.

기준 결과를 얻은 뒤에는 한 번에 한 층만 변경하는 원인 분리 실험을 수행하였다. Kyverno는 정책식을 유지하고 `pods/ephemeralcontainers` 매칭만 추가하였다. Gatekeeper는 웹훅과 컨테이너 수집식을 유지하고 일반 UPDATE 생략 조건에서 임시 컨테이너 하위 API만 제외하였다. Kubewarden은 먼저 정책 규칙에 하위 API UPDATE를 추가하고, 라우팅이 실제 생성된 webhook에 반영된 뒤에도 위반을 허용하는지를 확인하였다. 수정 뒤에도 안전한 요청은 허용되고 위험 요청만 거부되는 경우 해당 변경을 관찰된 미탐의 충분 원인으로 판정하였다.

## IV. 실험 결과 및 분석

### 4.1 오픈소스 도구 비교 결과

세 도구의 privileged 정책에 C0~C3을 적용한 결과 C0의 안전한 일반 Pod와 C2의 안전한 임시 컨테이너는 모두 허용됐고, C1의 일반 privileged Pod는 대상 정책의 이름이나 메시지와 함께 거부됐다. 그러나 C3의 privileged 임시 컨테이너는 모든 제품과 반복에서 HTTP 200으로 허용됐다. 표 2와 같이 제품별 3개 독립 설치와 설치당 5회 반복한 45회의 정식 실행에서 같은 결과가 나타났으므로 정책 활성화 실패나 일시적 준비 지연으로 설명하기 어렵다.

**표 2. privileged 정책의 정식 반복 결과**

| 제품 | 독립 설치 | 반복 | C0 | C1 | C2 | C3 | C3 미탐 |
|---|---:|---:|---:|---:|---:|---:|---:|
| Kyverno | 3 | 15 | 201 × 15 | 400 × 15 | 200 × 15 | 200 × 15 | 15/15 |
| Gatekeeper | 3 | 15 | 201 × 15 | 422 × 15 | 200 × 15 | 200 × 15 | 15/15 |
| Kubewarden | 3 | 15 | 201 × 15 | 400 × 15 | 200 × 15 | 200 × 15 | 15/15 |

후속 실제 실행에서도 세 도구는 일반 privileged Pod를 거부하면서 privileged 임시 컨테이너 추가를 허용하였다. 허용된 컨테이너는 모두 containerd 컨테이너 ID를 받고 `Running` 상태가 됐다. 여기서 `CapEff`는 Linux 프로세스에 실제로 활성화된 capability를 나타내는 비트마스크이다. 안전한 임시 컨테이너는 UID 65532와 `0000000000000000`의 `CapEff`를 보인 반면 privileged 임시 컨테이너는 UID 0과 `000001ffffffffff`의 `CapEff`를 보였다. 따라서 기준 실험의 HTTP 200은 형식적인 admission 응답에 그치지 않고 위험 설정이 저장되어 런타임 프로세스에 적용되는 결과로 이어졌다.

**표 3. privileged 임시 컨테이너의 실제 실행 결과**

| 제품 | 일반 privileged Pod | 안전한 임시 컨테이너 | privileged 임시 컨테이너 | 안전 CapEff | privileged CapEff |
|---|---:|---:|---:|---|---|
| Kyverno | 400 | 200, Running | 200, Running | `0000000000000000` | `000001ffffffffff` |
| Gatekeeper | 403 | 200, Running | 200, Running | `0000000000000000` | `000001ffffffffff` |
| Kubewarden | 400 | 200, Running | 200, Running | `0000000000000000` | `000001ffffffffff` |

privilege escalation과 capability 정책으로 범위를 확장한 결과도 동일했다. 세 제품은 일반 Pod의 `allowPrivilegeEscalation: true`와 `SYS_ADMIN` 추가를 각 정책의 고유 메시지로 거부했지만 같은 값을 가진 임시 컨테이너는 모두 HTTP 200으로 허용하였다. 허용 응답의 `spec.ephemeralContainers`에도 `true`와 `SYS_ADMIN`이 그대로 남아 있어 정책이 허용 뒤 안전한 값으로 변경했다는 설명도 배제할 수 있었다. 이 결과는 privileged 정책 하나의 오타가 아니라 서로 다른 컨테이너 보안 정책에서 반복되는 유효 적용 범위 문제임을 보여 준다.

**표 4. 추가 정책군의 판정 결과**

| 제품 | 일반 권한 상승 허용 | 임시 권한 상승 허용 | 일반 SYS_ADMIN | 임시 SYS_ADMIN |
|---|---:|---:|---:|---:|
| Kyverno | 400 | 200 | 400 | 200 |
| Gatekeeper | 403 | 200 | 403 | 200 |
| Kubewarden | 400 | 200 | 400 | 200 |

### 4.2 정책 유효 적용 범위 판정 방식 비교

일반 Pod 차단 여부만 확인하는 방식에서는 평가한 아홉 개 제품·정책 조합이 모두 정상으로 보인다. 각 제품은 일반 컨테이너의 privileged, privilege escalation, capability 위반을 실제로 거부했기 때문이다. 정책식 또는 모듈에 `ephemeralContainers` 관련 코드가 존재하는지만 확인하는 방식도 Kyverno와 Gatekeeper의 정책 및 Kubewarden privileged 모듈을 정상으로 판단할 수 있다. 그러나 실제 하위 API 요청에서는 이 정책들이 미탐을 보였다. 이는 정책의 보안 의미와 실제 집행 범위가 서로 다른 층에서 결정됨을 의미한다.

본 연구의 네 단계 판정 방식은 API 라우팅, 연산 분기, 객체 순회, 최종 집행을 분리한다. 이 방식으로 분석한 결과 Kyverno의 세 CEL 정책은 임시 컨테이너를 읽는 검사식을 가지고 있었지만 리소스 규칙이 일반 `pods`만 포함해 하위 API 요청이 검사식에 도달하지 않았다[5]. Gatekeeper는 하위 API 요청을 받고 임시 컨테이너를 수집했지만 세 정책 모두 UPDATE 요청을 먼저 허용하는 조건 때문에 위반 목록이 있어도 통과시켰다[6]. Kubewarden privileged 모듈은 임시 컨테이너를 검사할 수 있었지만 공개 정책 규칙이 Pod CREATE만 모듈에 전달했고, privilege escalation과 capability 모듈은 라우팅 외에도 임시 컨테이너 배열을 순회하지 않았다[7][8].

**표 5. 정책 유효 적용 범위 판정 방식 비교**

| 판정 방식 | 확인 대상 | 놓칠 수 있는 결함 |
|---|---|---|
| 일반 Pod 판정 | 정책 활성화와 일반 CREATE 거부 | 하위 API 전체 |
| 정책식·모듈 확인 | 표현된 보안 조건 | API 라우팅, 연산 분기 |
| 하위 API 등록 확인 | 요청 전달 가능성 | UPDATE 생략, 객체 순회 |
| 본 연구의 단계 구분 | 라우팅, 연산, 순회, 최종 결과 | 평가 범위 내 실제 결과와 일치 |

원인 분리 실험은 이러한 분석을 실제 판정으로 확인하였다. Kyverno는 하위 API 리소스 규칙만 추가하자 privileged, privilege escalation, capability 임시 컨테이너가 모두 거부로 바뀌었다. Gatekeeper는 일반 Pod UPDATE 생략은 유지하면서 `request.subResource`가 `ephemeralcontainers`인 UPDATE를 검사하도록 바꾸자 세 정책군이 모두 거부로 바뀌었다. Kubewarden privileged 정책은 하위 API UPDATE 규칙 추가만으로 거부됐지만 privilege escalation과 capability 정책은 실제 MutatingWebhook에 해당 경로가 추가된 뒤에도 위반을 허용하였다. 후자의 두 정책은 모듈이 `ephemeralContainers`를 순회하도록 추가 수정해야 함을 확인하였다.

**표 6. 제품별 원인 분리 결과**

| 제품 | 정책군 | 변경한 층 | 변경 전 | 변경 후 | 해석 |
|---|---|---|---:|---:|---|
| Kyverno | 세 정책군 | 하위 API 라우팅 추가 | 허용 | 거부 | 라우팅 수정으로 충분 |
| Gatekeeper | 세 정책군 | 임시 컨테이너 UPDATE 평가 | 허용 | 거부 | 연산 분기 수정으로 충분 |
| Kubewarden | privileged | 하위 API 라우팅 추가 | 허용 | 거부 | 라우팅 수정으로 충분 |
| Kubewarden | 권한 상승·capability | 하위 API 라우팅 추가 | 허용 | 허용 | 객체 순회 수정도 필요 |

Kubernetes 내장 통제 대조군은 임시 컨테이너가 원래 정책 예외라는 해석을 반증하였다. 하위 API update 권한이 있는 ServiceAccount가 PSA Baseline 네임스페이스에서 privileged 임시 컨테이너를 추가하자 API 서버는 `violates PodSecurity "baseline:latest"` 메시지와 함께 HTTP 403을 반환하였다. 반대로 PSA를 `privileged`로 둔 네임스페이스에서는 하위 API 권한이 없는 ServiceAccount의 요청을 RBAC가 HTTP 403으로 거부하였다. 즉 K8s가 제공하는 두 통제 지점은 정상적으로 작동했으며, 관찰된 문제는 공개 제3자 정책이 같은 보안을 해당 admission 경로에 끝까지 연결하지 못한 데 있다.

### 4.3 논의 및 한계

세 제품의 구현은 서로 다르지만 결함을 만든 전제는 유사하다. 일반 Pod가 생성된 뒤 `spec.containers`의 보안 필드는 변경할 수 없으므로 기존 정책은 Pod CREATE를 중심으로 등록하거나 UPDATE 평가를 생략하였다. 그러나 임시 컨테이너는 기존 컨테이너의 불변 필드를 수정하지 않고 별도 하위 API의 UPDATE를 통해 새 컨테이너 정의를 추가한다. 기존 컨테이너 수정과 새 임시 컨테이너 추가가 같은 UPDATE 연산 이름을 사용하면서 과거의 최적화와 불변 가정이 새로운 보안 공백으로 이어졌다.

이 결과가 K8s 권한 통제 전체의 무력화를 의미하지는 않는다. 공격자 또는 운영자가 해당 경로를 사용하려면 대상 네임스페이스에서 `pods/ephemeralcontainers`의 patch 또는 update 권한을 가져야 한다. 그러나 이 권한은 장애 대응과 디버깅을 위해 실제 사용자나 자동화에 부여될 수 있고, 정책 도구가 일반 Pod의 동일한 설정을 차단하는 모습을 본 관리자는 임시 컨테이너에도 같은 보장이 적용된다고 기대할 수 있다. 따라서 공격뿐 아니라 정상 운영자의 설정 실수도 정책을 통과해 기존 민감한 Pod 안에서 높은 권한의 컨테이너를 실행할 수 있다.

운영 환경에서는 하위 API 권한을 별도 RBAC 역할로 제한하고 가능한 네임스페이스에 PSA Baseline 또는 Restricted를 적용하여 위험을 줄일 수 있다. 제3자 정책은 일반 `pods`뿐 아니라 `pods/ephemeralcontainers`와 UPDATE가 실제 webhook 또는 정책 매칭 규칙에 포함되는지 확인해야 한다. 또한 정책식과 모듈은 일반·초기화·임시 컨테이너를 같은 보안 의미로 순회해야 하며, 일반 Pod의 불변 필드를 위한 UPDATE 생략은 임시 컨테이너 하위 API에 적용되지 않도록 구분해야 한다. 본 실험의 수정 결과는 임시 컨테이너 전체를 금지하지 않고도 안전한 진단 컨테이너를 허용하면서 위험한 설정만 차단할 수 있음을 보여 준다.

다만 정식 45회 반복과 실제 런타임 검증은 privileged 정책을 중심으로 수행하였다. privilege escalation과 capability 확장은 제품·정책 조합당 한 번의 독립 설치에서 범위를 확인했으므로 privileged 결과와 같은 반복 재현율을 부여할 수 없다. 또한 실험은 고정된 세 제품 버전과 Kubernetes 1.35.8 기반 로컬 kind 환경에서 수행했으므로 관리형 Kubernetes, 다른 제품 버전, 고가용성 구성에서 추가 검증이 필요하다. 실제 실행은 UID와 Linux capability 적용까지만 측정했으며 호스트 접근, 컨테이너 탈출 또는 노드 장악을 입증한 것은 아니다.

## V. 결론

본 연구는 Kyverno, Gatekeeper, Kubewarden의 공개 컨테이너 보안 정책과 임시 컨테이너 하위 API의 실제 admission 결과 사이의 불일치를 분석하였다. 세 도구 모두 일반 privileged Pod를 거부하면서 privileged 임시 컨테이너를 45회의 정식 실행에서 허용했고, 후속 실험에서는 해당 컨테이너가 UID 0과 높은 유효 capability를 가지고 실제 실행됐다. privilege escalation과 capability 정책에서도 일반 컨테이너 위반은 거부하고 임시 컨테이너 위반은 허용하는 결과가 반복됐다. 제품별 원인은 Kyverno의 하위 API 라우팅 누락, Gatekeeper의 UPDATE 생략, Kubewarden의 라우팅 및 일부 모듈의 객체 순회 누락으로 구분됐다.

반면 Kubernetes 내장 PSA와 RBAC는 동일한 하위 API 요청을 정상적으로 차단했고, 제품별 원인을 수정한 정책은 안전한 임시 컨테이너를 유지하면서 위험한 요청만 거부했다. 이를 통해 K8s 정책의 보장 여부를 일반 리소스 판정이나 정책식의 존재만으로 판단하기보다 API 라우팅, 연산 분기, 객체 순회와 최종 집행 결과를 함께 확인할 필요가 있음을 확인하였다. 향후에는 추가 정책군의 반복 수를 privileged 실험과 동일하게 확장하고, 제품 버전별 회귀 시점과 다른 K8s 정책 도구 및 관리형 환경을 대상으로 검증 범위를 확대할 예정이다.

## 참고문헌

[1] Kubernetes, “Dynamic Admission Control,” Kubernetes Documentation, https://kubernetes.io/docs/reference/access-authn-authz/extensible-admission-controllers/, accessed September 19, 2026.

[2] Kubernetes, “Pod Security Standards,” Kubernetes Documentation, https://kubernetes.io/docs/concepts/security/pod-security-standards/, accessed September 19, 2026.

[3] Kubernetes, “Ephemeral Containers,” Kubernetes Documentation, https://kubernetes.io/docs/concepts/workloads/pods/ephemeral-containers/, accessed September 19, 2026.

[4] Kubernetes SIG Node, “KEP-277: Ephemeral Containers,” Kubernetes Enhancements, https://github.com/kubernetes/enhancements/blob/master/keps/sig-node/277-ephemeral-containers/README.md, accessed September 19, 2026.

[5] Kyverno, “Disallow Privileged Containers CEL Policy,” Kyverno v1.19.1 source, https://github.com/kyverno/kyverno/blob/40ec788d48bb28d83dbf85538e962a59db9d45c6/charts/kyverno-policies/templates/baseline/disallow-privileged-containers.cel.yaml, accessed September 19, 2026.

[6] Open Policy Agent, “Gatekeeper Library Privileged Containers Policy,” gatekeeper-library commit 22a40962, https://github.com/open-policy-agent/gatekeeper-library/blob/22a40962f83268769bcec5dfe55e44b5a85c392a/src/pod-security-policy/privileged-containers/src.cel, accessed September 19, 2026.

[7] Kubewarden, “Recommended Privileged Policy Template,” kubewarden-controller commit 23657f51, https://github.com/kubewarden/kubewarden-controller/blob/23657f51d11fbc75ecd94f69c32a89ee5901cfcf/charts/admission-controller/templates/defaults/policies/_pod-privileged.tpl, accessed September 19, 2026.

[8] Kubewarden, “Pod Privileged Policy,” Kubewarden policies source, https://github.com/kubewarden/policies/blob/fd4c5c98fa765d5ad3db1a89a7bc027ea0bc89ff/policies/pod-privileged-policy/src/lib.rs, accessed September 19, 2026.
