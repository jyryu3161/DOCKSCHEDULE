# 외부 인터페이스 계약 (HTTP API)

소비자는 이 저장소의 React 화면과 `scripts/`의 검증 스크립트다. 모든 경로는 `/api` 아래이며 JSON을 주고받는다(파일 다운로드·업로드 제외).

## 공통 규칙

- **인증**: 로그인 응답이 설정하는 쿠키 `ds_session`(HttpOnly, SameSite=Strict). 인증이 필요한 요청은 쿠키를 보내야 한다(`credentials: same-origin`).
- **상태 변경 요청**(POST/PUT/PATCH/DELETE): 헤더 `X-DS-Request: 1` 필수. `Origin` 헤더가 있으면 호스트가 요청 `Host`와 같아야 한다. 위반 시 403 `{"detail": "요청 출처를 확인할 수 없습니다."}`.
- **오류 형식**: `{"detail": "한국어 메시지"}`. 입력 형식 오류(pydantic)는 422이며 `detail`이 오류 객체 배열이다. `ValueError`는 422와 메시지 문자열이다.
- **상태 코드 약속**: 401 로그인 필요/로그인 실패, 403 승인 전·정지·권한 없음·CSRF, 404 자료 없음 *또는 남의 자료*, 409 상태 충돌(재시도 불가 상태, 이미 있는 ID, 한도 도달), 413 업로드 한도 초과, 422 입력 오류·저장 공간 한도, 429 요청 과다, 503 분석 실행권 부족(`Retry-After: 3`).
- 모든 응답에 `Cache-Control: no-store`. 시간 값은 UTC naive ISO 문자열(뒤에 `Z` 없음)로 오며 화면이 `Z`를 붙여 해석한다.
- 이하 "승인 필요"는 `approved` 상태의 로그인 사용자, "소유자"는 해당 자료의 소유 학생 또는 관리자(그 외는 404).

## 계정

| 요청 | 입력 | 성공 출력 | 오류 |
| --- | --- | --- | --- |
| `POST /auth/register` (201) | `username`(3~80, `[A-Za-z0-9_.-]`), `name`, `student_number`, `password`(8~128) | 사용자 객체 `{id, username, name, student_number, role, status, cpu_override}` | 409 중복·`admin` ID, 422 형식, 429 |
| `POST /auth/login` | `username`, `password` | 사용자 객체 + 쿠키 설정 | 401, 403 거절/정지, 429 |
| `GET /auth/me` | — | 사용자 객체 | 401, 403 |
| `POST /auth/logout` | — | `{ok: true}` | — |
| `POST /auth/password` | `old_password`, `new_password` | `{ok: true}` (모든 세션 삭제) | 400 현재 비밀번호 불일치, 422 |
| `GET /health` | — | `{status, scheduler_heartbeat, scheduler_error}` (인증 불필요) | — |

## 관리자 (admin 필요, 아니면 403)

| 요청 | 입력 | 출력 | 오류 |
| --- | --- | --- | --- |
| `GET /admin/users` | — | 사용자 객체 배열(최근 가입 순) | — |
| `PATCH /admin/users/{id}` | `status`(`approved\|rejected\|suspended\|pending`, null 불가), `cpu_override`(1~4096 또는 null) | 사용자 객체 | 404, 400 관리자 계정 상태 변경, 422 CPU가 전체 한도 초과·status null |
| `POST /admin/users/{id}/reset-password` | — | `{temporary_password}` | 404 |
| `PUT /admin/settings` | 설정 15개 전부(아래, `gnina_top_n`은 생략하면 기본 1000) | `GET /settings`와 같은 객체 | 422 CPU 한도 불일치(기본 CPU > 전체, 전체 > 서버 CPU 수, 학생 개별 설정 > 전체) |
| `GET /admin/storage` | — | `{used_bytes, free_bytes, users:[사용자+사용량]}` | — |

설정 필드: `cpu_budget`, `max_students`, `default_cpus`, `max_compounds`(≤100000), `max_conformers`, `max_exhaustiveness`, `max_pending_per_user`, `compound_timeout`(10~86400초), `preparation_timeout`(60~86400초), `max_retries`(0~5), `storage_limit_gb`, `user_storage_limit_gb`, `retention_days`(0~3650), `gnina_top_n`(0~`max_compounds`, 기본 1000, 0=GNINA 자동 계산 안 함), `paused`.

`GET /settings`(승인 필요) → `{values, available_cpu_count, heartbeat, scheduler_error, allocated_cpus, active_students, queued}`.

## 업로드·단백질

| 요청 | 입력 | 출력 | 오류 |
| --- | --- | --- | --- |
| `POST /uploads?kind=pdb\|library` (201) | multipart `file` | `{id, filename, size, structure}` (`structure`는 PDB일 때 `inspect_pdb` 결과: `models, model, residues[], chains, seqres, atom_count`) | 413 크기, 422 PDB 형식 오류·저장 한도 |
| `GET /uploads/{id}/structure?model=` | — | PDB 구조 요약 | 404, 422 PDB 아님 |
| `POST /uploads/{id}/preview` | `{delimiter, encoding, header}` | `{columns, rows:[{row_number, values}], has_more, warnings, declared_delimiter, original_columns}` (최대 20행) | 404, 422 인코딩·구분자·형식 |
| `POST /receptors` (201) | `{upload_id, name, model, chains[], keep_heterogens[], ph}` | `{receptor_id, task_id}` | 404, 409 대기 작업 한도, 422 chain·유지 성분 |
| `GET /receptors` | — | `[{id, name, status, owner_id}]` (본인 것, 관리자는 전체) | — |
| `GET /receptors/{id}` | — | `{id, name, status, options, structure, report}` | 404 |
| `GET /receptors/{id}/file/{original\|pdb\|pdbqt\|json}` | — | 파일(`pdb\|pdbqt\|json`은 `ready`일 때만) | 404 |

## 작업

| 요청 | 입력 | 출력 | 오류 |
| --- | --- | --- | --- |
| `POST /jobs` (201) | `{name, receptor_id, library_id, library:{delimiter, encoding, header, cid_column, smiles_column}, center[3], size[3], selected_residues[], conformers, exhaustiveness, seed, strip_salts}` | 작업 객체 | 404, 409 대기 작업 한도, 422 receptor 미준비·옵션 한도 초과·library 형식·행 수 |
| `GET /jobs/summary` | — | `{total, running, done, counts}` | — |
| `GET /jobs?limit(1~200)&offset&search&state(all\|running\|done)&include_total` | — | 작업 배열 (`include_total=true`면 `{rows,total,limit,offset}`) | — |
| `GET /jobs/{id}` | — | 작업 객체 `{id, owner_id, owner_name, receptor_id, source_task_id, kind, name, status, parameters, cpu_ids, total, completed, failed, cancel_requested, error, created_at, started_at, finished_at}`. `kind='screen'`이면 `gnina: {active(대기·실행 중 gnina 작업 id 또는 null), status, scored, failed, pending, top_n, can_resume}`가 붙는다 | 404 |
| `POST /jobs/{id}/cancel` | — | 작업 객체 | 404 |
| `POST /jobs/{id}/retry` | — | 작업 객체 | 404, 409 아직 종료·반환 전 / 분석·`gnina` 작업 직접 재시도 / 분석·GNINA 진행 중 |
| `DELETE /jobs/{id}` | — | `{ok: true}` | 404, 409 종료된 screening만 / 분석 진행 중 |

## 결과·내보내기

`{compound_id}`는 library의 CID 문자열이 아니라 `results` 응답 각 행의 정수 `id`(DB 화합물 번호)다.

| 요청 | 입력 | 출력 | 오류 |
| --- | --- | --- | --- |
| `GET /jobs/{id}/results?page&page_size(1~200)&search&status&sort(affinity\|row\|consensus\|cnn_score\|cnn_affinity\|cnn_vs)&w(0~1, 기본 1)&min_cnn_score(0~1)` + 상호작용 필터 | — | `{total, page, rows:[{id,row_number,cid,smiles,normalized_smiles,status,affinity,error,elapsed,details,gnina}]}` (`affinity` 오름차순, 점수 없음은 뒤). `gnina`는 기록이 없으면 `null`, 있으면 `{status, cnn_score, cnn_affinity, cnn_vs, gnina_vina, error, rank:{vina, cnn_affinity, cnn_score, cnn_vs, consensus}}`(`succeeded`가 아니면 점수·순위가 null, 지표별 순위는 소수 가능, `consensus`는 정수) | 404, 422 필터·`w`·`min_cnn_score` 범위 |
| `GET /jobs/{id}/compounds/{compound_id}/{sdf\|pdbqt}` | — | 최상 pose 파일 | 404 (성공/부분 성공만) |
| `GET /jobs/{id}/scores?format=csv\|tsv&w` | — | 입력의 모든 행(실패·미완료 포함) 스트림. 끝에 GNINA 열 6개 추가 | 404, 422 |
| `POST /jobs/{id}/gnina` (201) | — | 새 `gnina` 작업 객체(`parameters={top_n, auto:false}`) | 404, 403 CSRF, 409 screening 미종료·활성 gnina 작업 있음·`gnina_top_n`=0·계산할 대상 없음, 422 저장 공간 한도 |
| `GET /jobs/{id}/archive` | — | ZIP: `scores.csv`, `manifest.json`(GNINA 기록이 있으면 `gnina:{version, binary_sha256, top_n, scored}`), `receptor/*`, `poses/row-N.{sdf,pdbqt}` | 404 |

## 상호작용 분석

상호작용 필터(결과·후보 CSV 공통 쿼리): `interaction=true`, `residue`(반복, 잔기 키 `chain:번호:insertion`, 최대 100개), `kind`(반복, `hydrogen_bond|hydrophobic|salt_bridge|pi_stacking|cation_pi|halogen_bond`), `match=any|all`. `interaction=true`이면 잔기·타입이 각각 1개 이상이어야 하고(422) 잔기는 receptor의 단백질 잔기여야 한다(422). 일치한 행에는 `matched_interactions:[{residue, kind, count, distance}]`가 붙는다.

| 요청 | 입력 | 출력 | 오류 |
| --- | --- | --- | --- |
| `GET /jobs/{id}/compounds/{compound_id}/interactions` | — | `{engine, engine_version, schema_version, interactions:[{id, kind, type, role, residue, ligand_atoms[], protein_atoms[], ligand_position, protein_position, distance, angles}], warnings[]}` | 404 pose 없음, 409 receptor 미준비, 503(`Retry-After: 3`), 422 분석 실패 |
| `GET /jobs/{id}/interaction-index` | — | `{eligible, analyzed, failed, remaining, job, busy, failures[≤10], residues[]}` | 404, 409 screening 아님 |
| `POST /jobs/{id}/interaction-index` (201) | — | 분석 작업 객체(`kind='interactions'`) | 404, 409 이미 진행 중·새로 분석할 pose 없음·receptor 미준비 |
| `GET /jobs/{id}/interaction-candidates.csv` | 상호작용 필터 + `search`, `status` | CSV 스트림(헤더 10열: `row_number, CID, SMILES, affinity_kcal_mol, matched_interactions, residue_match, selected_residues, selected_types, engine_version, exported_at_utc` 뒤에 GNINA 열 6개 `gnina_status, gnina_cnn_score, gnina_cnn_affinity, gnina_cnn_vs, gnina_vina, gnina_consensus_rank`; 쿼리 `w` 추가) | 404, 422 필터 없음 |

모든 CSV 응답은 UTF-8 BOM을 붙이고, 사용자 입력 텍스트가 수식 문자로 시작하면 `'` 접두를 붙인다.
