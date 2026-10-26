# migrations — Alembic 스키마 이력

## 범위
PostgreSQL(운영)과 SQLite(개발·테스트) 양쪽의 스키마 변경 이력. 현재 head는 `c4e8a1d57f23`(GNINA 점수 테이블·`gnina_top_n` 설정). 순서: `21f4ef049b76`(초기) → `742e1d0bc899`(산출물 용량 집계) → `9b7c31e2a640`(화합물 큐 인덱스) → `b63d14a829f0`(상호작용 인덱스) → `c4e8a1d57f23`.

## 이 모듈의 범위가 아닌 것
- 모델 정의(`backend/dockschedule/models.py`)와 운영 설정 기본값(`DEFAULT_SETTINGS`)은 여기서 바꾸지 않는다. 설정 값 채우기가 필요하면 데이터 migration으로 별도 작성한다.
- 이미 배포된 migration 파일은 수정하지 않는다(새 revision을 추가한다).

## 불변 조건
- `models.py`를 바꾸는 변경에는 같은 변경 안에 새 revision이 있어야 한다. api 컨테이너가 시작할 때 `alembic upgrade head`를 실행하므로 누락하면 운영 서버가 모델과 다른 스키마로 뜬다.
- 각 revision은 `upgrade`와 `downgrade`를 모두 가진다.
- SQLite에서는 `ALTER TABLE ... ADD COLUMN`을 직접 쓴다. 테이블을 재생성하는 방식은 `PRAGMA foreign_keys=ON` 상태에서 `ON DELETE CASCADE`로 자식 행(화합물 등)을 지운다. PostgreSQL은 `add_column` + `create_foreign_key`를 쓴다(`dialect.name`으로 분기).
- 기존 작업·화합물·결과 행이 업그레이드 후에도 보존되어야 한다.

## 핵심 구현 패턴
- `env.py`가 설정의 `DATABASE_URL`을 읽는다. `alembic.ini`는 `prepend_sys_path = backend`로 패키지를 import한다.
- 외래키에 이름을 붙여(`task_source_fk` 등) PostgreSQL에서 downgrade가 제약을 지울 수 있게 한다.
- 인덱스 이름은 모델의 `Index(...)` 이름과 같게 한다(`compound_status`, `analysis_queue`, `interaction_lookup` 등).

## 테스트 지침
- `tests/test_migrations.py` 방식: 임시 SQLite DB에 이전 revision까지 적용 → 작업·화합물 삽입 → 새 revision 업그레이드 → 데이터 보존과 인덱스 확인 → downgrade 왕복.
- 대규모 데이터와 PostgreSQL 동작은 운영 서버(`docker compose`)에서 `scripts/scale_check.py` 등으로 확인한다.
