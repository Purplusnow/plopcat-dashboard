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

import funnel as F
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


def ev(day, user, name, params=(), version="1.0 (v23)", country="KR", model="SM-S911N"):
    """GA4 events_* 한 줄을 흉내 낸다. 실제 스키마와 같은 모양이어야 의미가 있다."""
    # ★NULL 에 **타입을 붙인다.** 맨 NULL 을 쓰면 BigQuery 가 string_value 칼럼을
    #   INT64 로 추론해서(첫 줄이 전부 NULL 이면), 문자열 파라미터를 읽는 쿼리가
    #   "No matching signature for operator = ... INT64, STRING" 으로 터진다.
    #   실제 GA4 스키마와 **모양이 같아야** 이 하네스가 의미를 갖는다.
    ps = ",".join(
        "STRUCT('%s' AS key, STRUCT(%s AS int_value, %s AS string_value) AS value)"
        % (k, v if isinstance(v, int) else "CAST(NULL AS INT64)",
           "CAST(NULL AS STRING)" if isinstance(v, int) else "'%s'" % v)
        for k, v in params)
    return ("STRUCT('%s' AS _TABLE_SUFFIX, '%s' AS user_pseudo_id, '%s' AS event_name,"
            " STRUCT(%s AS country) AS geo, STRUCT('%s' AS version) AS app_info,"
            " STRUCT(%s AS mobile_model_name) AS device,"
            " [%s] AS event_params)"
            % (day, user, name,
               "NULL" if country is None else "'%s'" % country, version,
               "NULL" if model is None else "'%s'" % model, ps))


def table(rows):
    return "(SELECT * FROM UNNEST([%s]))" % ",".join(rows)


def run(sql):
    return [dict(r) for r in client.query(sql).result()]


def check_funnel_matches_game():
    """★퍼널 정의가 **게임과 같은지** 대조한다.

    tools/funnel.py 는 scripts/autoload/analytics.gd 의 ONB_STEPS 를 옮겨 적은 것이다.
    게임이 단계를 추가·개명했는데 여기가 그대로면, 화면은 멀쩡히 그려지면서
    **조용히 다른 퍼널**을 말한다 — 이게 제일 무서운 고장이다.

    게임 레포가 옆에 없으면(Actions 환경) 건너뛴다. 그 경우 사람이 볼 수 있게 말은 한다.
    """
    import re
    g = os.path.expanduser("~/dev/plopcat/scripts/autoload/analytics.gd")
    if not os.path.exists(g):
        print("  · 게임 레포가 없어 퍼널 대조를 건너뛴다 (로컬에서 한 번은 돌릴 것)")
        return
    src = open(g, encoding="utf-8").read()
    m = re.search(r"const ONB_STEPS := \{(.*?)\}", src, re.S)
    if not m:
        fails.append("게임에서 ONB_STEPS 를 못 찾았다")
        print("  ❌ 게임에서 ONB_STEPS 를 못 찾았다")
        return
    game = re.findall(r'"([a-z0-9_]+)"', m.group(1))
    chk("★퍼널 단계가 게임(analytics.gd ONB_STEPS)과 같다", F.STEP_KEYS, game)


def main():
    check_funnel_matches_game()
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
    rows.append(ev("20260101", "nomodel", "level_start", [("level", 1)], model=None))

    # ★규칙을 베끼지 않는다 — 수집기가 쓰는 **그 함수**를 부른다.
    #   예전엔 여기에 필터를 손으로 적어 놨는데, 그러면 수집기 규칙을 바꿔도
    #   검사는 옛 규칙으로 통과한다(검사가 아니라 장식이 된다).
    filt = Q.human("TRUE", "20251231", ["me"])
    lv = {r["lv"]: r for r in run(Q.levels(table(rows), filt))}

    chk("L1 클리어율 100%", round(lv[1]["rate"], 3), 1.0)
    chk("L2 클리어율 33.3%", round(lv[2]["rate"], 3), 0.333)
    chk("★아무도 못 깬 L3 이 결과에 남는다", 3 in lv, True)
    chk("L3 클리어 0", lv[3]["cleared"] if 3 in lv else None, 0)
    # ── ①-b ★intraday 중복 ────────────────────────────────────────
    # 내가 실제로 당한 함정이다. events_* 와일드카드는 **events_intraday_* 도 같이 잡는다.**
    # 그 사실을 모르고 UNION 을 하거나 날짜 중복을 안 막으면 같은 사람이 두 번 세어진다.
    # 답을 알고 재 본다: 한 사람이 같은 판을 세 테이블에 남겼을 때 **1명**이어야 한다.
    dup = [
        # 닫힌 일일 테이블(20260101) — 쓴다
        ev("20260101", "z", "level_start", [("level", 9)]),
        # 같은 날짜의 intraday — **중복이므로 버려야 한다**
        ev("intraday_20260101", "z", "level_start", [("level", 9)]),
        # 아직 안 닫힌 날짜의 intraday — 이건 **써야** 오늘 일이 오늘 보인다
        ev("intraday_20260102", "z", "level_clear",
           [("level", 9), ("attempts", 1), ("over", 0), ("play_secs", 5),
            ("hints", 0), ("undos", 0), ("tows", 0), ("restarts", 0)]),
    ]
    df = Q.human("TRUE", "20260101", [])
    n = run("SELECT COUNT(*) c, COUNT(DISTINCT user_pseudo_id) u FROM %s WHERE %s"
            % (table(dup), df))[0]
    chk("★같은 날짜의 intraday 는 버린다(두 번 세지 않는다)", n["c"], 2)
    chk("★안 닫힌 날짜의 intraday 는 쓴다(오늘 일이 오늘 보인다)",
        run("SELECT COUNT(*) c FROM %s WHERE %s AND event_name='level_clear'"
            % (table(dup), df))[0]["c"], 1)
    d9 = {r["lv"]: r for r in run(Q.levels(table(dup), df))}
    chk("중복이 섞여도 클리어율이 100%", round(d9[9]["rate"], 3) if 9 in d9 else None, 1.0)
    chk("중복이 섞여도 시작은 1명", d9[9]["started"] if 9 in d9 else None, 1)

    # ── ①-c 코호트 리텐션 ─────────────────────────────────────────
    # 답을 손으로 만든다. 1/1 에 2명(a,b), 1/2 에 1명(c) 설치.
    #   a: 1/1,1/2,1/3 접속  → D1,D2 생존
    #   b: 1/1 만            → 어디에도 안 남음
    #   c: 1/2,1/3           → 그 코호트의 D1 생존
    # 따라서 코호트 20260101 은 size 2, D1=1(50%), D2=1(50%)
    #       코호트 20260102 는 size 1, D1=1(100%)
    # ★흔한 실수: 전체 유저(3명)로 나눠 D1=33% 로 쓰는 것. 분모는 **그 코호트**다.
    ret = []
    for d in ["20260101", "20260102", "20260103"]:
        if d != "20260103":
            ret.append(ev(d, "a", "level_start", [("level", 1)]))
    ret.append(ev("20260103", "a", "level_start", [("level", 1)]))
    ret.append(ev("20260101", "b", "level_start", [("level", 1)]))
    ret.append(ev("20260102", "c", "level_start", [("level", 1)]))
    ret.append(ev("20260103", "c", "level_start", [("level", 1)]))
    rf = Q.human("TRUE", "20260103", [])
    rr = run(Q.retention(table(ret), rf))
    got = {}
    for r in rr:
        got.setdefault(r["cohort"], {"size": r["size"]})
        if r["n"] is not None:
            got[r["cohort"]][r["n"]] = r["u"]
    chk("코호트 20260101 크기 2", got.get("20260101", {}).get("size"), 2)
    chk("★그 코호트의 D1 = 1 (전체 3명으로 나누지 않는다)",
        got.get("20260101", {}).get(1), 1)
    chk("그 코호트의 D2 = 1", got.get("20260101", {}).get(2), 1)
    chk("나중 코호트 20260102 크기 1", got.get("20260102", {}).get("size"), 1)
    chk("★D0 은 세지 않는다(늘 100%라 칸만 먹는다)",
        0 in got.get("20260101", {}), False)

    # ── ①-d 버전 비교는 **같은 관측창**으로 ───────────────────────────
    # 새 버전은 코호트가 어려서 '아직 안 깬' 사람이 많다. 설치 후 1시간으로 잘라야
    # 모든 버전이 같은 조건을 받는다. 답: 두 버전 모두 1시간 안엔 1판씩이다.
    vr = [
        ev("20260101", "old1", "level_clear",
           [("level", 1), ("secs_since_install", 100), ("attempts", 1), ("over", 0),
            ("play_secs", 9), ("hints", 0), ("undos", 0), ("tows", 0), ("restarts", 0)],
           version="1.0 (v1)"),
        # 옛 버전 유저는 **하루 뒤에** 10판을 더 깼다 — 창을 안 걸면 이게 섞인다
        ev("20260102", "old1", "level_clear",
           [("level", 10), ("secs_since_install", 90000), ("attempts", 1), ("over", 0),
            ("play_secs", 9), ("hints", 0), ("undos", 0), ("tows", 0), ("restarts", 0)],
           version="1.0 (v1)"),
        ev("20260101", "new1", "level_clear",
           [("level", 1), ("secs_since_install", 200), ("attempts", 1), ("over", 0),
            ("play_secs", 9), ("hints", 0), ("undos", 0), ("tows", 0), ("restarts", 0)],
           version="1.0 (v2)"),
    ]
    vv = {r["ver"]: r for r in run(Q.versions(table(vr), rf))}
    chk("★버전 비교는 설치 1시간 창으로 자른다(옛 버전의 이튿날이 안 섞인다)",
        vv["1.0 (v1)"]["avg_lv_1h"], 1.0)
    chk("새 버전도 같은 창", vv["1.0 (v2)"]["avg_lv_1h"], 1.0)

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
