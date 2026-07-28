# v1.0.0·v1.0.1·최신 main 비교

저장소에는 `v1.0.0`, `v1.0.1` 이름의 Git tag가 없다. 아래 SHA는 실제 commit
object로 검증했으며 비교 기준으로만 사용했다.

| 기준 | SHA | 확인 |
| --- | --- | --- |
| v1.0.0 commit | `f56f414c89e8435797e86b420b926017cb91f979` | commit object |
| v1.0.1 commit | `eb77e3fd321772f3aa360fef00b8d07f31863f93` | commit object |
| 최신 origin/main | `d9f8392f7f39ea8518098ea6c49488ff254e3899` | 기준 |
| lazy refinement 원본 | `ee84e4f27726cc34e0099cb5489cf4015060d884` | 선택 적용 원본 |

| 항목 | 최신 main에서 유지 | 이번 선택 적용 |
| --- | --- | --- |
| Frontend UI·지도·nginx | 전체 유지 | 변경 없음 |
| 2·5·8% 경사 기준 | 유지 | 변경 없음 |
| QGIS/GLO-90·90m slope | 유지 | 회귀 테스트만 |
| 동적 topN 1~10 | 보강 대상 | Backend 권위 적용 |
| ODsay adaptive batch | 보강 대상 | 적용 |
| lazy loadLane·route-set | 보강 대상 | API/서버 적용 |
| shade KST 시간·weather gate | 보강 대상 | 적용 |
| cache·single-flight·counter | 보강 대상 | 적용 |

`origin/main`의 세 후속 커밋 중 배포 워크플로와
`frontend/Dockerfile.prod`, `frontend/nginx.conf` 변경도 그대로 보존했다.
