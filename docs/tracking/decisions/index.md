# 결정 기록

| 번호 | 결정 |
| --- | --- |
| [0001](0001-quickvina-engine.md) | docking 엔진으로 QuickVina 2.1 사용 |
| [0002](0002-prolif-interactions.md) | 상호작용 분석 도구로 ProLIF 선택 |
| [0003](0003-db-source-of-truth.md) | 상태의 기준은 PostgreSQL, Redis는 전달용이며 장애 시 우회 실행 없음 |
| [0004](0004-one-active-task-per-student-pinned-cpus.md) | 학생당 동시 작업 1개와 학생별 고정·비중복 CPU |
| [0005](0005-sequential-compounds-per-task.md) | 작업 안에서 화합물을 하나씩 순차 처리 |
| [0006](0006-interaction-summary-storage.md) | 상호작용은 잔기·타입 요약만 DB에 저장하고 원자별 표는 조회 때 계산 |
| [0007](0007-no-inferred-sequence-or-protonation.md) | 서열 추정·pH별 protonation/tautomer 열거를 하지 않음 |
| [0008](0008-gnina-rescoring.md) | GNINA는 QuickVina pose를 score_only로 재점수화하고 순위는 보는 시점에 계산 |
