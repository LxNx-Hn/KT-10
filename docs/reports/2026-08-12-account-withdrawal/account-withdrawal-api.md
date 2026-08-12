# 회원 탈퇴 API

- 최초 작업일: 2026-08-12
- 정책 개정: 2026-08-12 (법적 검토 반영)
- 범위: 백엔드 API만 (프론트 UI 미포함)
- 방식: **탈퇴 즉시 삭제 + 최소 정보 30일 분리 보관**

---

## 1. 정책

| 대상 | 처리 |
| --- | --- |
| 계정·프로필·이동 기록·서비스 데이터 | **탈퇴 시점에 즉시 삭제** |
| 시설 신고 | 작성자·자유입력·신고 위치를 지우고 시설 정보만 보존 |
| 부정 이용 방지·처리 오류 대응용 최소 정보 | 30일 분리 보관 후 파기 |
| 결제·환불·분쟁 기록 | **해당 없음** (이 서비스에 결제 기능이 없다) |
| 이용기록(추천 표시 기록) | 탈퇴와 무관하게 **1년 후 파기** |

### 30일 분리 보관 항목 (고지 대상 전체)

| 항목 | 목적 | 기간 |
| --- | --- | --- |
| 내부 회원 식별자 (`user_ref`) | 처리 상태 추적·문의 대응 | 최대 30일 |
| 탈퇴 일시 (`requested_at`) | 처리 이력 | 최대 30일 |
| 처리 상태 (`status`) | 처리 완료 여부 확인 | 최대 30일 |
| 부정 이용 방지 식별값 (`subject_hash`) | 부정 가입·탈퇴 반복 방지 | 최대 30일 |
| **카카오 회원번호 (`pending_provider_id`)** | **카카오 연결 끊기 재시도** | **최대 30일, 재시도 성공 시 즉시 삭제** |

마지막 항목은 **연결 끊기에 실패한 경우에만** 보관한다. 정상 처리되면 애초에
저장하지 않고, 재시도가 성공하는 즉시 지운다. 해시가 아닌 원본이므로 보관
사실을 고지에 반드시 포함해야 한다.

### 초기 설계에서 바뀐 점

초안은 "사용자 데이터를 전부 30일 남겼다가 통째로 삭제"하는 지연 삭제였다.
법적 검토를 거쳐 **즉시 삭제 + 최소 보관**으로 뒤집었다. 함께 바뀐 것들이다.

- `user_withdrawals`에서 `users` 외래키를 제거했다. 사용자 행이 먼저 사라지므로
  외래키가 있으면 기록이 CASCADE로 함께 삭제되어 "분리 보관"이 성립하지 않는다.
- 파기 배치의 대상이 `users` 행에서 **탈퇴 기록**으로 바뀌었다.
- **재로그인 자동 철회를 제거했다.** 데이터를 즉시 지우므로 되돌릴 것이 없다.
- 로그인 차단 로직이 필요 없어졌다. 사용자 행 자체가 없으니 인증에서 자연히
  걸러진다.

## 2. 탈퇴 시 데이터 처리

| 테이블 | 처리 | 근거 |
| --- | --- | --- |
| `users` | 즉시 삭제 | 계정 |
| `user_preferences` | `CASCADE` 삭제 | 프로필·접근성 설정·개인화 상태 |
| `route_reviews` | `CASCADE` 삭제 | 개인 작성물. 학습 동의도 함께 철회된 것으로 본다 |
| `route_impressions` | `CASCADE` 삭제 | 아래 참조 |
| `facility_reports` | 부분 보존 | 아래 참조 |
| `route_reviews.reviewed_by` | `SET NULL` | 관리자 검수 이력 유지 |

### 추천 표시 기록을 삭제하는 이유

`user_id`만 끊어도 `profile`(장애 유형 등)과 `feature_snapshot`(경로 피처)이
남아 **어디서 어디로 이동했는지 추론할 수 있다.** 외래키만 제거한 상태를
익명화로 볼 수 없다.

게다가 이 기록은 짝이 되는 후기와 조인해야 학습에 쓸 수 있는데
([export_consented_reviews.py](../../../backend/ml/export_consented_reviews.py)),
후기는 탈퇴 시 삭제되므로 남겨도 활용할 수 없다. 삭제가 맞다.

### 시설 신고에서 남기는 것과 지우는 것

승강기 고장 같은 정보는 다른 이용자에게 실질적 도움이 되므로 시설 식별과
유지보수를 위해 보존한다. 다만 **시설 자체를 식별·관리하는 데 필요한 정보만**
남긴다.

| 필드 | 처리 | 이유 |
| --- | --- | --- |
| `user_id` | **삭제** (`SET NULL`) | 작성자 연결 |
| `description` | **삭제** | 자유입력이라 무엇이 적혔는지 통제할 수 없다 |
| `reported_lat` / `reported_lng` | **삭제** | 시설 좌표가 아니라 **신고 시점 사용자의 GPS 위치**다 |
| `facility_name` | 보존 | 시설 식별에 필요한 유일한 단서 |
| `facility_type`, `issue_type` | 보존 | 드롭다운 선택값 |
| `status`, `resolution_note` | 보존 | 관리자 처리 이력 |

`description`과 좌표는 외래키로 처리할 수 없어 탈퇴 처리에서 명시적으로 비운다.

좌표를 지우는 이유는
[FacilityReport.tsx](../../../frontend/src/components/FacilityReport.tsx)가
`navigator.geolocation.getCurrentPosition()` 결과를 그대로 보내기 때문이다.
컬럼 이름과 달리 시설 위치가 아니라 **사용자가 신고 버튼을 누른 자리**다.

`facility_name`도 사용자가 직접 타이핑하는 자유입력이지만, 지우면 어느 시설에
대한 신고인지 알 수 없어져 기록 자체가 무의미해진다. 보존 가치와 맞바꾼
의도적 선택이다.

### 이용기록 보유기간 — 계정이 살아 있어도 1년

`route_impressions`는 추천을 화면에 보여줄 때마다 쌓이는 이용기록이다. 탈퇴
시에만 지우면 활동 중인 계정에는 무기한 남는다. 보유기간을 정하고 그 기간이
지나면 계정과 무관하게 파기한다.

```bash
python scripts/purge_expired_usage_logs.py --dry-run
python scripts/purge_expired_usage_logs.py
```

`USAGE_LOG_RETENTION_DAYS`(기본 365)가 기준이다. 0이면 자동 파기를 하지 않고
건너뛴다. 보유기간을 정의하지 않은 상태에서 임의 기준으로 지우지 않기
위해서다.

**후기가 달린 이용기록은 예외로 남긴다.** 후기의 피처 스냅샷으로 쓰이는 후기
기록의 일부이고, 학습 동의라는 별도 근거와 보관 정책을 따른다. 이 기록은
탈퇴 시 후기와 함께 삭제된다. 고지할 때 이 예외를 함께 적어야 한다.

## 3. 분리 보관 기록

```
user_withdrawals
  id                   자체 PK (users 참조 없음)
  user_ref             삭제된 users.id — 처리 추적·문의 대응용 내부 식별자
  subject_hash         sha256(salt + 회원번호) — 반복 탈퇴 판별
  requested_at         탈퇴 일시
  purge_after          파기 예정 시각
  status               completed | provider_unlink_pending
  pending_provider_id  연결 끊기 실패 시에만 보관하는 회원번호
```

### 부정 이용 방지 식별값을 해시로 두는 이유

필요한 성질은 **"같은 사람이면 같은 값이 나올 것"** 하나뿐이다. 누구인지 알
필요는 없다. 회원번호 원본을 들고 있으면 탈퇴한 사람을 30일간 계속 특정할 수
있고, 유출 시 그 값으로 카카오 계정을 조작할 수도 있다. 목적에 필요한 것보다
많은 능력을 갖게 되므로 해시만 남긴다.

**salt가 필수인 이유**: 카카오 회원번호는 숫자라 값의 범위가 좁다. salt 없이
해시하면 무차별 대입으로 역산된다. 그래서 `WITHDRAWAL_HASH_SALT`가 16자 미만이면
**약한 해시를 만들지 않고 `subject_hash`를 `NULL`로 둔다.** 안전하지 않은 값을
안전한 척 남기지 않고, 그 경우 반복 탈퇴 판별 기능만 비활성화된다.

세션·학습 salt와 다른 값을 써야 교차 대조를 막을 수 있다.

### salt는 서비스 전체가 공유하는 고정값이다

혼동하기 쉬운 지점이라 명시한다. **저장되는 것은 salt가 아니라 해시 결과다.**

```
sha256(salt + 회원번호)  →  이 결과만 DB에 남는다
       │       └ 사람마다 다름
       └ 서비스 전체가 공유하는 하나의 고정값
```

salt는 모두에게 같지만 섞이는 회원번호가 다르므로 **사람마다 다른 해시가
나온다.** 서로 다른 두 사용자의 값이 겹치지 않는다.

반대로 **같은 사람이 다시 탈퇴하면 같은 해시가 나온다.** 이것이 반복 탈퇴를
판별하는 원리이므로 의도된 동작이다.

**salt는 한 번 정하면 바꾸지 않는다.** 바꾸면 같은 사람인데도 다른 해시가 나와
이전 기록과 대조할 수 없고, 반복 탈퇴 판별이 그 시점부터 끊긴다. 주기적으로
교체하는 비밀번호와 성격이 다르다.

또한 이것은 암호화가 아니라 **해시**다. 회원번호에서 해시는 만들 수 있지만
해시에서 회원번호는 복구할 수 없다. 유출되어도 "같은 사람인지" 비교만
가능하다.

### salt는 자동 생성한다

`prepare_deployment_env.py`의 `GENERATED`에 등록되어 있어 배포 준비 스크립트가
43자 무작위 값을 만든다. 사람이 지으면 추측 가능한 값이 되기 쉽고, salt가
추측되면 회원번호가 역산되기 때문이다.

**이미 값이 있으면 덮어쓰지 않는다**(`if not values.get(key)`). 직접 만든 값을
넣어 두면 그대로 보존되므로, 자동 생성은 비어 있을 때의 안전망으로만 동작한다.

등록해 두면 검사 두 개가 함께 따라온다.

- **비어 있으면 배포 검사 실패** — salt 없이 배포하면 `subject_hash`가 `NULL`이
  되어 반복 탈퇴 판별이 조용히 꺼진다. 오류도 경고도 없어 알아채기 어려우므로
  배포 단계에서 막는다.
- **다른 생성 비밀값과 같으면 배포 검사 실패** — 세션·학습 salt 재사용을 막는다.

### 30일 내 재가입

**막지 않는다.** 반복 탈퇴 패턴은 `subject_hash`로 기록에 남아 사후 분석이
가능하다. 실수로 탈퇴한 정상 사용자가 다시 가입하려다 막히는 쪽이 손해가 크다고
판단했다.

재가입하면 **완전히 새 계정**이 된다. 이전 설정·후기는 이미 삭제됐으므로
물려받지 않는다.

## 4. 동작

### `POST /api/auth/withdraw`

1. 세션으로 본인 확인 (미로그인 401)
2. 관리자면 **409**로 거부
3. 카카오 어드민 키로 연결 끊기 시도
4. 탈퇴 기록 생성 (해시·상태·필요 시 회원번호)
5. **사용자 행 삭제** → 외래키 정책이 나머지 정리
6. 세션 쿠키 제거 후 **204**

되돌릴 수 없다. 철회 API는 제공하지 않는다.

### 로그인 차단

별도 로직이 없다. 사용자 행이 사라졌으므로 `current_user`는 401,
`optional_current_user`는 게스트로 처리한다. 다른 기기에 남은 세션 쿠키도
동일하게 막힌다.

### 파기 배치

```bash
python scripts/purge_withdrawn_users.py --dry-run
python scripts/purge_withdrawn_users.py
```

두 가지를 한다.

1. `provider_unlink_pending` 기록의 연결 끊기를 **재시도**한다. 성공하면
   예외적으로 보관하던 회원번호를 즉시 지우고 `completed`로 바꾼다.
2. `purge_after`가 지난 기록을 삭제한다.

**보관기간은 상한이므로 연장하지 않는다.** 연결 끊기가 끝내 실패해도 기한이
지나면 기록을 파기한다. 이 경우 카카오 연결이 남을 수 있어 경고 로그를 남기고
`purgedWithUnlinkPending`으로 집계하며 종료 코드 1을 반환한다.

출력 필드: `unlinkRecovered`, `unlinkStillFailing`, `dueCount`, `purged`,
`purgedWithUnlinkPending`.

## 5. 카카오 연결 끊기

로그인 시 액세스 토큰을 저장하지 않으므로 사용자 토큰으로는 연결을 끊을 수
없다. **앱 어드민 키가 유일한 경로**다.

```
POST https://kapi.kakao.com/v1/user/unlink
Authorization: KakaoAK ${KAKAO_ADMIN_KEY}
Content-Type: application/x-www-form-urlencoded;charset=utf-8

target_id_type=user_id&target_id={kakao_id}
```

어드민 키는 REST API 키와 **다른 값**이며, 앱의 모든 사용자에 대해 조회·연결
끊기가 가능한 마스터 키다. 프론트엔드에 절대 넣지 않는다.

**실패해도 탈퇴는 진행한다.** 외부 장애 때문에 사용자가 탈퇴하지 못하는 상황을
만들지 않는다. 대신 회원번호를 `pending_provider_id`에 예외적으로 보관해 배치가
재시도한다. 실패 로그에 회원번호와 응답 본문은 남기지 않는다.

## 6. 환경변수

| 변수 | 기본 | 설명 |
| --- | --- | --- |
| `KAKAO_ADMIN_KEY` | 빈 값 | 카카오 앱 어드민 키. 없으면 연결 끊기를 건너뛴다 |
| `WITHDRAWAL_RETENTION_DAYS` | 30 | 탈퇴 기록 분리 보관기간 |
| `WITHDRAWAL_HASH_SALT` | **자동 생성** | 반복 탈퇴 판별 해시 salt(16자 이상). 없으면 식별값 미보관 |
| `USAGE_LOG_RETENTION_DAYS` | 365 | 이용기록 보유기간. 0이면 자동 파기 안 함 |

`KAKAO_ADMIN_KEY`와 보유기간 두 개는 기본값이 있어 없어도 기동되고, 배포
검사에도 넣지 않았으므로 카카오 키를 받기 전에도 배포가 막히지 않는다.

`WITHDRAWAL_HASH_SALT`만 배포 검사의 필수 항목이다. 자세한 이유는 3장의
"salt는 자동 생성한다"를 참고한다.

`GENERATED`에 항목을 추가할 때는 **CI의 `docker-build` job에도 같은 이름의
환경변수를 넣어야 한다.** 그 job은 생성 로직을 거치지 않고 환경변수로 값을
주입한 뒤 배포 검사를 돌리므로, 빠뜨리면 CI가 실패한다.

## 7. 변경 파일

| 파일 | 내용 |
| --- | --- |
| `backend/app/database.py` | `UserWithdrawal` 재설계, `User.preference`에 `passive_deletes` |
| `backend/alembic/versions/20260812_0005_*.py` | 초기 대기열 테이블 |
| `backend/alembic/versions/20260812_0006_*.py` | 분리 보관 테이블로 교체 |
| `backend/alembic/versions/20260812_0007_*.py` | route_impressions를 CASCADE 삭제로 |
| `backend/app/api/auth.py` | `withdraw`, `unlink_kakao_account()`, `withdrawal_subject_hash()` |
| `backend/app/settings.py` | `kakao_admin_key`, `withdrawal_retention_days`, `withdrawal_hash_salt`, `usage_log_retention_days` |
| `scripts/purge_withdrawn_users.py` | 기록 파기 + 연결 끊기 재시도 배치 |
| `scripts/purge_expired_usage_logs.py` | 이용기록 보유기간 파기 배치 |
| `scripts/prepare_deployment_env.py` | `WITHDRAWAL_HASH_SALT`를 자동 생성 대상으로 등록 |
| `.github/workflows/ci.yml` | docker-build job에 새 생성 비밀값 주입 |
| `backend/Dockerfile` | `scripts/`를 이미지에 포함 |
| `.dockerignore` | `.DS_Store` 제외 |
| `.env.production.example`, `docker-compose.prod.yml` | 환경변수 선언 |
| `backend/tests/test_auth_withdrawal.py` | 탈퇴 계약 10건 |
| `backend/tests/test_purge_withdrawn_users.py` | 배치 계약 6건 |
| `backend/tests/test_purge_expired_usage_logs.py` | 이용기록 파기 계약 5건 |
| `backend/tests/test_prepare_deployment_env.py` | salt 누락·재사용 거부 2건 |

## 8. 작업 중 발견해 고친 문제

### `db.delete(user)`만으로는 외래키 정책이 적용되지 않았다

`User.preference` 관계에 `passive_deletes`가 없어서 SQLAlchemy가 DB의
`ON DELETE CASCADE`에 맡기지 않고 자식 FK를 직접 `NULL`로 바꾸려 했다.
`user_preferences.user_id`는 기본키라 실패한다.

```
Dependency rule on column 'users.id' tried to blank-out
primary key column 'user_preferences.user_id'
```

`passive_deletes=True`로 해결했다. 테스트에서 SQLite `PRAGMA foreign_keys=ON`을
켜 실제 DB 동작을 재현한 덕에 잡혔다.

### 배치 스크립트가 컨테이너에 없었다

`backend/Dockerfile`이 `backend/`와 `data/`만 복사해 `scripts/`가 이미지에
없었다. PostgreSQL은 compose 네트워크에만 있어 호스트에서 직접 붙을 수도 없다.
그대로 두면 탈퇴는 되지만 **파기가 영영 실행되지 않는다.** `COPY` 한 줄로
해결하고, 그때 딸려 들어온 `.DS_Store`도 `.dockerignore`에 추가했다.

## 9. 검증

| 검사 | 결과 |
| --- | --- |
| 백엔드 pytest | **314 passed**, 1 skipped |
| ruff / bandit / compileall | 통과 |
| `alembic upgrade` / `check` / `downgrade` (PostgreSQL 16) | 통과 |
| PostgreSQL 실동작 | 통과 |

### 실제 PostgreSQL에서 확인한 것

사용자와 딸린 데이터를 넣고 탈퇴 흐름을 그대로 실행했다.

- `users`, `user_preferences`, `route_reviews`, `route_impressions` → 0건
- `facility_reports` → 작성자·자유입력·GPS 제거, 시설명·유형·오류유형·관리자 메모 유지
- **`user_withdrawals` 기록은 생존** (외래키가 없으므로)

마이그레이션은 `alembic check`에서 "No new upgrade operations detected"로
모델과 스키마가 일치함을 확인했고, downgrade/upgrade 왕복도 정상이다.

### 테스트가 검증하는 계약

**탈퇴 10건** — 즉시 삭제, impression 삭제, 시설 신고 부분 보존, 최소 필드만 보관, 반복 탈퇴 해시 일치,
salt 없을 때 해시 미보관, unlink 실패 시 재시도 근거 보관, 세션 쿠키 제거,
관리자 409, 재로그인이 철회가 아닌 신규 가입임

**배치 6건** — 기한 경과 파기, 기한 내 보존, dry-run 무삭제, 재시도 성공 시
회원번호 제거, 재시도 실패 보고, 보관기간 상한이 미완료 연결 끊기보다 우선

**이용기록 파기 5건** — 1년 경과 파기, 기간 내 보존, 후기 달린 기록 예외 보존,
dry-run 무삭제, 보유기간 미설정 시 삭제하지 않고 건너뜀

## 10. 배포 전 필요한 것

1. **`KAKAO_ADMIN_KEY` 주입** (적용 완료)
2. **`WITHDRAWAL_HASH_SALT` 확인** — `prepare_deployment_env.py`가 자동
   생성하므로 손으로 만들 필요는 없다. 값이 비어 있으면 배포 검사가 막는다
3. **이미지 재빌드** — `Dockerfile`이 바뀌었으므로 `--build` 필요
4. **파기 배치 2개 스케줄 등록** — 하루 1회씩.
   **걸지 않으면 보관기간이 지나도 데이터가 남는다**
   - `purge_withdrawn_users.py` — 탈퇴 기록
   - `purge_expired_usage_logs.py` — 이용기록

```bash
# 탈퇴 기록 파기 + 밀린 연결 끊기 재시도
0 4 * * * cd /path/to/KT-10 && docker compose --env-file .env.production \
  -f docker-compose.prod.yml exec -T backend \
  python scripts/purge_withdrawn_users.py >> /var/log/kt10-purge.log 2>&1

# 보유기간이 지난 이용기록 파기
20 4 * * * cd /path/to/KT-10 && docker compose --env-file .env.production \
  -f docker-compose.prod.yml exec -T backend \
  python scripts/purge_expired_usage_logs.py >> /var/log/kt10-purge.log 2>&1
```

**배치가 두 개다.** 하나만 걸면 나머지 보유기간이 지켜지지 않는다.

## 11. 남은 일

### 탈퇴자가 아닌 사용자의 GPS는 그대로 저장된다

탈퇴 시에는 좌표를 지우지만, **활동 중인 사용자의 신고에는 여전히 신고 시점
GPS가 그대로 남는다.** 컬럼 이름이 `reported_lat`이라 시설 좌표처럼 보이지만
실제로는 사용자 위치다.

근본적으로 고치려면 신고 시 GPS로 주변 시설을 찾아 **매칭된 시설의 좌표만**
저장하고 사용자 위치는 버리는 방식이 맞다. 이 저장소에는 이미 AI 서비스가
9종 공간 레이어를 STRtree로 들고 있어 재료는 있지만, 백엔드 신고 API가 그
레이어에 접근하지 않는다. 매칭 반경·다중 후보·매칭 실패 정책을 정해야 하는
별도 기능 개선이라 이번 범위에서 다루지 않았다.

### 학습 내보내기 파일

[export_consented_reviews.py](../../../backend/ml/export_consented_reviews.py)가
동의 후기를 CSV·JSONL로 내보낸다. **탈퇴 처리는 DB만 건드리므로 이미 내보낸
파일에는 데이터가 남는다.** 현재 `ai/data/training/route_labels.csv`는 헤더만
있고 0행이라 정리할 대상이 없지만, 실제 내보내기를 시작하면 탈퇴자 데이터를
파일에서도 제거하는 절차가 필요하다.

### 그 밖에

**프론트 UI가 없다.** `frontend/src/auth/api.ts`에 `withdraw()`와 확인 모달이
필요하다. 되돌릴 수 없는 동작이므로 확인 절차 없이 노출하면 안 된다.

**개인정보처리방침과 탈퇴 화면 고지가 필요하다.** 보관 항목·목적·기간을
명확히 적어야 한다. 이 문서의 1~3장 내용이 그 근거가 된다.

**구 마이그레이션(`20260812_0005`) 시점의 탈퇴 신청도 자동 이관한다.**
`0006`은 기존 대기 건을 새 분리 보관 기록으로 옮기고, 해당 계정·프로필·후기·
이동 기록을 새 정책대로 즉시 삭제하며 시설 신고의 자유입력과 신고 위치를
비운다. 연결 끊기가 끝나지 않은 건의 카카오 회원번호만 재시도 목적으로 남긴다.
마이그레이션에는 운영 해시 salt를 주입하지 않으므로 기존 건의 `subject_hash`는
`null`로 보존한다.
