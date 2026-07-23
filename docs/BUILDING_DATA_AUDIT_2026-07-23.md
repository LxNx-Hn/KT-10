# 건물 높이 데이터 감사 기록

검증일: 2026-07-23 (Asia/Seoul)

## 결론

부산광역시 CSV를 VWorld 건물 footprint에 행 단위로 결합하지 않습니다.
실파일에는 좌표·도형·건물 고유 식별자가 없어 동일 건물을 안전하게 찾을
근거가 없기 때문입니다. 서비스용 실데이터 공급자는 도형과 높이를 같은
피처로 제공하는 `VWorld LT_C_BLDGINFO WFS`로 구현했습니다.

## 부산광역시 CSV 실파일 검사

- 공식 출처: [부산광역시 도시공간정보시스템 도로(건축물) 정보](https://www.data.go.kr/data/15084593/fileData.do)
- 파일명: `부산광역시_도시공간정보시스템_도로(건축물)정보_20250724.csv`
- 인코딩: CP949
- 크기: 23,735,642 bytes
- SHA-256: `EA2C5A8AF75DA0BC8693F8CB63AE95C99D491030A36C40EFBB18ECA34E1E472B`
- 포털 표시 행 수: 64,999
- 실제 CSV 행 수: 292,069
- 컬럼: 법정동명, 특수지구분명, 건축물용도명, 건축물구조명, 건축물면적,
  연면적, 대지면적, 높이, 건폐율, 용적율
- 좌표·도형·건물 ID: 없음
- 높이 `0`: 136,897행
- 양의 높이: 155,172행
- 300m 초과: 6행
- 최대 높이: 19,860,821m
- 모든 컬럼이 같은 중복 행: 28,130행(중복 집합에 포함된 행 수)

높이 `0`은 실제 0m 건물로 해석하지 않으며, 비현실적 극단값도 자동 보정하지
않습니다. 이 파일은 현재 모델 입력이 아니라 출처·품질 감사 자료입니다.

## 채택한 실데이터 계약

[VWorld GIS건물통합정보 WFS](https://www.vworld.kr/dev/v4dv_2ddataguide2_s002.do?svcIde=bldginfo)의
`LT_C_BLDGINFO` 레이어에서 경로 주변 `geometry`, `ufid`, `height`,
`bldrgst_pk`, `bd_mgt_sn`을 한 요청으로 조회합니다.

- `BUILDING_SOURCE=demo`: 합성 건물, `estimated_demo`
- `BUILDING_SOURCE=vworld` + 유효 키: 공공 건물, `estimated_public`
- `BUILDING_SOURCE=vworld` + 키 없음: HTTP 503
- VWorld 오류: HTTP 502
- 높이 결측·0·비유한 값: 그림자 계산에서 제외하고 커버리지에 반영
- 높이 일부 결측: 확인된 건물로 설명 가능한 최소 그늘(`lower_bound`)로 표시
- 알려진 높이 건물이 없음: 그늘을 0%로 만들지 않고 `unavailable`
- Polygon/MultiPolygon과 내부 링을 보존하고, 오목한 footprint를 볼록
  다각형으로 부풀리지 않는 평면 스윕 그림자 사용
- 실경로는 거리·geometry가 확인된 실외 도보 구간만 계산

실서비스 전에는 유효한 VWorld 키로 부산 실제 응답의 좌표계, 높이 단위,
결측률, 폐합 도형, 현장 그림자 오차를 표본 검증해야 합니다.
