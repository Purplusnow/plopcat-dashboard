#!/usr/bin/env python3
"""보상형 광고가 **누구에게** 안 나오나 — 나라·기기·버전별로 쪼갠다.

    python3 tools/adfill.py            # 표준출력에만 찍는다

형 제보(2026-10-23): "하트 채우기 광고 눌렀는데 잘 나온다", "이동횟수 부족할 때도 잘 나온다".
그런데 지표에는 보상형 43번 시도에 성공 1번이다.

★모순이 아니다. 형 기기는 **대시보드에서 제외**돼 있다(TEST_MODELS). 형의 성공은
  애초에 집계에 안 들어간다. 즉 실패하는 건 **형이 아닌 누군가**다.
  우리 유저는 이란·브라질이 대부분이고, 광고 재고는 **지역마다 전혀 다르다** —
  이란은 제재 지역이라 보상형 광고주가 사실상 없을 수 있다.

그래서 코드를 더 고치기 전에 **누가 실패하는지**부터 본다. 전부 이란이면 코드 문제가
아니라 지역 문제이고, 브라질도 실패하면 그때 코드를 다시 본다.
"""
import os
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
T = "`%s.%s.events_*`" % (PROJECT, DS)
MODELS = ", ".join("'%s'" % m.replace("'", "") for m in TEST_MODELS) or "''"

SQL = """
WITH ev AS (
  SELECT user_pseudo_id uid, event_name, geo.country country,
         device.mobile_model_name model, device.language lang, app_info.version ver,
         (SELECT value.string_value FROM UNNEST(event_params) WHERE key='placement') pl,
         (SELECT value.string_value FROM UNNEST(event_params) WHERE key='result') rs,
         (SELECT value.string_value FROM UNNEST(event_params) WHERE key='detail') detail
  FROM {t}
  WHERE geo.country IS NOT NULL AND geo.country != ''
), uc AS (                      -- 사람당 나라 하나(이벤트 최다) — VPN 때문에 그냥 세면 중복
  SELECT uid, ARRAY_AGG(c ORDER BY n DESC, c LIMIT 1)[OFFSET(0)] country
  FROM (SELECT uid, country c, COUNT(*) n FROM ev GROUP BY uid, c) GROUP BY uid
)
SELECT uc.country, e.model, e.lang, e.ver, e.pl, e.rs, e.detail, e.uid,
       e.model IN ({models}) is_test
FROM ev e JOIN uc USING (uid)
WHERE e.event_name = 'ad_watch'
""".format(t=T, models=MODELS)


def main() -> None:
    rows = [dict(r) for r in client.query(SQL).result()]
    rw = [r for r in rows if r["pl"] and r["pl"] != "inter"]
    print("ad_watch %d건 (보상형 %d건) — 테스트 기기 **포함**해서 본다\n" % (len(rows), len(rw)))

    print("═══ ① ★보상형 결과 × 나라 ═══")
    by = defaultdict(Counter)
    for r in rw:
        by[r["country"]][r["rs"]] += 1
    for c in sorted(by, key=lambda c: -sum(by[c].values())):
        d = by[c]
        tot = sum(d.values())
        ok = d.get("earned", 0)
        print("  %-14s 시도 %3d · 성공 %2d (%3.0f%%) · %s"
              % (c, tot, ok, 100.0 * ok / tot, dict(d.most_common())))

    print("\n═══ ② ★내 테스트 기기 vs 진짜 유저 ═══")
    for label, want in [("내 기기(제외 대상)", True), ("진짜 유저", False)]:
        g = [r for r in rw if bool(r["is_test"]) == want]
        if not g:
            print("  %-18s 보상형 기록 **없음**" % label)
            continue
        c = Counter(r["rs"] for r in g)
        ok = c.get("earned", 0)
        print("  %-18s 시도 %3d · 성공 %2d (%3.0f%%) · %s"
              % (label, len(g), ok, 100.0 * ok / len(g), dict(c.most_common())))

    print("\n═══ ③ 자리별(placement) ═══")
    for pl in sorted({r["pl"] for r in rw}):
        g = [r for r in rw if r["pl"] == pl]
        c = Counter(r["rs"] for r in g)
        print("  %-8s 시도 %3d · %s" % (pl, len(g), dict(c.most_common())))

    print("\n═══ ④ 실패 사유(detail) — 새 빌드가 퍼져야 채워진다 ═══")
    dt = Counter(r["detail"] for r in rw if r["rs"] == "no_ad")
    if not any(dt):
        print("  아직 비어 있다 — detail 을 싣는 빌드(v49+)가 유저에게 닿아야 한다")
    for d, n in dt.most_common(10):
        print("  %-40s %d건" % (d or "(없음)", n))

    print("\n═══ ⑤ 기기 모델별 — 특정 기종만 안 되는지 ═══")
    mm = defaultdict(Counter)
    for r in rw:
        mm[r["model"]][r["rs"]] += 1
    for m, c in sorted(mm.items(), key=lambda kv: -sum(kv[1].values()))[:10]:
        ok = c.get("earned", 0)
        print("  %-16s 시도 %3d · 성공 %d · %s" % (m, sum(c.values()), ok, dict(c.most_common())))


if __name__ == "__main__":
    main()
