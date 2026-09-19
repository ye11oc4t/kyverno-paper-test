# Kubernetes 공개 컨테이너 보안 정책의 임시 컨테이너 적용 불일치에 대한 실제 실행 기반 평가

**A Live-Execution Evaluation of Ephemeral-Container Enforcement Inconsistencies in Public Kubernetes Security Policies**

저자 및 소속: 추후 기입

## 요약

Kubernetes 보안 정책은 일반 Pod 생성 시 위험한 컨테이너 설정을 거부하더라도, 실행 중인 Pod에 임시 컨테이너를 추가하는 하위 API에서는 같은 설정을 놓칠 수 있다. 본 연구는 Kyverno, Gatekeeper, Kubewarden이 배포하는 공개 정책 가운데 privileged, 권한 상승 허용, Linux capability 제한 정책을 대상으로 일반 컨테이너 생성과 임시 컨테이너 추가의 실제 집행 결과를 비교하였다. Kubernetes 1.35.8 단일 노드 kind 환경에서 제품별 세 차례 독립 설치를 수행하고, 설치마다 세 정책을 하나씩 격리하여 활성화한 뒤 정책별 다섯 차례 반복하였다. 총 135개 실험 단위에서 정상 일반 Pod, 위반 일반 Pod, 정상 임시 컨테이너, 위반 임시 컨테이너의 540개 요청을 실제 API 서버에 반영하였다. 모든 정상 사례는 저장되고 실행됐으며 모든 일반 위반은 정책에 의해 거부됐다. 반면 위반 임시 컨테이너는 아홉 개 제품·정책 조합의 135회 모두 허용되어 Pod 객체에 저장되고 컨테이너 런타임에서 실행됐다. 실행 프로세스에서는 privileged의 전체 유효 capability, 권한 상승 허용 사례의 `NoNewPrivs=0`, capability 사례의 `SYS_ADMIN` 비트를 확인하였다. 소스와 배포 구성을 대조한 결과, 원인은 하위 리소스 등록 누락, UPDATE 연산의 포괄적 생략, 임시 컨테이너 배열 순회 누락이 결합된 유효 적용 범위 불일치로 설명된다. 본 연구는 정책의 보안 조건뿐 아니라 API 라우팅, 연산 분기, 객체 순회, 저장 및 실행 결과를 함께 검증해야 한다는 평가 방법과 재현 가능한 실증 자료를 제공한다.

**주제어:** Kubernetes, admission control, ephemeral container, policy enforcement, Kyverno, Gatekeeper, Kubewarden

## I. 서론

Kubernetes는 컨테이너를 Pod라는 실행 단위로 관리한다. 클러스터 관리자는 admission control을 이용해 API 요청이 저장되기 전에 객체를 검사하고, `privileged: true`, 권한 상승 허용, 과도한 Linux capability와 같은 설정을 차단할 수 있다[1,2]. 이러한 정책은 공격자가 높은 권한의 컨테이너를 실행하는 행위뿐 아니라 개발자와 운영자의 설정 실수를 막는 예방 통제로 사용된다.

그러나 일반 Pod 생성에서 정책이 정상 작동한다는 사실만으로 실행 중인 Pod의 모든 변경에도 같은 보장이 유지된다고 판단할 수 없다. 임시 컨테이너는 이미 존재하는 Pod에 진단 목적으로 추가하는 컨테이너이며, 일반 Pod 생성과 다른 `pods/ephemeralcontainers` 하위 API를 사용한다[3,4]. 이 요청은 HTTP PATCH로 전송할 수 있지만 admission 요청에서는 UPDATE 연산으로 표현된다. 정책이 일반 `pods` 생성만 등록하거나 모든 UPDATE를 기존 Pod의 불변 필드 변경으로 간주해 생략하면, 새 임시 컨테이너의 보안 설정은 검사식에 도달하지 못한다.

이 공백이 발생하면 `pods/ephemeralcontainers` 권한을 가진 사용자는 일반 컨테이너에서는 거부되는 설정을 기존 Pod 안에서 실행할 수 있다. 공격자는 악성 이미지를 높은 권한으로 실행할 수 있고, 정상 운영자도 잘못된 진단 명령이나 보안 문맥을 정책의 제지 없이 배포할 수 있다. 실제 피해 범위는 노드 구성, 런타임, Pod의 네임스페이스 공유, 마운트, 추가 보안 통제에 따라 달라진다. 그럼에도 조직이 명시적으로 금지한 설정이 저장되고 실행된다는 사실 자체가 정책 보장의 실패다.

본 연구는 다음 세 질문에 답한다. 첫째, 선택한 공개 정책은 일반 컨테이너 위반과 임시 컨테이너 위반을 동일하게 거부하는가. 둘째, 허용된 위반값은 API 응답에만 나타나는가, 아니면 Pod 객체에 저장되고 실제 프로세스로 실행되는가. 셋째, 서로 다른 도구에서 같은 현상이 나타나는 구현 원인은 무엇이며 운영자와 정책 제작자는 어떤 층을 보완해야 하는가.

이를 위해 Kyverno, Gatekeeper, Kubewarden의 공개 정책 세 종류를 실제 클러스터에 설치하고, 정책별로 정상·위반 일반 컨테이너와 정상·위반 임시 컨테이너를 분리된 Pod에 생성하였다. 각 허용 사례는 API 재조회, 컨테이너 상태, 로그, Linux 프로세스 보안 상태로 검증했다. 제품별 세 차례 독립 설치와 설치당 다섯 회 반복을 통해 준비 지연이나 일회성 응답을 결과에서 분리하였다.

본 연구의 타겟 독자는 Kubernetes 정책을 선택·운영하는 플랫폼 엔지니어와 보안 담당자, 공개 정책을 유지보수하는 개발자다. 학술적 기여는 컨테이너 보안 조건의 의미와 API별 실제 적용 범위를 분리하는 네 단계 평가 모형을 제시하고, 서로 다른 세 정책 엔진에서 공통 현상을 실제 저장과 실행까지 확인한 데 있다. 실무적 기여는 일반 Pod 대조군만으로는 발견하기 어려운 미탐을 재현하는 시험 절차와 즉시 적용 가능한 방어 지점을 제공하는 데 있다. 본 연구는 세 제품 전체가 임시 컨테이너를 처리할 능력이 없다고 주장하지 않으며, 고정한 버전과 공개 정책 구성의 유효 적용 범위를 평가한다.

## II. 배경 및 문제 정의

### 2.1 임시 컨테이너와 하위 API

임시 컨테이너는 실행 중인 Pod를 조사할 때 추가할 수 있는 특수 컨테이너다. 일반 컨테이너처럼 Pod 생성 시 `spec.containers`에 포함되지 않고, 기존 Pod에 대해 `pods/ephemeralcontainers` 하위 리소스를 갱신하여 `spec.ephemeralContainers`에 추가된다[3]. 기존 일반 컨테이너의 보안 문맥이 생성 후 사실상 불변이라는 가정과 달리, 이 하위 API는 새로운 컨테이너 정의를 실행 중인 Pod에 도입한다.

Kubernetes RBAC는 하위 API 권한을 일반 Pod 권한과 별도로 부여할 수 있다. 따라서 `pods/ephemeralcontainers`의 patch 또는 update 권한이 없는 사용자는 요청 자체를 수행할 수 없다. 반면 그 권한을 가진 사용자의 요청 내용이 모두 안전하다는 보장은 없다. Kubernetes 설계 문서는 임시 컨테이너 권한을 제한하고 admission controller가 그 내용을 검사해야 한다고 설명한다[4]. RBAC는 “누가 요청할 수 있는가”를 통제하고 admission 정책은 “요청 내용이 허용되는가”를 통제한다.

### 2.2 보안 조건

`privileged: true`는 컨테이너 격리를 크게 완화하고 광범위한 Linux capability를 부여한다. `allowPrivilegeEscalation: true`는 프로세스가 set-user-ID 실행 파일이나 파일 capability 등을 통해 현재보다 높은 권한을 얻을 수 있게 하며, Linux의 `no_new_privs` 방어와 연결된다. Linux capability는 root 권한을 기능별 비트로 나눈 것이고, `SYS_ADMIN`은 마운트와 여러 커널 관리 기능에 관련된 범위가 넓은 capability다. Kubernetes Pod Security Standards는 privileged를 Baseline에서 제한하고, 권한 상승과 capability 추가를 Restricted에서 더 엄격히 제한한다[2].

본 연구의 공통 기대값은 선택한 공개 정책이 일반 컨테이너에서 거부한 동일 보안 속성을 임시 컨테이너에서도 거부하는 것이다. 정상 입력을 거부하면 오탐, 위반값을 허용해 객체에 저장하면 미탐으로 정의한다. 실행 결과까지 확인한 이유는 admission 응답의 2xx가 실제 위험 상태로 이어졌는지를 구분하기 위해서다. 관찰한 미탐 수는 통제된 입력에 대한 재현 횟수이며 실제 운영 환경의 발생률이나 제품 전체의 탐지율을 뜻하지 않는다.

### 2.3 정책 유효 적용 범위의 네 단계

정책이 임시 컨테이너에 유효하게 적용되려면 네 단계가 모두 연결되어야 한다. 첫째, 정책 또는 웹훅 등록 규칙이 `pods/ephemeralcontainers` 요청을 받아야 한다. 둘째, UPDATE 연산을 일반 Pod 변경과 임시 컨테이너 추가로 구분해야 한다. 셋째, 정책식이나 모듈이 `containers`, `initContainers`, `ephemeralContainers`의 보안 필드를 실제로 순회해야 한다. 넷째, 최종 API 응답, 저장 객체, 런타임 상태가 정책의 보안 의미와 일치해야 한다.

이 구분이 필요한 이유는 소스에 `ephemeralContainers`라는 문자열이 있어도 요청 라우팅에서 제외될 수 있고, 요청이 엔진에 도달해도 UPDATE 예외 조건에서 통과할 수 있기 때문이다. 반대로 하위 API를 전부 차단하면 위반은 막지만 정상적인 진단 컨테이너도 사용할 수 없다. 따라서 위반 사례와 정상 사례를 함께 측정해야 한다.

### 2.4 알려진 문제와 연구 위치

임시 컨테이너의 admission 필요성은 새로운 주장이 아니다. Kubernetes KEP-277은 이 위험과 통제 지점을 명시했고[4], Kyverno 이슈 #2821에도 임시 컨테이너 요청 지원 문제가 기록되어 있다[6]. 본 연구의 새 기여는 필요성을 제안하는 데 있지 않다. 최신 공개 정책 형식과 배포 구성에서 세 보안 정책군의 불일치를 실제 저장·실행까지 동일한 방법으로 측정하고, 공통 원인을 정책 유효 적용 범위의 층으로 연결한 것이 기여다.

## III. 연구 방법

### 3.1 평가 대상 및 환경

평가 대상은 공개 소스와 배포 정책을 확인할 수 있고 서로 다른 실행 구조를 사용하는 Kyverno, Gatekeeper, Kubewarden이다. 이 표본은 목적 표집이므로 모든 Kubernetes 정책 도구의 결함률을 추정하는 데 사용할 수 없다. 실험 환경은 Windows 호스트의 WSL2 Ubuntu 24.04, Docker 기반 단일 노드 kind, Kubernetes 1.35.8, containerd 런타임이다.

**표 1. 평가 대상**

| 제품 | 엔진·차트 버전 | 평가한 공개 정책 |
|---|---|---|
| Kyverno | 앱 1.19.1, `kyverno`·`kyverno-policies` 차트 3.9.1 | CEL ValidatingPolicy의 `disallow-privileged-containers`, `disallow-privilege-escalation`, `disallow-capabilities-strict` |
| Gatekeeper | 3.23.1, gatekeeper-library 커밋 `22a40962f83268769bcec5dfe55e44b5a85c392a` | privileged-containers, allow-privilege-escalation, capabilities ConstraintTemplate·Constraint |
| Kubewarden | 앱 1.37.2, admission-controller 차트 6.0.2 | `pod-privileged`, `allow-privilege-escalation-psp`, `capabilities-psp` 모듈 v1.0.13의 protect 구성 |

제품은 각각 별도 클러스터에 설치했으며 다른 제3자 정책 엔진은 함께 설치하지 않았다. 같은 제품에서도 세 정책군을 동시에 활성화하지 않고 하나씩 적용했다. 이는 한 정책의 위반 입력이 다른 정책에 의해 먼저 거부되는 교란을 제거하기 위한 조치다. Kyverno는 정책 상태의 ready 값을, Gatekeeper는 ConstraintTemplate가 생성한 ValidatingAdmissionPolicyBinding의 존재를, Kubewarden은 ClusterAdmissionPolicy의 active 상태를 확인한 뒤 요청을 시작했다.

### 3.2 실험 사례

정책별 한 실험 단위는 표 2의 네 사례로 구성된다. 정상 일반 Pod와 위반 일반 Pod는 서로 다른 객체로 생성한다. 정상 임시 컨테이너와 위반 임시 컨테이너도 각각 별도의 기존 Pod에 추가하여 앞선 요청의 영향을 제거했다.

**표 2. 실험 사례와 기대값**

| 사례 | 실제 API 요청 | 입력 | 기대값 |
|---|---|---|---|
| C0 | `POST .../pods` | 정책을 준수하는 일반 컨테이너 | 허용·저장·실행 |
| C1 | `POST .../pods` | 해당 정책의 위반 일반 컨테이너 | 거부·미저장 |
| C2 | `PATCH .../pods/{name}/ephemeralcontainers` | 정책을 준수하는 임시 컨테이너 | 허용·저장·실행 |
| C3 | `PATCH .../pods/{name}/ephemeralcontainers` | 해당 정책의 위반 임시 컨테이너 | 거부·미저장 |

모든 정상 컨테이너는 `privileged: false`, `allowPrivilegeEscalation: false`, `capabilities.drop: [ALL]`, `runAsUser: 65532`, `seccompProfile: RuntimeDefault`를 사용했다. privileged 위반은 `privileged: true`, 권한 상승 위반은 비 root 사용자에서 `allowPrivilegeEscalation: true`, capability 위반은 `capabilities.add: [SYS_ADMIN]`을 사용했다. capability가 실제 프로세스에 적용됐는지 보기 위해 해당 위반 컨테이너는 UID 0으로 실행했다. 각 정책군은 하나씩 격리되어 있으므로 이 차이가 다른 평가 정책의 판정을 유발하지 않는다.

### 3.3 실제 저장 및 실행 판정

전용 ServiceAccount에 실험 네임스페이스의 Pod create·get·list·delete와 `pods/ephemeralcontainers` get·patch·update 권한을 부여했다. 제3자 정책의 결과를 내장 Pod Security Admission이 대신 차단하지 않도록 해당 네임스페이스의 Pod Security 수준은 privileged로 설정했다. 모든 C0~C3 요청은 ServiceAccount 토큰으로 API 서버에 직접 전송했다.

허용은 2xx 상태 코드만으로 판정하지 않았다. 요청 뒤 API 서버에서 Pod를 다시 조회하여 컨테이너 정의가 저장됐는지 확인하고, `containerStatuses` 또는 `ephemeralContainerStatuses`가 Running이나 Terminated에 도달했는지 확인했다. 이어서 컨테이너 로그의 `id`, `/proc/self/status`의 `CapEff`와 `NoNewPrivs`를 수집했다. privileged는 0이 아닌 전체 capability와 `NoNewPrivs=0`, 권한 상승 허용은 `NoNewPrivs=0`, `SYS_ADMIN` 사례는 capability 비트 21이 설정되어야 런타임 효과가 관찰된 것으로 판정했다.

C1의 거부는 대상 정책의 메시지를 포함한 4xx 응답과 객체 미존재를 함께 확인했다. 인증, RBAC, JSON 형식, Kubernetes 필드 검증 오류는 정책 탐지로 세지 않았다. C0와 C2는 정책 엔진과 이미지 실행 경로가 정상임을 확인하는 양성 대조군이다.

### 3.4 반복과 관측 규모

제품마다 새 kind 클러스터를 세 번 만들고 엔진을 독립 설치했다. 각 설치에서 세 정책군을 하나씩 활성화하고 정책군마다 다섯 차례 반복하였다. 따라서 제품·정책군 조합당 15개, 제품당 45개, 전체 135개 실험 단위가 생성됐다. 한 단위에는 네 API 요청이 있으므로 분석한 요청은 540개다. 같은 설치 안의 다섯 반복은 서로 다른 환경 표본이 아니라 반복 가능성 확인이며, 독립 설치 수는 제품당 세 개다.

각 반복이 끝나면 실험 네임스페이스를 제거했다. 요청 본문, HTTP 헤더·상태·응답, API 재조회 객체, 컨테이너 로그, 이벤트를 제품·설치·정책군·반복 경로에 보관했다. 원자료와 집계 산출물을 분리하고 증거 파일의 SHA-256 목록을 생성했다.

### 3.5 내장 통제 대조군

관찰된 허용이 Kubernetes가 임시 컨테이너를 정책 검사에서 의도적으로 제외했기 때문인지 확인하기 위해 별도 클러스터에서 실제 요청 대조 실험을 수행했다. 첫째, Pod Security Admission Baseline 네임스페이스에서 하위 API 권한이 있는 ServiceAccount로 정상 임시 컨테이너와 privileged 임시 컨테이너를 각각 추가했다. 둘째, Pod Security 수준을 privileged로 둔 네임스페이스에서 하위 API 권한이 없는 ServiceAccount로 privileged 임시 컨테이너를 추가했다.

## IV. 실험 결과

### 4.1 전체 판정 결과

135개 C0 정상 일반 Pod는 모두 HTTP 201로 저장되고 실행됐으며, 135개 C2 정상 임시 컨테이너는 모두 HTTP 200으로 저장되고 실행됐다. 따라서 정상 사례의 관찰된 오탐은 0/270이다. C1 일반 위반 135개는 모두 대상 정책에 의해 거부되어 저장되지 않았다. Kyverno와 Kubewarden은 HTTP 400, 준비가 완료된 Gatekeeper의 내장 정책 경로는 HTTP 422를 반환했다.

반면 C3 위반 임시 컨테이너 135개는 모두 HTTP 200으로 허용됐다. API 재조회에서 135개 모두 `spec.ephemeralContainers`에 위반값이 남아 있었고, 런타임 상태도 135개 모두 Running에 도달했다. 공통 기대값에 대한 관찰된 미탐은 135/135다. 이는 제품별 세 설치와 모든 반복에서 동일했다.

**표 3. 제품·정책군별 실제 판정 결과**

| 제품 | 정책군 | 일반 위반 거부 | 임시 위반 허용 | API 저장 | 실제 실행 | 런타임 효과 |
|---|---|---:|---:|---:|---:|---:|
| Kyverno | privileged | 15/15 | 15/15 | 15/15 | 15/15 | 15/15 |
| Kyverno | 권한 상승 | 15/15 | 15/15 | 15/15 | 15/15 | 15/15 |
| Kyverno | capabilities | 15/15 | 15/15 | 15/15 | 15/15 | 15/15 |
| Gatekeeper | privileged | 15/15 | 15/15 | 15/15 | 15/15 | 15/15 |
| Gatekeeper | 권한 상승 | 15/15 | 15/15 | 15/15 | 15/15 | 15/15 |
| Gatekeeper | capabilities | 15/15 | 15/15 | 15/15 | 15/15 | 15/15 |
| Kubewarden | privileged | 15/15 | 15/15 | 15/15 | 15/15 | 15/15 |
| Kubewarden | 권한 상승 | 15/15 | 15/15 | 15/15 | 15/15 | 15/15 |
| Kubewarden | capabilities | 15/15 | 15/15 | 15/15 | 15/15 | 15/15 |

### 4.2 런타임 보안 상태

정상 임시 컨테이너의 `CapEff`는 전 사례에서 `0000000000000000`, `NoNewPrivs`는 1이었다. privileged 임시 컨테이너는 UID 0, `CapEff=000001ffffffffff`, `NoNewPrivs=0`으로 실행됐다. 권한 상승 허용 임시 컨테이너는 UID 65532와 빈 capability 집합을 유지했지만 `NoNewPrivs=0`이었다. 따라서 현재 권한이 즉시 증가한 것은 아니어도, 정책이 금지하려던 권한 상승 가능 상태가 런타임에 적용됐다. capability 위반 임시 컨테이너의 `CapEff`는 `0000000000200000`으로, `SYS_ADMIN`에 해당하는 비트 21이 활성화됐다.

**표 4. 위반 임시 컨테이너의 실제 프로세스 상태**

| 정책군 | UID | `CapEff` | `NoNewPrivs` | 의미 |
|---|---:|---|---:|---|
| privileged | 0 | `000001ffffffffff` | 0 | 광범위한 capability가 실제 활성화됨 |
| 권한 상승 허용 | 65532 | `0000000000000000` | 0 | 권한 상승 방지 플래그가 설정되지 않음 |
| capabilities | 0 | `0000000000200000` | 1 | `SYS_ADMIN` 비트가 실제 활성화됨 |

본 실험은 호스트 파일 접근, 컨테이너 탈출, 노드 장악을 시도하지 않았다. 표 4는 정책 위반 설정이 저장에 그치지 않고 컨테이너 프로세스의 보안 상태로 이어졌음을 입증하는 범위의 결과다.

### 4.3 내장 통제 대조 결과

Pod Security Admission Baseline은 정상 임시 컨테이너를 HTTP 200으로 허용했고 해당 컨테이너는 Running 상태가 됐다. 같은 권한을 가진 ServiceAccount가 privileged 임시 컨테이너를 추가하자 HTTP 403으로 거부했으며 Pod 객체에는 저장되지 않았다. Pod Security 수준이 privileged인 네임스페이스에서도 하위 API 권한이 없는 ServiceAccount의 요청은 RBAC가 HTTP 403으로 거부했고 저장되지 않았다.

이 결과는 임시 컨테이너가 Kubernetes 설계상 무조건적인 정책 예외라는 설명과 맞지 않는다. 안전한 진단 컨테이너를 허용하면서 위험한 보안 설정만 내용 기반으로 거부할 수 있으며, 필요하면 RBAC로 추가 경로 자체를 제한할 수도 있다.

### 4.4 제품별 구현 원인

Kyverno의 평가 대상 CEL 정책은 검사식에서 `ephemeralContainers`를 읽지만 `matchConstraints.resourceRules.resources`에는 일반 `pods`만 포함한다[5]. 실제 임시 컨테이너 추가는 `pods/ephemeralcontainers` 하위 리소스이므로 검사식이 존재해도 요청이 해당 정책에 연결되지 않는다. 일반 Pod 위반이 매번 거부되고 하위 API 위반만 허용된 결과가 이 라우팅 차이와 일치한다.

Gatekeeper의 평가 대상 템플릿은 컨테이너 수집 변수에 임시 컨테이너를 포함하지만, K8sNativeValidation 표현식은 UPDATE 요청을 검사 결과와 관계없이 참으로 처리하고 Rego 구현도 UPDATE를 제외한다[7]. Gatekeeper가 생성한 ValidatingAdmissionPolicy는 일반 Pod 위반을 거부했지만 하위 API 위반은 최종적으로 통과했다. 즉 객체 순회 코드의 존재만으로 충분하지 않으며, 요청 등록과 UPDATE 분기가 함께 임시 컨테이너 경로를 보존해야 한다.

Kubewarden의 공개 정책 객체는 privileged와 권한 상승 정책의 Pod 규칙을 CREATE 중심으로 등록하고, capability 정책도 일반 `pods`의 CREATE·UPDATE만 지정한다[8]. `pod-privileged` 설정에는 임시 컨테이너를 건너뛰지 않도록 하는 값이 존재하지만 하위 API 요청이 모듈에 전달되지 않으면 그 검사 능력은 사용되지 않는다. 권한 상승과 capability 모듈은 소스 수준에서 임시 컨테이너 배열의 순회 여부도 별도로 확인해야 한다[9]. 세 정책군의 일반 위반 거부와 하위 API 위반 허용은 공개 정책 규칙의 요청 범위가 최소한 하나의 충분한 원인임을 보여 준다.

세 제품의 세부 구현은 다르지만 공통 전제는 같다. 일반 Pod가 생성된 뒤 기존 컨테이너의 보안 필드는 변경되지 않는다는 가정 때문에 `pods` CREATE에 집중하거나 UPDATE를 생략했다. 임시 컨테이너는 기존 필드를 수정하지 않으면서 UPDATE 형식의 하위 API로 새 컨테이너를 추가하므로 이 최적화의 경계 밖에 놓였다.

## V. 논의

### 5.1 의도된 예외인가

관찰된 현상을 임시 컨테이너의 의도된 무검사로 해석하기는 어렵다. Kubernetes 설계 문서는 admission controller가 임시 컨테이너 보안 설정을 검사할 수 있어야 한다고 설명하고[4], Pod Security Admission은 본 대조 실험에서 실제로 위험값을 차단했다. Kyverno 정책식과 Gatekeeper 템플릿은 임시 컨테이너 배열을 명시적으로 참조한다. Kubewarden privileged 정책에도 임시 컨테이너 검사 여부를 제어하는 설정이 있다. 이 근거는 제작자가 임시 컨테이너를 보안 의미에서 제외하려 했다기보다 정책 의미와 API 연결 범위가 분리된 것으로 해석하는 편을 지지한다.

다만 본 연구는 커밋 작성자의 역사적 의도를 직접 조사하지 않았다. 따라서 세 제품 전체의 공식 지원 약속 위반이라고 일반화하지 않고, 평가한 공개 정책 구성에서 공통 기대값과 실제 집행 범위가 불일치했다고 결론 내린다.

### 5.2 보안 및 운영 영향

공격이 성립하려면 주체가 대상 네임스페이스의 `pods/ephemeralcontainers` patch 또는 update 권한을 가져야 한다. 이 권한은 장애 대응과 디버깅을 위해 운영자, 개발자, 자동화 계정에 부여될 수 있다. 일반 Pod에서 같은 설정이 거부되는 모습을 본 관리자는 해당 정책이 컨테이너 종류와 관계없이 적용된다고 오해할 수 있다. 그 결과 악성 이미지뿐 아니라 잘못 작성된 진단 명령도 기존 서비스 Pod 안에서 예상보다 높은 권한으로 실행될 수 있다.

privileged와 `SYS_ADMIN`은 커널 공격 표면과 격리 우회 가능성을 늘린다. `allowPrivilegeEscalation: true`는 단독으로 권한을 즉시 높이지 않지만 이미지 안의 setuid 실행 파일이나 파일 capability 등 다른 조건과 결합될 수 있다. 실제 영향은 노드 격리, 사용자 네임스페이스, seccomp, AppArmor·SELinux, 볼륨과 소켓 노출에 따라 달라진다. 본 결과는 그러한 후속 공격의 성공률이 아니라 정책이 막기로 한 첫 단계가 실행까지 통과한다는 점을 입증한다.

### 5.3 완화 및 수정 방향

운영자는 `pods/ephemeralcontainers` 권한을 별도 역할로 분리하고 필요한 사용자와 자동화에만 부여해야 한다. 가능한 네임스페이스에는 Pod Security Admission Baseline 또는 Restricted를 적용하면 제3자 정책의 경로 누락이 있더라도 위험 설정을 추가로 차단할 수 있다. 본 대조 실험은 이 두 통제가 실제 요청에서 작동함을 확인했다.

정책 제작자는 세 층을 함께 수정해야 한다. 등록 규칙에는 `pods/ephemeralcontainers`와 UPDATE를 포함하고, 일반 Pod의 불변 필드를 위한 UPDATE 생략 조건은 임시 컨테이너 하위 리소스에 적용하지 않아야 한다. 정책식과 모듈은 일반·초기화·임시 컨테이너 배열을 동일한 보안 의미로 순회해야 한다. Kyverno CEL 정책은 하위 리소스 매칭을 추가하고, Gatekeeper 템플릿은 임시 컨테이너 UPDATE를 검사하도록 연산 분기를 좁혀야 하며, Kubewarden은 정책 규칙과 모듈 순회를 함께 확인해야 한다.

회귀 시험도 실제 API 경로를 사용해야 한다. 일반 Pod의 정상·위반 두 사례와 임시 컨테이너의 정상·위반 두 사례를 모두 실행하고, 응답 코드만이 아니라 저장 객체와 컨테이너 상태를 확인해야 한다. 이렇게 해야 라우팅 누락, 광범위한 UPDATE 예외, 검사 대상 배열 누락을 한 시험 행렬에서 구분할 수 있다.

### 5.4 학술적·실무적 기여와 한계

학술적으로 본 연구는 정책의 선언된 조건과 실제 적용 범위를 분리하고, 라우팅·연산·순회·최종 집행의 네 층으로 분석하는 방법을 제시했다. 서로 다른 세 엔진과 세 정책군에서 같은 결과가 나타난 것은 특정 정책 파일 하나의 오타보다 API 생명주기 변화와 기존 불변 가정의 충돌이 반복 가능한 연구 대상임을 보여 준다. 실제 저장과 런타임 프로세스 상태를 포함한 자료는 단순 정적 분석과 응답 비교보다 강한 실증 근거를 제공한다.

실무적으로는 사용 중인 정책이 일반 Pod를 거부한다는 사실만으로 보호 범위를 판단해서는 안 된다는 점, 하위 API 권한과 내용 검사를 함께 점검해야 한다는 점, 안전한 임시 컨테이너를 유지하면서 위험 설정만 차단할 수 있다는 점을 제시한다. 공개한 실행기와 증거 구조는 제품 버전 변경 시 회귀 시험으로 재사용할 수 있다.

한계도 존재한다. 실험은 Kubernetes 1.35.8, 단일 노드 kind, Linux containerd, 고정한 제품 버전에서 수행했다. 관리형 Kubernetes, 고가용성 구성, Windows 컨테이너, 다른 런타임과 최신·과거 제품 버전은 별도 검증이 필요하다. 세 제품과 세 정책은 목적 표집이므로 정책 생태계 전체의 미탐률을 추정할 수 없다. 설치당 다섯 반복은 재현성을 보여 주지만 서로 독립적인 운영 환경 15개를 뜻하지 않는다. 실제 공격 성공이나 피해 규모도 측정하지 않았다. 향후 연구에서는 제품별 수정본을 실제 하위 API 회귀 시험에 적용하고, 다른 하위 리소스와 정책군, 관리형 환경, 버전별 회귀 시점을 확대할 필요가 있다.

## VI. 결론

본 연구는 Kyverno, Gatekeeper, Kubewarden의 선택한 공개 정책에서 일반 컨테이너와 임시 컨테이너 사이의 집행 불일치를 실제 저장과 실행으로 확인했다. 세 제품, 세 정책군, 제품별 세 독립 설치와 설치당 다섯 반복으로 구성한 135개 실험 단위에서 정상 사례는 모두 허용·실행됐고 일반 위반은 모두 거부됐다. 그러나 위반 임시 컨테이너 135개는 모두 허용·저장·실행됐으며 privileged capability, 권한 상승 가능 상태, `SYS_ADMIN` 비트가 실제 프로세스에 적용됐다.

도출된 미탐은 임시 컨테이너가 진단용이라는 이름 때문에 안전한 것이 아니며, 정책의 보안 의미가 API 생명주기 전체에 연결되어야 함을 뜻한다. 원인은 제품별로 하위 리소스 등록, UPDATE 분기, 컨테이너 배열 순회의 층에서 나타났다. 반면 정상 입력의 관찰된 오탐은 없었고 Kubernetes 내장 PSA와 RBAC는 같은 실제 요청을 선택적으로 차단했다.

이 결과가 주는 시사점은 정책 보장을 일반 Pod 검사나 정책식의 존재만으로 평가할 수 없다는 것이다. 운영자는 하위 API 권한과 다중 방어를 점검해야 하고, 정책 제작자는 등록 규칙부터 런타임 결과까지 포함하는 회귀 시험을 갖춰야 한다. 향후 수정 정책과 더 넓은 제품·환경을 같은 방법으로 평가하면 Kubernetes 정책의 유효 적용 범위를 체계적으로 비교하고 API 확장에 따른 회귀를 조기에 발견할 수 있다.

## 참고문헌

[1] Kubernetes, “Dynamic Admission Control,” Kubernetes Documentation, https://kubernetes.io/docs/reference/access-authn-authz/extensible-admission-controllers/, accessed September 19, 2026.

[2] Kubernetes, “Pod Security Standards,” Kubernetes Documentation, https://kubernetes.io/docs/concepts/security/pod-security-standards/, accessed September 19, 2026.

[3] Kubernetes, “Ephemeral Containers,” Kubernetes Documentation, https://kubernetes.io/docs/concepts/workloads/pods/ephemeral-containers/, accessed September 19, 2026.

[4] Kubernetes SIG Node, “KEP-277: Ephemeral Containers,” Kubernetes Enhancements, https://github.com/kubernetes/enhancements/blob/master/keps/sig-node/277-ephemeral-containers/README.md, accessed September 19, 2026.

[5] Kyverno, “Disallow Privileged Containers CEL Policy,” Kyverno v1.19.1 source, https://github.com/kyverno/kyverno/blob/40ec788d48bb28d83dbf85538e962a59db9d45c6/charts/kyverno-policies/templates/baseline/disallow-privileged-containers.cel.yaml, accessed September 19, 2026.

[6] Kyverno, “Support Ephemeral Containers,” issue #2821, https://github.com/kyverno/kyverno/issues/2821, accessed September 19, 2026.

[7] Open Policy Agent, gatekeeper-library, commit `22a40962f83268769bcec5dfe55e44b5a85c392a`, https://github.com/open-policy-agent/gatekeeper-library/tree/22a40962f83268769bcec5dfe55e44b5a85c392a/library/pod-security-policy, accessed September 19, 2026.

[8] Kubewarden, admission-controller chart 6.0.2 recommended policy templates, https://github.com/kubewarden/kubewarden-controller/tree/23657f51d11fbc75ecd94f69c32a89ee5901cfcf/charts/admission-controller, accessed September 19, 2026.

[9] Kubewarden, policy modules, commit `fd4c5c98fa765d5ad3db1a89a7bc027ea0bc89ff`, https://github.com/kubewarden/policies/tree/fd4c5c98fa765d5ad3db1a89a7bc027ea0bc89ff/policies, accessed September 19, 2026.

## 재현 자료

- 실행기: `experiments/ephemeral-api-coverage/run-live-study.sh`, `run-live-matrix-case.sh`
- 집계기: `experiments/ephemeral-api-coverage/aggregate_live_matrix.py`
- 본실험 원자료와 집계: `experiments/ephemeral-api-coverage/results/2026-09-19-live-matrix/`
- 내장 통제 대조: `experiments/ephemeral-api-coverage/results/2026-09-19-live-native-controls/`
- 증거 해시: `experiments/ephemeral-api-coverage/results/2026-09-19-live-matrix/evidence-sha256.json`
