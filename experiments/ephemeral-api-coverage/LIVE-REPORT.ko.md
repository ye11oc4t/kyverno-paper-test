# privileged 임시 컨테이너 실제 실행 후속 실험

## 결론

2026-09-19의 API dry-run 실험에서 관찰한 허용 판정이 실제 저장과 실행으로 이어지는지 후속 검증했다. Kyverno, Gatekeeper, Kubewarden을 각각 새 kind 클러스터에 설치한 뒤 `dryRun` 없이 `pods/ephemeralcontainers`를 수정했다. 세 제품 모두 일반 privileged Pod 생성은 대상 정책으로 거부했지만, 같은 네임스페이스의 기존 Pod에 `privileged: true`인 임시 컨테이너를 추가하는 요청은 허용했다. 허용된 임시 컨테이너는 containerd 컨테이너 ID를 받고 `Running` 상태가 됐으며, 내부에서 UID 0과 유효 capability 비트마스크 `000001ffffffffff`가 관찰됐다.

이 결과로 기존 주장의 범위는 “admission 허용 판정”에서 “고정한 로컬 실험 환경에서 API 저장, 스케줄링 및 컨테이너 실행까지 성공”으로 확장된다. 노드 침해나 컨테이너 탈출은 시도하거나 입증하지 않았다.

## 환경과 격리

제품과 Kubernetes 버전은 dry-run 정식 실험과 동일하다.

- Kubernetes: kind, `kindest/node:v1.35.8`, containerd
- Kyverno: chart 3.9.1, app v1.19.1, 정책 chart 3.9.1의 CEL `ValidatingPolicy`
- Gatekeeper: chart/app v3.23.1, library commit `22a40962f83268769bcec5dfe55e44b5a85c392a`
- Kubewarden: admission-controller chart 6.0.2, app v1.37.2, `pod-privileged:v1.0.13`

각 제품은 다른 정책 제품이 없는 새 단일 노드 클러스터에 설치했다. 내장 Pod Security Admission이 제3자 정책의 판정을 가리지 않도록 실험 네임스페이스를 `privileged` 수준으로 설정했다. 전용 ServiceAccount에는 `pods` 생성과 `pods/ephemeralcontainers` 수정에 필요한 권한만 부여했다. 기준 Pod는 ServiceAccount 토큰 자동 마운트를 껐다.

실제 실행 컨테이너는 `busybox:1.36.1`을 사용했다. 명령은 UID와 `/proc/self/status`의 `CapEff`를 출력한 뒤 600초 동안 대기하는 것뿐이었다. 호스트 파일 접근, 네트워크 탐색, 노드 설정 변경 또는 탈출 동작은 수행하지 않았다. 증거를 수집한 뒤 세 클러스터를 모두 삭제했다.

## 실행 절차

각 독립 클러스터에서 다음 세 요청을 `dryRun` 없이 순서대로 전송했다.

1. `securityContext.privileged: true`인 일반 Pod를 실제 생성 요청했다.
2. 기존 기준 Pod에 `privileged: false`, UID 65532, 모든 capability 제거를 설정한 안전한 임시 컨테이너를 추가했다.
3. 같은 Pod에 `securityContext.privileged: true`인 임시 컨테이너를 추가했다.

각 임시 컨테이너 추가 뒤 API에서 Pod를 다시 조회하여 `spec.ephemeralContainers`, `status.ephemeralContainerStatuses`, `containerID`, `imageID`, `startedAt`을 저장했다. 이어서 컨테이너 로그와 별도 `exec`로 UID와 `CapEff`를 수집했다.

## 결과

| 제품 | 일반 privileged Pod | 안전한 임시 컨테이너 | privileged 임시 컨테이너 | 실제 상태 | 안전한 `CapEff` | privileged `CapEff` |
|---|---:|---:|---:|---|---|---|
| Kyverno | 400 거부 | 200 허용 | 200 허용 | Running | `0000000000000000` | `000001ffffffffff` |
| Gatekeeper | 403 거부 | 200 허용 | 200 허용 | Running | `0000000000000000` | `000001ffffffffff` |
| Kubewarden | 400 거부 | 200 허용 | 200 허용 | Running | `0000000000000000` | `000001ffffffffff` |

일반 privileged Pod의 응답에는 각각 다음 대상 정책이 거부 원인으로 기록됐다.

- Kyverno: `disallow-privileged-containers`
- Gatekeeper: `psp-privileged-container`
- Kubewarden: `no-privileged-pod`

세 제품의 privileged 임시 컨테이너 로그는 모두 다음 형태였다.

```text
LIVE_PRIVILEGED
uid=0(root) gid=0(root) groups=0(root),10(wheel)
CapEff: 000001ffffffffff
```

대조군인 안전한 임시 컨테이너는 UID 65532로 실행됐고 `CapEff`가 모두 0이었다. 따라서 privileged 임시 컨테이너의 값은 단순히 Pod 객체에 설정이 저장됐다는 증거에 그치지 않고, 런타임 프로세스에 높은 capability가 실제 적용됐다는 증거다.

## 해석

dry-run 실험에서는 API 서버가 위반 요청을 허용한다는 사실까지만 확인했다. 이번 후속 실험에서는 동일한 미탐이 실제 Pod 변경으로 저장되고, kubelet과 containerd가 이미지를 시작하며, privileged 임시 컨테이너 프로세스가 root와 높은 capability를 가지고 실행되는 단계까지 확인했다.

세 도구가 모두 일반 privileged Pod를 실제 거부했으므로 정책 미설치나 전체 집행 장애로 설명할 수 없다. 같은 계정과 네임스페이스에서 안전한 임시 컨테이너와 privileged 임시 컨테이너가 모두 실행됐으므로 RBAC, 스케줄링 및 이미지 실행 가능성도 대조됐다. 제품별 원인은 dry-run 원인 분리 실험에서 확인한 라우팅 누락 또는 UPDATE 예외와 일치한다.

## 한계

실제 실행 후속 실험은 제품별 한 개의 새 설치에서 한 번씩 수행했다. 판정의 반복성은 앞선 제품별 15회 dry-run에서 확인했지만, 실제 실행 자체를 설치당 여러 번 반복한 결과는 아니다. 로컬 단일 노드 kind와 containerd 환경이므로 관리형 Kubernetes, 다른 컨테이너 런타임, HA 구성으로 일반화할 수 없다.

실험은 root와 capability 적용까지만 측정했다. 호스트 파일시스템 접근, 다른 컨테이너의 메모리나 프로세스 접근, 서비스 계정 탈취, 노드 장악 또는 컨테이너 탈출은 평가하지 않았다. 실제 환경에서는 공격자나 운영자에게 `pods/ephemeralcontainers`의 `update` 또는 `patch` RBAC 권한이 있어야 하며, PSA Baseline·Restricted나 다른 admission 정책이 별도로 차단할 수 있다.

## 증거 파일

- `results/2026-09-19-live-execution/aggregate.json`: 세 실행을 검증한 기계 판독 집계
- `results/2026-09-19-live-execution/<product>/run-1/summary.json`: HTTP와 런타임 요약
- 각 실행의 `requests/`와 `responses/`: 실제 요청과 API 응답
- 각 실행의 `evidence/baseline-after.json`: 저장된 설정, containerd ID, 이미지 digest, 시작 시각과 실행 상태
- 각 실행의 `evidence/safe-container.log`: 안전한 대조 컨테이너의 UID와 capability
- 각 실행의 `evidence/privileged-container.log`: privileged 컨테이너의 UID와 capability
- `run-live-case.sh`: 공통 실제 실행기
- `aggregate_live_results.py`: 증거 일관성 검증과 집계 생성기
