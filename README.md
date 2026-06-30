# 교통약자 및 이동취약자 맞춤형 경로 추천 PWA

> 서비스명: **미정**  
> 플랫폼: **PWA 웹앱**  
> 지도 API: **Kakao Map API 기준 개발**  
> 발표 범위: **부산 부산진구(서면 일대) 한정 데모**  
> 핵심 방향: **차량 내비 제외, 보행·대중교통·교통약자 접근성 중심**

---

## 프로젝트 개요

보행자·대중교통 이용자·교통약자(고령자·아동·장애인·일반)를 위한 **접근성 중심 경로 추천 서비스**다.  
자동차 내비가 아니라 **계단·승강기·저상버스·날씨·보행 부담**을 자체 점수화해 경로를 재평가한다.

발표 데모는 **부산 부산진구(서면 일대)** 로 한정한다.

---

## 폴더 구조

```text
KT-10/
├─ frontend/   React + Vite + TypeScript PWA (검색 중심 UI · 음성 챗봇 · 지도 보조)
├─ backend/    Python FastAPI (점수화 엔진 · REST API · 라이브 프로바이더)
├─ data/       공유 데이터셋(JSON) — 프론트/백 단일 소스(부산진구 mock)
└─ docs/       문서(기획서 · 구현명세 · 백엔드 · 데이터 스키마)
```

| 폴더 | 설명 | 핵심 |
|---|---|---|
| [frontend](frontend) | PWA 웹앱 | 검색 홈·음성 챗봇·경로 카드 3개·지도 보조 |
| [backend](backend) | API 서버 | 8개 하위점수 × 프로필 가중치 · 키 있으면 live/없으면 mock |
| [data](data) | 데이터셋 | `places` · `routes.demo` · `bus_arrivals` · `weather` |
| [docs](docs) | 문서 | [기획서](docs/PLAN.md) · [구현명세](docs/IMPLEMENTATION.md) · [백엔드](docs/BACKEND.md) · [데이터](docs/DATA.md) |

---

## 빠른 실행

```bash
# 1) 프론트엔드 (기본 mock 데이터로 즉시 동작)
cd frontend
npm install
npm run dev            # http://localhost:5173
npm test               # 점수 검증 · 음성 파서 · UI

# 2) 백엔드 (선택 — 실데이터/서버 점수화)
cd backend
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000   # 문서 /docs
pytest
```

---

## API 키

키가 있으면 실데이터를 사용하고, 없으면 mock 데이터로 자동 폴백한다.

| 위치 | 키 | 효과 |
|---|---|---|
| `frontend/.env` | `VITE_KAKAO_MAP_KEY` | 실제 Kakao 지도 사용. 없으면 SVG 약도 표시 |
| `frontend/.env` | `VITE_DATA_SOURCE=live` + `VITE_API_BASE` | 백엔드 연동. 없으면 내장 mock 사용 |
| `backend/.env` | `KAKAO_REST_API_KEY` | 실제 Kakao 장소검색 |
| `backend/.env` | `OPENWEATHER_API_KEY` | 부산진구 실시간 날씨 |

각 폴더의 `.env.example` 참고. 키는 **서버 전용**으로 관리하고 클라이언트에 노출하지 않는다.

---

## 검증

- 프론트엔드와 백엔드 점수화 엔진은 **동일한 점수 표**를 기준으로 검증한다.
- 프로필별 추천 순위, 날씨 위험 반영, 저상버스 여부, 승강기 여부가 의도대로 점수에 반영되는지 확인한다.
- `data/` 를 단일 소스로 사용해 프론트/백엔드 데이터 불일치를 줄인다.

---

## 서비스명

**미정**
