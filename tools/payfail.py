#!/usr/bin/env python3
"""결제 실패 조사 — **이란이라서 실패하는 건가, 우리 버그인가.**

    python3 tools/payfail.py            # 표준출력에만 찍는다

형 질문 맥락(2026-10-13): 상점 시도 18회가 **전부 실패**인데, 브라질 유저가 31명
들어왔다. 이란은 Play 결제가 없으니 실패가 설계대로지만, **브라질은 결제가 되는
시장**이다. 거기서도 실패한다면 그건 우리 쪽 버그이고 매출이 통째로 막힌다.

★가르는 법: 실패 사유를 **나라별로** 쪼갠다.
  · no_details:*  = 그 상품을 스토어가 안 준다(미지원 지역) → 지역 문제
  · bad_apk_cert / bad_signature = 변조 APK → 우리가 막은 것
  · canceled      = 유저가 닫음 → 실패가 아니다
  · not_ready / no_billing / code:N = **우리 쪽 또는 연결 문제** ← 브라질에 이게 뜨면 버그
나라는 **사람당 하나로** 정한다(이벤트 최다). VPN 때문에 한 사람이 여러 나라로
잡히므로 그냥 세면 중복된다(대시보드 국가표와 같은 규칙).
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
  SELECT user_pseudo_id uid, event_name, event_timestamp ts,
         geo.country country, device.language lang, app_info.version ver,
         (SELECT value.string_value FROM UNNEST(event_params) WHERE key='reason') reason,
         (SELECT value.string_value FROM UNNEST(event_params) WHERE key='product_id') pid
  FROM {t}
  WHERE geo.country IS NOT NULL AND geo.country != ''
    AND (device.mobile_model_name IS NULL OR device.mobile_model_name NOT IN ({models}))
), uc AS (                      -- 사람당 나라 하나(이벤트 최다, 동률은 이름순)
  SELECT uid, ARRAY_AGG(c ORDER BY n DESC, c LIMIT 1)[OFFSET(0)] country,
         ARRAY_AGG(l ORDER BY n DESC, l LIMIT 1)[OFFSET(0)] lang
  FROM (SELECT uid, country c, IFNULL(lang,'') l, COUNT(*) n
        FROM ev GROUP BY uid, c, l)
  GROUP BY uid
)
SELECT uc.country, uc.lang, e.event_name, e.reason, e.pid, e.ver, e.uid
FROM ev e JOIN uc USING (uid)
WHERE e.event_name IN ('shop_open','purchase_start','purchase_fail','purchase')
""".format(t=T, models=MODELS)


def main() -> None:
    rows = [dict(r) for r in client.query(SQL).result()]
    ev = lambda name: [r for r in rows if r["event_name"] == name]

    print("═══ ① 나라별 결제 퍼널 (사람 수) ═══")
    by = defaultdict(lambda: defaultdict(set))
    for r in rows:
        by[r["country"]][r["event_name"]].add(r["uid"])
    for c in sorted(by, key=lambda c: -len(by[c]["shop_open"])):
        d = by[c]
        print("  %-14s 상점 %-4d 시도 %-4d 실패 %-4d 성공 %-4d"
              % (c, len(d["shop_open"]), len(d["purchase_start"]),
                 len(d["purchase_fail"]), len(d["purchase"])))

    print("\n═══ ② ★실패 사유 × 나라 (건수) ═══")
    fx = Counter((r["country"], r["reason"] or "(없음)") for r in ev("purchase_fail"))
    for (c, rs), n in fx.most_common(30):
        print("  %-14s %-28s %d건" % (c, rs, n))

    print("\n═══ ③ ★브라질만 — 결제가 되는 시장인데 실패했나 ═══")
    br = [r for r in ev("purchase_fail") if r["country"] == "Brazil"]
    if not br:
        print("  브라질 결제 실패 **0건** — 실패는 전부 다른 나라다(설계대로)")
    else:
        print("  브라질 결제 실패 %d건" % len(br))
        for (rs, pid, ver), n in Counter(
                (r["reason"] or "(없음)", r["pid"] or "-", r["ver"]) for r in br).most_common():
            print("     사유=%-24s 상품=%-16s %s  %d건" % (rs, pid, ver, n))
        print("  ※ no_details:* 면 그 상품이 스토어에 없다(상품 미등록·미승인).")
        print("     not_ready / no_billing / code:N 이면 **우리 쪽 문제**다.")

    print("\n═══ ④ 상품별 실패 ═══")
    for (pid, rs), n in Counter(
            (r["pid"] or "-", r["reason"] or "(없음)") for r in ev("purchase_fail")).most_common(20):
        print("  %-18s %-28s %d건" % (pid, rs, n))

    print("\n═══ ⑤ 상점을 열고도 **안 누른** 사람 ═══")
    for c in sorted(by, key=lambda c: -len(by[c]["shop_open"]))[:6]:
        o, s = by[c]["shop_open"], by[c]["purchase_start"]
        print("  %-14s 열었지만 안 누름 %d명 / 연 사람 %d명" % (c, len(o - s), len(o)))


if __name__ == "__main__":
    main()
