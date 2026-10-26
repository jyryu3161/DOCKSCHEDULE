# 시스템 구성

## 구성 요소와 연결

```
학생/관리자 브라우저 ──HTTP──▶ web (nginx, 호스트에 공개되는 유일한 포트)
                                 ├─ 정적 화면(React 빌드)
                                 └─ /api/ ──▶ api (FastAPI, 컨테이너 내부 8000, 호스트 미공개)
                                                │
                       ┌────────────────────────┼───────────────────────┐
                       ▼                        ▼                       ▼
                 PostgreSQL (상태·메타데이터)   storage/ 볼륨 (파일)     (조회용 pose 분석 하위 프로세스)

scheduler ──DB 폴링(1초)──▶ PostgreSQL ──(작업 예약)──▶ Redis(RQ 큐 'ds-<run_id>')
    └─ 하위 프로세스로 실행 ──▶ runner(작업당 1개, CPU 고정) ──fork──▶ 화합물당 1개 계산 프로세스 ──▶ QuickVina 2.1
```

| 구성 요소 | 역할 | 의존 방향 |
| --- | --- | --- |
| web | 접속 IP 허용 목록(`ALLOWED_NETWORKS`+Docker gateway)을 검사하고 `/api/`를 api로 프록시하며 화면을 서빙한다. `X-Forwarded-For`를 실제 source 주소로 덮어쓴다. | api |
| api | 인증·승인·소유권 검사, 업로드·작업 생성, 결과 조회·내보내기. 화학 계산 라이브러리를 import하지 않는다(조회용 pose 분석만 별도 하위 프로세스). 시작 때 `alembic upgrade head`를 실행한다. | PostgreSQL, storage |
| scheduler | 단일 프로세스 디스패처. 대기 작업에 서로 겹치지 않는 CPU 집합을 예약하고 runner를 하위 프로세스로 띄우며, 종료·취소·중단을 감지해 자원을 반환한다. 시작 때 이전 실행의 잔여 프로세스를 정리하고 중단된 작업을 되돌린다. | PostgreSQL, Redis, storage |
| runner | 예약 하나당 하나의 RQ SimpleWorker(burst). 예약된 CPU로 `sched_setaffinity`를 건 뒤 작업 종류별로 전처리·docking·상호작용 분석·GNINA 재점수화를 수행한다. | PostgreSQL, Redis, storage, QuickVina 바이너리 |
| PostgreSQL | 작업·화합물·진행 상태·자원 예약·설정·감사 기록의 단일 기준. 재시작 복구는 이 상태만 근거로 한다. | — |
| Redis | runner에게 작업 번호를 전달하는 큐와 연결 확인. 상태의 기준이 아니다. | — |
| storage/ | 업로드, 전처리 결과, 화합물별 pose, 작업 로그. 모든 서비스가 같은 볼륨을 마운트한다. | — |
| frontend | React SPA. 3D 구조는 NGL, 해시(`#`) 라우팅. | api(HTTP) |

api, scheduler, runner는 같은 이미지·같은 Python 패키지(`backend/dockschedule`)이며 컨테이너만 다르다. scheduler와 runner는 같은 컨테이너(같은 PID 네임스페이스)에서 동작하므로 PID로 프로세스를 추적한다.

## 대표 흐름: 학생이 docking을 제출해 결과를 받기까지

1. 브라우저가 PDB를 `POST /api/uploads?kind=pdb`로 올리면 api가 `storage/<user_id>/uploads/<upload_id>`에 저장하고 `uploads` 행과 PDB 구조 요약(chain·잔기 목록)을 응답한다.
2. `POST /api/receptors`가 `receptors` 행(`queued`)과 `kind='prepare'` 작업(`queued`)을 만든다.
3. scheduler가 1초마다 `queued` 작업 중 실행 가능한 것에 CPU를 예약(`reserved`, `cpu_ids`, `run_id`)하고 Redis 큐 `ds-<run_id>`에 작업을 넣은 뒤 runner 프로세스를 띄워 PID·생성시각을 DB에 기록한다.
4. runner가 상태를 `running`으로 바꾸고 PDBFixer/OpenMM/Open Babel로 `receptor.pdb`·`receptor.pdbqt`·`preparation.json`을 만든다. 성공하면 receptor는 `ready`, 작업은 `completed`가 되고 scheduler가 다음 tick에서 CPU를 반환한다.
5. library를 올리고 `POST /api/jobs`로 제출하면 api가 library를 읽어 화합물 행을 1000개씩 일괄 삽입하고 `kind='screen'` 작업을 `queued`로 만든다(한 트랜잭션, 실패 시 전부 롤백).
6. 3~4와 같이 예약된 runner가 `pending` 화합물을 `row_number` 순서로 하나씩 가져와 `running`으로 표시하고 fork한 계산 프로세스에서 SMILES 정규화→RDKit conformer·최소화→Meeko 준비→QuickVina를 실행한다. 결과(`best.sdf`, `best.pdbqt`, `result.json`)는 `storage/<owner>/tasks/<task>/<id//1000:05d>/<compound_id>/`에 쓰고 완료 즉시 DB에 반영한다(체크포인트).
7. 브라우저는 진행 중에도 `GET /api/jobs/{id}/results`로 완료된 점수를 조회하고, pose 파일과 점수 CSV/TSV·ZIP을 내려받는다.

## 경계 — 무엇이 넘나들고 무엇이 넘지 않는가

- 호스트 밖으로 공개되는 것은 web의 포트 하나뿐이다. DB와 Redis는 Compose 내부 네트워크에만 있고 api 포트도 호스트에 게시하지 않는다.
- api는 파일 경로를 DB 행(서버가 생성한 ID)과 `storage.inside()`로만 해석한다. 업로드 파일명은 경로나 명령에 쓰이지 않는다.
- 계산 프로세스는 DB에 직접 쓰지 않는다. 화합물 하나의 결과는 `result.json`으로 runner에 넘어가고 runner가 DB에 기록한다.
- GNINA 재점수화는 runner가 `screen`을 `completed`/`partial`로 끝내는 트랜잭션에서 `kind='gnina'` 작업(`source_task_id`=그 screening, CPU는 screen과 같은 수)을 자동 등록하고(scheduler가 예약)(`gnina_jobs.maybe_queue_after_screen`), runner가 `gnina.score_batch`로 상위 pose를 점수화해 `gnina_scores`에 저장한다. 순위(`gnina_rank`)는 api가 조회 때 계산하며 `gnina.py`(화학)는 api가 import하지 않는다.
- 상호작용 분석은 두 경로가 있다. (a) 한 pose의 원자별 표는 api가 하위 프로세스(CPU 1개·`nice 10`·45초·한 번에 하나)로 즉시 계산하고 영속화하지 않는다. 이 프로세스는 api 컨테이너가 쓸 수 있는 CPU 중 번호가 가장 큰 하나에 고정되며 scheduler의 CPU 예약과 무관하다(예약은 낮은 번호부터 배정되므로 `cpu_budget`을 서버 CPU 수 전부로 올리면 학생 CPU와 겹칠 수 있다). (b) 라이브러리 전체 분석은 scheduler가 `kind='interactions'` 작업(CPU 1개 예약)으로 돌리고 잔기·타입별 요약만 DB에 저장한다.

## 모듈 지도

| 모듈 | 역할 | 의존 방향 |
| --- | --- | --- |
| `backend/dockschedule` | api·scheduler·runner·화학 계산·상호작용 분석 | PostgreSQL, Redis, storage |
| `frontend` | 학생·관리자 화면과 NGL 뷰어 | api의 HTTP 계약 |
| `migrations` | Alembic 스키마 이력 | `backend/dockschedule/models.py`의 스키마와 일치해야 함 |
| `scripts` | 설치·백업·복원·실서비스 검증 스크립트 | 배포된 서비스, Docker Compose |
| `tests` | pytest(SQLite 기반 계약 테스트 + 실제 화학 통합 테스트) | `backend/dockschedule` |
| `third_party`, `tools` | QuickVina 라이선스 문서, 내려받은 QuickVina·GNINA 바이너리(`tools/`는 gitignore) | — |

## 외부 의존

- QuickVina 2.1 바이너리: GitHub의 고정 커밋에서 내려받고 SHA256을 검증한다(설치 시, 작업 시작 시).
- GNINA v1.3.3 바이너리(약 2GB)와 NVIDIA cuDNN·CUDA 런타임 wheel(이미지에 고정 버전으로 설치, CPU 전용으로만 사용): SHA256을 검증한다(작업 시작 시).
- 계산 라이브러리: PDBFixer·OpenMM, RDKit, Open Babel, Meeko, ProLIF·MDAnalysis. 모두 `uv.lock`으로 고정한다.
- 대상 플랫폼은 x86_64 Linux(고정 바이너리 때문).
