# 관리자 리뷰 검토

## 권한 부여

관리자 계정은 일반 사용자가 카카오 로그인을 한 번 완료해 `users` 행이 생성된
뒤에만 지정한다. 신규 가입자나 특정 닉네임을 자동 승격하지 않는다.

`backend/.env`의 `DATABASE_URL`이 운영 PostgreSQL을 가리키는 서버에서 실행한다.
카카오 숫자 ID는 카카오 개발자 도구 또는 승인된 운영 절차로 확인하며 채팅이나
Git에 기록하지 않는다.

```powershell
Set-Location backend
python -m ml.manage_admin --kakao-id <KAKAO_NUMERIC_ID> --confirm-kakao-id <KAKAO_NUMERIC_ID> --grant
```

권한 회수는 동일한 명령의 `--grant`를 `--revoke`로 바꾼다. 두 ID가 정확히
일치하지 않거나 사용자가 아직 생성되지 않았으면 명령은 변경 없이 실패한다.

## 열람과 검토

관리자는 앱 설정의 `사용자 리뷰 검토` 링크 또는 `/admin/reviews`로 들어간다.
화면 노출 여부와 별개로 모든 관리자 API는 서버에서 `users.is_admin`을 다시
검사한다.

- `GET /api/admin/route-reviews`: 상태·문제유형·학습동의·정보정확성 필터와 페이지네이션
- `GET /api/admin/route-reviews/{id}`: 원문 후기와 당시 서버 경로 계산 스냅샷
- `PATCH /api/admin/route-reviews/{id}`: 검토 상태, 근거 메모, 검토자, 검토 시각 기록

관리자 응답에는 카카오 ID·닉네임·사용자 ID를 포함하지 않는다. 검토 작업은
원문 평점·의견·학습동의를 변경하지 않으며, 학습 미동의 리뷰를 학습 데이터로
승격하지 않는다.

## 검토 상태

- `pending`: 검토 대기
- `verified`: 제출 내용의 근거를 확인함
- `rejected`: 현재 근거로 확인할 수 없음
- `resolved`: 원천 데이터 또는 서비스 조치를 완료함

`verified`는 사용자 제보를 확인했다는 뜻이며, 제보만으로 경사·계단·경사로
수치를 사용자 화면에 공개해도 된다는 뜻은 아니다. 사용자 노출 데이터는 별도의
출처·공간 일치·현장 검증 게이트를 통과해야 한다.
