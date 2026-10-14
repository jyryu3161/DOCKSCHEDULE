# 구현 검증 기록

2026-10-14, 이 저장소의 단일 서버 Docker Compose 배포에서 검증했다. 실제 docking 검증과 대량 DB 검증은 서로 다른 시험이다.

## 기능 및 운영 검증

| 검증 | 결과 |
| --- | --- |
| Python 테스트 | 19개 통과. 가입·승인·정지, CSRF, 자료 소유권, 큐 자원 불변 조건, 재시작 체크포인트, 파일 용량 집계, 보존 기간, 목록 페이지 조회, CSV quoting·중복 CID·실패 행, PDB model·chain·insertion·비표준 잔기 포함 |
| 실제 화학 계산 | 1L83에서 SEQRES 결손 A163/A164 복구, 수소와 rigid receptor PDBQT 준비, RDKit 최소화와 QuickVina 실행, conformer 중 최상 pose 선택, SDF 입체화학 보존 통과 |
| 비표준 잔기 | PDB MODRES에 근거한 아미노산 치환을 실제 전처리로 검증. 알 수 없는 ATOM 잔기를 일반 리간드처럼 조용히 삭제하지 않음 |
| 유지 성분 | 1L83의 benzene을 명시적으로 유지한 전처리 통과. 대체 위치가 있는 유지 성분은 occupancy에 따라 하나만 선택 |
| 실제 서비스 통합 | 학생 2명 가입·승인 → PDB 전처리 → TSV 매핑 → 각각 화합물 3개 실행. 학생별 유효 결과 2개와 잘못된 SMILES 오류 1개, 점수 export 및 타 사용자 접근 차단 확인 |
| CPU 제한 | 학생 2명의 worker, compound process, qvina 프로세스에 각각 `[0,1]`, `[2,3]` affinity 적용 확인. 두 작업 동시 실행 확인 |
| 재시작 | 실제 scheduler 컨테이너 재시작 후 5개 화합물 완료. 재시작 전 완료한 첫 pose의 SHA256과 시도 횟수 보존 |
| 취소 | 실행 중 하위 계산 종료, 완료한 첫 화합물 보존, CPU 예약 반환 확인 |
| 백업·복원 | 운영 백업을 별도 PostgreSQL DB와 임시 디렉터리에 복원. users/tasks/compounds 행 수 및 파일 81개 해시 일치. 비공개 설정 파일 권한 600 확인 |
| 접근 제한 | 운영 IP:port에서 HTTP 200. 허용하지 않은 Docker source에서 Nginx HTTP 403, 위조 X-Forwarded-For도 HTTP 403 |
| 브라우저 | Chromium으로 로그인, 대시보드, sequence→structure 및 실제 structure 클릭→sequence, 좌표/grid, pose·affinity, 관리자 설정, 모바일 화면·로그아웃 검증 통과 |
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
