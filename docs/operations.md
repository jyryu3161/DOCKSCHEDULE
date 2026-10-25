# 운영

x86_64 Linux에서 Docker Engine + Compose로 단일 서버에 배포한다. Compose 프로젝트 이름은 `dockschedule`, 서비스는 `db`, `redis`, `api`, `scheduler`, `web`이다.

## 최초 설치 (운영)

전제: Docker Engine과 Compose, Python 3, 인터넷(이미지 빌드 중 QuickVina 바이너리를 내려받음).

```bash
python3 scripts/install.py
```

1. `.env`가 없으면 관리자 초기 비밀번호를 입력받아(`ADMIN_PASSWORD` 환경변수로 대체 가능) `.env`(권한 600)를 만든다. 이미 있으면 건드리지 않는다. 비밀번호는 8자 이상, 개행·작은따옴표 불가.
2. `docker compose up --build -d`가 이미지를 빌드하고 서비스를 시작한다. 시작 순서는 `db`·`redis` healthy → `api`(시작 때 `alembic upgrade head`, 첫 실행이면 `admin` 계정 생성) healthy → `scheduler`, `web`. 이 순서를 바꾸면 scheduler가 스키마 없이 시작해 실패한다.
3. 기본 접속은 `http://127.0.0.1:8890`, 관리자 ID는 `admin`.

## 환경 설정 (`.env`)

| 변수 | 역할 / 유효 범위 |
| --- | --- |
| `ADMIN_PASSWORD` | 최초 실행 때만 `admin` 계정 생성에 쓰인다. 이후 변경은 DB에 저장된 hash가 기준이다. 비어 있고 `admin`이 없으면 api 시작 실패. |
| `POSTGRES_PASSWORD` | DB 비밀번호(설치 스크립트가 무작위 생성). 이미 만든 DB 볼륨이 있으면 바꾸어도 DB 안의 비밀번호는 바뀌지 않는다. |
| `BIND_IP`, `APP_PORT` | web이 호스트에 게시되는 주소·포트(기본 `127.0.0.1:8890`). 학내 제공 시 서버의 학내 IP를 지정한다. |
| `ALLOWED_NETWORKS` | 쉼표로 구분한 허용 CIDR. 학생의 실제 접속 source 주소 기준이며 `0.0.0.0/0`은 금지. 기본 `127.0.0.0/8,::1/128`. |
| `COOKIE_SECURE` | 학내 HTTP면 `false`, HTTPS reverse proxy 뒤면 `true`. |
| `SESSION_HOURS`, `MAX_UPLOAD_MB` | (선택) 로그인 유효시간(기본 12), 업로드 한도 MB(기본 100). 업로드 한도를 올리면 `frontend/nginx.conf`의 `client_max_body_size`도 함께 올려야 한다. |

`DATABASE_URL`, `REDIS_URL`, `STORAGE_ROOT`, `QVINA_BINARY`는 Compose가 컨테이너 환경에 주입한다. 설정을 바꾼 뒤에는 `docker compose up -d`로 반영한다.

관리자 화면에서 바꾸는 값(전체 CPU 한도, 동시 학생 수, 학생당 CPU, library·conformer·exhaustiveness 상한, 학생별 대기 작업 수, 화합물 시간 제한, 전처리 시간 제한, 재시도 횟수, 저장 한도, 보존 기간, 신규 배정 일시 중지)는 DB에 저장되며 새로 배정되는 작업부터 적용된다. 단 `compound_timeout`과 `max_retries`는 작업 제출 시점에 그 작업의 파라미터로 복사되므로 이미 제출된 작업(재시도 포함)에는 변경이 반영되지 않는다. `preparation_timeout`, `paused`, CPU 관련 값은 매번 DB에서 읽는다. 기본값은 CPU 한도 56, 동시 학생 8, 학생당 CPU 4, 화합물 상한 100,000이다.

## 개발 환경

```bash
uv sync
uv run python scripts/download-qvina.py          # tools/qvina2.1 (체크섬 검증)
npm --prefix frontend ci
```

- 백엔드 설정의 기본값은 SQLite(`storage/development.db`)와 `redis://localhost:6379/0`이다. scheduler와 runner는 Redis가 필요하다.
- 빈 개발 DB에서의 기동 순서(앞 단계가 없으면 뒤 단계가 실패한다): `uv run alembic upgrade head`(테이블 생성; api의 `bootstrap`은 테이블을 만들지 않는다) → `ADMIN_PASSWORD=<8자 이상> uv run uvicorn dockschedule.api:app --port 8091`(최초 `admin` 생성) → `uv run python -m dockschedule.scheduler`.
- 프런트 개발 서버(`npm --prefix frontend run dev`)는 `/api`를 `http://127.0.0.1:8091`로 프록시하므로 api를 8091 포트로 띄운다.

## 검증 명령

```bash
OPENMM_CPU_THREADS=2 OPENBLAS_NUM_THREADS=1 uv run pytest -q   # Python 전체 (실제 PDBFixer·QuickVina 포함, SQLite)
npm --prefix frontend run build                                # 타입 검사 + production build
cd frontend && npx playwright test                             # 브라우저 시나리오 (API는 mock, NGL은 실제)
```

- 운영 서버 대상 스크립트(주소가 loopback이 아니면 `--url http://서버IP:포트`, 브라우저는 `DOCKSCHEDULE_URL`):
  - `uv run python scripts/service_check.py` — 테스트 학생 2명 가입·승인, 실제 전처리·docking, CPU affinity, 다운로드 권한. 실행 동안 전체 설정을 `cpu_budget=4, max_students=2`로 일시 변경했다가 마지막에 복원하므로 실제 학생이 쓰지 않는 시간에 실행한다. 끝나면 테스트 계정을 정지하고 결과는 관리자에게 남는다.
  - `uv run python scripts/resilience_check.py` — 실제 scheduler 재시작·취소 검증. `ready` 상태의 단백질이 미리 있어야 하며 학생 작업이 없을 때만 실행한다.
  - `docker compose exec -T api python scripts/scale_check.py` — 별도 PostgreSQL DB로 80만 행 검증 후 삭제. docking 처리량 측정이 아니다.
  - `scripts/benchmark.py` — 같은 분자를 CPU 1·2·4·8개로 실행해 처리량 비교(`test-results/benchmark/report.json`).
  - `scripts/backup_check.py` — 실제 `backup.sh`를 실행(아래 백업 절의 서비스 중지 영향 동일)한 뒤 별도 DB·임시 디렉터리에 복원해 행 수·파일 해시를 비교. 임시 DB는 지우지만 `.backups/validation-*` 백업은 `.env` 사본과 함께 남으므로 직접 지운다.

## 중단·복구

- `docker compose restart scheduler`는 계산 프로세스를 정리하고 완료된 화합물 다음부터 재개한다.
- 작업 취소는 하위 계산 프로세스를 종료하고 실제 종료를 확인한 뒤에 CPU를 반환한다.
- 상태 점검: `/api/health`(scheduler heartbeat·오류), `docker compose logs --tail 100 api scheduler`, 작업별 계산 로그는 `storage/<user_id>/tasks/<task_id>/worker.log`.
- Redis 장애 중에는 새 작업이 시작되지 않는다. Redis를 복구하면 다음 tick부터 자동 재개한다.
- 데이터를 보존하려면 `docker compose down -v`와 DB·Redis 볼륨 삭제를 쓰지 않는다.

## 저장 공간

- 관리자 화면에서 전체·학생별 한도를 설정한다. 디스크 여유가 2 GiB 미만이면 새 계산·업로드를 거절한다.
- 외부에서 파일을 추가했거나 이전 데이터를 가져왔다면 scheduler를 멈추고 `docker compose exec -T api python scripts/reconcile-storage.py`로 기록을 재계산한다.
- 보존 기간 기본값 0은 자동 삭제 없음이다.

## 백업·복원

```bash
scripts/backup.sh /안전한/백업/경로     # api·scheduler를 잠시 멈추고 DB 덤프 + storage + .env 사본 저장 후 재시작
CONFIRM_RESTORE=yes scripts/restore.sh /안전한/백업/경로   # 현재 DB를 교체한다
```

- `backup.sh`가 scheduler를 멈췄다 다시 시작하면 실행 중이던 작업은 `queued`로 돌아가 마지막 화합물 하나를 다시 계산한다. 학생 작업이 없을 때 실행하는 것이 좋다.
- 백업은 자동 예약하지 않는다. 경로를 생략하면 `.backups/<날짜>`에 저장한다. 백업 디렉터리는 700, 파일은 600 권한이다.
- 복원 전 반드시 현재 백업을 먼저 만든다. 복원은 api·scheduler·web을 멈추고 기존 `storage`를 `storage.before-restore-<날짜>`로 옮긴 뒤 풀고 DB를 `--clean`으로 복원하고 서비스를 올린다. 복원 후 관리자 로그인, 작업 목록, 점수 파일, scheduler 상태를 확인한다.
- 복원에 쓰는 `.env`의 DB 비밀번호와 네트워크 설정이 백업 시점과 맞는지 먼저 확인한다.

## 업데이트 배포

1. 코드를 갱신하고 `docker compose up --build -d`(api·scheduler·web 이미지 재빌드).
2. api가 `alembic upgrade head`를 끝내고 healthy해진 뒤 새 scheduler가 시작된다. 기존 worker는 정상 종료 후 체크포인트부터 이어진다.
3. 이전 이미지로 되돌릴 때는 진행 중인 상호작용 분석을 취소하고 `interactions` 작업이 큐에 없는지 확인한다.
4. 배포 때 학생 작업이나 볼륨을 초기화하지 않는다.
