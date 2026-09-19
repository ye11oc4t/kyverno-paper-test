# 실제 저장·실행 기반 본실험 결과

Kubernetes v1.35.8 kind 클러스터에서 Kyverno 1.19.1(차트 3.9.1), Gatekeeper 3.23.1, Kubewarden 1.37.2(차트 6.0.2)를 각각 세 번 독립 설치했다. 설치별로 privileged, allowPrivilegeEscalation, Linux capabilities 정책을 하나씩 격리하여 활성화하고 각 정책군을 다섯 번 반복했다. 총 135개 실험 단위에서 정상 일반 Pod, 위반 일반 Pod, 정상 임시 컨테이너, 위반 임시 컨테이너의 네 요청을 실제로 처리했으므로 API 요청은 540건이다.

| 제품 | 정책군 | 일반 위반 거부 | 임시 위반 허용 | API 저장 | 컨테이너 실행 | 런타임 효과 관찰 |
|---|---|---:|---:|---:|---:|---:|
| gatekeeper | capabilities | 15/15 | 15/15 | 15/15 | 15/15 | 15/15 |
| gatekeeper | escalation | 15/15 | 15/15 | 15/15 | 15/15 | 15/15 |
| gatekeeper | privileged | 15/15 | 15/15 | 15/15 | 15/15 | 15/15 |
| kubewarden | capabilities | 15/15 | 15/15 | 15/15 | 15/15 | 15/15 |
| kubewarden | escalation | 15/15 | 15/15 | 15/15 | 15/15 | 15/15 |
| kubewarden | privileged | 15/15 | 15/15 | 15/15 | 15/15 | 15/15 |
| kyverno | capabilities | 15/15 | 15/15 | 15/15 | 15/15 | 15/15 |
| kyverno | escalation | 15/15 | 15/15 | 15/15 | 15/15 | 15/15 |
| kyverno | privileged | 15/15 | 15/15 | 15/15 | 15/15 | 15/15 |

모든 정상 일반 Pod와 정상 임시 컨테이너는 허용·저장·실행되었고, 모든 위반 일반 Pod는 정책 엔진에서 거부되어 저장되지 않았다. 반면 위반 임시 컨테이너는 모든 제품과 정책군 조합에서 허용되어 Pod 객체에 저장되고 컨테이너 런타임에 의해 실행되었다. privileged 사례는 0이 아닌 전체 유효 capability와 `NoNewPrivs=0`, allowPrivilegeEscalation 사례는 `NoNewPrivs=0`, capabilities 사례는 `SYS_ADMIN` 비트를 실제 프로세스 상태에서 확인했다.

각 반복의 요청 본문, HTTP 상태와 응답, API에서 다시 조회한 Pod 객체, 컨테이너 상태와 로그는 제품·설치·정책군·반복 디렉터리에 저장했다. `evidence-sha256.json`은 집계 산출물을 제외한 증거 파일의 SHA-256을 기록한다.
