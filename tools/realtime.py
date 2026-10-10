#!/usr/bin/env python3
"""실시간 — BigQuery events_intraday_* → docs/data/realtime.json.

보는 것은 하나다: **오늘 깔아본 사람들이 어디까지 갔는가.**
가입자를 한 줄씩 세우고 각자 퍼널의 어디서 멈췄는지 표시한다.

★ingame.py 와 **일부러 분리**한다 — 파일도 워크플로도 뷰도 따로다.
  intraday 는 후처리 전이고 '하루가 덜 찬' 값이라, 완결 지표(리텐션·코호트)에
  섞으면 왜곡된다. 집계된 이탈률은 인게임 뷰가 맡는다.

★여기서는 **봇도 같이 보여 준다**(숨기지 않고 표시만 한다). 업로드 직후 구글 스캔이
  수십 대 도는 게 정상인지 이상인지는 눈으로 봐야 알고, 조용히 지우면 영영 못 본다.

인증: GOOGLE_APPLICATION_CREDENTIALS. 데이터셋 위치=asia-northeast3.
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone

from google.cloud import bigquery

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import funnel as F

KST = timezone(timedelta(hours=9))
PROJECT = os.environ.get("BQ_PROJECT") or "plopcat-6d336"
LOCATION = os.environ.get("BQ_LOCATION") or "asia-northeast3"
EXCLUDE = [u.strip() for u in os.environ.get("EXCLUDE_USERS", "").split(",") if u.strip()]
OUT = os.path.join(os.path.dirname(__file__), "..", "docs", "data", "realtime.json")

client = bigquery.Client(project=PROJECT, location=LOCATION)
DS = (os.environ.get("BQ_DATASET")
      or [d.dataset_id for d in client.list_datasets(PROJECT)
          if d.dataset_id.startswith("analytics_")][0])
T = "`%s.%s.events_intraday_*`" % (PROJECT, DS)


def today_suffix():
    """intraday 테이블에 들어 있는 **가장 최근 날짜**.

    ★intraday 에 어제치가 남아 있을 수 있다(실측: 10/10 16명 + 10/11 1명).
      그걸 섞으면 '오늘 들어온 사람'이 어제 사람까지 세어 거짓이 된다.
      달력의 오늘이 아니라 **테이블이 가진 최신 날짜**를 쓴다 — GA4 속성의
      기준 시간대가 KST 가 아닐 수도 있어서, 달력으로 고르면 빈 날이 나온다.
    """
    r = q("SELECT MAX(_TABLE_SUFFIX) d FROM %s" % T)
    return r[0]["d"] if r and r[0]["d"] else ""


def q(sql):
    return [dict(r) for r in client.query(sql).result()]


def p_int(k):
    return "(SELECT value.int_value FROM UNNEST(event_params) WHERE key='%s')" % k


def p_str(k):
    return "(SELECT value.string_value FROM UNNEST(event_params) WHERE key='%s')" % k


def main():
    now = datetime.now(KST)
    day = today_suffix()
    if not day:
        print("intraday 테이블이 없다 — GA4 스트리밍 내보내기가 켜져 있는지 확인"); return

    # ── 한 줄 = 한 사람. 오늘 처음 연 사람만(first_open) ─────────────
    rows = q("""
WITH e AS (SELECT * FROM {t} WHERE _TABLE_SUFFIX='{d}'),
me AS (
  SELECT user_pseudo_id uid,
    MIN(event_timestamp) t0, MAX(event_timestamp) t1,
    ANY_VALUE(device.mobile_model_name) model,
    ANY_VALUE(geo.country) country, ANY_VALUE(geo.city) city,
    ANY_VALUE(device.language) lang,
    ANY_VALUE(app_info.version) ver,
    COUNTIF(event_name='first_open') > 0 is_new,
    MAX(IF(event_name='level_start', {lv}, NULL)) max_start,
    MAX(IF(event_name='level_clear', {lv}, NULL)) max_clear,
    COUNTIF(event_name='level_clear') clears,
    COUNTIF(event_name='level_stuck') stuck,
    COUNTIF(event_name='ad_reward') ads,
    COUNTIF(event_name='shop_open') shops,
    COUNTIF(event_name='purchase') buys,
    COUNTIF(event_name='app_remove') > 0 removed,
    COUNTIF(event_name='abuse') abuse,
    STRING_AGG(DISTINCT IF(event_name='onboard_step', {step}, NULL)) onb,
    STRING_AGG(DISTINCT IF(event_name='side_step', {step}, NULL)) side
  FROM e GROUP BY uid)
SELECT * FROM me ORDER BY t0 DESC LIMIT 300
""".format(t=T, d=day, lv=p_int("level"), step=p_str("step")))

    users, reach = [], {k: 0 for k in F.STEP_KEYS}
    bots = 0
    for r in rows:
        onb = set((r["onb"] or "").split(","))
        kind = _classify(r)
        rec = {
            "uid": r["uid"][:8],
            "t0": datetime.fromtimestamp(r["t0"] / 1e6, KST).strftime("%H:%M"),
            "mins": round((r["t1"] - r["t0"]) / 6e7, 1),
            "model": r["model"], "country": r["country"], "city": r["city"],
            "lang": r["lang"], "ver": r["ver"], "new": bool(r["is_new"]),
            "lv": r["max_clear"] or 0, "started": r["max_start"] or 0,
            "clears": r["clears"], "stuck": r["stuck"], "ads": r["ads"],
            "shops": r["shops"], "buys": r["buys"], "removed": bool(r["removed"]),
            "abuse": r["abuse"],
            # 척추 도달을 비트로 접는다 — 10칸 배열보다 짧고 화면에서 바로 푼다
            "reached": sum(1 << i for i, k in enumerate(F.STEP_KEYS) if k in onb),
            "side": sorted(x for x in (r["side"] or "").split(",") if x),
            "kind": kind,
        }
        users.append(rec)
        if kind == "bot":
            bots += 1
            continue                      # 봇은 **도달 집계에서만** 뺀다(줄은 남긴다)
        for i, k in enumerate(F.STEP_KEYS):
            if k in onb:
                reach[k] += 1

    out = {
        "updated": now.strftime("%Y-%m-%d %H:%M") + " KST",
        "project": PROJECT, "dataset": DS, "day": day,
        "steps": [{"key": k, "label": l} for k, l in F.ONB_STEPS],
        "reach": [{"key": k, "label": F.STEP_LABELS[k], "users": reach[k]} for k in F.STEP_KEYS],
        "users": users,
        "bots": bots,
        "humans": len(users) - bots,
    }
    out["versions"] = q("""
SELECT app_info.version ver, COUNT(DISTINCT user_pseudo_id) users,
  COUNTIF(event_name='first_open') installs
FROM {t} WHERE _TABLE_SUFFIX='{d}' GROUP BY ver ORDER BY users DESC
""".format(t=T, d=day))
    out["countries"] = q("""
SELECT IFNULL(geo.country,'(없음)') country, COUNT(DISTINCT user_pseudo_id) users
FROM {t} WHERE _TABLE_SUFFIX='{d}' GROUP BY country ORDER BY users DESC LIMIT 20
""".format(t=T, d=day))
    # ★변조 APK 차단이 **작동 중인지** 본다. 차단이 늘면 좋은 신호지만,
    #   정상 유저가 섞여 막히면 매출이 조용히 0 이 된다 — 그래서 사유별로 센다.
    out["purchase_fail"] = q("""
SELECT {r} reason, COUNT(*) n, COUNT(DISTINCT user_pseudo_id) users
FROM {t} WHERE _TABLE_SUFFIX='{d}' AND event_name='purchase_fail'
GROUP BY reason ORDER BY n DESC
""".format(t=T, d=day, r=p_str("reason")))
    out["abuse"] = q("""
SELECT {r} reason, COUNTIF({g}='true') granted, COUNT(*) n
FROM {t} WHERE _TABLE_SUFFIX='{d}' AND event_name='abuse'
GROUP BY reason ORDER BY n DESC
""".format(t=T, d=day, r=p_str("reason"), g=p_str("granted")))

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("✓ realtime %s — %d명(사람 %d · 봇 %d)" % (day, len(users), out["humans"], bots))


def _classify(r):
    """사람인가 — ★지우지 않고 **딱지만** 붙인다. 화면에서 걸러 보거나 같이 본다."""
    if (r["ver"] or "").startswith("dbg"):
        return "dbg"
    if r["uid"] in EXCLUDE:
        return "me"
    if not (r["country"] or "") or not (r["model"] or ""):
        return "bot"
    return "human"


if __name__ == "__main__":
    main()
