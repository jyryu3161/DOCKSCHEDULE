# 도메인 규칙

수업용 서비스다. 학생이 단백질(PDB)과 화합물 library(CSV/TSV의 SMILES)를 제출하면 QuickVina 2.1 docking 결과를 받고, affinity 상위 화합물은 GNINA로 재점수화된다. 점수는 교육용 계산값이며 실험적 친화도가 아니다.

## 용어

- **작업(task)**: 계산 단위. 종류는 `prepare`(단백질 전처리), `screen`(library docking), `interactions`(library 전체 상호작용 분석), `gnina`(상위 pose의 GNINA 재점수화). 화면의 "Screening"은 `screen`이다.
- **receptor**: 전처리를 마친(또는 마치는 중인) 단백질. 한 번 만들면 여러 screening에서 재사용한다.
- **화합물 행**: library의 한 행. 같은 CID가 여러 행에 나와도 별개의 행이다.
- **affinity**: QuickVina가 낸 점수(kcal/mol, 낮을수록 좋음). conformer 최소화 에너지와 별개의 값이다.
- **잔기 키**: `chain:번호:insertion code` (예: `A:25:`, chain이 비어 있으면 `:25:`). chain·번호·insertion code가 모두 같아야 같은 잔기다.

## 계정

- 가입한 계정은 `pending`이다. 관리자가 `approved`로 바꾸기 전에는 로그인만 되고 업로드·작업·조회는 모두 거절된다.
- 상태: `pending`, `approved`, `rejected`, `suspended`. `rejected`/`suspended`는 로그인할 수 없다.
- 계정을 `rejected`/`suspended`로 바꾸면 그 사용자의 모든 로그인 세션이 삭제되고, 대기·실행 중인 작업에 취소가 요청된다.
- `admin` ID는 가입으로 만들 수 없다. 관리자 계정은 `approved` 외의 상태로 바꿀 수 없다.
- 학생 CPU 개별 설정(`cpu_override`)은 전체 CPU 한도를 넘을 수 없고, 전체 한도를 개별 설정보다 낮출 수도 없다.

## 단백질 전처리(receptor)

입력은 PDB 하나, 사용할 model·chain, 유지할 비단백질 성분(금속·보조인자 등), 수소 추가 pH(기본 7.4, 0~14)다.

- 잔기 분류 순서: 물 이름(`HOH`,`WAT`,`DOD`)이면 `water`, 금속 이름이면 `metal`, 보조인자 이름(HEM·FAD·NAD 등)이면 `cofactor`, 그 외에 `ATOM` 기록이거나 표준 아미노산·`SEQRES`·`MODRES`에 나오는 이름이면 `protein`, 나머지는 `other`다. 따라서 이름이 금속·보조인자 목록에 있으면 `ATOM` 기록이어도 단백질이 아니다.
- 유지 대상은 선택한 chain의 비단백질 성분만 고를 수 있다. 목록에 없는 키를 보내면 거절한다. 유지하지 않기로 한 성분은 결과에 들어가지 않는다.
- 유지 성분에 대체 위치(altloc)가 있으면 occupancy 합이 가장 큰 하나만 남기고, 동률이면 `A`를 우선한다. 위치 표시가 없는 원자는 모든 대체 위치에 속한다.
- 결손 잔기 복구의 근거는 업로드한 PDB의 `SEQRES`뿐이다. `SEQRES`가 없으면 존재하는 잔기의 누락 원자만 보완하고 결손 잔기의 종류는 만들지 않으며, 보고서에 그 한계를 경고로 남긴다.
- 복구로 새로 생긴 잔기는 `modeled`로 표시한다(계산으로 만든 좌표이며 실험 좌표가 아니다). 새 잔기에는 기존 번호와 충돌하지 않는 번호(필요하면 insertion code)를 배정하고, 배정할 수 없으면 실패한다.
- `MODRES`에 근거한 비표준 아미노산은 표준 잔기로 치환하고 치환 내역을 보고서에 남긴다. 알 수 없는 `ATOM` 잔기를 리간드처럼 조용히 삭제하지 않는다.
- 전처리 결과가 다음 중 하나면 성공으로 표시하지 않고 실패시킨다: 선택한 chain에 단백질 잔기 없음, 중원자 간 거리 0.45 Å 미만, 결합 길이가 0.5~2.8 Å 밖, QuickVina가 지원하지 않는 원자형, PDBQT 변환 중 중원자 수 불일치, Gasteiger 전하 계산 불가.
- receptor 상태: `queued` → `preparing` → `ready` | `failed` | `cancelled`. `ready`인 receptor만 screening에 쓸 수 있다. 전처리 제한 시간(`preparation_timeout`)을 넘기면 `failed`가 된다.
- 금속 배위 전용 scoring은 제공하지 않는다. 금속·보조인자 조합 전체가 검증된 것은 아니다.

## Library와 화합물 행

- 형식: 구분자(한 글자, 줄바꿈·따옴표 제외)와 인코딩(`utf-8-sig`, `cp949`, `utf-16`, `latin-1`), header 유무를 학생이 지정하고 CID 컬럼과 SMILES 컬럼을 서로 다르게 고른다.
- 첫 줄이 정확히 `sep=<한 글자>` 형태이면 Excel의 구분자 안내로 보고 데이터에서 제외한다. 사용자가 고른 구분자가 안내와 다르면 미리보기에 경고를 띄우되 사용자의 선택을 따른다.
- 빈 컬럼명·중복 컬럼명은 `column_N`/`이름 [2]`처럼 고유하게 바꿔 모두 선택 가능하게 한다. 데이터는 잃지 않는다.
- 완전히 빈 줄은 오류 없이 건너뛴다.
- `row_number`는 원본 파일의 줄 번호다(따옴표 안 줄바꿈, `sep=` 줄을 반영). 결과·내보내기는 이 번호로 입력과 대응한다.
- CID는 문자열로 보존하고 중복을 허용한다. CID·SMILES는 앞뒤 공백을 제거한다. CID 500자 초과, SMILES 10,000자 초과이면 제출 전체를 거절한다.
- CID 또는 SMILES가 빈 행은 제출 시점에 `failed`(오류 "CID 또는 SMILES가 비어 있습니다.")로 기록되고 계산하지 않는다. 다른 행은 계속 진행한다.
- 행의 컬럼 수가 첫 행과 다르거나, 데이터가 0행이거나, 행 수가 `max_compounds`(관리자 설정, 1~100,000)를 넘으면 제출 전체를 거절한다. 거절된 제출은 작업도 화합물도 만들지 않는다(원자적).
- SMILES 정규화: 여러 조각이면 `strip_salts`(기본 켜짐)일 때 탄소를 가진 가장 큰 조각(중원자 수 기준)만 남기고 제거한 조각을 기록한다. 탄소 조각이 없거나 가장 큰 두 조각의 크기가 같으면 "주성분을 선택할 수 없음" 오류다. `strip_salts`를 끄면 여러 조각은 오류다. 중원자 200개 초과는 오류다. 입체화학과 형식전하는 보존하며 pH별 protonation·tautomer는 열거하지 않는다.

## 화합물 docking

- 입력: grid 중심 `center`(x,y,z), 박스 `size`(각 축 1~100 Å, 기본 20), conformer 수(1~100, 기본 1), exhaustiveness(1~1024, 기본 8), seed(기본 42), `strip_salts`. conformer 수와 exhaustiveness는 관리자 상한(`max_conformers`, `max_exhaustiveness`)을 넘을 수 없다. 선택 잔기는 receptor에 있는 키여야 한다.
- 계산: 정규화한 SMILES → 수소 추가 → ETKDGv3로 conformer 생성(RMS 0.5 Å 미만은 제거) → MMFF94 최소화(MMFF 파라미터가 없으면 UFF, 둘 다 없으면 실패) → Meeko로 PDBQT 준비(macrocycle은 conformer마다 rigid 처리) → QuickVina(`--num_modes 1`, 예약된 CPU 수를 `--cpu`로).
- 한 conformer가 실패(최소화 미수렴, 에너지 비유한, 준비 실패, QuickVina 오류)해도 다른 conformer는 계속한다. 모든 conformer가 실패하면 화합물이 `failed`다.
- 최종 pose는 conformer 중 affinity가 가장 낮은 것 하나다. 모든 conformer가 성공했고 요청한 수만큼 생성됐으면 `succeeded`, 하나라도 실패했거나 생성된 수가 요청보다 적으면 `partial`. 실패한 화합물에는 점수를 채우지 않는다(affinity는 비어 있다).
- 화합물 상태: `pending` → `running` → `succeeded` | `partial` | `failed`. 중단·재시작으로 `running`에 남은 행은 `pending`으로 되돌려 다시 실행한다. 완료된 행은 재실행하지 않는다.
- 화합물 처리 시간이 `compound_timeout`(기본 600초, 작업 제출 시점의 값이 작업에 복사되어 이후 설정 변경은 그 작업에 적용되지 않는다)을 넘으면 계산 프로세스 트리를 종료한다. 시도 횟수가 `max_retries`(기본 1) 이하이면 `pending`으로 되돌려 자동 재시도하고, 넘으면 `failed`(시간 초과 오류)다. 자동 재시도 대상은 시간 초과뿐이며 다른 실패는 자동 재시도하지 않는다. 재시도 후 성공하면 이전 오류를 지운다.
- 모든 결과에 엔진 SHA256, RDKit·Meeko 버전, conformer별 상태·에너지, 사용 CPU 수, 입력 파라미터를 `details`에 남긴다.

## 작업(task) 상태와 재시도

- 상태: `queued` → `reserved`(CPU 예약됨) → `running` → `completed` | `partial` | `failed` | `cancelled`.
- 종료 상태 계산(`screen`): 성공(`succeeded`/`partial`) 화합물이 하나도 없으면 `failed`; 있으면서 실패 행 또는 `partial` 행이 있으면 `partial`; 아니면 `completed`.
- 취소: 종료 전 작업에 취소를 요청할 수 있다. 하위 계산 프로세스를 종료한 뒤에야 CPU를 반환하고, 이미 완료된 화합물 결과는 보존한다. 종료된 작업의 취소 요청은 효과가 없다.
- 재시도: `partial`/`failed`/`cancelled`이면서 CPU가 반환되고 worker가 없을 때만 가능하다(그 전에는 409). `screen` 재시도는 `failed`·`running`·`partial` 화합물 중 CID와 SMILES가 둘 다 있는 행만 `pending`으로 되돌리고(시도 횟수·오류·점수·세부 정보 초기화) 성공 행은 유지한다. 입력이 빈 행은 계속 `failed`로 남는다. `prepare` 재시도는 receptor를 `queued`로 되돌린다.
- 삭제는 종료된 `screen`만 가능하다. 진행 중이면 취소하고 CPU가 반환된 뒤 삭제한다. 삭제는 그 screening의 파일·화합물·상호작용 분석을 지우며 원본 업로드와 receptor는 지우지 않는다.
- 학생이 직접 지울 수 있는 것은 현재 screening 작업뿐이다. 업로드와 receptor를 학생이 삭제하는 기능은 없다.

## 자원 배분

- 한 학생은 동시에 작업 하나만 실행한다(`prepare`·`screen`·`interactions`·`gnina` 합산). 같은 학생의 다른 작업은 `queued`로 기다린다.
- 실행 중 작업의 CPU 집합은 서로 겹치지 않는다. 작업이 배정받는 CPU 수는 `screen`/`prepare`는 학생 `cpu_override` 또는 `default_cpus`, `interactions`는 항상 1이다(`gnina`는 `screen`과 같다).
- 동시에 실행 중인 학생 수는 `max_students`, 배정된 CPU 합계는 `cpu_budget`을 넘지 않는다. 서버가 쓸 수 있는 CPU 수가 `cpu_budget`보다 작아도 서버 쪽이 한도다.
- 선택 순서: 대기 작업을 제출 시각 순으로 훑되, 이미 실행 중인 학생의 작업·승인되지 않은 학생의 작업·취소 요청된 작업은 건너뛴다. 필요한 CPU 수가 남은 한도나 비어 있는 CPU보다 크면 그 작업만 건너뛰고 뒤의 더 작은 작업이 먼저 실행될 수 있다(엄격한 FIFO가 아니다). 동시 학생 수 한도에 도달하면 더 보지 않는다.
- `paused`가 켜지면 새 배정을 하지 않는다. 이미 실행 중인 작업은 영향을 받지 않는다.
- 한도를 낮춰도 실행 중 작업의 예약은 종료 때까지 유지된다. 즉시 줄이려면 해당 작업을 취소해야 한다.
- 학생당 대기+실행 작업 수는 `max_pending_per_user`(기본 3) 미만이어야 새 작업(전처리·제출·재시도·분석 요청)을 만들 수 있다. `gnina` 작업은 이 개수에 세지 않는다.
- 같은 학생의 대기 `gnina` 작업은 그 학생의 다른 대기 작업보다 먼저 선택된다(`choose_tasks`가 학생의 가장 앞선 대기 작업 위치로 옮긴다). 자동 등록된 `gnina` 작업(`parameters.auto`)은 더 나아가 다른 학생의 대기 작업보다도 먼저 선택되어, screening이 비운 자리를 이어받아 docking+GNINA가 한 세트로 끝난 뒤 다음 학생으로 넘어간다. 수동 "이어서 계산" 작업은 일반 순서를 따른다.

## 저장 공간

- 사용량 = 업로드 크기 + receptor 산출물 크기 + 작업 산출물·로그 크기. 전체(`storage_limit_gb`)와 학생별(`user_storage_limit_gb`) 한도를 모두 검사하고, 디스크 여유가 (추가분 + 2 GiB)보다 작으면 거절한다. 새 업로드·전처리·제출·화합물 계산 시작 때마다 검사한다. 화합물 계산을 시작할 때 한도를 넘으면 그 화합물이 아니라 작업 전체가 `failed`(오류 메시지에 한도 사유)가 된다. 업로드 원본과 receptor 산출물은 삭제 수단이 없어(학생이 지울 수 있는 것은 screening 작업뿐) 학생별 한도에 계속 누적된다. 한도에 도달한 학생은 관리자가 한도를 올리거나 직접 정리하기 전에는 새 업로드·전처리·제출이 막힌다.
- 보존 기간 `retention_days`가 양수이면 종료 후 그 기간이 지난 `screen` 작업을(분석 작업 포함) 정기적으로 삭제하고 감사 기록을 남긴다. 0이면 자동 삭제하지 않는다. 진행 중인 상호작용 분석이 있는 작업은 삭제하지 않는다.

## Pose 상호작용 분석

- 대상은 성공/부분 성공이면서 affinity가 있는 pose, 그리고 `ready`인 receptor다.
- 판정은 ProLIF의 원자형·거리·각도 기준이다. 상호작용 타입은 6종이다: `hydrogen_bond`, `hydrophobic`, `salt_bridge`, `pi_stacking`, `cation_pi`, `halogen_bond`(이 여섯 가지가 전부다). 수소결합 기본 기준은 donor–acceptor 3.5 Å 이하, donor–H–acceptor 각도 130~180°, 소수성·염다리는 4.5 Å 이하이다.
- 분석하는 것은 전처리된 단백질의 아미노산 잔기와 선택한 pose뿐이다. 물 매개 결합, 금속 배위, 보조인자, 결합 에너지는 분석하지 않는다. 단백질의 수소 위치와 리간드의 원래 형식전하에 의존한다.
- 결과의 리간드 원자 번호는 내려받은 SDF의 1부터 시작하는 원자 순서와 같아야 한다. SDF에 수소가 없어 추가한 수소는 원본 번호가 없다(번호 없음으로 표시).
- "검출 0개"와 "분석 실패"를 구분한다. 분석이 실패해도 pose 조회·다운로드는 가능하다.

## Library 전체 상호작용 분석과 후보 검색

- 분석 요청 시점의 성공/부분 성공 pose가 대상이다. 화합물 분석 상태: `pending` → `succeeded` | `failed`. `succeeded`는 접촉이 0개여도 성공이며 재계산하지 않는다. 실패·취소된 항목과 새로 생긴 pose는 "미분석·실패 항목 분석"으로 이어서 처리한다(새로 분석할 pose가 없으면 409).
- 후보 검색 조건: 잔기 키 1개 이상 + 상호작용 타입 1개 이상(둘 다 필요). 타입은 OR이다. `match=any`는 선택 잔기 중 어느 하나에서 선택 타입 중 하나가 있으면 후보, `match=all`은 선택한 모든 잔기 각각에서 선택 타입 중 하나 이상이 있어야 후보다. 잔기마다 서로 다른 필수 타입을 지정하는 조건은 지원하지 않는다.
- 분석 성공 항목만 후보가 될 수 있다. 미분석·실패 항목은 후보에서 제외되며 화면에 개수를 따로 표시한다. 진행 중 검색에는 그때까지 저장된 결과만 포함된다.
- docking을 재시도해 다시 계산되는 화합물의 이전 분석·접촉 기록은 지운다.
- 분석 작업이 대기·실행 중인 screening은 docking 재시도와 삭제를 할 수 없다(분석을 취소해 자원이 반환된 뒤 가능). 분석 작업을 취소해도 docking 결과는 보존된다.
- 후보 CSV는 입력 순서로 화합물당 한 행, 일치한 잔기·타입·접촉 수·최소 거리, 검색 조건, 엔진 버전을 담는다.

## 내보내기

- 점수 CSV/TSV는 실패·미완료 행을 포함해 입력의 모든 행을 낸다(점수는 빈 값). ZIP은 receptor, 성공 pose(SDF·PDBQT), 점수표, 실행 설정(manifest)을 담는다. UTF-8 BOM을 붙인다.
- 학생이 입력한 문자열이 `=`, `+`, `-`, `@`, 탭, 캐리지 리턴으로 시작하면 앞에 `'`를 붙여 스프레드시트 수식으로 실행되지 않게 한다. 모든 CSV 내보내기에 적용한다.

## GNINA 재점수화와 후보 순위

- QuickVina pose는 바꾸지 않고 GNINA `--score_only`로 CNN 점수만 매긴다(CPU 전용, GNINA 기본 CNN). 입력은 전처리된 `receptor.pdb`와 화합물 `best.sdf`(수소가 없으면 좌표를 보존해 임시 입력에만 수소를 추가, protonation 열거 없음).
- 자동 등록: `screen`이 `completed`/`partial`이 되면(재시도 후 다시 끝나는 경우 포함) `gnina` 작업이 만들어진다. `cancelled`/`failed`에는 만들지 않는다. 관리자 설정 `gnina_top_n`(0~`max_compounds`, 기본 1000, 0이면 끔)은 작업 생성 시 `parameters.top_n`으로 복사된다. 계산할 화합물이 없거나 같은 screening에 대기·실행 중인 `gnina` 작업이 있으면 만들지 않는다.
- 대상: 성공/부분 성공이고 affinity가 있는 화합물을 affinity 오름차순, 동률은 `row_number` 순으로 정렬한 상위 정확히 N개. 이미 `succeeded`인 GNINA 기록은 다시 계산하지 않고, N 밖으로 밀린 기존 `succeeded` 기록도 지우지 않는다.
- 기록(`gnina_scores`): `status`는 `pending`→`succeeded`|`failed`, 점수는 `cnn_score`, `cnn_affinity`, `cnn_vs`(= `cnn_score × cnn_affinity`, 우리가 계산), `gnina_vina`(GNINA의 Vina 계열 점수, QuickVina `affinity`와 별개). 실패 화합물은 점수를 채우지 않고 순위에서 제외된다. 화합물을 묶음(기본 25개)으로 계산하고 묶음이 실패하면 하나씩 다시 실행해 실패를 격리한다.
- 종료 상태: 전부 성공 `completed`, 일부 실패 `partial`, 성공 없음 `failed`, 취소 `cancelled`(완료된 기록은 보존). 이어서 계산에서는 이미 성공한 기록도 성공 수에 포함되므로 새 대상이 모두 실패해도 `partial`이 된다. 학생은 `gnina` 작업만 취소할 수 있고 docking 결과는 보존된다. 중단·재시작 후에는 `pending` 기록만 이어서 계산한다.
- 이어서 계산(`POST /jobs/{id}/gnina`): 선정 규칙을 다시 적용해 계산 대상이 있으면 새 작업을 만든다(`gnina_top_n=0`·대상 없음·활성 작업 있음·screening 미종료는 409). `gnina` 작업의 `retry`는 409다.
- docking 재시도가 다시 계산하는 화합물의 GNINA 기록만 지운다. 재시도가 끝나면 자동 등록으로 새로 선정된 화합물만 계산한다. GNINA 작업이 대기·실행 중이면 그 screening의 docking 재시도·삭제는 409다.
- 순위는 보는 시점에 계산하며 저장하지 않는다. GNINA 집합 = `succeeded` 기록(점수·QuickVina affinity가 모두 있음). 지표별 순위는 QuickVina affinity 오름차순, `cnn_affinity`·`cnn_score`·`cnn_vs` 내림차순이며 동률은 평균 순위를 공유한다. 합의 순위 = `w × (cnn_affinity 순위) + (1−w) × (QuickVina 순위)`(`w` 0~1, 기본 0.5, 낮을수록 좋음)를 정렬한 정수 서수이고 동률은 `row_number` 순이다. 순위 값은 항상 GNINA 집합 전체 기준이며 검색·상태·`min_cnn_score`·상호작용 필터는 보이는 행만 바꾼다. 집합 밖 화합물은 GNINA 정렬에서 뒤에 온다.
- 내보내기: 점수 CSV/TSV·후보 CSV에 `gnina_status`, `gnina_cnn_score`, `gnina_cnn_affinity`, `gnina_cnn_vs`, `gnina_vina`, `gnina_consensus_rank`(`w` 기본 0.5)가 추가되고 ZIP manifest에 GNINA 버전·SHA256·`top_n`이 들어간다.
- 합의 순위의 가중치는 타깃마다 최적값이 달라 고정하지 않았고 검증 데이터도 없다. 점수는 교육용이며 실험 친화도가 아니다.
