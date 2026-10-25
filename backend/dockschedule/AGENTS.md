# backend/dockschedule — 서버 패키지

## 범위
api(FastAPI), scheduler(디스패처), runner(작업 실행), 화학 계산(전처리·docking), 상호작용 분석, DB 모델, 저장 경로 규칙. 세 진입점이 같은 패키지를 쓴다: `dockschedule.api:app`, `python -m dockschedule.scheduler`, `python -m dockschedule.runner`.

| 파일 | 맡는 일 |
| --- | --- |
| `api.py`, `schemas.py`, `security.py` | HTTP 엔드포인트, 입력 스키마, 인증·소유권(`approved`, `admin`, `owned`), 최초 설정·관리자 생성(`bootstrap`) |
| `scheduler.py` | `choose_tasks`(순수 선택 로직), 예약·worker 기동, `reap`/`recover`/`cleanup` |
| `runner.py` | 작업 실행(`run_task`): `prepare` / `screen` / `interactions` 분기, 화합물 루프, 취소·시간 제한 |
| `chemistry.py` | `prepare_receptor`, `normalize_smiles`, `dock_compound`, QuickVina 해시·원자형 검사 |
| `structure.py` | PDB 파싱(`inspect_pdb`, `selected_pdb`), 잔기 키 |
| `library.py` | CSV/TSV 읽기·미리보기·화합물 행 생성 |
| `interactions.py` | ProLIF 단일 pose 분석(단독 실행 가능한 모듈) |
| `interaction_service.py` | api용 pose 분석 하위 프로세스 호출(잠금·캐시·45초) |
| `interaction_index.py`, `interaction_worker.py` | library 전체 분석의 쿼리 로직 / 예약된 worker 루프 |
| `storage.py`, `processes.py` | 저장 경로·용량 집계 / 프로세스 트리 종료 |
| `models.py`, `db.py`, `config.py` | 스키마, 세션(`transaction()`), 설정과 `DEFAULT_SETTINGS` |

## 이 모듈의 범위가 아닌 것
- 화면 코드와 정적 파일 서빙(`frontend/`, nginx).
- 스키마 이력 파일(`migrations/`): `models.py`를 바꾸면 그쪽에 migration을 추가해야 하지만 migration 파일 자체는 여기 속하지 않는다.
- 운영 스크립트(`scripts/`)와 테스트(`tests/`).
- 건드리지 말 것: `tools/qvina2.1`(고정 해시 바이너리), `third_party/`, `storage/`(런타임 데이터).

## 불변 조건
- api 프로세스는 `chemistry`, `interactions`, RDKit, OpenMM, Open Babel을 import하지 않는다(`interaction_service`는 하위 프로세스로만 호출).
- `chemistry.py`는 `runner`가 만든 CPU 고정 worker 안에서만 import한다.
- 모든 자료 조회·변경 엔드포인트는 `owned(obj, user)`를 거친다. 남의 자료는 404.
- scheduler·runner의 `Task` 상태 변경은 `with_for_update`로 행을 잠그고 `task.run_id == run_id` 및 `cancel_requested`를 확인한 뒤에 한다. api의 취소는 잠금 없이 `cancel_requested`만 세우고 종료 처리는 scheduler·runner에 맡긴다. 사용자·작업을 함께 잠그면 순서는 사용자 → 작업.
- CPU 반환(`cpu_ids = []`, `worker_pid = None`)은 `account_task` 호출 후, worker가 이미 없거나(`matches`가 False) `stop_tree`로 종료시킨(최대 5초 대기) 뒤에만 한다.
- 프로세스 종료는 `stop_tree(pid, created)`로만 한다.
- 새 `Task.kind`/상태를 추가하면 `choose_tasks`, `reap`, `recover`, `cleanup`, 재시도·삭제 조건, `account_task`가 모두 그 종류를 처리해야 한다.
- 파일 경로는 `storage.receptor_dir/task_dir/compound_dir`와 `inside()`로만 만든다. `compound_dir`은 DB의 `Compound.id`로 정해지며 `row_number`가 아니다.
- 계산 프로세스가 DB를 쓰지 않는다. 결과는 `result.json`(임시 파일에 쓴 뒤 `replace`)으로만 넘긴다.
- 잔기 식별은 `residue_key(chain, number, insertion)`이다. 번호만으로 잔기를 비교하지 않는다.
- 사용자에게 보이는 오류 문구는 한국어다. 입력 오류는 `ValueError`(→ 422)로 올린다.

## 핵심 구현 패턴
- DB 세션: 요청에서는 `Depends(get_db)`, 백그라운드에서는 `with transaction() as db`(성공 시 커밋, 예외 시 롤백). 느린 계산 전에 `db.rollback()`으로 연결을 놓아준다(`interactions` 엔드포인트).
- 대량 읽기·내보내기: 새 `Session()`을 반복해서 열어 `id > last` keyset으로 500~1000행씩 읽는다.
- 화합물 루프(`runner.run_task`): `pending`을 `row_number` 순으로 하나 선택 → `running` 표시 → fork한 프로세스 실행 → 1초 간격으로 취소/시간 초과 확인 → `result.json` 반영 → 진행 카운터 증가.
- worker 기동 환경: scheduler가 `DS_CPU_IDS`, `OPENMM_CPU_THREADS`, `OMP_NUM_THREADS`(예약 CPU 수), BLAS 계열 1을 넣고 runner가 `sched_setaffinity`를 건다. 새 계산 경로도 따른다.
- 운영 설정은 `settings(db)['키']`로 읽는다(기본값 보강 없음). 새 키는 기존 DB에 값을 채워야 한다.
- CSV는 `safe()` 접두(`'`) + BOM 규칙을 따른다.

## 테스트 지침
- 스케줄링 규칙은 `choose_tasks`를 가짜 객체로 직접 호출해 검증한다(동시 학생 수, CPU 합계·비중복, 일시 중지, 사용자당 1개).
- 상태 전이·복구·재시도·삭제는 `admin_client` 픽스처(SQLite)와 `monkeypatch`로 프로세스 함수를 대체해 검증한다. 취소·교체된 `run_id`의 결과가 버려지는지, 용량 집계가 재시도에 멱등한지 포함한다.
- 화학 변경은 `tests/fixtures/1L83.pdb`로 전처리 → QuickVina → SDF 입체화학 보존까지 실제 실행한다(`tools/qvina2.1` 필요).
- 반드시 확인할 경계 사례: 같은 번호의 서로 다른 insertion/chain 잔기, 빈 chain, 빈 CID/SMILES 행, 중복 CID, 모든 conformer 실패, 타임아웃 후 자동 재시도, 접촉 0개 성공 vs 분석 실패.
- 잠금·동시성 변경은 SQLite 테스트로는 검증되지 않는다(PostgreSQL에서 확인).
