# frontend — 학생·관리자 화면

## 범위
React 18 + TypeScript SPA(Vite). 로그인/가입, 대시보드(작업 목록), 새 Screening(PDB 업로드·전처리·결합 위치 선택·library 매핑·제출), 작업 상세(진행·결과 표·3D pose·상호작용), 관리자 화면(사용자·자원 설정·저장 공간). 3D 구조는 NGL 2.4.0.

| 파일 | 맡는 일 |
| --- | --- |
| `src/main.tsx` | 모든 화면(`Login`, `App`, `Dashboard`, `NewJob`, `JobDetail`, `Admin`), 해시 라우팅 |
| `src/api.ts` | `api()`/`post()` 래퍼와 서버 응답 타입(`User`, `Job`, `Residue`, `Structure`) |
| `src/useLoad.ts` | 데이터 로딩 훅 |
| `src/Viewer.tsx` | NGL 뷰어(구조·pose·grid box·잔기 선택·상호작용 연결선) |
| `src/PoseInteractions.tsx`, `src/LibraryInteractions.tsx`, `src/interactions.ts` | pose 상호작용 표 / library 잔기·타입 후보 검색 UI / 공통 타입·라벨 |
| `e2e/*.spec.ts` | Playwright 시나리오(API mock + 실제 NGL) |

## 이 모듈의 범위가 아닌 것
- 인증·권한 판단, 상태 전이 규칙, 화학 판정. 화면은 서버 응답을 표시할 뿐 권한이나 규칙의 근거가 되지 않는다.
- nginx 설정(`nginx.conf`, `network-entrypoint.sh`)은 배포 구성이며 화면 로직이 아니다.

## 불변 조건
- 서버 호출은 `api()`/`post()`만 쓴다(`X-DS-Request: 1` 헤더와 `credentials: same-origin`이 여기서 붙는다). 직접 `fetch`로 상태 변경 요청을 보내지 않는다(뷰어의 파일 GET 제외).
- 서버가 보내는 시간은 UTC이며 `Z`를 붙여 해석한다(`date()` 헬퍼).
- 자동 갱신은 이전 요청이 끝난 뒤 다음 `setTimeout`을 예약한다. 화면 이동·언마운트 시 타이머와 진행 중 요청을 취소하고 이전 작업의 데이터·선택 상태를 비운다.
- NGL 뷰어(`Viewer`)와 `PoseInteractions`는 `lazy`로만 import한다(초기 번들 약 200 kB 유지, 뷰어 번들은 별도). `LibraryInteractions`는 정적 import다.
- 잔기는 `Residue.key`(`chain:번호:insertion`)로 식별한다. 번호만으로 선택·비교하지 않는다.
- 작업 목록의 페이지 크기는 `localStorage`의 `ds.jobs.pageSize`에 저장한다(10·20·50·100·200).
- 화면 문구는 한국어다.

## 핵심 구현 패턴
- 라우팅: `window.location.hash`(`go(path)`)와 `hashchange` 리스너.
- 뷰어: 구조 로딩 완료 후 pose를 한 번 요청하고, 폐기된 뷰어(`disposed`)의 늦은 응답은 무시한다. 구조 오류와 pose 오류를 따로 관리한다.
- 폴링은 응답 후 재예약하며 간격은 화면별로 다르다(전처리 대기 2초, 작업 상세 3초, 결과 4초).
- 개발 서버는 `/api`를 `http://127.0.0.1:8091`로 프록시한다.

## 테스트 지침
- `npm --prefix frontend run build`(타입 검사 포함)가 통과해야 한다.
- 브라우저 시나리오는 느린 응답, 작업 전환, 뷰어 지연 로딩, pose 요청 실패 후 복구, 모바일 폭 overflow, 상호작용 표·필터·CSV, 후보 검색을 다룬다. `DOCKSCHEDULE_URL`로 대상 서버를 지정하고 `CHROMIUM_PATH`로 브라우저를 지정할 수 있다.
- 브라우저 테스트는 API를 mock하므로 서버 계약 변경은 pytest에서도 확인한다.
