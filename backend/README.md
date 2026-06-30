# 백엔드 (Python · FastAPI)

교통약자 접근성 경로 추천 서비스의 **데이터 + 점수화 API**. 프론트엔드가 mock 으로 쓰던
장소·경로·버스 도착·날씨 데이터를 REST 로 제공하고, **자체 점수화 엔진**으로 서버측 추천도 제공한다.

점수화 로직은 프론트엔드 TypeScript 엔진(`src/scoring`)을 **1:1 포팅**했으며, 검증 테스트가
동일한 점수 표(프로필×경로, 날씨×위험)를 못박아 프론트/백 결과가 일치함을 보장한다.

## 실행

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate            # Windows (mac/linux: source .venv/bin/activate)
pip install -r requirements.txt

uvicorn app.main:app --reload --port 8000
# 문서(스웨거): http://localhost:8000/docs
```

## 테스트

```bash
pytest                # 26개: 점수 검증(파리티) + API 스모크
```

## 프론트엔드 연결

프론트엔드 루트 `.env` 에:

```
VITE_DATA_SOURCE=live
VITE_API_BASE=http://localhost:8000
```

→ 프론트엔드 `src/adapters/live.ts` 가 아래 엔드포인트를 호출한다. (기본은 mock)

## API

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET  | `/api/health` | 상태 확인 |
| GET  | `/api/places/search?q=` | 장소 검색 |
| GET  | `/api/weather?scenario=` | 날씨(normal/heatwave/coldwave/rain/dust) |
| GET  | `/api/bus/stops` | 정류장 목록 |
| GET  | `/api/bus/arrivals/{stopId}` | 정류장 도착(저상 여부 포함) |
| POST | `/api/routes/candidates` | 경로 후보 생성(점수화 전) |
| POST | `/api/routes/recommend` | 서버측 점수화 + 상위 N 추천 |

`POST /api/routes/recommend` 요청 예:

```json
{
  "origin": { "id": "gu-office", "name": "부산진구청", "lat": 35.1626, "lng": 129.053 },
  "destination": { "id": "seomyeon-stn", "name": "서면역", "lat": 35.1578, "lng": 129.0594 },
  "profile": "disabled",
  "weatherScenario": "rain",
  "options": { "lowFloorPriority": true },
  "topN": 3
}
```

## 구조

```
backend/
├─ app/
│  ├─ main.py            # FastAPI 앱 + 엔드포인트 + CORS
│  ├─ config.py          # 데모 지역(부산진구) + CORS 오리진
│  ├─ models.py          # Pydantic 모델(camelCase JSON alias)
│  ├─ scoring/           # 점수화 엔진(프론트 TS 1:1 포팅)
│  │  ├─ components.py   #  8개 하위 점수
│  │  ├─ weights.py      #  프로필 가중치 + 옵션 보정
│  │  ├─ explain.py      #  이유/주의/음성요약
│  │  └─ engine.py       #  가중합·정렬·상위N
│  └─ data/              # 부산진구 mock(places/routes/bus/weather)
└─ tests/                # pytest (점수 파리티 + API)
```

## 실 데이터 전환

`app/data/*` 의 mock 을 공공데이터(버스도착·저상차량), Kakao 길찾기, 기상청/에어코리아
연동으로 교체하면 된다. 모델·엔드포인트·점수화는 그대로 유지된다.
