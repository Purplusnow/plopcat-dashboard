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


def human(cond: str, last_daily: str, exclude=()) -> str:
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


def ads(table: str, filt: str) -> str:
    """광고 결과 분포 = **공급 실패율**. no_ad 가 많으면 인벤토리가 없는 것이다."""
    return """
SELECT {pl} placement, {rs} result, COUNT(*) n
FROM {t} WHERE {f} AND event_name = 'ad_reward'
GROUP BY placement, result ORDER BY n DESC LIMIT 30
""".format(t=table, f=filt, pl=p_str("placement"), rs=p_str("result"))


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
    """국가별 — 어디서 오고, 거기서 **깨는가**."""
    return """
WITH u AS (
  SELECT user_pseudo_id uid, ANY_VALUE(geo.country) c,
    MAX(IF(event_name='level_clear', {lv}, 0)) lv,
    COUNTIF(event_name='purchase') buys
  FROM {t} WHERE {f} GROUP BY uid
)
SELECT c country, COUNT(*) users, ROUND(AVG(lv), 1) avg_lv,
  COUNTIF(lv > 0) cleared_any, SUM(buys) buys
FROM u GROUP BY c ORDER BY users DESC LIMIT 25
""".format(t=table, f=filt, lv=INT("level"))
