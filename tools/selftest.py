#!/usr/bin/env python3
"""지표 쿼리 검증 — **답을 아는 합성 데이터**로 잰다.

왜 필요한가: 진짜 데이터로는 검증이 안 된다. 출시 전엔 유저가 한 명뿐이라
클리어율이 0.5 로 나와도 그게 맞는 값인지 쿼리가 틀린 건지 구분할 수가 없다.
**정답을 미리 아는 입력**을 넣어야 쿼리가 거짓말하는지 알 수 있다.

★tools/queries.py 를 **그대로** 부른다(베끼지 않는다). 쿼리를 고치면 여기서 바로 터진다.
★BigQuery 에서 실행하므로 문법·UNNEST·JOIN 동작이 **실제 엔진 기준**으로 검증된다.
  (서비스 계정에 테이블 생성 권한이 없어도 된다 — CTE 로 만들어 넣는다.)

사용:
    export GOOGLE_APPLICATION_CREDENTIALS=~/dev/keystore/plopcat-bq.json
    python3 tools/selftest.py
"""
import os
import sys

from google.cloud import bigquery

import queries as Q

client = bigquery.Client(project=os.environ.get("BQ_PROJECT") or "plopcat-6d336",
                         location=os.environ.get("BQ_LOCATION") or "asia-northeast3")
fails = []


def chk(name, got, want):
    ok = got == want
    print("  %s %s%s" % ("✅" if ok else "❌", name,
                         "" if ok else "  기대 %r / 실제 %r" % (want, got)))
    if not ok:
        fails.append(name)


def ev(day, user, name, params=(), version="1.0 (v23)", country="KR"):
    """GA4 events_* 한 줄을 흉내 낸다. 실제 스키마와 같은 모양이어야 의미가 있다."""
    ps = ",".join(
        "STRUCT('%s' AS key, STRUCT(%s AS int_value, %s AS string_value) AS value)"
        % (k, v if isinstance(v, int) else "NULL",
           "NULL" if isinstance(v, int) else "'%s'" % v)
        for k, v in params)
    return ("STRUCT('%s' AS _TABLE_SUFFIX, '%s' AS user_pseudo_id, '%s' AS event_name,"
            " STRUCT(%s AS country) AS geo, STRUCT('%s' AS version) AS app_info,"
            " [%s] AS event_params)"
            % (day, user, name,
               "NULL" if country is None else "'%s'" % country, version, ps))


def table(rows):
    return "(SELECT * FROM UNNEST([%s]))" % ",".join(rows)


def run(sql):
    return [dict(r) for r in client.query(sql).result()]


def main():
    # ── ① 레벨별 클리어율 ────────────────────────────────────────────
    # 정답을 손으로 만든다:
    #   L1 : 3명 시작, 3명 클리어        → 100%
    #   L2 : 3명 시작, 1명 클리어        → 33.3%   ← 벽
    #   L3 : 1명 시작, **아무도 못 깸**  → 0%      ← LEFT JOIN 이 아니면 줄 자체가 사라진다
    rows = []
    for u in ["a", "b", "c"]:
        rows.append(ev("20260101", u, "level_start", [("level", 1)]))
        rows.append(ev("20260101", u, "level_clear",
                       [("level", 1), ("attempts", 1), ("over", 0), ("play_secs", 10),
                        ("hints", 0), ("undos", 0), ("tows", 0), ("restarts", 0)]))
        rows.append(ev("20260101", u, "level_start", [("level", 2)]))
    rows.append(ev("20260101", "a", "level_clear",
                   [("level", 2), ("attempts", 3), ("over", 4), ("play_secs", 60),
                    ("hints", 1), ("undos", 2), ("tows", 0), ("restarts", 1)]))
    rows.append(ev("20260101", "a", "level_start", [("level", 3)]))
    # 사람이 아닌 줄 — 걸러져야 한다
    rows.append(ev("20260101", "bot", "level_start", [("level", 1)], country=None))
    rows.append(ev("20260101", "dbg1", "level_start", [("level", 1)], version="dbg 20260101"))
    rows.append(ev("20260101", "me", "level_start", [("level", 1)]))

    filt = ("IFNULL(geo.country,'') != '' AND IFNULL(app_info.version,'') NOT LIKE 'dbg%'"
            " AND user_pseudo_id NOT IN ('me')")
    lv = {r["lv"]: r for r in run(Q.levels(table(rows), filt))}

    chk("L1 클리어율 100%", round(lv[1]["rate"], 3), 1.0)
    chk("L2 클리어율 33.3%", round(lv[2]["rate"], 3), 0.333)
    chk("★아무도 못 깬 L3 이 결과에 남는다", 3 in lv, True)
    chk("L3 클리어 0", lv[3]["cleared"] if 3 in lv else None, 0)
    chk("봇·디버그·본인 기기가 분모에서 빠진다", lv[1]["started"], 3)
    chk("L2 평균 시도", lv[2]["attempts"], 3.0)
    chk("L2 평균 아이템(1+2+0+1)", lv[2]["items"], 4.0)
    chk("L2 평균 초과 수", lv[2]["over_moves"], 4.0)

    # ── ③ 못 깬 판 ─────────────────────────────────────────────────
    st = [ev("20260101", "a", "level_stuck", [("level", 7), ("attempts", 5), ("hints", 2)]),
          ev("20260101", "b", "level_stuck", [("level", 7), ("attempts", 3), ("hints", 0)]),
          ev("20260101", "c", "level_stuck", [("level", 9), ("attempts", 2), ("hints", 1)])]
    sr = run(Q.stuck(table(st), "TRUE"))
    chk("가장 많이 막힌 판이 맨 위", sr[0]["lv"], 7)
    chk("그 판 건수", sr[0]["n"], 2)
    chk("평균 시도 (5+3)/2", sr[0]["attempts"], 4.0)

    # ── ④ 수집 메타 ─────────────────────────────────────────────────
    al = [ev("20260101", "a", "album_open"), ev("20260101", "a", "album_open"),
          ev("20260101", "b", "album_open"),
          ev("20260101", "a", "picture_done"), ev("20260101", "a", "picture_done")]
    ar = run(Q.album(table(al), "TRUE"))[0]
    chk("조립 진입 **사람 수**(2회 연 a 를 1명으로)", ar["opened"], 2)
    chk("완성한 사람 수", ar["finished"], 1)
    chk("완성 그림 건수", ar["pictures"], 2)

    # ── ⑤ 광고 결과 ─────────────────────────────────────────────────
    ad = [ev("20260101", "a", "ad_reward", [("placement", "hint"), ("result", "earned")]),
          ev("20260101", "b", "ad_reward", [("placement", "hint"), ("result", "earned")]),
          ev("20260101", "c", "ad_reward", [("placement", "hint"), ("result", "no_ad")])]
    adr = run(Q.ads(table(ad), "TRUE"))
    chk("광고 결과가 많은 순", (adr[0]["result"], adr[0]["n"]), ("earned", 2))

    # ── ⑥ 온보딩 ───────────────────────────────────────────────────
    ob = [ev("20260101", "a", "onboard_step", [("step", 1)]),
          ev("20260101", "a", "onboard_step", [("step", 1)]),   # 같은 사람 중복
          ev("20260101", "b", "onboard_step", [("step", 1)]),
          ev("20260101", "a", "onboard_step", [("step", 2)])]
    obr = {r["step"]: r["users"] for r in run(Q.onboard(table(ob), "TRUE"))}
    chk("1단계는 **사람 수**(중복 제거)", obr[1], 2)
    chk("2단계", obr[2], 1)

    print()
    if fails:
        print("❌ selftest FAIL — %d건: %s" % (len(fails), ", ".join(fails)))
        return 1
    print("✅ selftest PASS — 쿼리가 답을 아는 입력에서 맞는 값을 낸다")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    sys.exit(main())
