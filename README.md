# PLOPCAT BOARD

퐁당냥(`com.purplusnow.plopcat`) 인게임 지표 보드. 정적 GitHub Pages.

**왜 인생 2막 보드(`secondact-dashboard`)에 안 붙였나** — 수집 뼈대는 이미
`BQ_PROJECT`/`BQ_DATASET` 환경변수로 분리돼 있어 공유할 게 사실상 없고,
**지표 로직은 겹치는 게 없다**(레벨 진행·그림 수집 vs 환생·도시·방치수익).
합치면 라이브로 돌아가는 보드를 멀티앱으로 리팩터링해야 하는데, 얻는 건
"리포 하나 덜 만들기"뿐이다. 앱이 더 쌓여 포트폴리오 뷰가 필요해지면
**각 앱 보드가 요약 JSON 을 뱉고 상위 보드가 모으는** 구조가 맞다.

## 구조

```
tools/ingame.py   BigQuery(GA4 export) → docs/data/ingame.json   (Actions 가 매일 실행)
docs/             정적 페이지. JSON 한 장만 읽는다(브라우저는 BigQuery 를 못 친다)
```

## 보는 것 — 퐁당냥은 "진행·난이도·수집·수익" 네 축

지표 정의의 **단일 출처는 게임 레포의 `docs/ANALYTICS.md`** 다. 여기 쿼리는 그 식을 옮긴 것일 뿐,
식을 바꾸려면 그쪽부터 고친다.

| | 보는 것 | 왜 |
|---|---|---|
| ① 레벨별 클리어율 | `level_clear / level_start` | **분모가 핵심** — `level_clear` 만 보면 깬 사람만 남아(생존 편향) "어려운 판"과 "아무도 도달 못 한 판"이 똑같이 0 으로 보인다 |
| ② 판당 비용 | 시도·아이템·초과 수·소요 시간 | 깨긴 깨는데 **괴로운 판**은 클리어율로는 안 보인다 |
| ③ 못 깬 판 | `level_stuck` | 벽에 막혀 떠난 유저는 `level_clear` 를 영영 안 쏜다 — **여기서만** 보인다 |
| ④ 수집 메타 | `album_open` → `picture_done` | 리텐션 기둥. 완성만 보면 "열어는 봤는데 안 맞춘" 유저가 안 보인다 |
| ⑤ 수익 | 상점 퍼널 · 광고 결과 분포 · `out_of_hearts` | `booster_use.source` 가 조달 경로(광고/젬/발바닥) 비중을 가른다 |

## ★사람이 아닌 줄을 거른다

셋 다 안 거르면 모수가 통째로 거짓이 된다.

1. **디버그 빌드** — `app_info.version LIKE 'dbg%'`. 개발 중 오토파일럿이 수백 판을 깨서
   클리어율·레벨 분포를 혼자 뒤집는다.
2. **Play 사전 출시 보고서 봇** — `IFNULL(geo.country,'') = ''`.
   빌드를 올릴 때마다 실기기에서 몇 분씩 돌리는데 전부 체류 0분·첫 단계 정지라
   리텐션·퍼널을 희석한다(인생 2막 실측: 실시간 385명 중 25명).
3. **개발자 본인 기기** — `EXCLUDE_USERS` 에 `user_pseudo_id` 를 넣는다.
   릴리스 빌드라 버전으로는 못 가른다.

## 돌리기

```bash
export GOOGLE_APPLICATION_CREDENTIALS=/path/sa.json
export BQ_PROJECT=<GCP 프로젝트>        # 기본 plopcat-6d336
export BQ_DATASET=analytics_<GA4속성ID>  # 비우면 자동 탐색
python3 tools/ingame.py
```

Actions 는 시크릿 `GCP_SA_KEY`(BigQuery Data Viewer + Job User)를 쓴다.
