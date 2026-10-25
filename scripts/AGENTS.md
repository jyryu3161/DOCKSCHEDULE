# scripts — 설치·백업·검증 스크립트

## 범위
운영자가 직접 실행하는 도구. 설치(`install.py`), QuickVina 내려받기·검증(`download-qvina.py`), 백업·복원(`backup.sh`, `restore.sh`), 저장 공간 재계산(`reconcile-storage.py`), 실서비스 검증(`service_check.py`, `resilience_check.py`, `scale_check.py`, `backup_check.py`), 처리량 측정(`benchmark.py`).

## 이 모듈의 범위가 아닌 것
- 서비스 로직. 스크립트는 `backend/dockschedule`을 호출하거나 HTTP API를 쓸 뿐 규칙을 따로 구현하지 않는다.
- pytest 테스트(`tests/`). 여기 검증 스크립트는 실제 배포된 서비스를 대상으로 한다.
- 건드리면 안 되는 것: `.env`의 값을 출력·로그하는 코드를 추가하지 않는다.

## 불변 조건
- 비밀(관리자·DB 비밀번호)을 출력하지 않는다. `install.py`는 기존 `.env`를 덮어쓰지 않으며 새 `.env`는 권한 600으로 만든다.
- `download-qvina.py`의 SHA256과 커밋은 `chemistry.py`의 `QVINA_SHA256`과 같아야 한다.
- `restore.sh`는 `CONFIRM_RESTORE=yes`와 백업 경로 인자가 없으면 실행하지 않고, 기존 `storage`를 지우지 않고 `storage.before-restore-<날짜>`로 옮긴다.
- `backup.sh`는 종료 시(오류 포함) 반드시 api·scheduler를 다시 시작한다(`trap`). 백업은 디렉터리 700·파일 600이다.
- `resilience_check.py`는 scheduler를 재시작하므로 학생 작업이 없을 때만 실행한다. `service_check.py`는 실행 동안 전체 설정(`cpu_budget=4, max_students=2`)을 일시 변경했다가 복원하므로 학생이 쓰지 않을 때만 실행한다. 만든 테스트 계정은 끝에 정지시키며 로그에 자격 증명을 남기지 않는다. `resilience_check.py`는 `ready` receptor가 이미 있어야 한다.
- `backup_check.py`는 실제 `backup.sh`를 실행하므로 api·scheduler가 잠시 멈춘다. 학생 작업이 없을 때만 실행한다. 임시 DB는 지우지만 `.backups/validation-*` 백업(`.env` 사본 포함)은 남는다.
- `scale_check.py`는 별도 임시 DB를 만들고 끝나면 삭제한다. 운영 DB를 대상으로 쓰지 않는다.

## 핵심 구현 패턴
- 스크립트는 저장소 루트에서 실행한다(`install.py`는 스스로 루트로 이동, `backup.sh`·`restore.sh`는 스크립트 위치 기준). HTTP 검증은 `X-DS-Request: 1` 헤더와 `--url` 옵션(기본 `http://127.0.0.1:8890`), 관리자 비밀번호는 `ADMIN_PASSWORD` 환경변수 또는 `.env`에서 읽는다.
- 결과 보고서는 gitignore된 `test-results/` 아래에 쓴다.

## 테스트 지침
- 스크립트를 바꾸면 안전한 대상(로컬 Compose 또는 임시 DB)에서 한 번 실행해 성공과 실패 경로(잘못된 인자, 확인 변수 누락)를 확인한다. 백업·복원은 `backup_check.py`로 별도 DB 복원 후 행 수·파일 해시를 비교한다.
