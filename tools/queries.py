#!/usr/bin/env python3
"""지표 쿼리 — **수집기와 검사가 같은 문자열을 쓴다.**

★왜 따로 뺐나: 검사가 쿼리를 **베껴 들고** 있으면, 진짜 쿼리를 고쳐도 검사는 멀쩡히
통과한다. 검사층이 대상과 같은 가정을 공유하면 안 된다는 걸 이 포트폴리오에서
이미 한 번 비싸게 배웠다(클라우드 조정 규칙 복사본 사건).

그래서 쿼리는 여기 한 곳에만 있고, 테이블 식(`table`)과 필터(`filt`)를 **주입**받는다.
  · tools/ingame.py  → 진짜 BigQuery 테이블을 넣는다
  · tools/selftest.py → 답을 아는 합성 데이터 CTE 를 넣는다

지표 정의의 단일 출처는 **게임 레포 docs/ANALYTICS.md** 다. 여기는 그 식의 구현일 뿐이다.
"""


def p_int(key: str) -> str:
    """이벤트 파라미터에서 정수 하나. GA4 UI 측정기준엔 빈값이지만 raw 엔 int_value 로 있다."""
    return "(SELECT value.int_value FROM UNNEST(event_params) WHERE key = '%s')" % key


def p_str(key: str) -> str:
    return "(SELECT value.string_value FROM UNNEST(event_params) WHERE key = '%s')" % key


#: 날짜 하나를 가리키는 식. events_* 와일드카드는 **events_intraday_YYYYMMDD 도 같이 잡고**,
#: 그때 _TABLE_SUFFIX 는 'intraday_20261010' 이라 날짜 비교가 전부 어긋난다.
#: 날짜를 비교하는 자리에서는 _TABLE_SUFFIX 대신 **반드시 이걸** 쓴다.
def INT(k: str) -> str:
    """이벤트 파라미터의 정수값. ★GA4 UI 에선 빈칸으로 보이지만 raw 에는 멀쩡히 있다."""
    return "(SELECT value.int_value FROM UNNEST(event_params) WHERE key='%s')" % k


def STR(k: str) -> str:
    return "(SELECT value.string_value FROM UNNEST(event_params) WHERE key='%s')" % k


DAY = "IF(STARTS_WITH(_TABLE_SUFFIX,'intraday_'), SUBSTR(_TABLE_SUFFIX,10), _TABLE_SUFFIX)"

#: app_info.version 은 "1.0 (v46)" 꼴이다 — 거기서 숫자만.
VER_NUM = r"SAFE_CAST(REGEXP_EXTRACT(app_info.version, r'v(\d+)') AS INT64)"

#: ★수 제한이 **처음 프로덕션에 나간** 버전. 그 아래 버전은 제한이 없어서 실패할 수 없다.
#:  v41~v45 는 빌드만 하고 올리지 않았으므로 라이브 기준 첫 버전은 46 이다.
LIMIT_FIRST_VER = 46


def human(cond: str, last_daily: str, exclude=(), test_models=()) -> str:
    """사람이 아닌 줄을 걷어낸 WHERE 조각. **수집기도 검사도 이 함수를 부른다.**

    ★예전엔 selftest 가 같은 규칙을 **베껴** 들고 있었다. 그러면 수집기 쪽 규칙을
      바꿔도 검사는 옛 규칙으로 통과한다 — 검사가 아니라 장식이 된다.

    거르는 것:
      · 중복 intraday — 일일 테이블이 이미 닫은 날짜. events_* 와일드카드는
        intraday 도 같이 잡으므로, 안 막으면 그 날짜가 **두 번** 세어진다.
      · 지역이 없는 줄 — Play 사전 출시 보고서 봇(업로드마다 수십 대가 돈다)
      · 기기 모델이 없는 줄 — 진짜 폰은 모델명을 늘 보낸다. 모델만 비고 지역은
        잡히는 줄이 있었다(체류 4초, 첫 판에서 정지) — 지역 조건으로는 안 걸린다.
      · 디버그 빌드 — 오토파일럿이 수백 판을 깨서 클리어율을 혼자 뒤집는다
      · 개발자 본인 — exclude 로 받은 user_pseudo_id
    ※BigQuery 에서 NULL != '' 은 TRUE 가 아니다. IFNULL 로 감싸야 둘 다 걸린다.
    """
    out = ("(%s)"
           " AND (NOT STARTS_WITH(_TABLE_SUFFIX,'intraday_')"
           " OR SUBSTR(_TABLE_SUFFIX,10) > '%s')"
           " AND IFNULL(geo.country,'') != ''"
           " AND IFNULL(device.mobile_model_name,'') != ''"
           " AND IFNULL(app_info.version,'') NOT LIKE 'dbg%%'") % (cond, last_daily)
    ids = [u for u in exclude if u]
    if ids:
        out += " AND user_pseudo_id NOT IN (%s)" % ",".join("'%s'" % u for u in ids)
    # ★내 테스트 기기는 **모델로도** 뺀다. user_pseudo_id 는 재설치마다 새로 생겨서
    #   EXCLUDE_USERS 가 늘 하루 늦는다 — 실제로 하루에 10개가 '한국 실유저'로
    #   잡혔고(SM-G998B, v28~v36 재설치), 그걸 보고 "한국 유저가 안 붙는다"는
    #   틀린 결론까지 냈다(2026-10-11). 모델로 막으면 그 날로 끝난다.
    # ⚠출시 후엔 같은 모델의 진짜 유저가 들어오므로 그때는 이 목록을 비운다.
    ms = [m for m in test_models if m]
    if ms:
        out += " AND IFNULL(device.mobile_model_name,'') NOT IN (%s)" % ",".join(
            "'%s'" % m for m in ms)
    return out


def kpi(table: str, filt: str, d1: str, d7: str) -> str:
    return """
SELECT
  COUNT(DISTINCT IF({day} = '{d1}', user_pseudo_id, NULL)) dau,
  COUNT(DISTINCT IF({day} >= '{d7}', user_pseudo_id, NULL)) wau,
  COUNT(DISTINCT user_pseudo_id) users,
  COUNT(DISTINCT IF(event_name = 'first_open', user_pseudo_id, NULL)) new_users
FROM {t} WHERE {f}
""".format(t=table, f=filt, d1=d1, d7=d7, day=DAY)


def levels(table: str, filt: str) -> str:
    """① 레벨별 클리어율.

    ★분모가 **시작한 사람**(level_start)이다. 깬 사람만 세면 생존 편향으로
      "어려운 판"과 "아무도 도달 못 한 판"이 똑같이 0 으로 보인다.
    ★LEFT JOIN 이어야 한다 — 아무도 못 깬 레벨이 결과에서 **사라지면** 그게 바로 벽인데
      안 보이게 된다(INNER JOIN 으로 쓰면 그렇게 된다).
    """
    return """
WITH s AS (
  SELECT {lv} lv, COUNT(DISTINCT user_pseudo_id) started
  FROM {t} WHERE {f} AND event_name = 'level_start' GROUP BY lv
), c AS (
  SELECT {lv} lv, COUNT(DISTINCT user_pseudo_id) cleared,
         AVG({att}) attempts, AVG({ovr}) over_moves, AVG({sec}) secs,
         AVG({h} + {u} + {w} + {r}) items
  FROM {t} WHERE {f} AND event_name = 'level_clear' GROUP BY lv
)
SELECT s.lv, s.started, IFNULL(c.cleared, 0) cleared,
       SAFE_DIVIDE(c.cleared, s.started) rate,
       ROUND(c.attempts, 2) attempts, ROUND(c.over_moves, 2) over_moves,
       ROUND(c.secs, 1) secs, ROUND(c.items, 2) items
FROM s LEFT JOIN c USING (lv)
WHERE s.lv IS NOT NULL
ORDER BY s.lv LIMIT 400
""".format(t=table, f=filt, lv=p_int("level"), att=p_int("attempts"),
           ovr=p_int("over"), sec=p_int("play_secs"), h=p_int("hints"),
           u=p_int("undos"), w=p_int("tows"), r=p_int("restarts"))


def stuck(table: str, filt: str) -> str:
    """③ 못 깬 판 — 벽에 막혀 떠난 유저는 level_clear 를 영영 안 쏜다."""
    return """
SELECT {lv} lv, COUNT(*) n, ROUND(AVG({att}), 2) attempts, ROUND(AVG({h}), 2) hints
FROM {t} WHERE {f} AND event_name = 'level_stuck'
GROUP BY lv HAVING lv IS NOT NULL ORDER BY n DESC LIMIT 25
""".format(t=table, f=filt, lv=p_int("level"), att=p_int("attempts"), h=p_int("hints"))


def fails(table: str, filt: str) -> str:
    """★수 제한 실패 — v46(2026-10-12)에 들어간 **이 게임의 첫 실패 상태**.

    왜 필요한가: 게임이 보내는 `level_fail` 을 대시보드가 **아예 조회하지 않고 있었다.**
    수 제한을 넣어 놓고 "얼마나 물리는지"를 못 보면 조일 근거가 없다.

    ★`level_stuck`(못 깬 판)과 **다르다.** stuck 은 떠난 사람이고, fail 은 수를 다 쓴
      사건이다. 한 사람이 같은 판에서 여러 번 fail 할 수 있다(수를 사서 이어 하면).
      그래서 건수(n)와 **사람 수(users)를 같이** 본다 — 건수만 보면 한 사람이
      열 번 막힌 판과 열 사람이 한 번씩 막힌 판이 똑같아 보인다.

    실패율의 분모는 **그 판을 시작한 사람**이다(level_start). 클리어한 사람으로 나누면
    "막혀서 못 깬 사람"이 분모에서 빠져 실패율이 **과소**로 나온다.

    ★★분모를 **제한이 있는 버전**으로 한정한다(started_lim). 수 제한은 v46 부터
      프로덕션에 나갔는데, 그 전 버전(v29·v36)에는 제한 자체가 없어서 **실패할 수가
      없다.** 그들을 분모에 넣으면 실패율이 통째로 희석된다 — 실제로 lv32 에서
      1/1 로 막힌 것이 1/44 = 2.3% 로 보였다(2026-10-13). 섞인 기간엔 이게 거짓말을 한다.
      ※rate(전체 분모)도 같이 남긴다 — 버전이 전부 넘어간 뒤엔 둘이 같아지고,
        그때까지는 **둘의 차이가 곧 '아직 안 넘어온 사람'의 크기**다.
    """
    return """
WITH f AS (
  SELECT {lv} lv, COUNT(*) n, COUNT(DISTINCT user_pseudo_id) users,
         ROUND(AVG({mv}), 1) moves, ROUND(AVG({lim}), 1) lim
  FROM {t} WHERE {f} AND event_name = 'level_fail' GROUP BY lv
), s AS (
  SELECT {lv} lv, COUNT(DISTINCT user_pseudo_id) started,
         COUNT(DISTINCT IF({vnum} >= {lvmin}, user_pseudo_id, NULL)) started_lim
  FROM {t} WHERE {f} AND event_name = 'level_start' GROUP BY lv
)
SELECT f.lv, f.users, f.n, s.started, s.started_lim,
       SAFE_DIVIDE(f.users, s.started) rate,
       SAFE_DIVIDE(f.users, s.started_lim) rate_lim, f.moves, f.lim
FROM f LEFT JOIN s USING (lv)
WHERE f.lv IS NOT NULL ORDER BY f.users DESC, f.lv LIMIT 30
""".format(t=table, f=filt, lv=p_int("level"), mv=p_int("moves"), lim=p_int("limit"),
           vnum=VER_NUM, lvmin=LIMIT_FIRST_VER)


def fail_summary(table: str, filt: str) -> str:
    """수 제한 한 줄 요약 — 전체에서 **몇 명이 한 번이라도 막혔나**, 그리고 어떻게 빠져나갔나.

    ★빠져나간 방법(booster_use kind='moves')을 같이 본다. 실패만 세면 "막혔다"까지만
      알고, 그게 **돈이 됐는지**(gem) 광고가 됐는지(ad) 그냥 떠났는지를 모른다.
    """
    return """
SELECT
  COUNT(DISTINCT IF(event_name='level_fail', user_pseudo_id, NULL)) fail_users,
  COUNTIF(event_name='level_fail') fails,
  COUNT(DISTINCT IF(event_name='level_start', user_pseudo_id, NULL)) players,
  COUNTIF(event_name='booster_use' AND {k}='moves' AND {s}='gem') buy_gem,
  COUNTIF(event_name='booster_use' AND {k}='moves' AND {s}='ad') buy_ad,
  SUM(IF(event_name='booster_use' AND {k}='moves' AND {s}='gem', {c}, 0)) gems_spent
FROM {t} WHERE {f}
""".format(t=table, f=filt, k=p_str("kind"), s=p_str("source"), c=p_int("cost"))


def album(table: str, filt: str) -> str:
    """④ 수집 메타 — 완성만 보면 '열어는 봤는데 안 맞춘' 유저가 안 보인다."""
    return """
SELECT
  COUNT(DISTINCT IF(event_name = 'album_open', user_pseudo_id, NULL)) opened,
  COUNT(DISTINCT IF(event_name = 'picture_done', user_pseudo_id, NULL)) finished,
  COUNTIF(event_name = 'picture_done') pictures
FROM {t} WHERE {f} AND event_name IN ('album_open','picture_done')
""".format(t=table, f=filt)


def shop_funnel(table: str, filt: str) -> str:
    return """
SELECT event_name step, COUNT(DISTINCT user_pseudo_id) users, COUNT(*) n
FROM {t} WHERE {f}
  AND event_name IN ('shop_open','purchase_start','purchase','purchase_fail')
GROUP BY step
""".format(t=table, f=filt)


#: 전면광고와 보상광고를 가르는 규칙. **한 곳에만** 둔다 — 화면과 쿼리가
#: 각자 가지면 갈라진다. 게임은 전면을 placement="inter" 로 쏘고(ads.gd),
#: 보상은 그 자리 이름(hint/heart/skip)으로 쏜다.
AD_KIND = "IF({pl} = 'inter', 'inter', 'reward')"


def ads(table: str, filt: str) -> str:
    """광고 — **전면과 보상을 나눠서** 본다(형 요청 2026-10-11).

    둘은 성격이 완전히 다르다:
      · 전면(inter) — 유저가 원해서 보는 게 아니다. 많이 띄울수록 돈이 되지만
        이탈도 같이 는다. 봐야 할 건 **노출 수**와 failed 비율이다.
      · 보상(reward) — 유저가 **자기 발로** 본다. 여기가 죽으면 무과금 유저의
        숨구멍이 막힌다. 봐야 할 건 자리(hint/heart/skip)별 **공급 실패율**이다.
        no_ad 가 많으면 인벤토리가 없는 것이고, 그건 우리 잘못이 아니라 시장이다.

    ★이름이 ad_watch 다. 예전엔 ad_reward 였는데 **Firebase 예약 이름**이라
    커스텀 전송이 조용히 버려졌다(2026-10-11 확인: 광고를 본 사람 8명인데 우리가
    보낸 ad_reward 는 0건). 과거 데이터를 같이 읽을 필요가 없다 — 애초에 하나도
    안 들어왔다. BigQuery 에 보이는 옛 ad_reward 는 AdMob 이 자동으로 쏜 것이다.
    """
    ★**버전을 같이** 본다(2026-10-17 추가). 광고 쪽을 고쳐 내보냈을 때, 새 빌드에서
    실제로 나아졌는지는 버전을 안 나누면 알 수가 없다 — 옛 빌드 유저의 실패가 계속
    쌓여서 전체 비율이 안 움직인다. 실측: v47(보상형 재시도·미리로드)을 올린 뒤
    no_ad 가 9→14 로 늘었는데, 그게 아직 안 고쳐진 v46 유저 때문인지 v47 이 여전히
    실패하는 건지 구분할 수 없었다. 그 질문이 곧 릴리스의 성패였다.
    """
    return """
SELECT {kind} kind, {pl} placement, {rs} result, app_info.version ver,
  COUNT(*) n, COUNT(DISTINCT user_pseudo_id) users
FROM {t} WHERE {f} AND event_name = 'ad_watch'
GROUP BY kind, placement, result, ver ORDER BY kind, n DESC LIMIT 60
""".format(t=table, f=filt, pl=p_str("placement"), rs=p_str("result"),
           kind=AD_KIND.format(pl=p_str("placement")))


def ad_summary(table: str, filt: str) -> str:
    """종류별 한 줄 요약 — 노출·사람·실패율.

    ★실패율의 분모는 **그 종류의 전체 노출**이다. 자리별로 나눠 평균을 내면
      적게 뜬 자리가 과대 대표된다.
    """
    return """
SELECT {kind} kind, COUNT(*) shows, COUNT(DISTINCT user_pseudo_id) users,
  COUNTIF({rs} IN ('failed','no_ad')) failed,
  ROUND(SAFE_DIVIDE(COUNTIF({rs} IN ('failed','no_ad')), COUNT(*)), 3) fail_rate
FROM {t} WHERE {f} AND event_name = 'ad_watch'
GROUP BY kind ORDER BY shows DESC
""".format(t=table, f=filt, rs=p_str("result"),
           kind=AD_KIND.format(pl=p_str("placement")))


def boosters(table: str, filt: str) -> str:
    """조달 경로 — 같은 힌트도 광고면 광고수익, 젬이면 결제수익, 발바닥이면 둘 다 아니다."""
    return """
SELECT {k} kind, {s} source, COUNT(*) n
FROM {t} WHERE {f} AND event_name = 'booster_use'
GROUP BY kind, source ORDER BY n DESC LIMIT 30
""".format(t=table, f=filt, k=p_str("kind"), s=p_str("source"))


def out_of_hearts(table: str, filt: str) -> str:
    return """
SELECT {lv} lv, COUNT(*) n FROM {t} WHERE {f} AND event_name = 'out_of_hearts'
GROUP BY lv HAVING lv IS NOT NULL ORDER BY n DESC LIMIT 20
""".format(t=table, f=filt, lv=p_int("level"))


def onboard(table: str, filt: str) -> str:
    """⑥ 온보딩 척추.

    ★계정당 평생 1회라 **창으로 자르면 코호트가 섞여** 퍼널이 역전된다
      (창 전에 1단계만 한 사람 + 창 안에서 5단계 한 사람). 그래서 기간 필터를 안 건다 —
      호출부가 filt 에 날짜 범위를 **넣지 않아야** 한다.
    """
    return """
SELECT {st} step, COUNT(DISTINCT user_pseudo_id) users
FROM {t} WHERE {f} AND event_name = 'onboard_step'
GROUP BY step HAVING step IS NOT NULL ORDER BY step
""".format(t=table, f=filt, st=p_int("step"))


# ══════════════════════════════════════════════════════════════════════
#  아래는 "인생 2막 수준"으로 올리면서 더한 것들 (2026-10-11)
# ══════════════════════════════════════════════════════════════════════

def retention(table: str, filt: str, max_day: int = 14) -> str:
    """코호트 리텐션 — 설치일 × Day n. **한 줄 = (코호트, n)** 로 납작하게 돌려준다.

    ★분모가 **그 날 설치한 사람**이다. 전체 유저로 나누면 어제 설치한 코호트가
      D7 을 채울 시간이 없어서 리텐션이 영영 우하향으로 보인다(가짜 하락).
    ★D0 은 세지 않는다 — 설치한 날 접속한 건 당연해서 늘 100%다. 칸만 먹는다.
    ★납작하게 주는 이유: 한 줄 안에서 ARRAY 를 만들려면 상관 서브쿼리가 필요한데
      그건 GROUP BY 와 안 맞는다(실제로 400 을 받았다). 모양 맞추기는 파이썬이 한다.
    """
    return """
WITH j AS (
  SELECT user_pseudo_id uid, MIN({day}) d0
  FROM {t} WHERE {f} GROUP BY uid
), a AS (
  SELECT DISTINCT user_pseudo_id uid, {day} d FROM {t} WHERE {f}
), x AS (
  SELECT j.d0 cohort,
    DATE_DIFF(PARSE_DATE('%Y%m%d', a.d), PARSE_DATE('%Y%m%d', j.d0), DAY) n,
    a.uid uid
  FROM j JOIN a USING (uid)
), sz AS (
  SELECT d0 cohort, COUNT(DISTINCT uid) size FROM j GROUP BY cohort
)
SELECT sz.cohort, sz.size, x.n, COUNT(DISTINCT x.uid) u
FROM sz LEFT JOIN x ON x.cohort = sz.cohort AND x.n BETWEEN 1 AND {m}
GROUP BY sz.cohort, sz.size, x.n
ORDER BY sz.cohort DESC, x.n
""".format(t=table, f=filt, day=DAY, m=max_day)


def versions(table: str, filt: str) -> str:
    """버전 비교 — 바꾼 게 **나아졌는지**를 보는 유일한 자리.

    ★같은 관측창으로 재야 한다. 새 버전은 코호트가 어려서 '아직 안 깬' 사람이 많고,
      그걸 모르고 비교하면 멀쩡한 버전을 회귀로 오인한다(인생 2막에서 실제로 겪었다).
      그래서 **설치 후 1시간 안의 행동만** 센다 — 모든 버전이 같은 1시간을 받는다.
    """
    return """
WITH u AS (
  SELECT user_pseudo_id uid, ANY_VALUE(app_info.version) ver,
    MAX(IF(event_name='level_clear' AND {ss} <= 3600, {lv}, NULL)) lv1h,
    COUNTIF(event_name='level_clear' AND {ss} <= 3600) clears1h,
    COUNTIF(event_name='onboard_step' AND {step}='lv1_clear') lv1,
    COUNTIF(event_name='app_remove') rm,
    MAX({ss}) secs
  FROM {t} WHERE {f} GROUP BY uid
)
SELECT ver, COUNT(*) users,
  ROUND(AVG(lv1h), 1) avg_lv_1h,
  ROUND(AVG(clears1h), 1) avg_clears_1h,
  ROUND(SAFE_DIVIDE(COUNTIF(lv1 > 0), COUNT(*)), 3) lv1_rate,
  ROUND(SAFE_DIVIDE(COUNTIF(rm > 0), COUNT(*)), 3) remove_rate,
  ROUND(AVG(secs) / 60, 1) avg_mins
FROM u GROUP BY ver ORDER BY ver DESC
""".format(t=table, f=filt, lv=INT("level"), ss=INT("secs_since_install"), step=STR("step"))


def pacing(table: str, filt: str) -> str:
    """진행 페이싱 — 구간마다 **몇 분** 걸리는가.

    ★클리어율만 보면 '느린 구간'이 안 보인다. 다 깨긴 깨는데 한 판에 10분씩 걸리면
      그게 이탈 지점이다. play_secs 의 중앙값을 쓴다(평균은 한 명의 방치가 뒤집는다).
    """
    return """
SELECT DIV({lv} - 1, 10) * 10 + 1 band,
  COUNT(DISTINCT user_pseudo_id) users, COUNT(*) clears,
  ROUND(APPROX_QUANTILES({sec}, 2)[OFFSET(1)], 0) median_secs,
  ROUND(AVG({mv} - {ms}), 1) over_moves
FROM {t} WHERE {f} AND event_name='level_clear' AND {lv} IS NOT NULL
GROUP BY band ORDER BY band
""".format(t=table, f=filt, lv=INT("level"), sec=INT("play_secs"),
           mv=INT("moves"), ms=INT("minsol"))


def risk(table: str, filt: str) -> str:
    """위험 신호 — 게임이 스스로 쏜 abuse.

    ★granted=true 가 진짜 문제다. '탐지는 했는데 **못 막은**' 건이고,
      유료 상품이 공짜로 나간 것이라 매출에 바로 닿는다.
    """
    return """
SELECT {r} reason, COUNTIF({g}='true') granted, COUNT(*) n,
  COUNT(DISTINCT user_pseudo_id) users
FROM {t} WHERE {f} AND event_name='abuse'
GROUP BY reason ORDER BY granted DESC, n DESC
""".format(t=table, f=filt, r=STR("reason"), g=STR("granted"))


def side_steps(table: str, filt: str) -> str:
    """곁가지 — 처음 만나는 기능들. 척추가 아니라 **발견율**로 본다."""
    return """
SELECT {s} step, COUNT(DISTINCT user_pseudo_id) users
FROM {t} WHERE {f} AND event_name='side_step' GROUP BY step ORDER BY users DESC
""".format(t=table, f=filt, s=STR("step"))


def countries(table: str, filt: str) -> str:
    """국가별 — 어디서 오고, 거기서 **깨는가**.

    ★한 사람이 **여러 나라로 잡힌다.** GA4 는 이벤트마다 IP 로 위치를 찍는데
      VPN 을 쓰면 그때그때 달라진다 — 실측(2026-10-11): 실유저 38명 중 8명이
      나라가 둘 이상이었고, 조합이 전부 'Iran + 어딘가'였다(Brazil·Chile·Germany).
      이란은 Play 가 공식 서비스하지 않아 VPN 이 사실상 기본이다.

    그래서 **사람당 나라를 하나로 정한다** — 이벤트가 가장 많은 나라(동률은 이름순).
      · 그냥 GROUP BY geo.country 로 세면 **같은 사람이 여러 나라에 중복**으로 들어가
        합계가 유저 수보다 커진다(실시간 뷰가 그랬다: 브라질 9).
      · ANY_VALUE 로 집으면 **실행할 때마다 값이 바뀐다**(인게임 뷰가 그랬다: 브라질 5).
      둘 다 틀렸고, 둘이 서로 달라서 형이 알아챘다.

    vpn 칸은 **숨기지 않고 보여 준다** — 나라가 둘 이상이던 사람 수다.
    """
    return """
WITH ec AS (
  SELECT user_pseudo_id uid, geo.country c, COUNT(*) n
  FROM {t} WHERE {f} GROUP BY uid, c
), pick AS (
  SELECT uid, ARRAY_AGG(c ORDER BY n DESC, c LIMIT 1)[OFFSET(0)] c,
    COUNT(*) > 1 vpn
  FROM ec GROUP BY uid
), u AS (
  SELECT user_pseudo_id uid,
    MAX(IF(event_name='level_clear', {lv}, 0)) lv,
    COUNTIF(event_name='purchase') buys
  FROM {t} WHERE {f} GROUP BY uid
)
SELECT pick.c country, COUNT(*) users, ROUND(AVG(u.lv), 1) avg_lv,
  COUNTIF(u.lv > 0) cleared_any, SUM(u.buys) buys, COUNTIF(pick.vpn) vpn
FROM pick JOIN u USING (uid)
GROUP BY country ORDER BY users DESC LIMIT 25
""".format(t=table, f=filt, lv=INT("level"))


# ══════════════════════════════════════════════════════════════════════
#  아이템 구입(주력 BM) — 2026-10-12
# ══════════════════════════════════════════════════════════════════════

#: 돈을 쓴 것만. free/ad/perk 는 **공짜로 받은 것**이라 매출 분석에 섞으면 안 된다.
PAID = "IN ('paw','gem')"


def item_by_source(table: str, filt: str) -> str:
    """아이템 × 지불수단 — 무엇을 무엇으로 사나.

    ★free/ad/perk 를 같이 세면 "치우기가 제일 많이 팔린다"가 된다. 실제로는
      공짜로 받은 것이다. 쓴 돈(cost)은 **paw/gem 일 때만** 의미가 있다.
    """
    return """
SELECT {k} kind, {s} source, COUNT(*) uses,
  COUNT(DISTINCT user_pseudo_id) users,
  SUM(IFNULL({c},0)) spent
FROM {t} WHERE {f} AND event_name='booster_use'
GROUP BY kind, source ORDER BY kind, uses DESC
""".format(t=table, f=filt, k=STR("kind"), s=STR("source"), c=INT("cost"))


def item_by_level(table: str, filt: str, band: int = 10) -> str:
    """구간별 — **어느 판에서 지갑이 열리나.**

    ★이게 이 탭의 핵심이다. 난이도 곡선과 겹쳐 보면 "막히는 구간 = 파는 구간"이
      맞는지 알 수 있다. 안 맞으면 상점이 엉뚱한 데 서 있는 것이다.
    """
    return """
SELECT DIV({lv} - 1, {b}) * {b} + 1 band,
  COUNT(DISTINCT user_pseudo_id) users,
  COUNTIF({s} {paid}) paid_uses,
  COUNTIF(NOT ({s} {paid})) free_uses,
  SUM(IF({s}='gem', IFNULL({c},0), 0)) gems,
  SUM(IF({s}='paw', IFNULL({c},0), 0)) paws
FROM {t} WHERE {f} AND event_name='booster_use' AND {lv} IS NOT NULL
GROUP BY band ORDER BY band
""".format(t=table, f=filt, b=band, lv=INT("level"), s=STR("source"),
           c=INT("cost"), paid=PAID)


def item_first_buy(table: str, filt: str) -> str:
    """**첫 유료 사용**이 몇 판째인가 — 지갑이 처음 열리는 지점.

    ★평균이 아니라 분포로 본다. 한 명이 100판에서 산 게 평균을 끌어올리면
      "다들 늦게 산다"로 읽힌다.
    """
    return """
WITH f AS (
  SELECT user_pseudo_id uid, MIN({lv}) lv
  FROM {t} WHERE {f} AND event_name='booster_use' AND {s} {paid} AND {lv} IS NOT NULL
  GROUP BY uid)
SELECT DIV(lv - 1, 10) * 10 + 1 band, COUNT(*) users
FROM f GROUP BY band ORDER BY band
""".format(t=table, f=filt, lv=INT("level"), s=STR("source"), paid=PAID)


def shop_by_level(table: str, filt: str) -> str:
    """상점을 **어느 판에서 여나** — 연 것과 산 것의 간격이 전환 손실이다."""
    return """
SELECT {k} kind, COUNT(*) opens, COUNT(DISTINCT user_pseudo_id) users
FROM {t} WHERE {f} AND event_name='shop_open'
GROUP BY kind ORDER BY opens DESC
""".format(t=table, f=filt, k=STR("kind"))


def wall_vs_sales(table: str, filt: str, band: int = 10) -> str:
    """막힘 × 구매 — **막히는 구간에서 실제로 사나.**

    ★상점이 제자리에 있는지 보는 유일한 방법이다. 막힘은 많은데 구매가 0 이면
      값이 비싸거나 상점이 안 보이는 것이고, 둘 다 적으면 난이도가 낮은 것이다.
    """
    return """
WITH s AS (
  SELECT DIV({lv} - 1, {b}) * {b} + 1 band, COUNT(*) stuck
  FROM {t} WHERE {f} AND event_name='level_stuck' GROUP BY band
), h AS (
  SELECT DIV({lv} - 1, {b}) * {b} + 1 band, COUNT(*) ooh
  FROM {t} WHERE {f} AND event_name='out_of_hearts' GROUP BY band
), p AS (
  SELECT DIV({lv} - 1, {b}) * {b} + 1 band, COUNT(*) buys,
    SUM(IF({src}='gem', IFNULL({c},0), 0)) gems
  FROM {t} WHERE {f} AND event_name='booster_use' AND {src} {paid} GROUP BY band
), c AS (
  SELECT DIV({lv} - 1, {b}) * {b} + 1 band, COUNT(DISTINCT user_pseudo_id) players
  FROM {t} WHERE {f} AND event_name='level_start' GROUP BY band
)
SELECT c.band, c.players, IFNULL(s.stuck,0) stuck, IFNULL(h.ooh,0) out_of_hearts,
  IFNULL(p.buys,0) buys, IFNULL(p.gems,0) gems
FROM c LEFT JOIN s USING (band) LEFT JOIN h USING (band) LEFT JOIN p USING (band)
ORDER BY c.band
""".format(t=table, f=filt, b=band, lv=INT("level"), src=STR("source"),
           c=INT("cost"), paid=PAID)
