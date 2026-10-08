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


def kpi(table: str, filt: str, d1: str, d7: str) -> str:
    return """
SELECT
  COUNT(DISTINCT IF(_TABLE_SUFFIX = '{d1}', user_pseudo_id, NULL)) dau,
  COUNT(DISTINCT IF(_TABLE_SUFFIX >= '{d7}', user_pseudo_id, NULL)) wau,
  COUNT(DISTINCT user_pseudo_id) users,
  COUNT(DISTINCT IF(event_name = 'first_open', user_pseudo_id, NULL)) new_users
FROM {t} WHERE {f}
""".format(t=table, f=filt, d1=d1, d7=d7)


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
