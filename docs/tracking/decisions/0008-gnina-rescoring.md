# 0008. GNINA는 QuickVina pose를 score_only로 재점수화하고 순위는 보는 시점에 계산

## 맥락
선별 벤치마크에서 Vina pose + GNINA CNN 점수가 Vina 점수 단독보다 농축 성능이 높게 보고된다(실험 hit rate와는 다른 지표). Vina와 GNINA 점수를 합치는 가중치의 최적값은 타깃마다 다르고 이 서비스에는 검증 데이터가 없다. 학생 CPU는 한 번에 작업 하나이며 GPU는 범위 밖이다.

## 결정
- docking 완료 후 affinity 상위 N개(기본 1000, 관리자 설정 `gnina_top_n`, 0이면 끔)를 별도 `gnina` 작업으로 자동 재점수화한다. pose는 바꾸지 않고(`--score_only`) CPU 전용, receptor는 PDB, pose는 수소를 포함해 입력한다.
- CNNscore·CNNaffinity·CNN_VS·GNINA의 Vina 계열 점수를 화합물별로 저장하고, 순위는 저장하지 않고 조회 때 계산한다. 기본 정렬은 QuickVina 순위와 CNNaffinity 순위의 가중 평균(기본 0.5, 학생이 화면에서 조정)이며 모든 점수로도 정렬할 수 있다.
- 공식 GNINA 정적 바이너리(v1.3.3)와 NVIDIA wheel 런타임을 고정 버전·체크섬으로 이미지에 넣는다.
- GNINA 작업은 대기 작업 한도에 세지 않고 같은 학생의 대기 screening보다 먼저 실행한다.
- 실행 시간 기준으로 N을 정하지 않는다(시간 무관). 측정값은 `docs/engineering-notes.md`에 기록한다.

## 대안
- GNINA로 다시 docking 또는 재최소화: 느리고 pose·상호작용 분석과 어긋난다.
- GPU 사용: 프로젝트 범위 밖이며 GPU 공유·격리 규칙이 새로 필요하다.
- 소스에서 CPU 전용 빌드: 빌드 재현성이 약해 고정 바이너리 원칙(결정 0001)과 맞지 않는다.
- receptor PDBQT 입력: 수소 병합으로 CNN 점수 신뢰도가 떨어질 수 있다(측정에서 PDB와 PDBQT 점수가 달랐다).
- 순위를 DB에 저장: 가중치를 보는 시점에 바꿀 수 없다.

## 결과
- 이미지가 약 6.3 GB로 커지고 첫 빌드가 길다. 공식 바이너리는 호스트(glibc 2.31)에서 실행되지 않으며 실제 GNINA 실행 테스트는 이미지 안에서만 가능하다(단위 테스트는 가짜 바이너리).
- 합의 가중치의 최적값은 검증하지 않았다. 점수는 교육용이며 실험 친화도가 아니다.
- docking 재시도가 다시 계산하는 화합물의 GNINA 기록은 지워지고 재시도가 끝나면 새로 선정된 화합물만 다시 계산된다.
