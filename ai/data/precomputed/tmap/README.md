# TMAP 휠체어 경사로 사전가공 캐시

`python -m data_tools.precollect_tmap_ramps`가 ORS wheelchair 선형과 일치한다고
검증한 TMAP `searchOption=30` 성공 응답만 이 디렉터리에 내보냅니다.

- API 키, 요청 헤더, 인증·쿼터·일시 오류는 저장하지 않습니다.
- 사용자 요청에서는 읽기만 하며 TMAP 네트워크 fallback을 실행하지 않습니다.
- 생성된 `route-*.json`과 감사 보고서는 데이터 갱신·배포 단계에서 검토합니다.
- 공급자 계약 또는 정규화 규칙 변경 시 cache/data schema version을 올리고 다시
  수집합니다.
