# 구현 명세

## 런타임 흐름

1. 프론트가 Kakao Local 검색으로 부산 내 출발지·도착지를 선택한다.
2. 백엔드가 요청 프로필, 이번 이동 조건, 로그인 사용자의 장기 설정을 AI 서버에 전달한다.
3. AI 서버가 ODsay·TMAP·OSMnx를 독립 호출하고 실패 공급자를 메타데이터에 남긴다.
4. ODsay `mapObj`와 `loadLane` geometry, 보행 geometry를 구간별로 결합한다.
5. EPSG:5179 버퍼 공간 피처와 Open-Meteo GLO-90 지형 피처를 계산한다.
6. 검증된 프로필별 XGBRanker가 최대 10개를 순위화한다.
7. 백엔드가 로그인 사용자의 후기 기반 온라인 상태로 재정렬하고 상위 N개를 반환한다.
8. 프론트는 Kakao 지도 위에 실제 구간별 폴리라인을 표시하고 추정 geometry는 점선으로 구분한다.

지도 공급자는 경로 생성자가 아닙니다. Kakao/Naver 지도 링크에서 대중교통 geometry를 역추출하지 않습니다.

## 사실성 규칙

- 키 미설정·API 오류·빈 응답은 가짜 직선이나 0분 경로로 대체하지 않음
- 계단·승강기·저상버스·혼잡이 확인되지 않으면 `null`/미확인 유지
- 혼잡은 교통카드 데이터가 연결되기 전까지 추정하지 않음
- GLO-90 경사는 90m 지형 추정으로 표시하며 실측 보도 구배라고 주장하지 않음
- 사고다발지역은 모델 입력에서 제외
- 숫자 모델 점수는 내부 정렬·진단 전용이며 UI에 표시하지 않음
- 추천 이유는 관측 사실만 사용하고 SHAP 값을 인과 설명으로 사용하지 않음

## 학습·개인화

운영 모델은 `ai/data/rankers.pkl`이며 실제 라벨 없이는 생성되지 않습니다. `POST /labeling/candidates`는 모델 준비 전 후보·피처를 만들고, `POST /recommend`는 모델이 없거나 요청 프로필 모델이 없으면 503을 반환합니다.

후기 저장 전 서버가 route/model/feature snapshot을 서명합니다. 리뷰는 실제 표시된 impression과 일치해야 하며 만족도·이용 가능·재사용 의향으로 개인 온라인 상태를 갱신합니다. 전역 후보 학습은 후기별 동의가 있는 데이터만 익명화하고, 팀이 명시한 50% 미만의 비중으로만 후보 모델에 섞습니다.

## 데이터베이스

PostgreSQL만 지원하며 SQLite 자동 대체는 없습니다. Alembic `20260720_0001`이 사용자, 프로필, impression, 리뷰, 시설 신고 스키마를 생성합니다. 시설 신고는 관리자 검토 상태만 바꾸고 원본 공간 데이터를 자동 수정하지 않습니다.

## UI

- 검색 전: 장소 검색, 실제 현재 위치, 짐 많음·계단 회피, 프로필, 음성
- 검색 후: 특성 중심 경로 카드, 구간별 지도, 날씨 실측, 저상버스 도착, 실제 이용 후기, 시설 신고
- 로그인: 카카오 OAuth authorization-code + state + HttpOnly 서비스 세션
- 게스트: 경로 검색 가능, 프로필·후기 개인화 저장 불가

## 검증 명령

```powershell
$env:PYTHONPATH='ai'
.\.venv\Scripts\python.exe -m pytest ai\tests -q
.\.venv\Scripts\python.exe -m pytest backend\tests -q
.\.venv\Scripts\python.exe -m compileall -q ai backend
cd frontend
npm test -- --run
npm run build
```

외부 키가 없는 CI는 계약·실패경계·모델 학습·UI를 검증합니다. 실제 공급자 응답 검증은 키 입력 후 별도 smoke 단계로 실행해야 합니다.
