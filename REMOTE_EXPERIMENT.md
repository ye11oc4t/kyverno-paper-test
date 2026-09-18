# KSYBOB 환경 원격 실행 실험

**전체 결과: PASS**

실행 시각(UTC): `2026-09-18T14:32:32.8092217+00:00`

이 문서는 지정된 Windows 호스트에서 PowerShell 명령을 실제 실행한 결과이다. Git 비교는 `git fetch origin main` 성공 후, 이 보고서를 커밋하기 전에 수행했다.

## 1. 실행 환경 — PASS

| 항목 | 측정값 |
|---|---|
| COMPUTERNAME | `KSYBOB` |
| 현재 작업 경로 | `C:\Users\ksybo\Documents\Codex\projects\kyverno-paper-test` |
| Windows 버전 | `Microsoft Windows NT 10.0.26200.0` |
| PowerShell 버전 | `7.6.5` |
| Git 버전 | `git version 2.53.0.windows.3` |

## 2. Git 상태 — PASS

| 항목 | 측정값 |
|---|---|
| origin | `https://github.com/ye11oc4t/kyverno-paper-test.git` |
| 현재 브랜치 | `main` |
| 실험 시점 HEAD | `ae31067a052aace23812601917c5fceb1803a75b` |
| 실험 시점 origin/main | `ae31067a052aace23812601917c5fceb1803a75b` |
| HEAD와 origin/main 일치 | PASS |

위 SHA는 보고서 작성 전의 저장소 상태이며, 이 보고서를 추가하는 커밋의 SHA는 아니다.

## 3. 임시 파일 생성·읽기·삭제 — PASS

검증 파일: `work/remote-experiment-6854edda4acb4338919b55befd8754a8.txt`

| 검사 | 결과 |
|---|---|
| 임시 파일 생성 및 존재 확인 | PASS |
| 읽은 내용과 기록한 내용의 완전 일치 | PASS |
| 임시 파일 삭제 | PASS |

## 4. 삭제 후 잔여 파일 확인 — PASS

`Test-Path`와 같은 파일명을 대상으로 한 디렉터리 조회로 재확인했다. 해당 검증 파일의 잔여 개수: **0개**.

## 실행 범위

- 요청된 호스트 이름과 버전 정보만 기록했으며 비밀번호, 토큰, 기타 환경변수 값은 수집하거나 기록하지 않았다.
- 시스템 설정 및 Git 전역 설정은 변경하지 않았다.
- 저장소와 실행 계정의 소유자 차이로 발생한 Git 안전성 검사는 해당 저장소에 한정한 명령별 `-c safe.directory=...` 옵션으로 처리했다. 영구 설정은 저장하지 않았다.
- 이 결과는 실행 환경, Git 상태 및 파일 입출력 검증 결과이며, Codex 앱의 프로젝트 등록 상태는 검사 대상에 포함하지 않았다.
