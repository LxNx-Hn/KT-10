# AI 구현 인수인계

## 완료

- ODsay `searchPubTransPathT` + `loadLane`, TMAP 보행, 부산 전역 동적 OSMnx 경로 수집
- 공급자별 명시적 오류와 geometry 정확도(`exact/mixed/estimated`)
- EPSG:5179 공간 버퍼 피처와 Open-Meteo Copernicus GLO-90 지형 피처
- 사고정보 제거, 결측값 `None` 유지, 교통카드 전 혼잡 추정 금지
- 9인 실제 라벨 전용 XGBRanker, 초기 라벨링 후보 생성 API/CLI
- 짐·계단·저상 우선·이동지원 조건의 학습 가능한 상호작용 피처
- 서버 서명 후기 snapshot, 로그인 사용자 온라인 개인화, 동의 후기 후보 재학습
- 모델 미준비 시 `/recommend` 503, `/model/status`로 상태 확인

## 운영 전 필수

1. `ai/.env`, `backend/.env`, `frontend/.env`에 발급 키 입력
2. 부산역 중심 OD 목록 확정 후 9인 라벨링 패키지 생성
3. 라벨 품질 검토 후 `python -m scoring.train`
4. 실제 공급자 smoke test와 전문가·실사용자 검증
5. `data/catalog.json`의 미확인 URL·라이선스 채우기

PPO 강화학습은 사용하지 않습니다. 현재 후기량과 안전성 요구에서는 서명된 명시적 피드백을 이용한 온라인 로지스틱 개인화와 통제된 XGBRanker 재학습이 구현되어 있습니다. RL 소스는 연구 실험으로만 남고 운영 의존성에 포함되지 않습니다.
