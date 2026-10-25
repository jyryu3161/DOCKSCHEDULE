# 규칙 (위반하면 깨지는 것)

## 검증 게이트 (병합 전 통과)

1. `OPENMM_CPU_THREADS=2 OPENBLAS_NUM_THREADS=1 uv run pytest -q` 전체 통과. 실제 화학 테스트(PDBFixer, QuickVina)를 포함하므로 `tools/qvina2.1`이 있어야 한다(`uv run python scripts/download-qvina.py`). 테스트는 SQLite 임시 DB를 쓴다.
2. `npm --prefix frontend run build` 통과(`tsc -b` 타입 검사 포함). 화면 변경은 추가로 `cd frontend && npx playwright test`(Chromium) 관련 시나리오 통과.
3. 스키마(`models.py`)를 바꾸면 같은 변경에 Alembic migration을 추가하고 `tests/test_migrations.py` 방식으로 업그레이드·다운그레이드 시 기존 작업·화합물이 보존되는지 검증한다.
4. 스케줄링·복구·취소·소유권·용량 계산을 바꾸면 해당 불변 조건을 검증하는 테스트(`tests/test_contracts.py`, `tests/test_regressions.py`)를 추가·수정한다. 운영 서버에서는 `scripts/service_check.py`(실제 서비스 통합), 학생 작업이 없을 때 `scripts/resilience_check.py`(재시작·취소)로 확인한다.

## 의존성·환경

- Python은 3.12(`>=3.12,<3.13`)만 지원한다. 의존성은 `pyproject.toml` + `uv.lock`(Dockerfile은 `--frozen`), frontend는 `package-lock.json`(`npm ci`)으로 고정한다. 새 의존성은 두 파일을 함께 갱신한다.
- 설정은 환경변수/`.env`(pydantic-settings)로만 읽는다. 비밀(`ADMIN_PASSWORD`, `POSTGRES_PASSWORD`)을 코드·문서·로그에 쓰지 않고 `.env`를 커밋하지 않는다.
- 관리자가 바꾸는 운영 설정은 DB의 `settings` 행(`DEFAULT_SETTINGS`는 최초 생성 때만 쓰임)이 기준이다. 코드에서 환경변수로 대체하지 않는다.
- QuickVina는 고정 SHA256(`QVINA_SHA256`)과 일치하는 바이너리만 쓴다. 버전을 바꾸면 `chemistry.py`, `scripts/download-qvina.py`, `THIRD_PARTY.md`의 커밋·해시를 함께 갱신한다.

## 프로세스·모듈 경계

- api 프로세스에서 `chemistry`, `interactions`(ProLIF/MDAnalysis), RDKit, OpenMM, Open Babel을 import하지 않는다. 화학 계산은 CPU가 고정된 runner의 하위 프로세스나 `interaction_service`의 하위 프로세스에서만 수행한다. (위반하면 api가 CPU 제한 밖에서 계산하고 시작 시간·메모리가 커진다.)
- `chemistry.py`는 CPU 제한이 걸린 계산 worker 안에서만 import한다(모듈 docstring 참조).
- 계산 프로세스는 DB에 쓰지 않는다. 화합물 결과는 `result.json` 한 파일로 runner에 전달되고, 쓸 때는 `.tmp`에 쓴 뒤 `replace`한다.
- 작업 상태와 결과를 바꾸는 scheduler·runner 코드는 `Task` 행을 `with_for_update`로 잠그고 `run_id`가 자기 것인지 확인한다. api의 재시도·삭제는 `with_for_update`로 잠그고, 취소는 `cancel_requested` 플래그만 세워 실제 종료는 scheduler·runner가 처리한다. 사용자와 작업을 함께 잠글 때는 항상 사용자 → 작업 순서다(교착 방지).
- CPU 반환(`cpu_ids`/`worker_pid` 초기화)은 worker 프로세스 트리를 종료시키고(`stop_tree`, 최대 5초 대기) PID·생성 시각 대조로 더 이상 살아 있지 않음을 확인한 뒤에만 한다. 살아 있는 프로세스가 남은 채 예약을 풀지 않는다.
- 프로세스를 죽일 때는 `processes.stop_tree`(자손 먼저, PID 생성 시각 대조)만 쓴다. PID만으로 `kill`하지 않는다.
- 파일 경로는 서버가 만든 ID와 `storage` 모듈의 경로 함수(`receptor_dir`, `task_dir`, `compound_dir`)로만 만든다. 사용자 입력 문자열을 경로·명령 인자에 넣지 않는다.
- 모든 자료 API는 `owned()`로 소유권을 검사한다. 새 엔드포인트가 이 검사를 건너뛰면 안 된다(남의 자료는 404).
- 사용자가 만든 작업 하나는 사용자별 CPU를 점유한다. 새 종류의 작업을 추가할 때도 `scheduler.choose_tasks`의 사용자당 1개 규칙과 CPU 예약·반환 경로를 그대로 따른다.

## 데이터베이스

- 스키마 변경은 migration으로만 한다. api 컨테이너 시작 명령이 `alembic upgrade head`를 실행하고 scheduler는 api가 healthy해진 뒤 시작한다. migration은 SQLite(테스트)와 PostgreSQL(운영) 양쪽에서 동작해야 하며, SQLite에서 테이블 재생성이 외래키 CASCADE로 데이터를 지우지 않도록 한다(`b63d14a829f0` 참조).
- 큰 목록을 다루는 쿼리는 인덱스(`compound_results`, `compound_status`, `analysis_queue`, `interaction_lookup`)를 타야 한다. 화합물 전체를 메모리에 올리거나 요청마다 전체 파일을 훑지 않는다(용량은 DB에 누적한다).
- 대량 목록·내보내기는 `id` 기준 keyset으로 500~1000행씩 스트리밍한다.

## API·계약 패턴

- 입력 검증은 pydantic 스키마(`schemas.py`)와 `ValueError`(→ 422, `{"detail": 한국어 메시지}`)로 한다. 그 외 오류는 `HTTPException`에 한국어 `detail`을 넣는다.
- 상태 변경 요청은 `X-DS-Request: 1` 헤더가 필요하다. 프런트의 `api()`/`post()`가 자동으로 붙인다. 새 호출도 이 래퍼를 쓴다.
- CSV 내보내기는 수식 방지(`'` 접두)와 UTF-8 BOM을 적용한다.

## 프런트엔드

- 서버 요청은 `src/api.ts`의 `api()`/`post()`만 쓴다. 화면 문자열은 한국어다.
- 자동 갱신은 이전 요청이 끝난 뒤 다음을 예약한다(요청 중첩 금지). 화면을 떠나면 진행 중 요청을 취소하고 이전 작업의 데이터·선택 상태를 비운다.
- NGL 뷰어(`Viewer`)와 pose 상호작용 패널(`PoseInteractions`)은 `lazy` import로 필요한 화면에서만 로딩한다. 초기 번들에 NGL을 넣지 않는다.
- 타입 검사(`tsc -b`)가 build의 일부이므로 타입 오류가 있으면 build가 실패한다.

## 테스트·커밋

- 회귀 테스트는 실패를 재현하는 것이어야 하며 SQLite 임시 DB(`tests/conftest.py`)를 쓴다. 실제 화학 계산이 필요한 테스트만 `tools/qvina2.1`에 의존한다.
- `.pdb` 파일은 고정폭 컬럼과 의도된 끝 공백을 가지므로 `.gitattributes`의 `-whitespace`를 유지하고 편집기에서 공백을 자동 정리하지 않는다.
- `storage/`, `tools/`, `test-results/`, `.backups/`, `.env`는 커밋하지 않는다.
