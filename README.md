# PLOPCAT BOARD

최종 업데이트: 2026-10-11

퐁당냥(`com.purplusnow.plopcat`) 지표판. 정적 페이지 + GitHub Actions 수집.
**https://purplusnow.github.io/plopcat-dashboard/**

브라우저는 BigQuery 를 못 치므로, Actions 가 쿼리를 돌려 `docs/data/*.json` 으로
떨궈 두고 페이지가 그걸 읽는다. 서버가 없다.

## 뷰 다섯

| 뷰 | 보는 것 | 데이터 | 수집 |
|---|---|---|---|
| **매출** | 마케팅비 · 광고매출 · 인앱매출 · ROAS | `daily.json` | 손 + 자동(아래) |
| **인게임** | 클리어율 · 벽 · 리텐션 · 버전비교 · 페이싱 · 위험신호 | `ingame.json` | 매일 11:20 KST |
| **실시간** | 오늘 들어온 사람이 어디까지 갔나 | `realtime.json` | 30분마다 |
| **광고** | 리워드 광고 결과 · AdMob 매출 | `ingame.json`+`daily.json` | 〃 |
| **가입자** | 가입일별 코호트, 한 줄 = 한 사람의 평생 누적 | `users/*.json` | 매일 |

## 설계에서 양보하지 않은 것

- **퍼널 정의는 한 곳** — `tools/funnel.py`. 실시간·가입자·인게임 세 화면이 같이 쓴다.
  세 화면이 다른 퍼널을 말하면 비교가 불가능해진다.
  그리고 그 정의가 **게임(`analytics.gd` ONB_STEPS)과 같은지** selftest 가 대조한다 —
  게임이 단계를 바꿨는데 여기가 그대로면 화면이 조용히 다른 퍼널을 말한다.
- **거른 줄을 보여 준다** — 모수에서 뺀 사람을 사유별로 화면에 띄운다.
  조용히 지우면 진짜 유저를 봇으로 오인해도 알 길이 없다.
  실시간 뷰는 아예 지우지 않고 **딱지만** 붙인다.
- **답을 아는 입력으로 검산** — `tools/selftest.py` 가 합성 GA4 행을 만들어
  쿼리를 돌린다. 수집 **전에** CI 에서 돌아간다. 유저가 몇 명뿐인 지금
  실데이터로는 "0.5가 맞는 값인지 쿼리가 틀린 건지" 구분이 안 된다.
- **리텐션 분모는 그 코호트** — 전체 유저로 나누면 어제 설치한 코호트가 D7을
  채울 시간이 없어 가짜 우하향이 나온다.
- **버전 비교는 같은 관측창**(설치 후 1시간) — 안 그러면 멀쩡한 버전이 회귀로 보인다.
- **intraday 중복 금지** — `events_*` 와일드카드는 intraday 를 **이미** 잡는다.
  따로 UNION 하면 두 번 세고, 같은 날짜가 양쪽에 있어도 두 번 센다.

## 돌리기

```bash
export GOOGLE_APPLICATION_CREDENTIALS=~/dev/keystore/plopcat-bq.json
export EXCLUDE_USERS="$(gh variable get EXCLUDE_USERS -R Purplusnow/plopcat-dashboard)"

python3 tools/selftest.py     # 쿼리 검산 — 늘 먼저
python3 tools/ingame.py       # 인게임 + 매일
python3 tools/users.py        # 가입자 코호트
python3 tools/realtime.py     # 오늘
python3 tools/whoami.py       # 내 기기 후보 찾기 → EXCLUDE_USERS

node tools/pagetest.js             # 페이지가 실데이터로 끝까지 그려지나
MODE=empty node tools/pagetest.js  # 데이터가 하나도 없어도 안 터지나
```

★`pagetest` 는 브라우저 없이 최소 DOM 을 만들어 `app.js` 를 **진짜 파일로** 돌린다.
Pages 가 200 을 준다고 화면이 그려지는 건 아니다 — 한 줄에서 터지면 흰 화면이 뜨는데
배포는 "성공"으로 남는다. 빈 데이터 모드가 특히 중요하다: 지금은 대부분의 섹션이
비어 있는 게 **평소 상태**고, 수집기가 하루 실패해도 같은 상황이 된다.

## 아직 비어 있는 것 — 형이 넣어야 채워진다

| 무엇 | 왜 비었나 | 넣는 법 |
|---|---|---|
| **마케팅비** | Google Ads 를 아직 안 돌렸다 | 돌리기 시작하면 Ads 스크립트를 붙이거나 `daily.json` 에 손으로 |
| **AdMob 매출** | 퐁당냥 전용 자격증명이 없다 | AdMob API OAuth(**새로 발급** — 다른 프로젝트 것 재사용 금지) |
| **인앱매출** | 아직 실결제가 없다 | GA4 `purchase` 가 쌓이면 자동 |

⚠ **다른 프로젝트의 키·토큰·계정 식별자는 가져오지 않는다.** 이 리포의
`config.json` 에 든 세율·환율폴백·국가티어 표만 인생 2막에서 가져왔는데,
그건 Play 콘솔에 적힌 **공개된 사실**이지 연동정보가 아니다.

## 설정

Actions 변수(`gh variable`): `BQ_PROJECT` `BQ_DATASET` `BQ_LOCATION` `EXCLUDE_USERS`
시크릿: `GCP_SA_KEY` (BigQuery 데이터 뷰어 + 작업 사용자)
