#!/usr/bin/env python3
"""퐁당냥 인게임 지표 수집 — BigQuery(GA4 export) → docs/data/ingame.json.

브라우저는 BigQuery 를 직접 못 치므로 여기서 쿼리를 돌려 JSON 한 장으로 떨궈두고,
정적 페이지가 그걸 읽는다. GitHub Action(ingame.yml)이 하루 1회 실행.

★숫자 파라미터(level/attempts/…)는 GA4 UI 측정기준엔 빈값으로 보이지만
  BigQuery raw 에는 value.int_value 로 정상 존재한다 — 여기서 직접 읽는다.
  (그래서 GA4 맞춤 정의를 안 만들고 BigQuery 로 간다.)

★지표 정의의 단일 출처는 **게임 레포의 docs/ANALYTICS.md** 다.
  여기 쿼리는 그 식을 옮긴 것일 뿐이다. 식을 바꾸려면 그쪽부터 고친다.

인증: GOOGLE_APPLICATION_CREDENTIALS(서비스계정 JSON 경로).
"""
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone

from google.cloud import bigquery

import queries as Q

KST = timezone(timedelta(hours=9))      # 수집 스케줄이 KST라 갱신 표기도 KST

# ★os.environ.get(키, 기본값) 은 **빈 문자열도 값으로 친다.** Actions 가
#   미설정 vars 를 "" 로 넘기면 기본값이 통째로 사라진다(projects//datasets 404 를 봤다).
#   그래서 전부 `or 기본값` 으로 받는다 — 안 넣어도 돌아가야 한다.
PROJECT = os.environ.get("BQ_PROJECT") or "plopcat-6d336"
DATASET = os.environ.get("BQ_DATASET") or ""        # 비우면 자동 탐색
LOCATION = os.environ.get("BQ_LOCATION") or "asia-northeast3"
WINDOW_DAYS = int(os.environ.get("WINDOW_DAYS") or "45")

# ★개발자 본인 기기 — 릴리스 빌드라 버전으로는 못 가른다. user_pseudo_id 로 뺀다.
#   (쉼표로 여러 개. tools/whoami.py 가 후보를 찾아 준다.)
EXCLUDE_USERS = [u.strip() for u in os.environ.get("EXCLUDE_USERS", "").split(",") if u.strip()]

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

OUT = os.path.join(os.path.dirname(__file__), "..", "docs", "data", "ingame.json")

client = bigquery.Client(project=PROJECT, location=LOCATION)


def find_dataset() -> str:
    """analytics_<GA4속성ID> 를 찾는다. 속성 ID 를 사람이 외우고 다닐 이유가 없다."""
    if DATASET:
        return DATASET
    names = [d.dataset_id for d in client.list_datasets(PROJECT) if d.dataset_id.startswith("analytics_")]
    if not names:
        sys.exit("✗ %s 에 analytics_* 데이터셋이 없다 — GA4 BigQuery 내보내기가 켜져 있는지 확인" % PROJECT)
    if len(names) > 1:
        print("· analytics_* 가 여럿이다 %s → 첫 번째를 쓴다. BQ_DATASET 으로 고정할 것." % names)
    return names[0]


DS = find_dataset()
TABLE = "`%s.%s.events_*`" % (PROJECT, DS)


# ─────────────────────────────────────────────────────────────────────
# ★사람이 아닌 줄을 거른다. 셋 다 안 거르면 모수가 통째로 거짓이 된다.
#   · 디버그 빌드 — 오토파일럿이 수백 판을 깨서 클리어율을 혼자 뒤집는다
#   · 지역이 안 잡히는 줄 — Play 사전 출시 보고서 봇(체류 0분·첫 단계 정지)
#   · 개발자 본인 — EXCLUDE_USERS
#   ※BigQuery 에서 NULL != '' 은 TRUE 가 아니므로 IFNULL 로 감싸야 둘 다 걸린다.
def human(cond: str) -> str:
    base = ("(%s) AND _TABLE_SUFFIX NOT LIKE 'intraday%%'"
            " AND IFNULL(geo.country,'') != ''"
            " AND IFNULL(app_info.version,'') NOT LIKE 'dbg%%'") % cond
    if EXCLUDE_USERS:
        ids = ",".join("'%s'" % u for u in EXCLUDE_USERS)
        base += " AND user_pseudo_id NOT IN (%s)" % ids
    return base


def q(sql: str) -> list:
    return [dict(r) for r in client.query(sql).result()]


def main() -> None:
    end = date.today() - timedelta(days=1)          # 마지막으로 landing 됐을 법한 날
    win = (end - timedelta(days=WINDOW_DAYS)).strftime("%Y%m%d")
    end_s = end.strftime("%Y%m%d")
    rng = "_TABLE_SUFFIX BETWEEN '%s' AND '%s'" % (win, end_s)

    out = {
        "updated": datetime.now(KST).strftime("%Y-%m-%d %H:%M") + " KST",
        "window_days": WINDOW_DAYS,
        "project": PROJECT, "dataset": DS,
        "excluded_users": len(EXCLUDE_USERS),
    }

    # ── 모수 ─────────────────────────────────────────────────────────
    out["last_table"] = (q("SELECT MAX(_TABLE_SUFFIX) t FROM %s WHERE %s"
                           % (TABLE, human("TRUE"))) or [{"t": None}])[0]["t"]

    out["kpi"] = _kpi(rng, end)

    # ★쿼리는 tools/queries.py 한 곳에만 있다. 여기서 베껴 들면 selftest 와 갈라진다.
    f_win = human(rng)
    out["levels"] = q(Q.levels(TABLE, f_win))
    out["stuck"] = q(Q.stuck(TABLE, f_win))
    out["album"] = q(Q.album(TABLE, f_win))
    out["shop_funnel"] = q(Q.shop_funnel(TABLE, f_win))
    out["ads"] = q(Q.ads(TABLE, f_win))
    out["boosters"] = q(Q.boosters(TABLE, f_win))
    out["out_of_hearts"] = q(Q.out_of_hearts(TABLE, f_win))
    # ★온보딩만 **기간을 안 건다** — 계정당 평생 1회라 창으로 자르면 코호트가 섞여
    #   퍼널이 역전된다(창 전에 1단계만 한 사람 + 창 안에서 5단계 한 사람).
    out["onboard"] = q(Q.onboard(TABLE, human("TRUE")))

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    k = out["kpi"][0] if out["kpi"] else {}
    print("✓ %s — DAU %s · 신규 %s · 누적 %s · 레벨 %d행"
          % (OUT, k.get("dau"), k.get("new_users"), k.get("users"), len(out["levels"])))


def _kpi(rng: str, end: date) -> list:
    d1 = end.strftime("%Y%m%d")
    d7 = (end - timedelta(days=6)).strftime("%Y%m%d")
    return q(Q.kpi(TABLE, human(rng), d1, d7))


if __name__ == "__main__":
    main()
