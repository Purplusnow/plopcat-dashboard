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

KST = timezone(timedelta(hours=9))      # 수집 스케줄이 KST라 갱신 표기도 KST

PROJECT = os.environ.get("BQ_PROJECT", "plopcat-6d336")
DATASET = os.environ.get("BQ_DATASET", "")          # 비우면 자동 탐색
LOCATION = os.environ.get("BQ_LOCATION", "asia-northeast3")
WINDOW_DAYS = int(os.environ.get("WINDOW_DAYS", "45"))

# ★개발자 본인 기기 — 릴리스 빌드라 버전으로는 못 가른다. user_pseudo_id 로 뺀다.
#   (쉼표로 여러 개. tools/whoami.py 가 후보를 찾아 준다.)
EXCLUDE_USERS = [u.strip() for u in os.environ.get("EXCLUDE_USERS", "").split(",") if u.strip()]

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


def ev(name: str) -> str:
    return "event_name = '%s'" % name


def p_int(key: str) -> str:
    """이벤트 파라미터에서 정수 하나."""
    return ("(SELECT value.int_value FROM UNNEST(event_params) WHERE key = '%s')" % key)


def p_str(key: str) -> str:
    return ("(SELECT value.string_value FROM UNNEST(event_params) WHERE key = '%s')" % key)


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

    # ── ① 레벨별 클리어율 — 분모가 핵심이다 ───────────────────────────
    #    level_clear 만 보면 **깬 사람만** 남아(생존 편향) "어려운 판"과
    #    "아무도 도달 못 한 판"이 똑같이 0 으로 보인다.
    out["levels"] = q("""
        WITH s AS (
          SELECT %s lv, COUNT(DISTINCT user_pseudo_id) started
          FROM %s WHERE %s GROUP BY lv
        ), c AS (
          SELECT %s lv, COUNT(DISTINCT user_pseudo_id) cleared,
                 AVG(%s) attempts, AVG(%s) over_moves, AVG(%s) secs,
                 AVG(%s + %s + %s + %s) items
          FROM %s WHERE %s GROUP BY lv
        )
        SELECT s.lv, s.started, IFNULL(c.cleared, 0) cleared,
               SAFE_DIVIDE(c.cleared, s.started) rate,
               ROUND(c.attempts, 2) attempts, ROUND(c.over_moves, 2) over_moves,
               ROUND(c.secs, 1) secs, ROUND(c.items, 2) items
        FROM s LEFT JOIN c USING (lv)
        WHERE s.lv IS NOT NULL
        ORDER BY s.lv LIMIT 400
    """ % (p_int("level"), TABLE, human("%s AND %s" % (rng, ev("level_start"))),
           p_int("level"), p_int("attempts"), p_int("over"), p_int("play_secs"),
           p_int("hints"), p_int("undos"), p_int("tows"), p_int("restarts"),
           TABLE, human("%s AND %s" % (rng, ev("level_clear")))))

    # ── ③ 못 깬 판 — 벽에 막혀 떠난 유저는 여기서만 보인다 ─────────────
    out["stuck"] = q("""
        SELECT %s lv, COUNT(*) n, ROUND(AVG(%s), 2) attempts, ROUND(AVG(%s), 2) hints
        FROM %s WHERE %s GROUP BY lv HAVING lv IS NOT NULL
        ORDER BY n DESC LIMIT 25
    """ % (p_int("level"), p_int("attempts"), p_int("hints"),
           TABLE, human("%s AND %s" % (rng, ev("level_stuck")))))

    # ── ④ 수집 메타(리텐션 기둥) ──────────────────────────────────────
    out["album"] = q("""
        SELECT
          COUNT(DISTINCT IF(event_name = 'album_open', user_pseudo_id, NULL)) opened,
          COUNT(DISTINCT IF(event_name = 'picture_done', user_pseudo_id, NULL)) finished,
          COUNTIF(event_name = 'picture_done') pictures
        FROM %s WHERE %s
    """ % (TABLE, human("%s AND event_name IN ('album_open','picture_done')" % rng)))

    # ── ⑤ 수익 ──────────────────────────────────────────────────────
    out["shop_funnel"] = q("""
        SELECT event_name step, COUNT(DISTINCT user_pseudo_id) users, COUNT(*) n
        FROM %s WHERE %s GROUP BY step
    """ % (TABLE, human("%s AND event_name IN "
                        "('shop_open','purchase_start','purchase','purchase_fail')" % rng)))

    # 광고 결과 분포 = **공급 실패율**. no_ad 가 많으면 인벤토리가 없는 것이다.
    out["ads"] = q("""
        SELECT %s placement, %s result, COUNT(*) n
        FROM %s WHERE %s GROUP BY placement, result ORDER BY n DESC LIMIT 30
    """ % (p_str("placement"), p_str("result"),
           TABLE, human("%s AND %s" % (rng, ev("ad_reward")))))

    # 아이템 조달 경로 — 같은 힌트라도 광고면 광고수익, 젬이면 결제수익, 발바닥이면 둘 다 아니다
    out["boosters"] = q("""
        SELECT %s kind, %s source, COUNT(*) n
        FROM %s WHERE %s GROUP BY kind, source ORDER BY n DESC LIMIT 30
    """ % (p_str("kind"), p_str("source"),
           TABLE, human("%s AND %s" % (rng, ev("booster_use")))))

    # 하트 바닥 = 과금·이탈 압력이 걸리는 지점
    out["out_of_hearts"] = q("""
        SELECT %s lv, COUNT(*) n FROM %s WHERE %s
        GROUP BY lv HAVING lv IS NOT NULL ORDER BY n DESC LIMIT 20
    """ % (p_int("level"), TABLE, human("%s AND %s" % (rng, ev("out_of_hearts")))))

    # ── ⑥ 온보딩 척추(계정당 평생 1회) ────────────────────────────────
    #    ★평생 이벤트라 **창으로 자르면 코호트가 섞여** 퍼널이 역전된다
    #      (창 전에 1단계 한 사람 + 창 안에서 5단계 한 사람). 전체 기간으로 센다.
    out["onboard"] = q("""
        SELECT %s step, COUNT(DISTINCT user_pseudo_id) users
        FROM %s WHERE %s GROUP BY step HAVING step IS NOT NULL ORDER BY step
    """ % (p_int("step"), TABLE, human(ev("onboard_step"))))

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    k = out["kpi"][0] if out["kpi"] else {}
    print("✓ %s — DAU %s · 신규 %s · 누적 %s · 레벨 %d행"
          % (OUT, k.get("dau"), k.get("new_users"), k.get("users"), len(out["levels"])))


def _kpi(rng: str, end: date) -> list:
    d1 = end.strftime("%Y%m%d")
    d7 = (end - timedelta(days=6)).strftime("%Y%m%d")
    return q("""
        SELECT
          COUNT(DISTINCT IF(_TABLE_SUFFIX = '%s', user_pseudo_id, NULL)) dau,
          COUNT(DISTINCT IF(_TABLE_SUFFIX >= '%s', user_pseudo_id, NULL)) wau,
          COUNT(DISTINCT user_pseudo_id) users,
          COUNT(DISTINCT IF(event_name = 'first_open', user_pseudo_id, NULL)) new_users
        FROM %s WHERE %s
    """ % (d1, d7, TABLE, human(rng)))


if __name__ == "__main__":
    main()
