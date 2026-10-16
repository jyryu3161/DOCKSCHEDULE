# DOCKSCHEDULE

수업용 QuickVina 2.1 virtual screening 플랫폼입니다. 학생이 PDB와 SMILES library를 제출하면 단백질 전처리, RDKit conformer 생성·최소화, docking과 결과 조회를 수행합니다.

- 간단한 회원가입과 관리자 승인, 학생별 자료 접근 권한
- PDB 내부 서열에 근거한 결손 잔기·원자 복구와 receptor 준비
- 연동된 sequence/structure viewer의 잔기 선택 또는 좌표 직접 입력
- CSV/TSV의 구분자, 인코딩, CID·SMILES 컬럼 지정
- 전체 CPU 한도, 동시 학생 수, 학생별 CPU 배분 및 순차 화합물 처리
- 중단 후 재개, 작업 취소, 실패 항목 재시도
- 화합물당 최상 pose 1개, affinity 표, 전체 점수 CSV/TSV와 결과 ZIP
- ProLIF 기반 단백질–리간드 상호작용 표, 잔기·원자별 3D 강조, 유형 필터와 CSV
- 라이브러리 전체 상호작용 분석, 지정 잔기·타입별 후보 필터(하나 이상/모두)와 후보 CSV

## 실행

x86_64 Linux에서 Docker Engine과 Compose를 준비하고 실행합니다.

```bash
python3 scripts/install.py
```

최초 관리자 ID는 `admin`이며 초기 비밀번호는 설치 시 입력합니다. 기본 접속 주소는 `http://127.0.0.1:8890`입니다. 학내 운영 시 비공개 `.env`에서 `BIND_IP`, `APP_PORT`, `ALLOWED_NETWORKS`를 설정한 뒤 `docker compose up -d`로 반영합니다. 학생의 실제 접속 CIDR만 허용하며 DB와 Redis는 외부에 노출하지 않습니다.

## 문서

- [설계와 구현 범위](docs/implementation-plan.md)
- [설치·사용·백업·복원 안내](docs/operations.md)
- [검증 결과와 성능 측정](docs/validation.md)
- [계산 도구와 라이선스](THIRD_PARTY.md)
- [참고 플랫폼 MDSCHEDULER](https://github.com/jyryu3161/MDSCHEDULER)

## 개발 환경

```bash
uv sync
uv run python scripts/download-qvina.py
OPENMM_CPU_THREADS=2 OPENBLAS_NUM_THREADS=1 uv run pytest -q
npm --prefix frontend ci
npm --prefix frontend run build
```

React/TypeScript/NGL, FastAPI, PostgreSQL, Redis/RQ를 사용합니다. 화학 계산은 PDBFixer/OpenMM, RDKit, Open Babel, Meeko와 체크섬을 고정한 QuickVina 바이너리로 실행하며, 선택한 pose의 상호작용은 ProLIF/MDAnalysis로 분석합니다. 실제 서비스 통합, 재시작·취소, 80만 행 조회·export, 브라우저 검증 스크립트는 `scripts/`와 `frontend/e2e/`에 있습니다.

자동 복구 구조와 docking score는 교육용 계산 결과입니다. PDB에 서열 정보가 없는 결손의 아미노산 종류를 추정하지 않으며, ligand pH별 protonation·tautomer 열거는 수행하지 않습니다.
