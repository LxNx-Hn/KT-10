# 회원 탈퇴 API

- 작업일: 2026-08-12
- 범위: 백엔드 API만 (프론트 UI 미포함)
- 방식: 즉시 삭제가 아닌 **30일 보관 후 파기**

---

## 1. 무엇을 만들었나

`POST /api/auth/withdraw` 엔드포인트와, 보관기간이 지난 계정을 실제로 지우는 배치
스크립트를 만들었다.

탈퇴는 즉시 삭제가 아니다. 신청하면 **로그인만 즉시 막고** 사용자 데이터는
30일간 제자리에 남는다. 기한이 지나면 배치가 파기한다. 유예기간을 둔 이유는
실수로 신청한 사용자가 되돌릴 수 있게 하기 위해서다.

## 2. 설계 결정과 근거

### 왜 대기열 방식인가

30일 유예를 만드는 방법은 두 가지였다.

| 방식 | 내용 | 채택 |
| --- | --- | --- |
| 대기열 테이블 | 탈퇴 신청 사실만 기록하고 데이터는 제자리에 둔다 | **채택** |
| 아카이브 이전 | 별도 테이블로 데이터를 옮기고 원본을 즉시 지운다 | 미채택 |

아카이브 방식은 `users` 행을 지우는 순간 `user_preferences`와 `route_reviews`가
CASCADE로 함께 사라져, 30일 뒤에 지울 것도 복구할 것도 남지 않는다. 제대로
하려면 자식 테이블 아카이브를 각각 만들어야 해서 테이블 3~4개와 복구 로직이
따라붙는다.

무엇보다 이 저장소의 외래키 정책이 이미 **"users 행 하나를 지우면 나머지가
알아서 정리된다"** 는 전제로 설계돼 있다. 대기열 방식이 그 설계를 그대로
활용한다.

### 탈퇴 시 데이터가 어떻게 되나

파기 시점에 기존 외래키 정책이 그대로 적용된다.

| 테이블 | 정책 | 결과 |
| --- | --- | --- |
| `user_preferences` | `CASCADE` | 삭제 (개인화 상태 포함) |
| `route_reviews` | `CASCADE` | 삭제 |
| `route_impressions.user_id` | `SET NULL` | **익명 보존** |
| `facility_reports.user_id` | `SET NULL` | **익명 보존** |
| `route_reviews.reviewed_by` | `SET NULL` | 검수 이력 유지 |

개인 설정과 후기는 지우고, 시설 신고처럼 공익적 기록은 익명으로 남긴다.

### 그 밖의 결정

**관리자는 탈퇴할 수 없다 (409).** `route_reviews.reviewed_by`가 `SET NULL`이라
관리자를 지우면 후기 검수 이력의 담당자가 통째로 비어 감사 추적이 끊긴다.
권한을 회수한 뒤 탈퇴해야 한다.

**카카오 unlink 실패가 탈퇴를 막지 않는다.** 외부 장애 때문에 사용자가
탈퇴하지 못하는 상황을 만들지 않는다. 실패는 `provider_unlinked=false`로
기록하고 파기 배치가 재시도한다.

**재로그인하면 탈퇴가 철회된다.** 유예기간의 목적이 실수 복구이기 때문이다.
연결 끊기 후 회원번호가 바뀌는 경우에는 신규 가입 분기로 흘러 충돌하지 않는다.

**보관기간은 신청 시점 값으로 고정된다.** 나중에 설정을 바꿔도 이미 신청한
사용자에게 약속된 기한은 흔들리지 않는다.

## 3. 동작

### 탈퇴 신청 — `POST /api/auth/withdraw`

1. 세션으로 본인 확인 (미로그인 401)
2. 관리자면 **409**로 거부
3. 이미 신청한 계정이면 기한을 바꾸지 않고 **204** (멱등)
4. 카카오 어드민 키로 연결 끊기 시도 (실패해도 진행)
5. 대기열 등록 + **닉네임 즉시 삭제**
6. 세션 쿠키 제거 후 **204**

닉네임은 파기를 기다릴 이유가 없는 표시용 개인정보라 즉시 지운다.

### 로그인 차단

`current_user`는 **401**, `optional_current_user`는 게스트(`None`)로 처리한다.
다른 기기에 남은 세션 쿠키로도 접근할 수 없다.

### 파기 배치

```bash
python scripts/purge_withdrawn_users.py --dry-run   # 대상만 집계
python scripts/purge_withdrawn_users.py             # 실제 파기
```

기한이 지난 계정의 `users` 행을 삭제하면 위의 외래키 정책이 모두 적용된다.
unlink에 실패했던 계정은 파기 전에 한 번 더 시도하고, **재시도도 실패하면
파기하지 않고 대기열에 남긴다.** 카카오 연결이 남은 채 우리 기록만 사라지는
상태를 조용히 만들지 않기 위해서다. 이 경우 종료 코드 1을 반환해 스케줄러가
실패를 감지할 수 있다.

JSON 요약을 출력한다: `dueCount`, `purged`, `unlinkRetried`,
`skippedUnlinkFailed`, `missingUser`.

## 4. 변경 파일

| 파일 | 내용 |
| --- | --- |
| `backend/app/database.py` | `UserWithdrawal` 모델 추가, `utc_now_naive`·`new_session` 공개화, `User.preference`에 `passive_deletes` |
| `backend/alembic/versions/20260812_0005_user_withdrawal.py` | `user_withdrawals` 테이블 + `purge_after` 인덱스 |
| `backend/app/api/auth.py` | `withdraw` 엔드포인트, `unlink_kakao_account()`, 인증 차단, 재로그인 철회 |
| `backend/app/settings.py` | `kakao_admin_key`, `withdrawal_retention_days` |
| `scripts/purge_withdrawn_users.py` | 파기 배치 (신규) |
| `.env.production.example`, `docker-compose.prod.yml` | 환경변수 선언 |
| `backend/tests/test_auth_withdrawal.py` | 탈퇴 플로우 테스트 7건 (신규) |
| `backend/tests/test_purge_withdrawn_users.py` | 파기 배치 테스트 5건 (신규) |

### `user_withdrawals` 스키마

| 컬럼 | 설명 |
| --- | --- |
| `user_id` | PK, `users.id` 참조, `CASCADE` |
| `requested_at` | 신청 시각 |
| `purge_after` | 파기 예정 시각 (인덱스) |
| `provider_unlinked` | 카카오 연결 끊기 성공 여부 |

행이 존재하면 곧 탈퇴 신청 상태다. 별도 플래그 컬럼을 두지 않았다.

## 5. 카카오 연결 끊기

로그인 시 액세스 토큰을 저장하지 않으므로 사용자 토큰으로는 연결을 끊을 수
없다. **앱 어드민 키가 유일한 경로**다.

```
POST https://kapi.kakao.com/v1/user/unlink
Authorization: KakaoAK ${KAKAO_ADMIN_KEY}
Content-Type: application/x-www-form-urlencoded;charset=utf-8

target_id_type=user_id&target_id={kakao_id}
```

어드민 키는 REST API 키와 **다른 값**이다. 비어 있으면 연결 끊기를 건너뛰고
우리 DB만 정리한다. 실패 로그에 회원번호와 응답 본문은 남기지 않는다.

## 6. 작업 중 발견해 고친 버그

**`db.delete(user)`만으로는 외래키 정책이 적용되지 않았다.**

`User.preference` 관계에 `passive_deletes`가 없어서, SQLAlchemy가 DB의
`ON DELETE CASCADE`에 맡기지 않고 직접 자식의 FK를 `NULL`로 바꾸려 했다.
그런데 `user_preferences.user_id`는 기본키라 `NULL`이 될 수 없어
`AssertionError`가 발생했다.

```
Dependency rule on column 'users.id' tried to blank-out
primary key column 'user_preferences.user_id'
```

`passive_deletes=True`를 추가해 해결했다. **기존 코드를 고친 유일한 지점**이다.

테스트에서 SQLite의 `PRAGMA foreign_keys=ON`을 켜 실제 DB와 같은 동작을
재현한 덕에 잡혔다. 켜지 않았다면 테스트는 통과하고 운영에서 터졌을 것이다.

## 7. 검증

| 검사 | 결과 |
| --- | --- |
| 백엔드 pytest | **303 passed**, 1 skipped (작업 전 291 → +12) |
| AI pytest | 235 passed, 2 skipped (회귀 없음) |
| 프론트 vitest | 400 passed (회귀 없음) |
| `ruff check backend scripts --select E4,E7,E9,F` | 통과 |
| `compileall backend scripts` | 통과 |
| `alembic heads` | `20260812_0005` 단일 head |

### 테스트가 검증하는 계약

**탈퇴 플로우 7건**

- 대기열 등록, 닉네임 마스킹, 사용자 행 보존, 예정일 = 신청 + 30일
- 세션 쿠키 제거
- 재요청이 기한을 늘리거나 줄이지 않음
- 카카오 unlink 실패해도 탈퇴 진행, 실패 기록 남김
- 관리자 탈퇴 409, 대기열에 등록되지 않음
- 탈퇴 계정은 유효한 세션 쿠키로도 접근 불가
- 재로그인 시 탈퇴 철회

**파기 배치 5건**

- 기한 경과 계정 파기 + 외래키 정책 실제 동작 (CASCADE 삭제 / SET NULL 익명화)
- 기한 내 계정은 보존
- `--dry-run`은 집계만 하고 삭제하지 않음
- unlink 재시도 성공 시 파기
- unlink 재시도 실패 시 파기하지 않고 대기열 유지

## 8. 배포 전 필요한 것

1. **`KAKAO_ADMIN_KEY` 발급 후 주입** — 없으면 탈퇴는 되지만 사용자의 카카오
   "연결된 서비스"에 앱이 남는다
2. **파기 배치 스케줄 등록** — `scripts/purge_withdrawn_users.py`를 하루 1회
   실행하도록 외부 cron에 건다. **걸지 않으면 30일이 지나도 아무것도
   파기되지 않는다**
3. `WITHDRAWAL_RETENTION_DAYS` 확인 (기본 30)

## 9. 남은 일과 미검증 사항

**프론트 UI가 없다.** 이번 범위에서 제외했다. `frontend/src/auth/api.ts`에
`withdraw()` 함수와 확인 모달이 필요하다. 되돌릴 수 없는 동작이므로 확인
절차 없이 노출하면 안 된다.

**카카오 unlink 후 회원번호 유지 여부가 미검증이다.** 카카오 문서에 명시가
없어 어느 쪽이든 안전하게 동작하도록 설계했다.

- 유지된다면 → 재로그인이 탈퇴 철회로 이어진다 (의도한 동작)
- 바뀐다면 → 새 계정이 만들어지고 옛 계정은 기한 후 파기된다

실제 계정으로 한 번 확인해두면 좋다.

**개인정보 파기 관련 법적 요건은 검토하지 않았다.** 30일 보관이 서비스 정책상
적절한지는 별도 판단이 필요하다.
