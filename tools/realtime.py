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
## 내 테스트 기기 모델. ★uid 는 **재설치할 때마다 새로 생겨서** EXCLUDE_USERS 가
## 늘 하루 늦는다(실제로 매번 새 uid 가 '사람'으로 잡혔다). 모델로도 가른다.
## ⚠출시 후엔 같은 모델의 **진짜 유저**가 들어오므로 그때는 이 목록을 비운다.
TEST_MODELS = [m.strip() for m in
               (os.environ.get("TEST_MODELS") or "SM-G998B,SM-G991N").split(",") if m.strip()]
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


#: 이 실행이 BigQuery 에서 **긁은 바이트**. 비용은 긁은 양으로 매겨진다(월 1TB 무료).
#: ★안 재면 "비싼가?"에 영원히 추측으로 답하게 된다 — 실제로 형이 물었다(2026-10-13).
_SCANNED = [0]


def _bill(job) -> None:
    _SCANNED[0] += int(job.total_bytes_processed or 0)


def scan_report() -> str:
    gb = _SCANNED[0] / 1024 ** 3
    # $6.25/TB (us/asia 표준). 월 1TB 는 무료라 대부분 0 원이지만, 추세는 보여 준다.
    return "BigQuery 긁은 양 %.1f MB (%.4f GB) · 이 요금제 기준 약 $%.5f · 월 1TB 무료" % (
        _SCANNED[0] / 1024 ** 2, gb, gb / 1024 * 6.25)


def q(sql):
    job = client.query(sql)
    rows = [dict(r) for r in job.result()]
    _bill(job)
    return rows


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
cc AS (
  -- ★사람당 나라를 **하나로** 정한다(이벤트 최다, 동률은 이름순).
  --   ANY_VALUE 로 집으면 **돌릴 때마다 값이 바뀐다** — 아래 국가 집계는 이미 이렇게
  --   고쳤는데 이 목록만 ANY_VALUE 로 남아 있어서, 같은 사람이 목록엔 Brazil,
  --   국가표엔 Iran 으로 나올 수 있었다(형이 전에 잡은 그 버그와 같은 종류다).
  SELECT uid, ARRAY_AGG(c ORDER BY n DESC, c LIMIT 1)[SAFE_OFFSET(0)] c, COUNT(*) > 1 vpn
  FROM (SELECT user_pseudo_id uid, IFNULL(geo.country,'') c, COUNT(*) n
        FROM e GROUP BY uid, c)
  GROUP BY uid),
me AS (
  SELECT user_pseudo_id uid,
    MIN(event_timestamp) t0, MAX(event_timestamp) t1,
    ANY_VALUE(device.mobile_model_name) model,
    ANY_VALUE(geo.city) city,
    ANY_VALUE(device.language) lang,
    -- ★버전은 **마지막 이벤트 기준**이다. ANY_VALUE 면 하루 중에 업데이트한 사람의
    --   버전이 임의로 집혀서, 지금처럼 신버전 전파를 지켜볼 때 옛 버전으로 보일 수 있다.
    ARRAY_AGG(app_info.version IGNORE NULLS
              ORDER BY event_timestamp DESC LIMIT 1)[SAFE_OFFSET(0)] ver,
    COUNTIF(event_name='first_open') > 0 is_new,
    MAX(IF(event_name='level_start', {lv}, NULL)) max_start,
    MAX(IF(event_name='level_clear', {lv}, NULL)) max_clear,
    COUNTIF(event_name='level_clear') clears,
    COUNTIF(event_name='level_stuck') stuck,
    COUNTIF(event_name='ad_watch') ads,
    COUNTIF(event_name='shop_open') shops,
    COUNTIF(event_name='purchase') buys,
    COUNTIF(event_name='app_remove') > 0 removed,
    COUNTIF(event_name='abuse') abuse,
    STRING_AGG(DISTINCT IF(event_name='onboard_step', {step}, NULL)) onb,
    STRING_AGG(DISTINCT IF(event_name='side_step', {step}, NULL)) side
  FROM e GROUP BY uid)
SELECT me.*, cc.c country, cc.vpn FROM me JOIN cc USING (uid)
ORDER BY t0 DESC LIMIT 300
""".format(t=T, d=day, lv=p_int("level"), step=p_str("step")))

    users, reach, seen = [], {k: 0 for k in F.STEP_KEYS}, {}
    for r in rows:
        onb = set((r["onb"] or "").split(","))
        kind = _classify(r)
        rec = {
            "uid": r["uid"][:8],
            "t0": datetime.fromtimestamp(r["t0"] / 1e6, KST).strftime("%H:%M"),
            "mins": round((r["t1"] - r["t0"]) / 6e7, 1),
            "model": r["model"], "country": r["country"], "city": r["city"],
            "lang": r["lang"], "ver": r["ver"], "new": bool(r["is_new"]),
            "vpn": bool(r["vpn"]),
            "lv": r["max_clear"] or 0, "started": r["max_start"] or 0,
            "clears": r["clears"], "stuck": r["stuck"], "ads": r["ads"],
            "shops": r["shops"], "buys": r["buys"], "removed": bool(r["removed"]),
            "abuse": r["abuse"],
            # 척추 도달을 비트로 접는다 — 10칸 배열보다 짧고 화면에서 바로 푼다
            "reached": sum(1 << i for i, k in enumerate(F.STEP_KEYS) if k in onb),
            "side": sorted(x for x in (r["side"] or "").split(",") if x),
            "kind": kind,
        }
        seen[kind] = seen.get(kind, 0) + 1
        # ★사람이 아닌 줄은 **목록에 아예 안 넣는다**(형 지시 2026-10-11).
        #   봇·스캔은 업로드마다 수십 대가 돌고, 내 기기는 버전 바꿀 때마다 새 uid 가
        #   생긴다 — 둘 다 목록을 덮어서 정작 봐야 할 사람이 스크롤 아래로 밀린다.
        #   ★다만 **몇 개를 뺐는지는 숫자로 남긴다**(KPI 의 봇·내기기 칸).
        #   조용히 지우면 진짜 유저를 봇으로 오인해도 알 길이 없다.
        if kind != "human":
            continue
        users.append(rec)
        for i, k in enumerate(F.STEP_KEYS):
            if k in onb:
                reach[k] += 1

    out = {
        "updated": now.strftime("%Y-%m-%d %H:%M") + " KST",
        "project": PROJECT, "dataset": DS, "day": day,
        "steps": [{"key": k, "label": l} for k, l in F.ONB_STEPS],
        "reach": [{"key": k, "label": F.STEP_LABELS[k], "users": reach[k]} for k in F.STEP_KEYS],
        "users": users,
        # ★seen 은 **빼기 전** 수다. users 에는 봇·디버그가 없으므로 거기서 세면 0 이 된다.
        "kinds": {k: seen.get(k, 0) for k in ("human", "bot", "me", "dbg")},
        "bots": seen.get("bot", 0),
        "humans": seen.get("human", 0),
    }
    # ★아래 집계들도 **사람만** 센다(형 지시). 예전엔 봇·스캔이 그대로 섞여서
    #   "버전별 설치 11" 같은 수가 전부 구글 스캔이었다.
    #   조건을 한 줄로 만들어 모든 쿼리가 같이 쓴다 — 각자 적으면 하나를 빠뜨린다.
    only_human = ("IFNULL(geo.country,'') != '' AND IFNULL(device.mobile_model_name,'') != ''"
                  " AND IFNULL(app_info.version,'') NOT LIKE 'dbg%'")
    if EXCLUDE:
        only_human += " AND user_pseudo_id NOT IN (%s)" % ",".join("'%s'" % u for u in EXCLUDE)
    if TEST_MODELS:
        only_human += " AND IFNULL(device.mobile_model_name,'') NOT IN (%s)" % ",".join(
            "'%s'" % m for m in TEST_MODELS)

    out["versions"] = q("""
SELECT app_info.version ver, COUNT(DISTINCT user_pseudo_id) users,
  COUNTIF(event_name='first_open') installs
FROM {t} WHERE _TABLE_SUFFIX='{d}' AND {h} GROUP BY ver ORDER BY users DESC
""".format(t=T, d=day, h=only_human))
    # ★사람당 나라를 **하나로** 정한다 — 인게임 뷰와 같은 규칙(queries.countries 주석).
    #   그냥 GROUP BY 로 세면 VPN 유저가 여러 나라에 중복으로 들어가 합계가 유저 수를
    #   넘는다(실측: 브라질 9 인데 실제로는 7명이 이란과 같은 사람이었다).
    out["countries"] = q("""
WITH ec AS (
  SELECT user_pseudo_id uid, geo.country c, COUNT(*) n
  FROM {t} WHERE _TABLE_SUFFIX='{d}' AND {h} GROUP BY uid, c
), pick AS (
  SELECT uid, ARRAY_AGG(c ORDER BY n DESC, c LIMIT 1)[OFFSET(0)] c, COUNT(*) > 1 vpn
  FROM ec GROUP BY uid
)
SELECT c country, COUNT(*) users, COUNTIF(vpn) vpn
FROM pick GROUP BY country ORDER BY users DESC LIMIT 20
""".format(t=T, d=day, h=only_human))
    # ★변조 APK 차단이 **작동 중인지** 본다. 차단이 늘면 좋은 신호지만,
    #   정상 유저가 섞여 막히면 매출이 조용히 0 이 된다 — 그래서 사유별로 센다.
    out["purchase_fail"] = q("""
SELECT {r} reason, COUNT(*) n, COUNT(DISTINCT user_pseudo_id) users
FROM {t} WHERE _TABLE_SUFFIX='{d}' AND {h} AND event_name='purchase_fail'
GROUP BY reason ORDER BY n DESC
""".format(t=T, d=day, h=only_human, r=p_str("reason")))
    out["abuse"] = q("""
SELECT {r} reason, COUNTIF({g}='true') granted, COUNT(*) n
FROM {t} WHERE _TABLE_SUFFIX='{d}' AND {h} AND event_name='abuse'
GROUP BY reason ORDER BY n DESC
""".format(t=T, d=day, h=only_human, r=p_str("reason"), g=p_str("granted")))

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    k = out["kinds"]
    print("✓ realtime %s — %d줄 (사람 %d · 봇 %d · 내기기 %d · 디버그 %d)"
          % (day, len(users), k["human"], k["bot"], k["me"], k["dbg"]))
    print("  " + scan_report())


def _classify(r):
    """사람인가 — ★지우지 않고 **딱지만** 붙인다. 화면에서 걸러 보거나 같이 본다."""
    if (r["ver"] or "").startswith("dbg"):
        return "dbg"
    if r["uid"] in EXCLUDE or (r["model"] or "") in TEST_MODELS:
        return "me"
    if not (r["country"] or "") or not (r["model"] or ""):
        return "bot"
    return "human"


if __name__ == "__main__":
    main()
