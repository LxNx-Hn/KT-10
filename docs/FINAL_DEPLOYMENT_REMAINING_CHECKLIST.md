# 최종 배포 잔여 작업 체크리스트

기준일: 2026-07-25 (Asia/Seoul)

이 문서는 현재 `main`을 실제 운영 서비스로 공개하기 전에 남은 외부
작업과 검증 절차를 정리합니다. 제품 기준은 `PRODUCT_DECISIONS.md`,
구현·데이터·모델의 상세 상태는
`CURRENT_STATUS_AND_FOLLOW_UP_REPORT.md`를 우선합니다.

## 1. 현재 완료 판정

| 범위 | 판정 | 근거 |
| --- | --- | --- |
| 규칙 기반 `live` 검증 데모 | 완료 | 실제 Kakao Local·ODsay·OSMnx·GLO-90·VWorld·OpenWeather·부산 버스 연결 |
| Kakao 지도 중심 PWA | 완료 | 장소 검색, 경로 3개, 경사·그늘 상태, 카드 이동, PWA build와 접근성 검증 |
| 로컬 프로덕션 Compose | 완료 | PostgreSQL·AI·백엔드·프론트 4개 서비스 `healthy` |
| 코드·이미지 품질 검증 | 완료 | 테스트·compile·lint·보안 감사·Docker hardened runtime·GitHub Actions 통과 |
| 인터넷 공개 운영 배포 | 미완료 | 실제 HTTPS origin과 공급자 콘솔 등록이 필요 |
| 초기 평가 기반 `ai` 순위 모델 | 완료 | 380 OD·1,137개 후보·6,822개 평가, 6개 프로필 OD holdout과 순위 API 검증 |
| 사람 검증 운영 모델 | 미완료 | 실제 사용자·전문가 라벨과 관리자 승인 모델이 없음 |
| 현장 수준 경사·그늘 정확도 검증 | 미완료 | GLO-90·공공 건물 높이 결과의 현장 표본 검증이 필요 |

규칙 기반 `live` 서비스는 학습 모델 없이 정상 동작합니다.
`ROUTE_MODE=ai`, `RANKER_TIER=bootstrap_baseline`은 로컬 비교에 사용할 수
있습니다. 인터넷 공개 운영은 사람 검증과 관리자 승격을 거친
`human_validated`만 사용합니다.

## 2. 배포 전에 사용자에게 필요한 정보

다음 값은 저장소나 로컬 코드에서 결정할 수 없습니다.

1. 최종 HTTPS origin
   - 예: `https://route.example.kr`
   - DNS와 TLS 인증서를 적용할 실제 도메인이어야 합니다.
2. 배포 대상
   - VM, 사내 서버, 클라우드 Run/VM 등 실제 Docker 실행 환경
   - 최소 권장 사양은 2 CPU, 4GB RAM과 영구 볼륨 디스크입니다.
3. 배포 서버/NAT의 고정 egress 공인 IPv4
   - ODsay Server Key 허용 IP에 등록해야 합니다.
   - `localhost`, 사설 IP, Docker 내부 IP, 프론트 도메인은 등록 대상이
     아닙니다.

키 문자열은 현재 로컬 `.env.production`에 준비되어 있으며 Git에서
무시됩니다. 채팅, 문서, 커밋에는 키 값을 기록하지 않습니다.

## 3. 외부 콘솔에서 해야 할 필수 작업

최종 origin을 `${PUBLIC_ORIGIN}`이라고 할 때 다음을 등록합니다.

- Kakao Developers
  - 웹 플랫폼 사이트 도메인: `${PUBLIC_ORIGIN}`
  - OAuth Redirect URI:
    `${PUBLIC_ORIGIN}/api/auth/kakao/callback`
  - Client secret 활성 상태 확인
- VWorld
  - API 사용 도메인: `${PUBLIC_ORIGIN}`
- ODsay
  - Server Key 허용 IP: 배포 서버/NAT의 고정 egress 공인 IPv4
- DNS/TLS
  - DNS가 배포 서버 또는 Load Balancer를 가리키도록 설정
  - Caddy, Nginx 또는 Load Balancer에서 HTTPS 종료
  - 내부 앱 `127.0.0.1:8080`으로 `Host`와
    `X-Forwarded-Proto=https`를 설정해 전달

## 4. 서버 배포 절차

배포 서버의 저장소 루트에서 실행합니다.

```powershell
$env:PYTHONUTF8='1'
python scripts\prepare_deployment_env.py --import-existing
# .env.production의 PUBLIC_ORIGIN을 실제 HTTPS origin으로 설정
python scripts\prepare_deployment_env.py --check
docker compose --env-file .env.production -f docker-compose.prod.yml config --quiet
docker compose --env-file .env.production -f docker-compose.prod.yml up -d --build
docker compose --env-file .env.production -f docker-compose.prod.yml ps
```

4개 서비스가 모두 `healthy`가 된 뒤 우선 OD 캐시를 준비합니다.

```powershell
python scripts\prewarm_route_cache.py `
  --base-url http://localhost:8080 `
  --od-file data\precompute\priority_od_pairs.json `
  --max-cached-seconds 3
```

`postgres-data`, `osmnx-cache`, `odsay-cache`, `elevation-cache`,
`vworld-cache` named volume을 재배포 때 삭제하지 않습니다.

## 5. 배포 완료 검증

실제 외부 HTTPS origin을 대상으로 실행합니다.

```powershell
$env:PYTHONUTF8='1'
python scripts\verify_deployment.py --base https://route.example.kr

cd frontend
npm ci
$env:E2E_BASE_URL='https://route.example.kr'
npm run test:e2e:places
```

완료 조건은 다음과 같습니다.

- `/api/readiness`의 `ready=true`와 `missing=[]`
- Kakao 지도·`북구청`·`부산역` 장소 검색 정상
- Kakao 로그인과 callback 후 session 정상
- 실제 경로 3개와 경사·건물 그늘 상태 표시
- PWA manifest·service worker·보안 헤더 정상
- 브라우저 콘솔 오류 없음
- AI·백엔드·프론트·PostgreSQL 모두 `healthy`

## 6. 현재 재검증 결과

2026-07-24 현재 로컬 프로덕션 런타임에서 확인한 결과입니다.

- `.env.production --check`: 통과
- 선택 TMAP 키: 미설정, OSMnx 실제 보행 geometry로 대체되어 배포
  필수조건 충족
- 공급자: Kakao Local, ODsay, VWorld, OpenWeather, 부산 버스 `live`
- `북구청→부산역`: 경로 3개
- 캐시 응답: 2.21초
- 실제 보행 geometry 준비: 3/3
- GLO-90 지형 상태 준비: 3/3
- 그늘 상태 준비: 3/3
- Docker 서비스: 4/4 `healthy`
- 최종 `main` GitHub Actions: 5/5 job 성공
- 로컬 readiness 미통과 항목:
  `origin_security`, `kakao_login`

마지막 두 항목은 로컬 HTTP에서는 통과시킬 수 없으며, 실제 HTTPS origin과
Kakao 콘솔 등록 후 검증해야 합니다.

## 7. 운영 후속 품질 작업

다음은 서비스 공개 자체와 구분되는 품질 고도화 작업입니다.

1. 부산의 평지·급경사·고층 밀집 지역을 층화해 GLO-90 경사와 실제
   보행 구배를 표본 비교합니다.
2. VWorld 건물 높이 단위·결측률을 감사하고 시간대별 현장 건물 그늘과
   계산 결과를 표본 비교합니다.
3. 현재 그늘에는 나무·지형 그림자가 포함되지 않는다는 설명을 유지합니다.
4. ODsay·VWorld·OpenWeather·Overpass의 할당량, 오류율, 캐시 적중률과
   응답시간을 운영 모니터링합니다.
5. 실제 사용자 또는 전문가 라벨을 확보할 때 규칙 baseline과 후보
   XGBRanker를 OD holdout으로 비교하고, 관리자가 승인한 모델만
   `human_validated`로 수동 승격합니다.

GLO-90 경사는 약 90m 지형 추정이며 보도 실측 구배가 아닙니다.
VWorld 건물 그늘도 공공 도형·높이에 기반한 `estimated_public` 결과이지
현장 안전 보장이 아닙니다. 야간과 미확인 값은 0으로 바꾸지 않습니다.
