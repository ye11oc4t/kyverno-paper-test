# 72/72의 재해석과 조건·도구 확장

2026-09-19 KST · KSYBOB · [측정 전 계획](PLAN.ko.md)

이전 72/72는 실제 관측된 결과였지만, 원래 연구 질문을 답하기에는 설계가 좁았다. 우리가 두 컨테이너 유형을 모두 검사하도록 작성한 단순한 자체 정책이 의도대로 동작하는지 확인한 결과다. 공개 정책의 기본 범위, 실제 운영 구성, 예외와 보고 기능까지 평가한 결과처럼 받아들이면 안 된다. 이번에는 원본을 다시 분석하고 입력 조건과 오픈소스 구현을 늘렸다.

확장 실행은 실제 Admission 4종 × 24개 사례에서 96/96 일치했고, 별도 Polaris 정적 검사도 24/24 일치했다. 조건을 넓힌 뒤에도 이 명시적 사용자 정의 계약의 판정 불일치는 관측되지 않았다. 다만 새로 확인한 계측 문제와 공식 예제의 역할 차이는 “정상 점수·정책 존재·실제 차단”을 같은 사실로 취급하면 안 된다는 것을 보여준다.

## 왜 모두 일치했는가

첫째, 가장 중요한 적용 조건을 실험 작성자가 미리 충족시켰다. 정책은 두 요청 유형과 컨테이너 필드를 명시적으로 다루고 있었고, 규칙은 이름 접두사와 이미지 문자열의 일치 여부였다. 따라서 성공은 엔진이 이 명시적 계약을 수행할 수 있다는 기준 결과다. 현장에서 쓰이는 정책이 자동으로 같은 범위를 보장한다는 증거가 아니다.

둘째, 반복 수가 입력 다양성보다 컸다. 원본 요청에서 Pod 이름과 서버가 부여한 값은 제외하고 경로와 컨테이너 설정을 비교하니 엔진당 8개 사례명은 실제 6개 설정으로 줄었다. 이름 규칙의 적합 입력과 이미지 규칙의 적합 입력이 같았다. 이를 한 클러스터에서 세 번 반복한 것이므로 72개의 독립된 상황을 평가한 셈이 아니다. 재분석 결과는 [v1-reanalysis.json](v1-reanalysis.json)에 있다.

셋째, 제품 수와 평가 방식의 독립성은 다르다. 기존 VAP와 Kyverno 실험은 CEL 규칙을 사용했고, 추가한 Kubewarden의 CEL 정책도 Kubernetes와 호환되는 CEL 인터프리터를 묶어 실행한다. 배포·호출·집행 구현은 늘었지만 언어 차원의 독립 구현이 그만큼 늘었다고 말할 수 없다. 이번에는 Rego인 Gatekeeper와 JSON Schema인 Polaris도 구분해서 해석했다. [Kubewarden CEL 설명](https://docs.kubewarden.io/admission-controller/1.37/en/tutorials/writing-policies/CEL/01-intro-cel.html)

넷째, 정상 설치·정상 통신·명시적 집행 상태에서만 측정했다. 정책 준비 확인을 통과한 후 요청했고 API 서버의 거부, 저장 상태와 시험 프로세스 시작을 대조했다. 이것은 기능 실험의 통제 조건이며, 장애·준비 중 상태·모든 정책 예외를 대표하지 않는다. 감사 기록만으로 허용 요청의 개별 규칙 실행을 확정하지 않았고, 같은 작성자의 검토라는 한계도 유지한다.

## 확장한 조건

| 조건 | 확인하려는 성질 |
| --- | --- |
| 단일·복수 적합 입력, 유효한 경계 이름 | 전부 거부하는 구현을 성공으로 세지 않음 |
| 첫 요소·마지막 요소의 부적합 | 목록 순서에 따라 검사 범위가 달라지는지 |
| 이름 중간에만 접두사 존재, 구분자 없는 이름 | 접두사 규범을 부분 문자열 검사와 혼동하는지 |
| 한 요소에서 두 규칙 부적합 | 하나 이상의 해당 규칙 거부가 발생하는지 |
| 서로 다른 두 요소의 부적합 | 여러 요소의 조건을 함께 다루는지 |
| 정상 Ephemeral Container가 있는 상태의 후속 요청 | 기존 목록을 보존하면서 새 입력을 판단하는지 |
| 복수 추가 요청의 거부 후 상태 | 일부만 저장되지 않고 기존 객체가 유지되는지 |

일반·Ephemeral 경로에 각각 11개 사례를 두고, 기존 Ephemeral Container가 있는 두 사례를 추가했다. 엔진당 24개를 한 번씩 실행하며 순서를 고정 seed로 섞었다. v1의 반복 24회와 v2의 서로 다른 계획 사례 24회는 의미가 다르다. 모든 컨테이너는 동일한 무해한 pause 내용이고 보안 통제는 유지했다. 두 규칙이 동시에 부적합할 때 모든 오류 메시지를 열거해야 한다고 요구하지는 않았다.

## 실행 결과

네 Admission 엔진 모두 7개 적합 요청을 허용하고 17개 부적합 요청을 해당 시험 규칙으로 거부했다. 합계 96/96건에서 입력·감사 기록·기대 결과를 대조했으며 동결한 입력 해시도 일치했다. 거부 요청은 부분 저장 없이 기존 상태를 유지했고, 기존 Ephemeral Container가 있는 사례에서도 이전 항목이 보존됐다.

| 도구·버전 | 실행 방식 | 확장 사례 결과 | 증거 범위 |
| --- | --- | --- | --- |
| VAP / Kubernetes 1.35.8 | 실제 Admission | 24/24 | 요청·감사·객체·실행 |
| Kyverno 1.19.1 | 실제 Admission, CEL ValidatingPolicy | 24/24 | 요청·감사·객체·실행 |
| Gatekeeper 3.23.1 | 실제 Admission, Rego | 24/24 | 요청·감사·객체·실행 |
| Kubewarden 1.37.2 | 실제 Admission, CEL/WASM | 24/24 | 요청·감사·객체·실행 |
| Polaris 10.2.5 | 객체 파일의 정적 JSON Schema 검사 | 24/24 | 24개 객체·48개 규칙의 결과 |

Kubewarden은 chart 6.0.2와 CEL 정책 1.6.4를 사용했고 정책 모듈은 OCI digest로 고정했다. Polaris는 Admission 기능도 제공하지만 이번에는 CLI 정적 검사만 실행했다. 그 24건을 API 차단 성공 횟수에 합산하지 않는다. [Polaris의 두 실행 방식](https://polaris.docs.fairwinds.com/admission-controller/), [정적 검사 설명](https://polaris.docs.fairwinds.com/infrastructure-as-code/)

정책 결과가 일치했다고 모든 컨트롤러 기능이 정상이라는 뜻은 아니다. Kubewarden은 최종 정책 상태가 active였다. Kyverno는 v1과 같이 webhook 구성이 완료된 상태에서도 보고 기능의 읽기 권한 부족으로 `ready=false`를 표시했다. 해당 상태를 감추거나 권한을 바꿔 정상으로 처리하지 않았다. Admission 판정과 배경 보고 기능의 상태를 분리해 해석한다. [Kubewarden 상태](results/20260918T153225Z-kubewarden/final-policies.json), [Kyverno 상태](results/20260918T153548Z-kyverno/final-policies.json)

Gatekeeper도 Rego webhook의 세 컨트롤러는 `enforced=true`였지만 audit 컨트롤러의 별도 VAP 항목에는 `K8sNativeValidation engine is missing`이 남아 있었다. 이 실행으로 VAP 생성 경로의 정상 동작까지 주장하지 않는다. 허용된 총 28건의 개별 정책 평가 증거는 여전히 UNKNOWN이고, 거부된 68건은 명시적 시험 규칙 거부와 저장 결과를 확인했다. [Gatekeeper 상태](results/20260918T153759Z-gatekeeper/final-policies.json)

모든 측정이 끝난 뒤 kind 클러스터와 실행 중인 Docker 컨테이너가 남지 않았음을 확인했다. 재실행용 도구와 이미지 캐시는 유지했다.

## 실제로 드러난 계측 문제

Polaris 첫 시도는 `.json` 파일을 입력으로 주었다. CLI가 모든 입력에서 종료 코드 0과 점수 100을 반환했지만 `Results`는 빈 배열이었고 평가된 객체가 없었다. 단순 종료 코드 비교로는 적합 사례 7개가 맞은 것으로 보였지만, 실제 평가를 입증하지 못했으므로 전체 시도를 제외했다. 문서의 YAML 입력 방식에 맞춰 파일 확장자를 `.yaml`로 바꾸고 JSON 형태의 내용은 유지하자 24개 객체와 48개 규칙이 실제 평가됐다.

이는 특정 Ephemeral Container 정책 누락을 입증한 결과가 아니다. 입력 선택과 측정 분모를 확인하지 않으면 평가하지 않은 상태를 정상 판정으로 오해할 수 있다는 계측 교훈이다. 최종 검증기는 점수 대신 정확히 한 객체, 두 규칙의 결과와 각 규칙의 참·거짓 값을 모두 요구한다. [제외 기록](results/polaris-2026-09-18T153342-397071+0000/disposition.json), [재실행 대조](results/polaris-2026-09-18T153418-695284+0000/crosscheck.json)

## 공식 자료에서 확인한 보장 범위

추가 자료 조사도 “모든 도구가 Ephemeral Container를 모른다”는 전제와 맞지 않았다. 현재 고정한 Kyverno의 이미지 레지스트리 ClusterPolicy 예제와 이미지 저장소 ValidatingPolicy 예제, Gatekeeper의 allowedrepos template 모두 Ephemeral Container 필드를 참조한다. 이 세 개의 목적 표집은 전체 정책 라이브러리의 대표 표본이 아니며, 소스의 필드 참조는 실제 요청에서 선택·집행됐다는 증명도 아니다. 불변 commit과 파일 해시는 [source-review.json](source-review.json)에 기록했다.

또한 확인한 Kyverno 예제의 기본 동작은 각각 Audit, Warn+Audit였다. 정책이 경고·감사를 의도하는지 차단을 약속하는지부터 구분해야 “거부되지 않았다”를 올바르게 해석할 수 있다. Gatekeeper template은 별도 constraint와 실제 webhook 배포 상태도 함께 검토해야 한다. 문서, 정책 언어, 집행 모드, 평가 대상의 역할을 맞추지 않고 차단률 하나로 순위를 매기는 설계는 부적절하다. [Kyverno ClusterPolicy 예제](https://github.com/kyverno/policies/blob/2716f4a26a3c27590a1d6d960dee4ce043e4fa4a/best-practices/restrict-image-registries/restrict-image-registries.yaml), [Kyverno ValidatingPolicy 예제](https://github.com/kyverno/policies/blob/2716f4a26a3c27590a1d6d960dee4ce043e4fa4a/other-vpol/allowed-image-repos/allowed-image-repos.yaml), [Gatekeeper template](https://github.com/open-policy-agent/gatekeeper-library/blob/22a40962f83268769bcec5dfe55e44b5a85c392a/library/general/allowedrepos/template.yaml)

Polaris는 사용자 정의 검사를 객체·PodSpec·Container 등 서로 다른 단위에 지정할 수 있다. 이번에는 전체 PodSpec을 검사하는 계약을 명시했다. 스캐너가 어떤 객체를 읽었는지, 어느 단위에 규칙을 적용했는지와 실제 Admission 호출 여부를 각각 기록해야 한다. [Polaris custom checks](https://polaris.docs.fairwinds.com/customization/custom-checks/)

## 연구 주장과 해결 방향

현재 근거가 지지하는 것은 적용 범위를 명시한 단순 정책의 일관성과 측정 절차의 중요성이다. 특정 제품의 취약점이나 생태계 공통 결함은 아직 입증하지 못했다. 동시에 목적 표집의 성공만으로 모든 공개 보안 정책이 올바르다고 결론 내릴 수도 없다. 기존의 “모든 도구가 놓친다”를 결론으로 정해 놓고 실패 조건을 찾아 끼워 맞추는 방식으로 연구를 진행해서는 안 된다.

연구 질문은 “문서와 운영자가 기대하는 정책 보장이 어떤 구성·평가 조건에서 실제 요청의 판정과 일치하는가”로 정밀하게 잡을 수 있다. 대응해야 할 층은 정책의 약속, 요청 선택, 객체 필드 검사, 집행 모드, 저장 결과, 관측 결과다. 이 층들이 어긋나면 운영자가 믿는 보장과 실제 상태가 달라질 수 있으나, 원인은 제품의 판정 오류일 수도 있고 정책 설정·역할의 차이 또는 계측 누락일 수도 있다. 확인하기 전에 같은 원인으로 묶어서는 안 된다.

방어적 개선은 정책 문서에 적용 대상과 집행 모드를 명시하고, 배포 시 해당 계약과 구성의 일치 여부를 점검하며, 적합·부적합 사례와 실제 평가 수를 함께 검증하는 것이다. 회귀 검증에서는 차단률 외에 정상 입력 허용, 거부 후 상태 보존, 증거가 없는 항목의 UNKNOWN 표시를 유지해야 한다. 특정 PR은 확인된 원인을 고치는 산출물일 수 있지만 연구의 결론을 대신하지 않는다.

남은 한계는 Kyverno legacy ClusterPolicy의 실제 비교, 공개 정책의 대표 표집, 다른 Kubernetes 버전, 독립된 반복 환경, 장애·예외·변이 정책과의 상호작용이다. 이들은 이번 결과에 포함되지 않는다. 논문의 새로움과 실용성을 주장하려면 관련 연구와 비교하고 더 명확한 계약 표집 기준이 필요하다. 도구 수나 성공 횟수가 늘었다는 사실만으로 논문 기여가 확보된 것은 아니다.

재현 절차는 [README](README.md), 실제 Admission 집계는 [crosscheck.json](results/crosscheck.json), 정적 검사 집계는 [offline-crosscheck.json](results/offline-crosscheck.json)에 있다.
