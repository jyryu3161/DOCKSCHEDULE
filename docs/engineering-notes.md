# 엔지니어링 노트 (증상 → 원인 → 대응)

## 설정·스키마

- **새 운영 설정 키를 추가했는데 기존 서버에서 `KeyError`로 요청이 실패한다.** 원인: `DEFAULT_SETTINGS`는 `settings` 행이 없을 때(최초 실행)만 DB에 복사되고, 코드는 `settings(db)['키']`로 직접 읽는다. 대응: 새 키를 추가하면 기본값을 채우는 migration(또는 읽는 곳의 기본값 처리)을 같은 변경에 넣고, `ResourceSettings`(스키마)·관리자 화면·`DEFAULT_SETTINGS`를 함께 고친다. 검증: 기존 DB(키 없는 `settings.values`)로 `GET /api/settings`와 해당 기능이 동작하는지 확인한다.
- **SQLite에서 migration을 돌렸더니 기존 작업·화합물이 사라진다.** 원인: SQLite는 컬럼 추가 시 테이블을 재생성하는데 외래키(`PRAGMA foreign_keys=ON`)의 `ON DELETE CASCADE`가 자식 행을 지운다. 대응: `ALTER TABLE ... ADD COLUMN`을 직접 쓰는 `b63d14a829f0` 방식을 따르고, `tests/test_migrations.py`처럼 데이터가 있는 DB로 업그레이드를 검증한다.
- **테스트는 통과하는데 운영(PostgreSQL)에서 경쟁 조건이 난다.** 원인: 테스트는 SQLite라 `with_for_update`가 아무 효과가 없고 동시성이 재현되지 않는다. 대응: 잠금·동시 업로드·용량 검사 변경은 PostgreSQL에서 `scripts/service_check.py`, `scripts/scale_check.py`로 따로 확인한다(`scale_check`는 별도 임시 DB를 만들고 지운다).

## API 라우팅

- **`/api/jobs/summary`가 작업 ID로 해석되어 404가 난다.** 원인: FastAPI는 선언 순서대로 매칭한다. 대응: `summary`는 `/{task_id}`보다 먼저, `/compounds/{id}/interactions`는 `/compounds/{id}/{format}`보다 먼저 선언돼 있어야 한다. 비슷한 고정 경로를 추가할 때 순서를 지킨다.
- **Playwright 시나리오가 통과해도 계산·DB가 맞다는 뜻이 아니다.** 브라우저 테스트는 API 응답을 mock하고 NGL/WebGL만 실제로 돌린다. 화학 판정과 저장은 pytest와 `service_check`로 확인한다.

## 잔기·구조 식별

- **같은 번호의 잔기가 한 개로 합쳐진다/다른 chain 잔기가 섞인다.** 원인: PDB 잔기는 (chain, 번호, insertion code) 셋으로만 구분되고 chain이 비어 있을 수 있다. 대응: 항상 `residue_key(chain, number, insertion)` 형태 키(`A:25:`)를 쓰고 번호만으로 비교하지 않는다. 검증: 같은 번호가 insertion code 또는 chain으로 갈라지는 케이스(`tests/test_contracts.py`, 1L83 통합 테스트).
- **ProLIF 결과의 잔기 번호가 PDB와 어긋난다.** 원인: ProLIF `ResidueId`는 insertion code를 담지 못한다. 대응: 분석 중에는 잔기마다 고유 내부 번호(1..N)를 부여하고 출력할 때 원래 chain·번호·insertion으로 되돌린다(`_load_protein`의 `residues` 매핑). 이 매핑을 우회하지 않는다.
- **염다리·수소결합이 가까운 곁사슬 사이에서 엉뚱하게 검출된다.** 원인: 거리로 결합을 추정하면 공유결합이 잘못 생긴다. 대응: 결합 정보를 OpenMM의 잔기 template 연결(이황화 결합 포함)에서 가져온다. 거리 기반 결합 추정으로 바꾸지 않는다.
- **분석 결과의 리간드 원자 번호가 다운로드한 SDF와 어긋난다.** 원인: 수소가 빠진 SDF에 수소를 추가하면 원자가 늘어난다. 대응: 원래 원자(0..n-1)의 순서를 바꾸지 않고 뒤에 추가하며, 추가된 수소는 원본 번호 없이(null) 표시한다.
- **PDB 파일을 편집/커밋하면 파싱이 깨진다.** 원인: PDB는 고정폭 컬럼이며 의도적인 끝 공백이 있다. 대응: `.gitattributes`의 `*.pdb -whitespace`를 유지하고 공백 자동 정리를 켜지 않는다.

## 스케줄러·계산 프로세스

- **scheduler를 두 개 띄우면 두 번째가 즉시 종료한다.** 원인: `storage/scheduler.lock`에 비차단 `flock`을 건다. 대응: 정상 동작이다. 스케줄러는 반드시 하나만 둔다(`docker compose restart scheduler`).
- **재시작 뒤 이전 실행의 계산 프로세스가 남아 CPU를 쓴다.** 원인: 디스패처가 runner를 띄운 직후 PID를 DB에 기록하기 전에 죽으면 PID가 없다. 대응: `recover()`가 PID 생성 시각 대조로 죽이고, PID가 기록되지 않은 경우를 위해 명령행에 `dockschedule.runner`와 `run_id`가 있는 프로세스를 찾아 죽인다. 이 두 경로를 지우지 않는다. 검증: `tests/test_contracts.py`의 checkpoint recovery·dispatch failure 테스트.
- **계산 중 프로세스가 중단되면 마지막 화합물이 다시 실행된다.** 원인: 화합물 결과는 완료 시점에만 DB에 반영된다(체크포인트). 대응: `running`으로 남은 행은 복구 때 `pending`으로 되돌린다. 완료된 화합물은 재실행하지 않는다. "정확히 한 번"을 가정한 로직을 넣지 않는다.
- **취소했는데 화합물 결과가 DB에 반영된다/반영되지 않는다.** 원인: runner는 결과를 쓰기 직전에 `run_id`와 `cancel_requested`를 다시 확인해 취소·교체된 실행의 결과를 버린다. 대응: 결과 반영 코드는 항상 `Task`를 잠근 뒤 `run_id`를 확인하는 패턴을 유지한다.
- **CPU를 늘려도 처리량이 비례해 늘지 않는다.** 근거: 1·2·4·8 CPU에서 평균 16.5·8.4·5.1·2.7초/화합물(50개 분자, 비전용 서버, 단일 수용체). 기본값(8명×4 CPU)으로 80만 개를 단순 외삽하면 약 5.9일이다. 실제 40명 동시 부하로 검증한 값은 아니다. 용량·시간 추정은 이 한계를 밝히고 쓴다.
- **스레드 수가 예약 CPU를 넘어 다른 학생의 CPU를 쓴다.** 원인: 라이브러리가 CPU 수를 자동 감지한다. 대응: scheduler가 runner 환경에 `OPENMM_CPU_THREADS`, `OMP_NUM_THREADS`(=예약 CPU 수), BLAS 계열 1을 넣고 runner가 `sched_setaffinity`를 건다. QuickVina는 `--cpu`로 제한한다. 새 계산 경로도 이 세 가지를 따른다.
- **runner가 매 화합물마다 느리게 시작한다.** 원인: 과학 라이브러리 import가 무겁다. 대응: runner가 미리 import하고 `fork`로 화합물마다 프로세스를 만든다. `spawn`으로 바꾸면 매번 import 비용이 든다.
- **Redis가 죽으면 새 작업이 시작되지 않는다.** 원인: 의도된 동작이다. scheduler가 새 배정을 멈추고 `scheduler_error`를 남긴다(`/api/health`와 관리자 화면에 표시). 다른 executor로 우회하는 코드를 추가하지 않는다.

## 저장 공간 집계

- **저장 용량이 실제와 어긋난다.** 원인: 용량은 업로드, 전처리, 화합물 하나가 끝날 때마다 DB에 누적하며 진행 중 파일은 해당 단계 종료 후에 반영된다. 외부에서 파일을 넣거나 옛 데이터를 가져오면 DB와 어긋난다. 대응: scheduler를 멈춘 유지보수 시간에 `docker compose exec -T api python scripts/reconcile-storage.py`로 재계산한다.
- **재시도하면 용량이 두 번 합산된다.** 원인: 이전 값을 빼지 않고 더하는 구현. 대응: `account_compound`는 (새 크기 − 기존에 기록된 `artifact_bytes`)의 차이만 더한다. 이 방식을 유지한다(회귀 테스트: `test_storage_accounting_is_idempotent_after_restart_and_retry`).

## 상호작용 분석 API

- **상호작용 조회가 503으로 실패한다.** 원인: api 프로세스 하나가 pose 분석을 한 번에 하나만 실행하고 3초 안에 실행권을 못 얻거나 45초를 넘기면 거절한다. 대응: 정상 동작이며 `Retry-After: 3`을 보내므로 클라이언트가 재시도한다. api를 여러 프로세스로 늘리면 이 제한과 캐시(최근 32개)가 프로세스별로 따로 적용된다는 점을 감안한다.
- **재시도·삭제 직후 예전 분석 결과가 보인다.** 원인: 캐시 키가 파일 경로·inode·크기·수정시각이다. 대응: 계산 전후 키가 다르면 결과를 버리고 오류를 낸다. 파일 신원 확인(`_identity`)을 제거하지 않는다.

## 배포·운영 함정

- **`docker compose down -v`로 모든 학생 데이터가 사라진다.** 대응: 재시작은 `docker compose restart <서비스>`나 `up -d`만 쓴다. `-v`는 DB·Redis 볼륨을 지운다.
- **api를 갱신했는데 scheduler가 옛 스키마로 실행된다.** 원인: migration은 api 시작 명령에서 실행된다. 대응: api가 migration을 끝낸 뒤 scheduler가 시작된다(`depends_on: api healthy`). 갱신할 때 기존 worker를 정상 종료(`stop_grace_period: 30s`)하고 재시작하면 체크포인트부터 이어진다.
- **web 이미지만 다시 빌드하면 허용 IP 변경이 반영되지 않는다.** 대응: `ALLOWED_NETWORKS`는 web 컨테이너 시작 시 `network-entrypoint.sh`가 읽어 설정을 만든다. `.env` 수정 후 `docker compose up -d`로 web을 다시 만든다.
- **허용 IP를 넣었는데도 로컬 접속이 403이다.** 원인: 호스트에서 게시 포트로 접속하면 Docker bridge gateway에서 온 것으로 보인다. 대응: entrypoint가 기본 경로의 gateway를 자동 허용하므로 별도로 추가하지 않는다.

## 점검 체크리스트

**새 작업 종류(`Task.kind`)를 추가할 때**: ① `scheduler.choose_tasks`의 CPU 수 규칙 ② runner의 분기 ③ `reap`/`recover`/`cleanup`에서 `kind`별 상태 처리 ④ api의 재시도·삭제 조건 ⑤ 용량 집계(`account_task`) ⑥ 프런트의 상태 표시를 모두 확인하고, 각 경로를 테스트로 덮는다.

**운영 설정을 추가할 때**: 위 "설정·스키마" 첫 항목의 대응을 따른다.

**화학 계산 코드를 바꿀 때**: 단위 테스트에 더해 실제 PDB(`tests/fixtures/1L83.pdb`)로 전처리→QuickVina→SDF(입체화학 보존)→상호작용 흐름이 통과하는지(`tests/test_chemistry.py`, `tests/test_interactions.py`) 확인한다.
