#!/usr/bin/env python3
"""광고매출이 **GA4 안에 이미 들어와 있는지** 확인한다.

    python3 tools/adrev.py            # 표준출력에만 찍는다

형 제보(2026-10-15): AdMob 에선 광고매출이 발생 중인데 대시보드는 계속 0이다.
원인은 명확하다 — 퐁당냥엔 AdMob 연동이 **아예 없다**(daily.json 이 비어 있다).

★그런데 자격증명을 새로 발급받기 전에 **공짜 길**이 있는지 먼저 본다.
  AdMob 앱을 Firebase 프로젝트에 연결해 두면, SDK 가 `ad_impression` 이벤트를
  GA4 로 보낸다. 거기엔 노출 1건의 **추정 수익**(value+currency)과 지면 정보가 붙는다.
  이미 들어와 있으면 BigQuery 만으로 일별 광고매출을 만들 수 있고,
  OAuth 자격증명이 아예 필요 없다.

없으면 AdMob API 를 새로 붙이는 수밖에 없다(README 의 '남은 구멍' 표 참고).
어느 쪽인지 **먼저 알고** 움직이려고 만든 일회성 조사다.
"""
import os
from collections import Counter

from google.cloud import bigquery

PROJECT = os.environ.get("BQ_PROJECT") or "plopcat-6d336"
LOCATION = os.environ.get("BQ_LOCATION") or "asia-northeast3"

client = bigquery.Client(project=PROJECT, location=LOCATION)
DS = (os.environ.get("BQ_DATASET")
      or [d.dataset_id for d in client.list_datasets(PROJECT)
          if d.dataset_id.startswith("analytics_")][0])
T = "`%s.%s.events_*`" % (PROJECT, DS)


def run(sql):
    return [dict(r) for r in client.query(sql).result()]


def main() -> None:
    print("═══ ① GA4 에 들어온 이벤트 전부 ═══")
    rows = run("""
SELECT event_name, COUNT(*) n, COUNT(DISTINCT user_pseudo_id) users
FROM {t} GROUP BY event_name ORDER BY n DESC LIMIT 60
""".format(t=T))
    for r in rows:
        mark = "   ◀◀ 광고 수익" if r["event_name"] == "ad_impression" else ""
        print("  %-26s %6d건 %4d명%s" % (r["event_name"], r["n"], r["users"], mark))

    has = any(r["event_name"] == "ad_impression" for r in rows)
    print("\n═══ ② ★ad_impression (AdMob↔Firebase 연동 시 자동) ═══")
    if not has:
        print("  **없다.** AdMob 앱이 Firebase 에 연결돼 있지 않거나, SDK 가 안 보낸다.")
        print("  → 광고매출을 대시보드에 넣으려면 둘 중 하나:")
        print("     (가) AdMob 콘솔에서 이 앱을 Firebase 프로젝트에 **연결**한다.")
        print("          그러면 ad_impression 이 GA4 로 들어오고, 자격증명 없이 일별 매출이 선다.")
        print("          ※ 연결 후 들어온 노출부터만 잡힌다 — 과거분은 안 온다.")
        print("     (나) AdMob API OAuth 자격증명을 **퐁당냥 전용으로 새로** 발급한다.")
        print("          과거분까지 받을 수 있지만 발급·갱신 품이 든다.")
        return

    print("  **있다!** 자격증명 없이 일별 광고매출을 만들 수 있다.")
    for r in run("""
SELECT (SELECT value.string_value FROM UNNEST(event_params) WHERE key='currency') cur,
       COUNT(*) n,
       ROUND(SUM((SELECT value.double_value FROM UNNEST(event_params) WHERE key='value')), 4) revenue
FROM {t} WHERE event_name='ad_impression' GROUP BY cur
""".format(t=T)):
        print("  통화 %-6s 노출 %5d건 · 추정수익 %s" % (r["cur"], r["n"], r["revenue"]))

    print("\n═══ ③ 일별 ═══")
    for r in run("""
SELECT IF(STARTS_WITH(_TABLE_SUFFIX,'intraday_'),
          SUBSTR(_TABLE_SUFFIX,10), _TABLE_SUFFIX) day,
       COUNT(*) n,
       ROUND(SUM((SELECT value.double_value FROM UNNEST(event_params) WHERE key='value')), 4) revenue
FROM {t} WHERE event_name='ad_impression' GROUP BY day ORDER BY day
""".format(t=T)):
        print("  %s  노출 %4d · %s" % (r["day"], r["n"], r["revenue"]))

    print("\n═══ ④ 지면별 ═══")
    for r in run("""
SELECT (SELECT value.string_value FROM UNNEST(event_params) WHERE key='ad_format') fmt,
       (SELECT value.string_value FROM UNNEST(event_params) WHERE key='ad_unit_name') unit,
       COUNT(*) n,
       ROUND(SUM((SELECT value.double_value FROM UNNEST(event_params) WHERE key='value')), 4) revenue
FROM {t} WHERE event_name='ad_impression' GROUP BY fmt, unit ORDER BY n DESC LIMIT 15
""".format(t=T)):
        print("  %-16s %-24s %4d건 · %s" % (r["fmt"], r["unit"], r["n"], r["revenue"]))


if __name__ == "__main__":
    main()
