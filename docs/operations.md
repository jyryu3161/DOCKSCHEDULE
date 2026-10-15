# DOCKSCHEDULE 운영 안내

이 서비스는 학생의 PDB와 SMILES library를 받아 CPU에서 QuickVina 2.1을 실행한다. PostgreSQL에 진행 상태를 기록하고, Redis와 RQ로 계산 worker를 실행한다. Docker Compose 프로젝트 이름은 `dockschedule`이다.

## 설치와 접속

x86_64 Linux, Docker Engine과 Compose를 사용한다. 저장소에서 `python3 scripts/install.py`를 실행하면 관리자 초기 비밀번호를 입력받고 서비스를 구성한다. 기존 `.env`가 있으면 다시 초기화하지 않는다. 최초 관리자 ID는 `admin`이다. 변경한 관리자 비밀번호는 DB에 hash로 저장되며, 서비스를 재시작해도 설치 당시 비밀번호로 되돌리지 않는다.

`.env`의 `BIND_IP`, `APP_PORT`, `ALLOWED_NETWORKS`를 운영 환경에 맞게 지정한다. 예를 들어 서버 주소가 `103.49.46.62`이고 학생의 접속 대역이 `103.49.46.0/25`라면 해당 IP에 웹 포트를 바인딩하고 그 CIDR을 허용 목록에 넣는다. CIDR은 접속하는 학생의 실제 source IP 기준이다. 다른 학내 subnet은 학교에서 확인한 대역만 추가한다. IP와 포트로 접속하며 DB와 Redis 포트는 호스트에 공개하지 않는다.

기본 설치는 `127.0.0.1:8890`으로 시작한다. 설정 변경 후 `docker compose up -d`로 반영한다. Nginx는 localhost와 명시한 학내 대역만 허용한다. Docker의 포트 전달을 통해 들어오는 호스트 로컬 연결을 위해 해당 Docker bridge의 gateway 주소도 허용한다. 임의의 `X-Forwarded-For` 헤더로 접근 제한을 우회할 수 없도록 프록시가 실제 source 주소로 덮어쓴다.

`COOKIE_SECURE=false`는 학내 HTTP 접속용 설정이다. 학교 HTTPS reverse proxy를 추가한다면 인증서와 origin 전달을 구성하고 `COOKIE_SECURE=true`로 전환한다. `.env`와 백업은 비공개 파일로 관리한다.

## 학생 사용 순서

1. ID, 이름, 학번, 비밀번호로 가입하고 관리자의 승인을 기다린다.
2. 새 Screening에서 PDB를 업로드한다. model, chain, 유지할 금속과 보조인자, 수소 추가 pH를 확인한 뒤 전처리를 요청한다.
3. 전처리 완료된 단백질을 선택하고 sequence 또는 structure viewer에서 잔기를 선택한다. 중심 좌표와 박스 크기를 직접 조정할 수도 있다.
4. CSV 또는 TSV library를 업로드한다. 구분자, 인코딩, header 여부를 지정하고 미리보기에서 CID와 SMILES 컬럼을 선택한다. Excel의 첫 줄 `sep=,` 같은 안내는 자동으로 건너뛴다. 빈 컬럼명과 중복 컬럼명은 선택할 수 있게 자동 표기하며, `Catalog ID`도 CID 후보로 인식한다.
5. Conformer 수와 exhaustiveness를 설정하고 제출한다. 기본 conformer 1개를 RDKit으로 생성·최소화하며, 최종 결과는 화합물당 best pose 1개다.
6. 작업 화면에서 진행 중 결과를 조회한다. 점수 CSV와 TSV에는 실패와 미완료 행도 포함된다. ZIP에는 receptor, 최상 pose, 점수표와 실행 설정이 들어간다.
7. 성공한 화합물을 선택하면 pose 아래에 상호작용 표가 나타난다. 수소결합, 소수성 접촉, 염다리, π–π, 양이온–π, 할로젠 결합을 유형별로 필터링할 수 있다. 행을 클릭하면 해당 잔기와 ligand 원자를 강조하고 거리·라벨을 표시한다. `리간드 원자 번호`는 SDF의 1부터 시작하는 원자 번호이며, `상호작용 CSV`는 현재 필터에 표시되는 모든 행을 내려받는다.

브라우저를 닫아도 계산은 계속된다. 실패하거나 취소한 작업은 완료된 화합물을 유지한 상태로 미완료 및 부분 실패 항목을 재시도할 수 있다. CSV 문자열이 Excel 수식으로 실행되지 않게 필요한 셀에는 작은따옴표가 앞에 붙는다.

Screening 작업 목록의 `페이지당 표시`에서 10·20·50·100·200개를 선택할 수 있다. 선택은 같은 브라우저에 저장되며, 검색·상태 필터에 해당하는 전체 개수와 페이지를 표시한다. 작업 목록 표시 개수와 library의 화합물 개수 상한은 별도 설정이다.

작업당 library 화합물 상한의 기본값은 100,000개다. 관리자는 `Library 최대 화합물 수`에서 1–100,000개 범위로 조정할 수 있다.

## Pose 상호작용 분석

기존 도킹 결과도 전처리 `receptor.pdb`와 `best.sdf`가 있으면 다시 docking하지 않고 분석한다. 단백질 chain, 잔기 번호와 insertion code를 유지하며 ligand 원자 번호는 내려받은 SDF의 원자 순서와 일치한다. 표에는 각도 계산에 참여한 수소·인접 원자와 방향족 고리 원자도 포함한다. 수소결합 거리는 donor–acceptor 간 거리이고 `DHA_angle`은 donor–H–acceptor 각도다. π 상호작용은 고리 중심, 할로젠 결합은 할로젠–acceptor 거리를 표시한다.

분석은 ProLIF의 원자형·거리·각도 조건에 따른 후보 검출이다. 수소결합은 3.5 Å 이하이면서 DHA 130–180°, 소수성 접촉과 염다리는 4.5 Å 이하가 기본값이다. 단백질의 수소 위치와 ligand의 원래 형식전하에 의존하며 protonation/tautomer를 다시 열거하지 않는다. 물 매개 결합, 금속 배위와 보조인자는 분석 대상에서 제외한다. 검출 0개와 분석 실패를 별도로 표시하며, 실패해도 pose 조회와 다운로드는 가능하다.

조회용 API는 `/api/jobs/{task_id}/compounds/{compound_id}/interactions`다. 기존 소유권 검사를 적용하고 성공·부분 성공 pose만 받는다. 단일 API 프로세스에서 분석을 하나씩 실행하며, 낮은 우선순위의 별도 프로세스를 CPU 1개·45초로 제한한다. 이는 docking scheduler의 CPU 예약과 별도인 웹 서비스의 부가 작업이다. 동시 요청이 3초 내 실행권을 얻지 못하면 503과 재시도 안내를 반환한다. 최근 32개 보고서를 메모리에 캐시하고 파일 변경 시 무효화하며, 별도 영속 결과 파일이나 DB migration은 필요 없다. 여러 API worker로 확장할 경우 이 제한과 캐시는 worker별로 적용된다.

업데이트는 개발 환경에서 `uv sync`와 frontend build로 반영한다. Docker 배포에는 API와 frontend 이미지 재빌드가 필요하다. 이 기능을 적용하기 위해 기존 screening 작업이나 데이터를 초기화할 필요는 없다.

## 관리자 자원 배분

전체 계산 CPU 한도, 동시 학생 수, 기본 학생당 CPU와 학생별 CPU 재정의를 설정한다. 하나의 학생은 한 번에 한 작업을 실행하고, 그 작업의 화합물과 conformer는 순차 처리한다. 예약한 CPU 집합은 학생끼리 겹치지 않는다. 전처리도 같은 자원 한도를 사용한다.

설정 변경은 신규 작업 배정에 적용된다. 실행 중인 작업의 자원은 종료 때 반환되므로 한도를 낮추면 잠시 실제 배정이 새 한도보다 클 수 있다. 즉시 중단하려면 해당 작업을 취소한다. 신규 배정 일시 중지는 이미 실행 중인 작업에는 영향을 주지 않는다.

CPU를 더 배정하는 것이 항상 전체 수업의 처리량을 높이지는 않는다. `scripts/benchmark.py`는 동일한 분자를 CPU 1, 2, 4, 8개로 실행해 처리량을 비교한다. 측정 조건과 결과는 `test-results/benchmark/report.json`에 저장한다. 초기 50개 분자 측정에서 학생당 CPU 4개는 평균 5.11초였으며, 기본 동시 8명으로 80만 개를 단순 외삽하면 약 5.9일이다. 자세한 가정과 한계는 [검증 기록](validation.md)을 확인한다.

## 중단과 복구

`docker compose restart scheduler`는 계산 프로세스를 정리하고 완료된 화합물 다음부터 재개한다. 작업과 결과를 지우려는 목적이 아니라면 Docker volume을 삭제하지 않는다. `docker compose down -v`는 DB와 큐의 영속 데이터를 제거하므로 일반 재시작에 사용하지 않는다.

계산 중 프로세스가 중단되면 마지막 미완료 화합물이 다시 실행될 수 있다. 완료한 결과는 체크포인트로 보존된다. 작업 취소는 하위 qvina 프로세스까지 종료하며, 자원 반환은 실제 프로세스 종료를 확인한 뒤 이루어진다.

Redis 장애 시 새로운 작업을 다른 executor로 우회 실행하지 않는다. `/api/health`와 관리자 화면의 scheduler 오류를 확인한다. `docker compose logs --tail 100 api scheduler`로 서비스를 점검하고, 작업별 계산 로그는 `storage/<user_id>/tasks/<task_id>/worker.log`에서 확인한다.

## 저장 공간과 보존 기간

관리자 화면에서 전체 및 학생별 용량 한도를 설정한다. 디스크 여유가 2GiB보다 적으면 새 계산 또는 업로드를 거절한다. 결과 보존 기간의 기본값 `0`은 자동 삭제하지 않는다는 뜻이다. 양수로 설정하면 해당 기간이 지난 종료된 screening 작업을 정기적으로 삭제하고 감사 기록에 남긴다. 원본 단백질과 재사용 receptor는 보존한다. 용량은 업로드와 각 화합물·전처리 결과 저장 시 DB에 누적하며 실행 중인 파일은 해당 단계 종료 후 반영된다. 물리 디스크 여유는 매번 별도로 확인한다. 외부에서 파일을 추가하거나 이전 버전 데이터를 가져왔다면 scheduler를 멈춘 유지보수 시간에 `docker compose exec -T api python scripts/reconcile-storage.py`로 기록을 재계산한다.

작업 화면의 삭제 기능은 종료된 screening의 결과를 삭제한다. 진행 중 작업은 취소하고 CPU가 반환된 후 삭제한다. 내려받은 결과를 확인한 뒤 삭제한다.

## 백업과 복원

`scripts/backup.sh /안전한/백업/경로`는 API와 계산 worker를 잠시 중지하고 DB, storage, 비공개 배포 설정을 백업한 뒤 다시 시작한다. 백업은 자동 실행하도록 예약하지 않는다. 저장 위치의 권한은 소유자만 접근하도록 제한한다.

복원은 현재 DB를 바꾸므로 먼저 현재 백업을 만든다. 사용할 `.env`의 DB 비밀번호와 네트워크 설정을 확인한 뒤 `CONFIRM_RESTORE=yes scripts/restore.sh /백업/경로`를 실행한다. 기존 storage는 날짜가 붙은 디렉터리로 보존한다. 복원 후 관리자 로그인, 작업 목록, 점수 파일, scheduler 상태를 확인한다.

## 검증 명령

개발 환경은 `uv sync`, `npm --prefix frontend ci`로 준비한다. 일반 검증은 `uv run pytest -q`, 화면 build는 `npm --prefix frontend run build`다. 실제 chemistry 테스트는 `tools/qvina2.1`이 필요하며 `uv run python scripts/download-qvina.py`로 준비한다.

운영 주소가 loopback이 아니라면 아래 HTTP 스크립트에 `--url http://서버IP:포트`를 지정하고, 브라우저 검증에는 `DOCKSCHEDULE_URL` 환경변수를 지정한다.

`uv run python scripts/service_check.py`는 테스트 학생 2명을 가입·승인시키고 실제 전처리와 docking, CPU affinity, 다운로드 권한을 검사한다. 생성한 테스트 계정은 끝나면 정지하고 결과는 관리자에게 남긴다. `uv run python scripts/resilience_check.py`는 실제 scheduler 재시작과 취소를 검증하므로 학생 작업이 없는 유지보수 시간에 실행한다.

`docker compose exec -T api python scripts/scale_check.py`는 별도 PostgreSQL DB를 만들어 80만 행을 검증한 뒤 해당 테스트 DB를 삭제한다. 실제 docking 처리량을 측정하는 검증은 아니다. 브라우저 검증은 `cd frontend && npx playwright test`로 실행하며, 필요한 Chromium 경로는 `CHROMIUM_PATH`로 지정할 수 있다.

## 과학 계산 범위

PDB의 `SEQRES`로 확인되는 결손 잔기와 기존 잔기의 누락 원자를 복구한다. `ATOM`만 있는 PDB에서 알 수 없는 아미노산 서열을 추정하지 않는다. 복구한 구조는 실험 좌표와 구분해 표시한다. 긴 결손 구간과 결합 부위 복구 결과는 구조를 확인한 뒤 해석한다.

PDBFixer/OpenMM으로 단백질을 준비하고 Open Babel의 Gasteiger 전하와 rigid PDBQT 출력을 사용한다. Ligand는 RDKit ETKDGv3와 MMFF94 또는 UFF, Meeko의 Gasteiger 전하 및 PDBQT 준비 경로를 사용한다. 원래 SMILES의 입체화학과 형식전하를 유지하며 pH별 ligand protonation 및 tautomer 열거는 수행하지 않는다. Macrocycle은 QuickVina 2.1 호환을 위해 각 입력 conformer에서 ring을 rigid하게 처리한다. 지원하지 않는 화학 성분과 원자형은 오류로 표시한다.

화합물의 docking affinity와 최소화 에너지는 다른 값이다. 점수는 동일한 receptor와 설정 안에서 비교하며 실험적 친화도로 해석하지 않는다. 엔진 체크섬, 전처리 설정, conformer별 상태와 최상 pose를 결과에 기록한다.
