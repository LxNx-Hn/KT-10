# 교통약자 및 이동취약자 맞춤형 경로 추천 PWA

> 서비스명: **미정**  
> 플랫폼: **PWA 웹앱**  
> 지도 API: **Kakao Map API 기준 개발**  
> 발표 범위: **부산 부산진구(서면 일대) 한정 데모**  
> 핵심 방향: **차량 내비 제외, 보행·대중교통·교통약자 접근성 중심**

---

## 프로젝트 개요

- 대상: 보행자·대중교통 이용자·교통약자
- 프로필: 일반, 고령자, 아동, 장애인
- 서비스 성격: 접근성 중심 경로 추천 PWA
- 핵심 차별점: 빠른 길보다 실제 이동 가능성 중심
- 재평가 기준: 계단, 승강기, 저상버스, 날씨, 보행 부담, 안전성
- 발표 데모: 부산 부산진구 서면 일대 한정

---

## 서비스 범위

### 포함

- 검색 중심 홈 화면
- 실시간 음성 챗봇
- 경로 카드 3개 추천
- Kakao Map 기반 지도 보조 화면
- 저상버스 도착 조회
- 저상버스 우선 경로 추천
- 날씨 기반 점수 반영
- 프로필별 경로 점수화
- 점수 검증용 테스트 시나리오

### 제외

- 자동차 내비게이션
- 차량용 실시간 교통 최적화
- 주차 추천 및 결제
- EV 충전
- 대리운전
- 렌터카
- 드라이브 경로 추천

---

## 폴더 구조

```text
KT-10/
├─ frontend/   React + Vite + TypeScript PWA (검색 중심 UI · 음성 챗봇 · 지도 보조)
├─ backend/    Python FastAPI (점수화 엔진 · REST API · live/mock provider)
├─ data/       공유 데이터셋(JSON) — 프론트/백엔드 단일 소스
└─ docs/       문서(기획서 · 구현명세 · 백엔드 · 데이터 스키마)
```

| 폴더 | 설명 | 핵심 |
|---|---|---|
| [frontend](frontend) | PWA 웹앱 | 검색 홈·음성 챗봇·경로 카드 3개·지도 보조 |
| [backend](backend) | API 서버 | 8개 하위점수 × 프로필 가중치 · live/mock provider |
| [data](data) | 공유 데이터셋 | `places` · `routes.demo` · `bus_arrivals` · `weather` |
| [docs](docs) | 문서 | [기획서](docs/PLAN.md) · [구현명세](docs/IMPLEMENTATION.md) · [백엔드](docs/BACKEND.md) · [데이터](docs/DATA.md) |

---

## 빠른 실행

```bash
# 프론트엔드
cd frontend
npm install
npm run dev            # http://localhost:5173
npm test               # 점수 검증 · 음성 파서 · UI

# 백엔드
cd backend
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000   # 문서 /docs
pytest
```

---

## API 키

| 위치 | 키 | 효과 |
|---|---|---|
| `frontend/.env` | `VITE_KAKAO_MAP_KEY` | 실제 Kakao 지도 사용. 미설정 시 SVG 약도 표시 |
| `frontend/.env` | `VITE_DATA_SOURCE=live` + `VITE_API_BASE` | 백엔드 연동. 미설정 시 내장 mock 사용 |
| `backend/.env` | `KAKAO_REST_API_KEY` | 실제 Kakao 장소검색 |
| `backend/.env` | `OPENWEATHER_API_KEY` | 부산진구 실시간 날씨 |

- 환경 변수 예시: 각 폴더의 `.env.example`
- 키 관리 기준: 서버 전용 키의 클라이언트 노출 방지

---

## 경로 점수화

| 점수 항목 | 반영 데이터 |
|---|---|
| 접근성 | 계단, 승강기, 휠체어 접근 가능성 |
| 보행 부담 | 도보거리, 실외 보행거리, 환승 도보거리 |
| 저상버스 | 도착 차량 유형, 저상버스 여부, 대기시간 |
| 날씨 위험 | 기온, 강수, 폭염, 한파, 풍속, 미세먼지 |
| 안전성 | 사고위험지역, 횡단보도, 공사구간 |
| 데이터 신뢰도 | 출처, 갱신일, 검증 여부, mock 여부 |

---

## 검증

- 프론트엔드·백엔드 점수화 엔진: 동일 점수 표 기준
- 검증 항목: 프로필별 추천 순위, 날씨 위험 반영, 저상버스 여부, 승강기 여부
- 데이터 기준: `data/` 단일 소스
- 발표 기준: 부산진구 대표 경로 중심 수동 검증

---

## 서비스명

- 미정
