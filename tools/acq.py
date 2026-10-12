#!/usr/bin/env python3
"""유입 출처 조사 — **브라질 타겟 광고비가 실제로 누구를 데려왔나.**

    python3 tools/acq.py            # 표준출력에만 찍는다(대시보드 파일 안 건드림)

형 질문(2026-10-12): "마케팅을 브라질 타겟으로 하고 있는데, 실제로는 이란 유저들이
VPN을 브라질로 붙어서 광고를 보고 다운받은 상황으로 봐야하나?"

★가르는 열쇠는 **설치 시점 국가**다. 대시보드의 '대표 국가'는 그 사람 이벤트가 가장
  많은 나라라서, VPN을 설치할 때만 켜고 평소엔 끄면 **대표는 Iran, 설치는 Brazil** 이
  된다. 그 경우 브라질 광고비가 이란 유저를 데려온 것이고, 지금 국가 표로는 안 보인다.
  그래서 first_open 이벤트의 geo 를 따로 본다.

★두 번째 열쇠는 **traffic_source**(최초 유입, 유저 스코프). 광고로 들어왔으면
  medium 이 cpc 류이고 campaign 이름이 붙는다. organic 이면 광고비와 무관하다.

왜 대시보드에 안 넣고 따로 두나 — 이건 **한 번 답을 내면 끝나는 조사**다.
상시 지표로 만들면 매일 쿼리 비용만 들고 아무도 안 본다. 결론은 메모리로 남긴다.
"""
import os
import sys
from collections import Counter, defaultdict

from google.cloud import bigquery

PROJECT = os.environ.get("BQ_PROJECT") or "plopcat-6d336"
LOCATION = os.environ.get("BQ_LOCATION") or "asia-northeast3"
TEST_MODELS = [m.strip() for m in
               (os.environ.get("TEST_MODELS") or "SM-G998B,SM-G991N").split(",") if m.strip()]

client = bigquery.Client(project=PROJECT, location=LOCATION)
DS = (os.environ.get("BQ_DATASET")
      or [d.dataset_id for d in client.list_datasets(PROJECT)
          if d.dataset_id.startswith("analytics_")][0])
# ★events_* 는 intraday_* 까지 포함한다(와일드카드가 접두 일치). 따로 UNION 하면 중복이다.
T = "`%s.%s.events_*`" % (PROJECT, DS)

MODELS = ", ".join("'%s'" % m.replace("'", "") for m in TEST_MODELS) or "''"

# ★봇 제외는 geo 로 한다 — 구글 사전출시 스캔은 geo.country 가 **비어 있고** 실행마다
#   새 uid 다(공용 메모리 play-prelaunch-bot-traffic). 기기명으로는 안 걸린다.
SQL = """
WITH ev AS (
  SELECT user_pseudo_id uid, event_name, event_timestamp ts,
         geo.country country, device.language lang, device.mobile_model_name model,
         traffic_source.name ts_name, traffic_source.medium ts_medium,
         traffic_source.source ts_source
  FROM {t}
  WHERE geo.country IS NOT NULL AND geo.country != ''
    AND (device.mobile_model_name IS NULL OR device.mobile_model_name NOT IN ({models}))
), first_ev AS (          -- 설치 시점(= 가장 이른 이벤트)의 나라
  SELECT uid,
    ARRAY_AGG(STRUCT(country, lang, ts_name, ts_medium, ts_source)
              ORDER BY ts LIMIT 1)[OFFSET(0)] f
  FROM ev GROUP BY uid
), open_ev AS (           -- first_open 이벤트가 따로 있으면 그쪽이 더 정확하다
  SELECT uid, ARRAY_AGG(country ORDER BY ts LIMIT 1)[OFFSET(0)] c
  FROM ev WHERE event_name = 'first_open' GROUP BY uid
), dom AS (               -- 대시보드가 쓰는 '대표 나라'(이벤트 최다)
  SELECT uid, ARRAY_AGG(c ORDER BY n DESC, c LIMIT 1)[OFFSET(0)] c, COUNT(*) > 1 multi
  FROM (SELECT uid, country c, COUNT(*) n FROM ev GROUP BY uid, c)
  GROUP BY uid
)
SELECT d.uid, d.c dom_country, d.multi,
       IFNULL(o.c, f.f.country) install_country,
       f.f.lang lang, f.f.ts_name campaign, f.f.ts_medium medium, f.f.ts_source source
FROM dom d
LEFT JOIN first_ev f USING (uid)
LEFT JOIN open_ev o USING (uid)
""".format(t=T, models=MODELS)


def main() -> None:
    rows = [dict(r) for r in client.query(SQL).result()]
    print("조사 대상 %d명 (봇·테스트기기 제외, events_* 전체 기간)\n" % len(rows))

    def is_fa(r):
        return str(r.get("lang") or "").lower().startswith("fa")

    # ① 설치 국가 × 대표 국가 — 여기가 질문의 핵심
    print("═══ ① 설치 시점 국가 → 평소 국가 (명)  ★다르면 설치할 때만 VPN 을 켠 것 ═══")
    cross = Counter((r["install_country"], r["dom_country"]) for r in rows)
    for (ic, dc), n in cross.most_common(25):
        mark = "  ← 설치≠평소" if ic != dc else ""
        print("  %-14s → %-14s %4d%s" % (ic, dc, n, mark))

    print("\n═══ ② 설치 시점 국가별 — 그중 페르시아어 기기 ═══")
    by_ic = defaultdict(list)
    for r in rows:
        by_ic[r["install_country"]].append(r)
    for ic, rs in sorted(by_ic.items(), key=lambda kv: -len(kv[1]))[:12]:
        fa = sum(1 for r in rs if is_fa(r))
        print("  %-14s 설치 %4d명 · 페르시아어 %4d명 (%3.0f%%)"
              % (ic, len(rs), fa, 100.0 * fa / len(rs)))

    print("\n═══ ③ 유입 출처 (traffic_source, 최초 유입) ═══")
    src = Counter((r.get("source"), r.get("medium"), r.get("campaign")) for r in rows)
    for (s, m, c), n in src.most_common(15):
        print("  source=%-16s medium=%-12s campaign=%-24s %4d명"
              % (s or "(없음)", m or "(없음)", c or "(없음)", n))

    print("\n═══ ④ ★브라질로 설치한 사람들의 정체 ═══")
    br = [r for r in rows if r["install_country"] == "Brazil"]
    if not br:
        print("  브라질 설치 0명")
    else:
        fa = [r for r in br if is_fa(r)]
        print("  브라질 설치 %d명 중 페르시아어 기기 **%d명** (%.0f%%)"
              % (len(br), len(fa), 100.0 * len(fa) / len(br)))
        print("  그들의 평소 국가:", dict(Counter(r["dom_country"] for r in fa)))
        print("  그들의 유입 출처:",
              dict(Counter("%s/%s" % (r.get("source") or "-", r.get("medium") or "-")
                           for r in fa)))
        print("  진짜 브라질인(비페르시아어)의 유입 출처:",
              dict(Counter("%s/%s" % (r.get("source") or "-", r.get("medium") or "-")
                           for r in br if not is_fa(r))))

    print("\n═══ ⑤ 페르시아어 기기 전체의 설치 국가 ═══")
    fa_all = [r for r in rows if is_fa(r)]
    print("  페르시아어 %d명 / 전체 %d명 (%.0f%%)"
          % (len(fa_all), len(rows), 100.0 * len(fa_all) / max(1, len(rows))))
    print("  설치 국가:", dict(Counter(r["install_country"] for r in fa_all).most_common()))


if __name__ == "__main__":
    main()
