# 로컬 테스트 가이드

이 문서는 Windows PowerShell에서 현재 `main`을 실제 Kakao 지도·장소검색,
ODsay 경로, GLO-90 경사, VWorld 건물 그늘까지 종단 테스트하는 절차다.
기본 로컬 테스트는 운영 승인을 받지 않은 AI 모델을 사용하지 않고
`ROUTE_MODE=live`의 규칙 베이스라인으로 실행한다.

## 1. 준비물

- Docker Desktop
- Git
- Python 3.11 이상
- 저장소 루트의 Git에서 무시되는 `.env.production`

키 값은 터미널, 문서, Git에 출력하거나 붙여 넣지 않는다. 현재
`.env.production`이 있으면 다시 만들 필요가 없다. 파일이 없을 때만
다음 명령으로 로컬 환경파일을 만들고, 다운로드한 env의 정확한 경로를
`--import-env`에 전달한다.

```powershell
cd C:\Users\KiKi\Desktop\CODE\KT\KT-10
$env:PYTHONUTF8='1'
python scripts\prepare_deployment_env.py --import-existing `
  --import-env 'C:\Users\KiKi\Downloads\<전달받은-env-파일명>'
```

환경 설정을 검증한다.

```powershell
python scripts\prepare_deployment_env.py --check
docker compose --env-file .env.production -f docker-compose.prod.yml config --quiet
```

두 명령이 모두 종료 코드 0이어야 한다. 값이 누락되면 검증기가 키 문자열을
출력하지 않고 누락된 변수 이름만 표시한다.

## 2. 실제 서비스 실행

```powershell
docker compose --env-file .env.production -f docker-compose.prod.yml `
  up -d --build --wait
docker compose --env-file .env.production -f docker-compose.prod.yml ps
```

`postgres`, `ai`, `backend`, `frontend`가 모두 `healthy`이면
<http://localhost:8080>을 연다. 첫 빌드는 이미지 다운로드를 포함해 몇 분
걸릴 수 있다. Compose 포트가 `127.0.0.1:8080`에 바인딩되어 있어도
브라우저 주소는 카카오 JavaScript 키에 등록한 `localhost`를 사용한다.
`http://127.0.0.1:8080`은 카카오 개발자 콘솔에 별도 Web 도메인으로
등록하지 않았다면 지도 SDK가 `domain mismatched`로 거부한다.

우선 OD 세 개를 한 번 준비하면 이후 테스트의 외부 API 대기시간을 줄일 수
있다.

```powershell
.\.venv\Scripts\python.exe scripts\prewarm_route_cache.py `
  --base-url http://localhost:8080 `
  --od-file data\precompute\priority_od_pairs.json `
  --max-cached-seconds 3
```

가상환경이 없다면 `python scripts\prewarm_route_cache.py ...`로 실행해도
된다. 결과 JSON의 `status`가 `ok`여야 한다.

## 3. 브라우저에서 확인할 항목

1. 지도에 `API 연결 모드`가 표시되고 Kakao 지도가 렌더링되는지 확인한다.
2. 출발지에 `북구청`을 입력한 뒤 반드시 드롭다운의
   `부산광역시북구청` 결과를 선택한다.
3. 도착지에 `부산역`을 입력한 뒤 반드시 드롭다운의 `부산역` 결과를
   선택한다. 텍스트만 입력하고 결과를 선택하지 않으면 좌표가 확정되지
   않는다.
4. `경로 찾기`를 눌러 `추천 경로 3개`가 나타나는지 확인한다.
5. 카드에 `규칙 베이스라인 적합 점수`, 소요시간·도보·환승, 90m 지형
   경사, 건물 그늘 상태가 구분돼 표시되는지 확인한다.
6. 카드를 좌우로 스와이프하거나 `이전 경로 보기`·`다음 경로 보기`
   버튼을 눌렀을 때 카드와 지도 경로가 함께 바뀌는지 확인한다.
7. `그늘` 버튼을 켰을 때 선택 경로의 건물 그림자 폴리곤과
   녹색·주황 도보 구간이 나타나는지 확인한다.
8. 프로필과 `짐 많음`, `유아차`, `그늘 우선`, `계단 회피`,
   `환승 최소` 조건을 바꿔 다시 검색하고 설명과 순서가 갱신되는지
   확인한다.

현재 그늘은 VWorld 건물 도형·높이와 태양 위치로 계산한 건물 그늘이며
나무·지형 그늘은 포함하지 않는다. 경사는 GLO-90 약 90m 지형 추정이고
보도 턱이나 역사 내부 경사를 뜻하지 않는다. 미확인 값은 0으로 표시하지
않는다.

## 4. 자동 스모크와 실제 장소검색 E2E

규칙 베이스라인 상태에서 종단 스모크를 실행한다.

```powershell
$env:PYTHONUTF8='1'
.\.venv\Scripts\python.exe scripts\verify_deployment.py `
  --base http://localhost:8080 `
  --allow-local-readiness-gaps
```

완료 문구는
`배포 스모크 검증 완료: PWA, 보안 헤더, 장소, 날씨, 버스, 실경로, 경사도, 그늘`
이다. 이 옵션은 `localhost` HTTP에서만
`origin_security`, `kakao_login` 두 항목을 허용한다. 경로·건물·장소·날씨·
버스·DB 등 다른 readiness 항목이 빠지면 계속 실패하며, 공개 HTTPS 배포
검증에는 이 옵션을 사용하지 않는다.

실제 Kakao Places 선택과 경로 카드까지 브라우저 자동화로 확인하려면 다음을
실행한다.

```powershell
cd frontend
npm ci
npx playwright install chromium
$env:E2E_BASE_URL='http://localhost:8080'
npm run test:e2e:places
cd ..
```

## 5. 학습 모델 실행

현재 배포 저장소에는 동결된 평가 데이터셋과 학습 모델이 포함돼 있습니다.
다음 두 파일이 Git에 추적되는지 확인한 뒤 로컬 `.env.production`에서
`ROUTE_MODE=ai`, `RANKER_TIER=bootstrap_baseline`을 선택합니다.

- 모델: `ai/data/rankers.bootstrap-baseline.zip`
- 지표·계보: `ai/data/rankers.bootstrap-baseline.metadata.json`

로컬 origin과 6개 프로필 모델 계약을 함께 검증한 뒤 서비스를 올립니다.

```powershell
python scripts\prepare_deployment_env.py --check
docker compose --env-file .env.production -f docker-compose.prod.yml `
  up -d --build --wait
docker compose --env-file .env.production -f docker-compose.prod.yml `
  exec -T ai python -c `
  "import json,urllib.request; print(json.dumps(json.load(urllib.request.urlopen('http://localhost:8001/model/status')), ensure_ascii=False))"
```

`ready=true`, `configured_tier=bootstrap_baseline`,
`model_tier=bootstrap_baseline`이어야 합니다. AI 내부 상태 API는 공개
프론트에 노출하지 않으므로 Compose의 AI 컨테이너 안에서 조회합니다.
같은 장소 검색을 실행하면 경로 카드에는 내부 평가 방식과 무관하게
`프로필 적합 점수`만 표시돼야 합니다.

로컬 모델 모드는 `PUBLIC_ORIGIN`이 `localhost` 또는 `127.0.0.1`이고,
모델 ZIP·메타데이터·6개 프로필 계약이 모두 확인될 때만 배포 준비
검증을 통과합니다. 공개 origin에서는 관리자 승인 모델만 허용합니다.
계단·엘리베이터·저상버스 피처가 미확인인 후보가 있으면 장애인 접근성을
보장하지 않습니다.

## 6. 오류 확인과 종료

오류가 나면 키 값을 출력하지 않고 서비스 로그 끝부분만 확인한다.

```powershell
docker compose --env-file .env.production -f docker-compose.prod.yml `
  logs --tail 200 ai backend frontend
```

ODsay 403이면 로컬 PC가 외부로 나갈 때 사용하는 공인 IPv4가 ODsay
Server Key 허용 IP와 같은지 확인한다. Kakao 검색 결과가 없으면 REST 키,
지도 자체가 비면 JavaScript 키와 `http://localhost:8080` 도메인 등록을
각각 확인한다.

컨테이너만 종료하고 캐시는 보존하려면 다음을 실행한다.

```powershell
docker compose --env-file .env.production -f docker-compose.prod.yml down
```

`down -v`는 PostgreSQL·ODsay·OSMnx·고도·VWorld 캐시까지 삭제하므로 일반
테스트 종료에는 사용하지 않는다.
