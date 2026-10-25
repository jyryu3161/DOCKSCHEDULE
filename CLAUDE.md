# DOCKSCHEDULE

수업용 QuickVina 2.1 virtual screening 웹 플랫폼이다. 학생(약 40명)이 PDB와 SMILES library(최대 100,000개)를 제출하면 단백질 전처리, 화합물 3D 준비, docking, 결과·단백질–리간드 상호작용 조회를 학내망 단일 서버(Docker Compose)에서 CPU로 수행한다. 규모는 약 8천 줄(FastAPI + PostgreSQL + Redis/RQ 백엔드, React/TypeScript/NGL 프런트엔드)이며 GPU, MD, 외부 공개 서비스, 다중 서버는 범위 밖이다. 점수는 교육용 docking score이고 실험 친화도가 아니다.

## 프로젝트 구조

```
.
├── CLAUDE.md                          ← Claude Code 진입점
├── AGENTS.md                          ← 에이전트 진입점
├── docs/
│   ├── architecture.md                ← 구성 요소, 연결, 대표 흐름, 모듈 지도
│   ├── business-rules.md              ← 도메인 규칙: 계정·전처리·library·docking·작업 상태·자원 배분·상호작용
│   ├── security.md                    ← 인증 흐름, 권한 매트릭스, 감사 대상, 자격 증명
│   ├── standards.md                   ← 병합 전 검증 게이트, 경계·잠금·DB·API 규칙
│   ├── engineering-notes.md           ← 함정과 대응(증상→원인→대응), 점검 체크리스트
│   ├── operations.md                  ← 설치, 환경 설정, 검증 명령, 백업·복원, 배포
│   ├── contracts.md                   ← HTTP API 계약(입력·출력·오류)
│   └── tracking/
│       ├── status.md                  ← 완료·검증 상태와 남은 일
│       ├── decisions/
│       │   ├── index.md               ← 결정 목록
│       │   └── NNNN-<이름>.md         ← 트레이드오프가 있던 결정 각각
│       └── findings.md                ← 지금 해결하지 못한 문제
├── backend/dockschedule/AGENTS.md     ← 서버 패키지: api·scheduler·runner·화학·상호작용
├── frontend/AGENTS.md                 ← React 화면과 NGL 뷰어
├── migrations/AGENTS.md               ← Alembic 스키마 이력
└── scripts/AGENTS.md                  ← 설치·백업·실서비스 검증 스크립트
```

## 절대 어기면 안 되는 규칙

1. **학생 간 자료 격리**: 자료를 읽거나 바꾸는 모든 API는 `owned()`로 소유자(또는 관리자)를 확인한다. 남의 자료는 403이 아니라 404로 응답한다.
2. **CPU 격리**: 작업마다 겹치지 않는 CPU를 예약하고 한 학생은 동시에 작업 하나만 실행한다. CPU 반환은 worker 프로세스 트리를 종료시키고 더 이상 살아 있지 않은 것을 확인한 뒤에만 한다.
3. **api 프로세스에서 화학 계산 금지**: RDKit·OpenMM·Open Babel·ProLIF는 CPU가 고정된 worker나 제한된 하위 프로세스에서만 실행한다.
4. **완료된 결과는 보존**: 취소·재시작·재시도·복구 어느 경로에서도 이미 완료된 화합물의 결과와 점수를 지우거나 다시 계산하지 않는다(재시도가 명시적으로 초기화하는 실패·부분 성공 행 제외).
5. **스키마 변경 = migration 동반**, QuickVina는 고정 SHA256 바이너리만 사용한다.

## 작업 전 읽을 것

항상: `docs/standards.md`, `docs/engineering-notes.md`, 수정할 모듈의 `AGENTS.md`.

작업 종류별 추가:
- 인증·권한·새 엔드포인트 → `docs/security.md`(권한 매트릭스, 감사 대상)와 `docs/contracts.md`(상태 코드·공통 규칙). 새 엔드포인트는 소유권 검사·CSRF 헤더·오류 형식을 같은 방식으로 따른다.
- 스케줄러·runner·작업 상태·취소·재시도 → `docs/business-rules.md`의 "작업(task) 상태와 재시도"·"자원 배분", `docs/engineering-notes.md`의 "스케줄러·계산 프로세스".
- 모델·스키마·설정 키 변경 → `docs/engineering-notes.md`의 "설정·스키마"(기본 설정은 최초 생성 때만 DB에 들어감, SQLite migration의 CASCADE 함정).
- 전처리·화합물 준비·docking → `docs/business-rules.md`의 해당 절과 `docs/tracking/decisions/0007-*`(서열·protonation을 추정하지 않음).
- 상호작용 분석 → `docs/business-rules.md`의 상호작용 두 절, `docs/engineering-notes.md`의 "잔기·구조 식별"과 "상호작용 분석 API".
- 배포·백업·설정 → `docs/operations.md`(특히 `down -v` 금지, 시작 순서).
- 이전 결정을 바꾸려는 경우 → `docs/tracking/decisions/index.md`에서 해당 결정을 먼저 확인한다.

## 문제 발견 시

다음은 즉시 사용자에게 보고한다: 다른 학생의 자료가 노출되는 경로, 인증·CSRF·허용 IP 우회, 비밀번호·`.env`·백업의 노출, 학생 CPU가 겹치거나 반환되지 않는 현상, DB·storage 데이터 손실 위험(`down -v`, 복원, 행 삭제를 일으키는 migration), api·DB·Redis 포트의 호스트 공개.

그 외 지금 고치지 못하는 문제는 원인과 "지금 못 고치는 이유"를 적어 `docs/tracking/findings.md`에 기록한다. 고칠 수 있으면 고치고 얻은 지식은 `docs/engineering-notes.md`에, 새 규칙은 `docs/standards.md`에 남긴다.
