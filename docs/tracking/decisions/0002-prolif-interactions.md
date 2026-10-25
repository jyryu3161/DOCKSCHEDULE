# 0002. 상호작용 분석 도구로 ProLIF 선택

## 맥락
docking pose의 수소결합·소수성·염다리·π·할로젠 상호작용을 원자 단위로 표와 3D 화면에 보여주고, library 전체에서 잔기·타입별 후보를 찾아야 한다. 입력은 Meeko가 만든 결합 차수·입체화학 보존 SDF와 수소가 포함된 전처리 PDB다.

## 결정
ProLIF(MDAnalysis 포함)를 쓴다. RDKit 분자를 직접 받고, 원래 분자 기준 `parent_indices`와 거리·각도 metadata를 제공하며, `count=True`로 한 잔기의 모든 원자 조합을 보존한다. 수소결합은 직접 만든 거리 판정이 아니라 ProLIF의 원자형·각도 기준을 쓴다.

## 대안
- ODDT: RDKit/Open Babel 기반이고 구현은 가능하지만 표에 필요한 거리·각도와 toolkit별 원자/잔기 대응을 따로 조립해야 해서 연결 비용이 크다.
- PLIP: PDB complex와 보고서 생성에 적합하나 receptor와 SDF를 complex로 조립하고 리간드 원자 대응을 검증하는 단계가 추가로 필요해 채택하지 않았다.

## 결과
- MDAnalysis 등 의존성이 늘어 `uv.lock`으로 고정해야 하고, MDAnalysis의 폐기 예고 경고가 있다.
- ProLIF의 `ResidueId`에 insertion code가 없어 분석 중 내부 번호를 부여하고 출력에서 원래 식별자로 복원해야 한다.
- 물 매개 결합, 금속 배위, 보조인자 상호작용과 에너지 해석은 지원하지 않는다.
