#!/usr/bin/env python3
"""전체 가입자 — BigQuery(확정 일별 테이블) → docs/data/users/YYYY-MM-DD.json.

한 줄 = 한 사람의 **지금까지의 최종 상태**다. 가입 당일이 아니라 평생 누적으로 본다 —
레벨 50 은 며칠에 걸쳐 쌓는 값이라 가입일만 보면 영영 안 보인다.

파일을 **가입일별로** 쪼갠다. 화면이 최신 코호트부터 하루씩 당겨 읽는다.
평생 누적이라 옛 코호트도 그 사람들이 다시 오면 값이 바뀌므로 매번 다시 쓰되,
★**내용이 같으면 파일을 건드리지 않는다** — 안 그러면 휴면 코호트까지 매일 커밋에 올라온다.

퍼널 정의는 tools/funnel.py 를 **실시간 화면과 같이 쓴다.** 두 화면이 다른 퍼널을
말하면 비교가 불가능해진다.

인증: GOOGLE_APPLICATION_CREDENTIALS.
"""
import json
import os
import sys

from google.cloud import bigquery

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import funnel as F
import queries as Q

PROJECT = os.environ.get("BQ_PROJECT") or "plopcat-6d336"
LOCATION = os.environ.get("BQ_LOCATION") or "asia-northeast3"
EXCLUDE = [u.strip() for u in os.environ.get("EXCLUDE_USERS", "").split(",") if u.strip()]
DIR = os.path.join(os.path.dirname(__file__), "..", "docs", "data", "users")

client = bigquery.Client(project=PROJECT, location=LOCATION)
DS = (os.environ.get("BQ_DATASET")
      or [d.dataset_id for d in client.list_datasets(PROJECT)
          if d.dataset_id.startswith("analytics_")][0])
T = "`%s.%s.events_*`" % (PROJECT, DS)


def q(sql):
    return [dict(r) for r in client.query(sql).result()]


def main():
    last_daily = q("SELECT MAX(_TABLE_SUFFIX) t FROM %s WHERE _TABLE_SUFFIX NOT LIKE 'intraday%%'"
                   % T)[0]["t"] or "00000000"
    f = Q.human("TRUE", last_daily, EXCLUDE)
    rows = q("""
SELECT user_pseudo_id uid,
  MIN({day}) joined,
  MAX({day}) last_day,
  COUNT(DISTINCT {day}) days,
  ANY_VALUE(device.mobile_model_name) model,
  ANY_VALUE(geo.country) country,
  ANY_VALUE(device.language) lang,
  MAX(app_info.version) ver,
  MAX(IF(event_name='level_clear', {lv}, NULL)) lv,
  COUNTIF(event_name='level_clear') clears,
  COUNTIF(event_name='level_stuck') stuck,
  COUNTIF(event_name='ad_reward') ads,
  COUNTIF(event_name='purchase') buys,
  SUM(IF(event_name='purchase', {val}, 0)) spend,
  COUNTIF(event_name='picture_done') pics,
  COUNTIF(event_name='app_remove') > 0 removed,
  STRING_AGG(DISTINCT IF(event_name='onboard_step', {step}, NULL)) onb
FROM {t} WHERE {f} GROUP BY uid
""".format(t=T, f=f, day=Q.DAY, lv=_i("level"), val=_f("value"), step=_s("step")))

    by_day = {}
    for r in rows:
        onb = set((r["onb"] or "").split(","))
        d = "%s-%s-%s" % (r["joined"][:4], r["joined"][4:6], r["joined"][6:8])
        by_day.setdefault(d, []).append({
            "uid": r["uid"][:8], "model": r["model"], "country": r["country"],
            "lang": r["lang"], "ver": r["ver"], "days": r["days"],
            "last": r["last_day"], "lv": r["lv"] or 0, "clears": r["clears"],
            "stuck": r["stuck"], "ads": r["ads"], "buys": r["buys"],
            "spend": round(float(r["spend"] or 0), 2), "pics": r["pics"],
            "removed": bool(r["removed"]),
            "reached": sum(1 << i for i, k in enumerate(F.STEP_KEYS) if k in onb),
        })

    os.makedirs(DIR, exist_ok=True)
    wrote = kept = 0
    for d, us in by_day.items():
        us.sort(key=lambda x: (-x["lv"], x["uid"]))
        body = json.dumps({"date": d, "users": us}, ensure_ascii=False, indent=1)
        p = os.path.join(DIR, d + ".json")
        # ★같으면 안 쓴다 — 휴면 코호트가 매일 커밋에 올라오는 걸 막는다
        if os.path.exists(p) and open(p, encoding="utf-8").read() == body:
            kept += 1
            continue
        open(p, "w", encoding="utf-8").write(body)
        wrote += 1
    idx = sorted(by_day, reverse=True)
    json.dump({"days": idx, "total": sum(len(v) for v in by_day.values())},
              open(os.path.join(DIR, "index.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("✓ users — %d일 코호트 · %d명 (새로 쓴 파일 %d · 그대로 둔 것 %d)"
          % (len(idx), sum(len(v) for v in by_day.values()), wrote, kept))


def _i(k):
    return "(SELECT value.int_value FROM UNNEST(event_params) WHERE key='%s')" % k


def _f(k):
    return ("(SELECT IFNULL(value.double_value, IFNULL(value.float_value, 0))"
            " FROM UNNEST(event_params) WHERE key='%s')" % k)


def _s(k):
    return "(SELECT value.string_value FROM UNNEST(event_params) WHERE key='%s')" % k


if __name__ == "__main__":
    main()
