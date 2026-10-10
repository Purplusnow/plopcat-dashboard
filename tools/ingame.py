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
# ★오늘 일이 오늘 보이게 — intraday 도 읽는다.
#
# GA4 일일 테이블(events_YYYYMMDD)은 **하루 이상 늦게** 닫힌다. 그것만 보면
# 대시보드가 늘 이틀 뒤를 가리킨다(실제로 last_table 이 20261008 에 멈춰 있었다).
# events_intraday_YYYYMMDD 는 거의 실시간이라 그걸 덧댄다.
#
# ★함정 둘:
#   ① events_* 와일드카드는 **intraday 도 이미 잡는다.** 그래서 따로 UNION 하면
#      같은 이벤트를 두 번 센다(내가 즉석 쿼리에서 실제로 당했다 — 모든 줄이 2배로 나왔다).
#      여기서는 UNION 하지 않고, 와일드카드가 주는 걸 **걸러서** 쓴다.
#   ② 같은 날짜가 일일·intraday 양쪽에 있으면 역시 두 번 세어진다. 일일 테이블이
#      닫히는 순간 그 날짜의 intraday 가 중복이 된다. 그래서 **마지막 일일 날짜보다
#      뒤인 intraday 만** 쓴다.
def last_daily_day() -> str:
    r = q("SELECT MAX(_TABLE_SUFFIX) t FROM %s WHERE _TABLE_SUFFIX NOT LIKE 'intraday%%'" % TABLE)
    return (r[0]["t"] if r and r[0]["t"] else "00000000")


#: 날짜 비교는 전부 이 식으로 — queries.py 와 **같은 정의**를 가져다 쓴다(두 벌이 되면 갈라진다)
DAY = Q.DAY


def human(cond: str) -> str:
    """★규칙은 queries.Q.human 한 곳에 있다 — 여기서 다시 쓰지 않는다.
    tools/selftest.py 가 **같은 함수**를 합성 데이터로 검산한다."""
    return Q.human(cond, LAST_DAILY, EXCLUDE_USERS)


# ★걸러낸 걸 **보여 준다.** 조용히 지우면 지워진 걸 알 길이 없다 — 진짜 유저를
#   봇으로 오인해 지워도 아무 표시가 안 난다. 사유별로 세어 대시보드에 띄운다.
def filtered_counts(rng: str) -> list:
    reasons = [
        ("구글 자동스캔(지역 없음)", "IFNULL(geo.country,'') = ''"),
        ("모델명 없음(스캔 의심)", "IFNULL(geo.country,'') != '' AND IFNULL(device.mobile_model_name,'') = ''"),
        ("디버그 빌드(개발용)", "IFNULL(app_info.version,'') LIKE 'dbg%'"),
    ]
    if EXCLUDE_USERS:
        ids = ",".join("'%s'" % u for u in EXCLUDE_USERS)
        reasons.append(("개발자 기기(지정 제외)", "user_pseudo_id IN (%s)" % ids))
    out = []
    for label, cond in reasons:
        n = q("SELECT COUNT(DISTINCT user_pseudo_id) n FROM %s WHERE (%s) AND (%s)"
              % (TABLE, rng, cond))
        out.append({"reason": label, "users": n[0]["n"] if n else 0})
    return out


def q(sql: str) -> list:
    return [dict(r) for r in client.query(sql).result()]


#: 일일 테이블이 닫힌 마지막 날짜. 이 뒤의 intraday 만 덧댄다(중복 방지).
#: ★여기서 계산한다 — q() 가 정의된 **뒤**여야 하고, human() 이 쓰기 **전**이어야 한다.
LAST_DAILY = last_daily_day()


def main() -> None:
    # ★끝을 **오늘**로 둔다. 예전엔 '어제'였다 — 일일 테이블이 늦게 닫히니 어쩔 수 없었지만,
    #   이제 intraday 를 읽으므로 오늘 일이 오늘 보인다.
    end = date.today()
    win = (end - timedelta(days=WINDOW_DAYS)).strftime("%Y%m%d")
    end_s = end.strftime("%Y%m%d")
    # ★날짜 비교에 _TABLE_SUFFIX 를 그대로 쓰면 intraday 가 통째로 빠진다
    #   ('intraday_20261010' 은 '20261010' 과 문자열 비교가 안 맞는다). DAY 를 쓴다.
    rng = "%s BETWEEN '%s' AND '%s'" % (DAY, win, end_s)

    out = {
        "updated": datetime.now(KST).strftime("%Y-%m-%d %H:%M") + " KST",
        "window_days": WINDOW_DAYS,
        "project": PROJECT, "dataset": DS,
        "excluded_users": len(EXCLUDE_USERS),
    }

    # ── 모수 ─────────────────────────────────────────────────────────
    out["last_table"] = (q("SELECT MAX(_TABLE_SUFFIX) t FROM %s WHERE %s"
                           % (TABLE, human("TRUE"))) or [{"t": None}])[0]["t"]

    out["last_daily"] = LAST_DAILY            # 일일 테이블이 닫힌 데까지
    out["filtered"] = filtered_counts(rng)   # 사람이 아니라고 보고 뺀 것들
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

    # ── 인생 2막 수준으로 올리며 더한 것들 (2026-10-11) ───────────────
    # ★리텐션·버전비교는 **기간을 걸지 않는다.** 코호트가 창 밖으로 잘리면
    #   D7 을 채울 시간이 없는 코호트만 남아 리텐션이 가짜로 우하향한다.
    f_all = human("TRUE")
    out["retention"] = _ret(q(Q.retention(TABLE, f_all)))
    out["versions"] = q(Q.versions(TABLE, f_all))
    out["pacing"] = q(Q.pacing(TABLE, f_win))
    out["risk"] = q(Q.risk(TABLE, f_all))
    out["side_steps"] = q(Q.side_steps(TABLE, f_all))
    out["countries"] = q(Q.countries(TABLE, f_all))

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    k = out["kpi"][0] if out["kpi"] else {}
    print("✓ %s — DAU %s · 신규 %s · 누적 %s · 레벨 %d행"
          % (OUT, k.get("dau"), k.get("new_users"), k.get("users"), len(out["levels"])))


def _ret(rows: list) -> list:
    """납작한 (코호트, n, u) 를 코호트별 한 줄로 접는다.

    ★비율은 **여기서** 낸다 — 화면에서 나누면 분모를 잘못 잡기 쉽다
      (코호트 크기가 아니라 전날 수로 나누는 실수).
    """
    out = {}
    for r in rows:
        c = out.setdefault(r["cohort"], {"cohort": r["cohort"], "size": r["size"] or 0, "d": []})
        if r["n"] is None:
            continue                      # 그 코호트에 재방문이 0 인 경우(LEFT JOIN)
        out[r["cohort"]]["d"].append({
            "n": r["n"], "u": r["u"],
            "rate": round(r["u"] / c["size"], 3) if c["size"] else None})
    return sorted(out.values(), key=lambda x: x["cohort"], reverse=True)


def _kpi(rng: str, end: date) -> list:
    d1 = end.strftime("%Y%m%d")
    d7 = (end - timedelta(days=6)).strftime("%Y%m%d")
    return q(Q.kpi(TABLE, human(rng), d1, d7))


if __name__ == "__main__":
    main()
