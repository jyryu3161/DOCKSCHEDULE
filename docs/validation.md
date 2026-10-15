# 구현 검증 기록

## Pose 상호작용 확장 검증 (2026-10-16)

로컬 개발 환경에서 `OPENMM_CPU_THREADS=2 OPENBLAS_NUM_THREADS=1 .venv/bin/pytest -q` 전체 51개와 frontend production build가 통과했다. 기존 Starlette 경고와 MDAnalysis의 deprecated import 경고가 있으며 테스트 실패는 없다.

추가한 상호작용 테스트는 실제 ProLIF로 수소결합의 양방향 donor/acceptor·거리·각도 조건, 같은 잔기의 여러 acceptor, 방향족 고리 중심과 원자 목록, 할로젠–acceptor 거리, carboxylate 공명 원자와 염다리를 확인한다. SDF 원자 순서와 누락 수소 처리, 파일 교체·삭제·분석 중 재시도의 캐시 무효화, API 인증·소유권·pose 상태와 오류 응답도 검증한다. 기존 1L83 실제 전처리/QuickVina 테스트에 상호작용 생성, SDF 원자 좌표 대응, 빈 chain과 같은 번호/이름의 두 insertion residue가 분리되는지 확인하는 검증을 추가했다.

Chromium에서 `interactions.spec.ts`와 `review-regressions.spec.ts`의 7개 시나리오가 통과했다. 상호작용 표·3D 강조·원자 라벨·유형 필터·CSV, pose 전환 시 늦은 응답 차단, 분석 실패 후 재시도와 모바일 overflow, 기존 viewer의 오류 복구와 lazy loading을 확인했다. 브라우저는 API 응답을 mock하고 실제 NGL/WebGL을 사용한다. 화학 판정은 별도의 실제 Python 테스트로 검증한다. 결과 화면은 실행 시 `test-results/browser/interactions.png`에 저장한다.

1L83와 `C[C@H](O)c1ccccc1`의 별도 smoke test에서 18개 원자별 상호작용이 검출됐으며, CPU 1개의 조회용 subprocess는 약 1.65초, 캐시 재조회는 0.001초 미만이었다. 한 구조에서의 관측값이며 동시 학생 부하나 전체 receptor 크기에 대한 성능 보장은 아니다. 물 매개 결합, 금속 배위, 보조인자와 실험적 결합 에너지는 검증 범위에서 제외한다.

## 초기 배포 검증 (2026-10-14)

2026-10-14, 이 저장소의 단일 서버 Docker Compose 배포에서 검증했다. 실제 docking 검증과 대량 DB 검증은 서로 다른 시험이다.

## 기능 및 운영 검증

| 검증 | 결과 |
| --- | --- |
| Python 테스트 | 27개 통과. 가입·승인·정지, CSRF, 자료 소유권, 큐 자원 불변 조건, 재시작 체크포인트, 파일 용량 집계, 보존 기간, 목록 페이지 조회·필터별 전체 개수, Excel sep 안내·빈/중복 헤더·CSV quoting·중복 CID·실패 행, PDB model·chain·insertion·비표준 잔기 포함 |
| 실제 화학 계산 | 1L83에서 SEQRES 결손 A163/A164 복구, 수소와 rigid receptor PDBQT 준비, RDKit 최소화와 QuickVina 실행, conformer 중 최상 pose 선택, SDF 입체화학 보존 통과 |
| 비표준 잔기 | PDB MODRES에 근거한 아미노산 치환을 실제 전처리로 검증. 알 수 없는 ATOM 잔기를 일반 리간드처럼 조용히 삭제하지 않음 |
| 유지 성분 | 1L83의 benzene을 명시적으로 유지한 전처리 통과. 대체 위치가 있는 유지 성분은 occupancy에 따라 하나만 선택 |
| 실제 서비스 통합 | 학생 2명 가입·승인 → PDB 전처리 → TSV 매핑 → 각각 화합물 3개 실행. 학생별 유효 결과 2개와 잘못된 SMILES 오류 1개, 점수 export 및 타 사용자 접근 차단 확인 |
| Library 상한 | 기본값과 관리자 설정 상한을 100,000개로 확대. CSV 100,000행 입력 허용, 100,001행 거절 및 관리자 설정 경계 확인. 전체 docking 부하 검증과는 별도 |
| CPU 제한 | 학생 2명의 worker, compound process, qvina 프로세스에 각각 `[0,1]`, `[2,3]` affinity 적용 확인. 두 작업 동시 실행 확인 |
| 재시작 | 실제 scheduler 컨테이너 재시작 후 5개 화합물 완료. 재시작 전 완료한 첫 pose의 SHA256과 시도 횟수 보존 |
| 취소 | 실행 중 하위 계산 종료, 완료한 첫 화합물 보존, CPU 예약 반환 확인 |
| 백업·복원 | 운영 백업을 별도 PostgreSQL DB와 임시 디렉터리에 복원. users/tasks/compounds 행 수 및 파일 81개 해시 일치. 비공개 설정 파일 권한 600 확인 |
| 접근 제한 | 운영 IP:port에서 HTTP 200. 허용하지 않은 Docker source에서 Nginx HTTP 403, 위조 X-Forwarded-For도 HTTP 403 |
| 브라우저 | Chromium 3개 시나리오 통과. Excel CSV 업로드 미리보기와 Catalog ID 자동 선택, 페이지당 표시 개수·설정 저장·마지막 페이지, 로그인, 대시보드, sequence→structure 및 실제 structure 클릭→sequence, 좌표/grid, pose·affinity, 관리자 설정, 모바일 화면·로그아웃 검증 |
| 배포 | PostgreSQL/Redis/API health 정상, scheduler heartbeat 정상. DB와 Redis는 호스트 포트 미공개 |

`npm --prefix frontend run build`도 통과했다. Python 테스트에는 Starlette의 향후 httpx 연동 변경을 알리는 deprecation warning 1개가 남아 있다. 현재 테스트 실패는 없다.

## 80만 행 상태·결과 처리

격리된 PostgreSQL DB에 학생 40명 × 20,000행을 생성하고 테스트 후 해당 DB를 삭제했다. 실제 80만 회 docking을 수행한 수치는 아니다.

| 항목 | 측정값 |
| --- | ---: |
| 20,000행 CSV 읽기 | 0.033초 |
| 800,000개 화합물 DB 입력 | 54.03초 |
| affinity 정렬 첫 50개 결과 조회 | 0.0067초 |
| 한 library 20,000행 CSV export | 0.75초 |
| 검증 프로세스 RSS | 89.94 MiB |

용량 확인은 화합물 완료 시 파일 크기를 DB에 누적하고 업로드·receptor·작업 단위 합계를 조회한다. 매 화합물마다 전체 결과 파일을 탐색하지 않는다. 중단 시 미완료 화합물의 파일 크기를 다시 반영하며 재시도 시 중복 합산하지 않는 회귀 테스트를 포함한다.

## 실제 docking 처리량

Intel Xeon Gold 6226R 2개, 물리 core 32개 / 논리 CPU 64개 환경에서 CPU 1, 2, 4, 8개별 50개 분자의 실측 결과를 기록한다.

RDKit NCI 예제 중 heavy atom 8–35개, rotatable bond 8개 이하의 앞 50개를 사용했다. Receptor 1L83, box 20×20×20 Å, exhaustiveness 8, conformer 1, seed 42이며 모든 CPU 설정에서 동일한 분자를 실행했다. RDKit 준비와 qvina 실행 시간을 포함한다. 이 서버에서 다른 검증도 함께 수행한 wall time이며 전용 장비의 통제된 성능 비교는 아니다.

| CPU / 작업 | 평균 초 / 화합물 | 중앙값 | 95백분위 | 성공 |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 16.53 | 13.98 | 41.69 | 50 / 50 |
| 2 | 8.39 | 7.29 | 19.11 | 50 / 50 |
| 4 | 5.11 | 4.02 | 10.64 | 50 / 50 |
| 8 | 2.70 | 2.33 | 5.32 | 50 / 50 |

기본 운영 설정인 동시 학생 8명·학생당 CPU 4개에서 평균 5.11초를 단순 적용하면 **80만 개에 약 5.9일**이다. 40명 전체의 실제 완료 시간을 검증한 값은 아니며, 분자 복잡도, 여러 conformer, 전처리·재시도, DB/I/O 및 서버의 다른 사용량에 따라 늘어난다. CPU 8개를 8명에게 주면 총 64개가 되므로 현재 CPU 한도 56개에서는 최대 7명만 동시에 배정된다.

한 분자의 보존 pose와 입력 conformer 파일은 평균 약 6.6KB, 이 표본의 최대는 11.4KB였다. 80만 개의 순수 파일 내용은 약 5.3GB로 외삽되며 DB, worker 결과 JSON, 로그, 파일시스템 할당 공간, 입력과 백업은 별도다. 원본 [50개 분자 실측](measurements/docking-50-compounds.json)과 [80만 행 DB 측정](measurements/database-800k.json)을 함께 보관한다.


4 CPU 표본에서 가장 오래 걸린 분자 1개를 별도로 실행한 메모리 probe에서는 Python 최대 RSS가 122.8MiB였다. 자식 프로세스 high-water RSS도 122.8MiB로, fork 상속을 포함하므로 두 값을 동시 사용량으로 합산하지 않는다. 이는 전체 worker·전처리·40명 실행 메모리 상한이 아니다. [단일 분자 메모리 기록](measurements/memory-single-compound.json)을 보관한다.

## 적용 범위와 남은 운영 확인

- 실제 학생 PC에서 학교 라우팅·방화벽을 통과하는 접속은 이 서버만으로 확인할 수 없다. 현재 서버 서브넷을 허용했으며 다른 학내 source CIDR은 `.env`에 추가한다.
- 금속과 보조인자의 임의 조합 전체를 검증한 것은 아니다. Gasteiger 전하 또는 QuickVina 원자형 검증 실패는 전처리 실패로 표시한다. 금속 배위 전용 scoring을 제공하지 않는다.
- PDB에 없는 외부 서열을 추론하지 않는다. 긴 결손의 정확한 접힘이나 실험적 결합 친화도는 이 자동 처리로 보장하지 않는다.
- Ligand protonation/tautomer 열거는 제외하며 macrocycle은 각 conformer에서 rigid하게 준비한다. 원래 SMILES의 형식전하와 입체화학을 유지한다.
- 40명 동시 실제 docking 부하 시험을 수행한 것은 아니다. 자원 선택 규칙은 자동 테스트, 실제 프로세스 격리는 학생 2명 통합 시험으로 검증했다.

## 재현

[운영 안내](operations.md)에 검증 명령을 정리했다. `scripts/service_check.py`, `scripts/resilience_check.py`, `scripts/scale_check.py`, `scripts/backup_check.py`, `scripts/benchmark.py`, `frontend/e2e/workspace.spec.ts`를 사용한다. 운영 주소를 변경했다면 HTTP 검증에 `--url`, 브라우저 검증에 `DOCKSCHEDULE_URL`을 지정한다. 원본 실행 보고서와 화면은 gitignored `test-results/`에 보관한다.

## 2026-10-15 코드 검토와 회귀 검증

완료된 전처리를 뒤늦은 timeout 검사로 실패 처리하는 문제, 중단 후 receptor 상태가 `preparing`에 남는 문제를 수정했다. 재시도에서는 빈 CID/SMILES의 입력 오류를 유지하고 이전 계산 메타데이터를 초기화한다. 자동 timeout 재시도 후 성공한 화합물에 이전 오류가 남던 문제도 수정했다. 계정 상태에 명시적 `null`을 보내면 DB 오류 대신 422를 반환한다.

스케줄러와 worker의 작업 상태 변경을 행 잠금으로 보호하며 재시도와 삭제도 worker 종료를 확인한다. 재시도는 계정 정지와 같은 순서로 사용자, 작업을 잠근다. 업로드 파일 처리와 PDB 검사는 API의 작업 스레드에서 실행하고, PostgreSQL에서는 업로드의 최종 용량 검사와 저장을 직렬화한다.

프런트엔드는 이전 조회가 끝난 후 다음 자동 갱신을 예약한다. 화면 이동 시 요청을 취소하고 이전 작업의 데이터와 선택 상태를 제거한다. 3D 뷰어는 필요한 화면에서만 로딩하며, 구조 로딩 완료 후 pose를 한 번 요청한다. 폐기된 뷰어의 응답을 무시하고 구조와 pose 오류를 각각 관리한다.

| 항목 | 수정 전 | 수정 후 |
| --- | ---: | ---: |
| 초기 JavaScript 번들 | 1,509.91 kB | 196.95 kB |
| 초기 JavaScript gzip | 433.66 kB | 61.60 kB |
| 작업 목록 SELECT 수: 소유자 9명, 작업 9개, 인증·전체 개수 포함 | 12 | 4 |
| 전체·사용자 저장 용량 검사 SELECT 수 | 6 | 1 |

번들 크기는 Vite production build 출력 기준이다. 별도 3D 뷰어 번들은 1,310.59 kB이며 뷰어 사용 시 내려받는다. 용량 검사는 기존 DB 세션을 재사용해 아직 커밋되지 않은 계산 결과 크기도 확인한다. 대량 library의 다음 화합물 선택에는 `(task_id, status, row_number)` 인덱스와 단일 `pending` 상태 조건을 사용해 별도 정렬을 없앴다.

- 전체 Python 테스트 **38개 통과**: 기존 실제 PDBFixer/OpenMM·QuickVina 계산 포함. 수정 전에는 신규 회귀 테스트 6개에서 상태 오류·입력 검증 오류·반복 조회를 재현했다.
- production preview의 브라우저 회귀 시나리오 **4개 통과**: 느린 응답, 작업 전환, 뷰어 지연 로딩, pose 요청 실패 후 복구. API는 테스트 응답으로 대체하고 NGL은 실제 PDB/SDF를 로딩한다.
- TypeScript 검사와 production build 통과.
- 임시 SQLite DB에서 Alembic 신규 설치·인덱스 downgrade·재upgrade 및 정렬 없는 실행 계획 확인. 운영 PostgreSQL의 동시 실행과 배포 검증은 이번 검사에 포함하지 않았다.
- 기존 Starlette/httpx deprecation warning 1개는 남아 있다.

회귀 테스트 재현:

```bash
OPENMM_CPU_THREADS=2 OPENBLAS_NUM_THREADS=1 uv run pytest -q
npm --prefix frontend run build
npm --prefix frontend run preview -- --port 5180 --strictPort
# 다른 터미널에서 실행
cd frontend
DOCKSCHEDULE_URL=http://127.0.0.1:5180 npx playwright test e2e/review-regressions.spec.ts
```

인덱스 변경은 migration `9b7c31e2a640`에 포함된다. 배포 시 기존 API 시작 명령의 `alembic upgrade head`로 적용한다. 이번 검토에서는 운영 서비스를 재배포하거나 운영 DB를 변경하지 않았다.
