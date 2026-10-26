# GNINA 1.3.3 CPU score_only 측정

환경: `python:3.12-slim-bookworm` + 고정 버전 NVIDIA wheel(`/opt/gnina-libs`, `ldconfig`), 호스트 Linux 5.15, `docker run --cpuset-cpus=<N개 코어> -e CUDA_VISIBLE_DEVICES=`. GPU 없음, `--no_gpu`.
입력: 수용체 `receptor.pdb`(작업 `d12f2215…`의 receptor `1ea3c935…`, DB `tasks.receptor_id`로 확인), 리간드는 같은 작업의 QuickVina best pose SDF 40개(H 포함, 제목줄을 `pose_<번호>`로 고유화).
명령: `gnina --score_only --no_gpu --cpu N -r receptor.pdb -l <sdf> -o <out.sdf>`. 측정은 1회씩이고 호스트에 다른 부하가 있어 ±10% 정도 흔들릴 수 있다.

## 처리 시간 (40개 pose)

| --cpu / cpuset | 화합물당 프로세스 1개 (초/개) | 40개를 SDF 한 파일로 1프로세스 (초/개) | 프로세스 오버헤드 (초/개) |
|---|---|---|---|
| 1 | 1.74 (69.4 s) | 1.23 (49.1 s) | 약 0.5 |
| 2 | 1.95 (78.1 s) | 1.25 (49.9 s) | 약 0.7 |
| 4 | 2.17 (86.9 s) | 1.51 (60.2 s) | 약 0.7 |

- `--cpu`를 늘려도 빨라지지 않았고(오히려 약간 느림) score_only의 화합물당 시간은 거의 1 CPU 시간이다. 학생 작업은 `--cpu 1` 프로세스를 CPU 개수만큼 병렬로 띄우는 편이 낫다(추정, 병렬 실행은 측정하지 않음).
- 화합물마다 프로세스를 새로 띄우면 모델 적재로 0.5~0.7초가 더 든다. 여러 분자를 한 SDF로 넘기는 batch가 유리하다.
- batch와 단일 실행의 점수 차이는 최대 1e-6, `--cpu` 1과 4의 차이도 최대 1e-6이다(결정적).
- 이 값은 score_only(재채점)이다. `--minimize`·docking 시간이 아니다.

## 점수 예 (pose, `receptor.pdb`)

| pose | Affinity(kcal/mol) | CNNscore | CNNaffinity |
|---|---|---|---|
| pose_100 | -6.50335 | 0.03785 | 3.85254 |
| pose_101 | -6.85050 | 0.18090 | 3.66572 |
| pose_102 | -6.39728 | 0.31429 | 4.34528 |
| pose_103 | -7.65930 | 0.11691 | 4.41511 |
| pose_108 | -8.79438 | 0.25122 | 4.27764 |

## receptor.pdb 대 receptor.pdbqt (참고, 첫 10개 pose, batch)

pdbqt도 수용체로 읽힌다. Affinity는 10개 중 6개가 같고 4개는 최대 0.29 kcal/mol 달랐다(pose_100 -6.503 대 -6.270, pose_105 -6.669 대 -6.959). CNNscore 차이는 최대 0.08, CNNaffinity 차이는 최대 0.15였다(pose_105 CNNscore 0.139 대 0.216). 원자 유형·수소 처리가 달라서 생기는 차이로 보이며 원인은 확인하지 않았다. 점수는 수용체 형식마다 다르므로 한 가지로 고정해야 한다.

## 출력 형식 (파서용)

`tests/fixtures/gnina_score_only_output.txt`는 3개 분자 batch의 실제 stdout이다.

stdout (분자 입력 순서대로 반복):
```
Commandline: ...
## Name <가중치 항 이름들...>                      <- 한 번만 나오는 헤더
Affinity: -6.50335 (kcal/mol)                      <- minimizedAffinity와 같은 값
CNNscore: 0.03785                                  <- 소수 5자리
CNNaffinity: 3.85254
CNNvariance: 0.85047
Intramolecular energy: -0.46904
Term values, before weighting:
## pose_100 61.37487 1102.98926 ...                <- "## <SDF 제목줄> <항 값들>"
```
- 분자 구분은 `Affinity:` 줄로 시작하는 블록이고, 블록 끝은 `## <이름> ...` 줄이다. 이름은 SDF 제목줄이다. 모든 pose의 제목줄이 같으면(QuickVina `best.sdf`는 `best`) 이름으로 구분할 수 없으므로 순서로 대응시키거나 제목줄을 고유하게 바꿔야 한다.
- stdout 값은 반올림되어 있어 정밀도가 필요하면 SDF 속성을 쓴다.

`-o out.sdf` 출력은 입력 순서 그대로이며 분자마다 입력 속성(`<meeko>` 등)을 유지하고 아래 속성을 덧붙인다(소수 10자리, `$$$$`로 끝남):
```
> <minimizedAffinity>
-6.50335

> <CNNscore>
0.0378533304

> <CNNaffinity>
3.8525428772

> <CNN_VS>
0.1458315849

> <CNNaffinity_variance>
0.8504686356

$$$$
```
`CNN_VS`는 `CNNscore × CNNaffinity`이다(0.0378533 × 3.85254 ≈ 0.14583).
`-o`를 주지 않으면 stdout만 나온다. 종료 코드는 모든 실행에서 0이었다(잘못된 입력 파일의 종료 코드는 측정하지 않음).
