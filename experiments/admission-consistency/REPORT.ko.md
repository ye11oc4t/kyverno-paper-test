# 일반·Ephemeral 컨테이너의 Admission 정책 일관성 파일럿

실행일: 2026-09-19 KST · 호스트: KSYBOB · 사전 설계: [연구 프로토콜](../../research/ephemeral-policy-consistency/PROTOCOL.ko.md)

후속 검토: [확장 실험 v2](../admission-consistency-v2/REPORT.ko.md)는 이 결과의 입력 중복과 추론 범위를 재검토하고 Kubewarden 및 Polaris를 추가했다. 아래 원래 측정 결과와 원본은 보존한다.

세 엔진의 주 분석 72회 실행에서 기대값과 실제 Admission·객체·실행 관측이 모두 일치했다. 이번 조건에서는 일반·Ephemeral 컨테이너 간 정책 판정 불일치가 관측되지 않았다. 따라서 이 결과는 “Kubernetes 정책 도구들이 공통으로 놓치는 결함”이라는 주장을 뒷받침하지 않는다. 엔진당 8개 계획 사례를 세 번 반복한 결과이며, 72개의 독립된 사례나 모든 보안 정책에 대한 안전성 입증은 아니다.

## 평가 질문과 방법

이 파일럿은 일반 컨테이너를 포함한 Pod 생성과 실행 중인 Pod에 Ephemeral Container를 추가하는 요청에서, 두 유형을 모두 대상으로 명시한 정책이 같은 규범 기대값을 지키는지 평가한다. 사용자 제공 SA 논문에서는 주장과 실제 성립 조건을 구분하고 독립 관측으로 검증하는 글의 구조만 참고했다. SA 자동 마운트나 인증 가능성은 평가 변수가 아니다.

시험 규칙은 컨테이너 이름의 `study-` 접두사와 사전에 정한 이미지 식별자다. 이미지 식별자 두 개는 같은 무해한 pause 이미지 내용을 가리킨다. 각 규칙에 대해 일반·Ephemeral 유형과 적합·부적합 입력을 조합했다. 엔진당 계획 사례는 8개이며 이를 같은 엔진 클러스터에서 세 번 반복한다. 서로 다른 엔진은 각각 새 클러스터에서 실행하고, 사례마다 새 Pod를 사용한다. 세 번의 반복은 기능 재현성 확인이며 독립된 환경 표본 세 개가 아니다.

여기서 8개는 계획된 요인 조합의 수다. 두 규칙을 함께 설치하고 부적합 사례에서는 해당 규칙의 필드 하나만 변경한다. 두 규칙의 적합 사례는 같은 컨테이너 설정을 재사용하므로 서로 다른 정책 의미를 가진 독립 입력으로 해석하지 않는다.

정책은 이 연구에서 직접 작성했으며 일반 컨테이너와 Ephemeral Container 필드를 모두 검사한다. VAP와 Kyverno는 CEL 표현식을, Gatekeeper는 같은 의도의 Rego 제약을 사용한다. 이 비교는 명시한 사용자 정의 정책의 일관성 평가다. 공개 정책 라이브러리의 기본 범위나 모든 보안 정책을 표집한 결과가 아니다. 두 요청은 객체 구조와 컨테이너 유형도 달라지므로, 결과를 API 경로 하나의 인과 효과로 해석하지 않는다.

## 환경과 관측

| 항목 | 고정 값 |
| --- | --- |
| 호스트 | KSYBOB, WSL2 Ubuntu 24.04, Docker 29.8.0 |
| 클러스터 | kind v0.33.0, Kubernetes v1.35.8, 단일 노드 |
| VAP | Kubernetes v1.35.8 내장 기능 |
| Kyverno | v1.19.1, `ValidatingPolicy` API |
| Gatekeeper | v3.23.1, `ConstraintTemplate` 및 제약 |
| 시험 이미지 | pause 3.10, digest 고정, 동일 내용의 두 로컬 별칭 |
| 기본 보안 통제 | 시험 namespace의 PSA restricted v1.35 |

각 실행의 `frozen-inputs.json`은 실행 코드, 기대값, 정책, 설치 manifest의 해시와 이미지 ID를 기록한다. `runner-used.py`와 `expectations-used.csv`는 실제 측정에 사용한 소스를 보존한다. Kubernetes 버전은 Kyverno 1.19의 문서상 지원 범위인 1.33–1.35 안에서 선택했다. [Kyverno 지원 버전](https://kyverno.io/docs/installation/releases/)

적합 입력의 성공 조건은 API 허용, 대상 필드 저장, 무해한 시험 컨테이너 시작의 동시 확인이다. 부적합 입력은 해당 시험 규칙의 명시적 거부 메시지가 있고 입력이 저장되지 않아야 성공으로 센다. RBAC 오류나 이미지 시작 실패를 정책 차단으로 세지 않는다. 감사 로그는 요청 이름·namespace·동작·subresource로 연결하고, API 결과뿐 아니라 제출한 이름·이미지 및 거부 메시지도 대조한다. 정상 base Pod 생성과 감사·정책 준비 점검은 측정 횟수에서 제외한다.

허용된 요청에 대해서는 이 증거만으로 개별 정책 표현식의 평가를 직접 입증하지 못하므로 평가 증거를 `UNKNOWN`으로 기록한다. 명시적 거부에는 `EXPLICIT_RULE_DENIAL`을 기록한다. 감사 로그, 클라이언트 출력, 객체 상태라는 서로 다른 관측을 대조했지만 별도 외부 검토자의 검증은 수행하지 않았다.

Kyverno의 최종 정책 상태는 `WebhookConfigured=True`와 함께 `RBACPermissionsGranted=False`, `ready=false`를 기록했다. 상태 메시지는 Ephemeral Container subresource에 대한 보고 기능의 읽기 권한 부족을 가리킨다. 실제 Admission 거부 응답에는 Kyverno의 `vpol.validate` webhook과 해당 규칙 메시지가 있고, 아래 Admission 관측은 기대값과 일치했다. 보고 기능까지 정상이라고 간주하지 않으며, 이 상태를 해소하려고 실험 도중 권한을 변경하지 않았다. 원문은 [Kyverno 정책 상태](results/20260918T151828Z-kyverno/final-policies.json)에 보존했다.

Gatekeeper의 최종 제약 상태는 세 webhook 컨트롤러에서 `enforced=true`를 기록했다. 동시에 audit 컨트롤러의 `vap.k8s.io` 항목에는 `K8sNativeValidation engine is missing`이 있고 audit 컨테이너의 재시작 횟수는 2였다. 본 시험의 template은 Rego 구현이며 거부 응답은 Gatekeeper webhook에서 관측했다. 이 결과로 VAP 생성이나 audit 컨트롤러의 정상 동작까지 보증하지 않는다. [Gatekeeper 제약 상태](results/20260918T152255Z-gatekeeper/final-policies.json), [컨트롤러 상태](results/20260918T152255Z-gatekeeper/engine-pods.json)

## 주 분석 결과

세 엔진 모두 적합 입력 12건을 허용·저장·시작했고 부적합 입력 12건을 해당 시험 규칙으로 거부했다. 각 엔진의 8개 계획 사례는 세 번의 반복에서 같은 결과를 냈다. 표의 성공은 측정한 계약의 일치를 뜻하며 제품의 모든 하위 기능이 정상이라는 뜻은 아니다.

| 엔진 | 기대값 일치 | 감사 로그 대조 | 원본 요청·관측 대조 | 적합 허용 / 부적합 거부 |
| --- | --- | --- | --- | --- |
| VAP | 24/24 | 24/24 | 24/24 | 12 / 12 |
| Kyverno | 24/24 | 24/24 | 24/24 | 12 / 12 |
| Gatekeeper | 24/24 | 24/24 | 24/24 | 12 / 12 |
| 합계 | 72/72 | 72/72 | 72/72 | 36 / 36 |

집계 원본은 [crosscheck.json](results/crosscheck.json)이다. 허용·거부의 양쪽 결과가 모두 기대값과 일치해야 성공으로 계산한다.

일반 컨테이너와 Ephemeral Container의 각 경로는 36/36건이 기대값과 일치했다. 엔진·규칙·적합성·반복을 고정한 대응쌍은 36/36쌍에서 양쪽 모두 기대대로 판정됐다. 허용된 36건의 개별 정책 평가 증거는 `UNKNOWN`이고 거부된 36건은 명시적 시험 규칙 거부 증거가 있다.

주 분석 실행은 [VAP](results/20260918T151413Z-vap/evidence-crosscheck.json), [Kyverno](results/20260918T151828Z-kyverno/evidence-crosscheck.json), [Gatekeeper](results/20260918T152255Z-gatekeeper/evidence-crosscheck.json)다. 입력 동결 해시와 기대값 원본도 모두 일치했다. 시험 종료 후 남은 kind 클러스터와 실행 중인 Docker 컨테이너가 없음을 확인했다. 재실행용 도구와 이미지 캐시는 남겨 두었다.

## 시행착오와 제외 기록

성공한 실행만 남기는 대신 모든 시도와 원본 기록을 보존했다. 준비 실패와 계측 불충분은 제품의 정책 판정 오류로 세지 않았다.

| 실행 ID | 측정 횟수 | 처리와 이유 |
| --- | --- | --- |
| `20260918T151000Z-vap` | 0 | Docker 이미지 가져오기 실패. 아키텍처를 지정한 이미지 archive로 수정 |
| `20260918T151058Z-vap` | 24 | 판정은 모두 일치했으나 감사 로그가 없어 주 분석에서 제외. kubeadm patch를 수정하고 감사 준비 확인을 추가 |
| `20260918T151227Z-kyverno` | 0 | 감사 설정 문제를 확인하여 설치 중 중단. 원본 MISMATCH 표기는 정책 판정이 아님 |
| `20260918T151541Z-kyverno` | 0 | 정책 등록 시 webhook 연결 거부로 종료. 준비 단계의 연결 오류에 한정한 대기를 추가 |
| `20260918T152031Z-gatekeeper` | 0 | 실행 스크립트가 생성된 제약 리소스 이름을 잘못 가정하여 준비 확인 실패. CRD의 실제 kind와 group으로 조회하도록 수정 |

Kyverno의 연결 실패는 deployment 준비 완료 직후 발생했다. 준비 시점 차이가 원인 후보이나 이 실행 하나로 근본 원인을 확정하지 않는다. 이후 Kyverno 실행에서는 정책 등록이 첫 시도에 성공했다. 측정 대상 요청은 자동 재시도하지 않았다. 모든 시도에서 해당 실행이 만든 클러스터를 정리했다. 측정 완료 실행 사이의 스크립트 변경은 이후 엔진의 준비·기록 절차에 관한 것이며, 정책 의미와 8개 기대값 및 측정 요청 절차는 유지했다. 실행별 원본 스크립트와 해시로 차이를 확인할 수 있다.

## 해석과 논문에서의 위치

정책이 존재한다는 사실과 운영 중 각 요청에 정책이 적용된다는 사실을 구분하는 것이 연구의 출발점이다. Kubernetes가 Ephemeral Container를 별도 subresource로 처리하므로, 정책 의도에서 실제 집행까지의 연결을 확인할 이유가 있다. 이 연결에 실제 누락이 있으면 운영자가 믿는 정책의 보장 범위와 저장·실행 가능한 상태가 달라질 수 있다. 다만 이 파일럿의 명명·이미지 식별 규칙만으로 실제 침해나 권한 획득을 입증할 수는 없다. [Ephemeral Containers](https://kubernetes.io/docs/concepts/workloads/pods/ephemeral-containers/), [Admission 매칭 규칙](https://kubernetes.io/docs/reference/access-authn-authz/extensible-admission-controllers/)

공백이 관측됐을 때 검토할 원인은 요청 적용 범위, 컨테이너 필드의 검사 범위, 예외·바인딩, 집행 모드 및 관측 누락이다. 이들은 사전 원인 후보이며 관측된 제품 결함 목록이 아니다. 방어적 개선은 정책의 약속과 실제 검사 범위를 명시하고 적합·부적합 대응 사례로 회귀 검증하는 방향이다. 현재 결과만으로 특정 Kyverno PR이 필요하다거나 여러 도구가 같은 결함을 갖는다고 결론 낼 수 없다.

이번 파일럿은 프로토콜의 RQ1에 대한 제한된 실증이다. 차이에 대한 RQ2, 공식 정책·예제 범위의 RQ3, 확인된 원인의 수정 전후 비교인 RQ4까지 완료했다고 주장하지 않는다. 공개 정책의 문서상 보장 범위와 실제 구현 범위를 조사하려면 별도의 출처 고정과 표집 기준이 필요하다. 이 결과를 이후 연구의 기준 실험으로 두고, 논문은 실제 확인한 범위에 맞춰 주장해야 한다.

버전 조합은 하나이고 클러스터는 엔진당 하나이며, 반복 순서는 고정되어 있다. 기본 설치 manifest의 장애 처리 설정도 완전히 동일하지 않다. 예를 들어 Gatekeeper의 validation webhook은 `failurePolicy: Ignore`를 사용하며 이 파일럿은 통신 장애나 fail-open 동작을 평가하지 않는다. 정상 동작 시 사용자 정의 규칙의 판정 일관성으로 결론을 한정한다. 다른 보안 목표, 초기화 컨테이너, 기존 Ephemeral Container가 있는 객체, 다른 subresource, 성능과 모든 공개 정책으로 일반화하지 않는다.

재실행 방법과 증거 파일 설명은 [README](README.md)에 있다.
