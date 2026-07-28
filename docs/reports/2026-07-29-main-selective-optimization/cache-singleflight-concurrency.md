# Cache·single-flight·route-set 동시성

- route-set: Backend 프로세스 메모리, TTL 1,800초, 최대 256 entries
- ODsay search/loadLane: 영속 cache volume, TTL 기본 1,800초
- route feature: 영속 cache volume
- TMAP: 영속 cache volume
- VWorld·shade: Backend 영속 cache volumes
- Backend/AI: production Compose 기준 각각 단일 Uvicorn process

검증된 계약:

- 존재하지 않는 route-set token 10,000건이 lock map을 증가시키지 않음
- 동일 OD 동시 10건의 search network 1회
- 동일 mapObj 동시 10건의 loadLane network 1회
- 동일 후보 Backend 동시 10건의 AI refinement 1회
- 다른 후보 refinement는 병렬 진행
- refinement 중 rescore가 geometry와 weather 결과를 서로 덮지 않음
- 만료 중 도착한 refinement 결과는 409로 폐기
- stale revision 전체 replace는 409
- semaphore 대기 중 취소는 network attempt로 집계하지 않음

한계:

- 프로세스 재시작·rolling deploy에서 route-set 소실
- 다중 worker·수평 확장에서는 token affinity가 필요
- Redis는 이번 범위에서 도입하지 않음
- production `.env.production`에 32자 이상 `AI_INTERNAL_SERVICE_TOKEN` 주입 필요
