#!/usr/bin/env python3
"""개발자 본인 기기 찾기 — BigQuery 의 user_pseudo_id 중 **사람이 아닌 것**을 가려낸다.

왜 필요한가: 출시 전에는 모수의 전부가 개발자 본인이다. 그걸 안 빼면
클리어율·퍼널·리텐션이 통째로 거짓이 된다. 그런데 어느 id 가 내 기기인지는
화면 어디에도 안 적혀 있다 — **행동으로 추정**하는 수밖에 없다.

가려내는 단서(강한 순):
  1. 디버그 빌드(app_info.version LIKE 'dbg%') — 블루스택. 이건 추정이 아니라 확정이다.
  2. 비정상 진행 속도 — 하루에 수십~수백 판. 오토파일럿이 아니면 안 나온다.
  3. 결제가 있는데 매출이 0 — 라이선스 테스터(테스트 결제는 과금되지 않는다)
  4. 기기 모델이 내가 쓰는 것과 같음

★출력은 **후보 목록**이지 정답이 아니다. 눈으로 보고 EXCLUDE_USERS 에 넣는다.
  자동으로 빼지 않는 이유: 진짜 헤비 유저를 봇으로 오인해 지우면 그 사실을
  알아챌 방법이 없다(지워진 건 안 보인다).

사용:
    export GOOGLE_APPLICATION_CREDENTIALS=/path/sa.json
    python3 tools/whoami.py
"""
import os
from datetime import date, timedelta

from google.cloud import bigquery

PROJECT = os.environ.get("BQ_PROJECT") or "plopcat-6d336"
LOCATION = os.environ.get("BQ_LOCATION") or "asia-northeast3"
DATASET = os.environ.get("BQ_DATASET") or ""

client = bigquery.Client(project=PROJECT, location=LOCATION)

if not DATASET:
    cands = [d.dataset_id for d in client.list_datasets(PROJECT)
             if d.dataset_id.startswith("analytics_")]
    if not cands:
        raise SystemExit("✗ analytics_* 데이터셋이 없다 — GA4 BigQuery 내보내기 확인")
    DATASET = cands[0]

TABLE = "`%s.%s.events_*`" % (PROJECT, DATASET)
WIN = (date.today() - timedelta(days=60)).strftime("%Y%m%d")

SQL = """
SELECT
  user_pseudo_id,
  ANY_VALUE(device.mobile_model_name) model,
  ANY_VALUE(geo.country) country,
  STRING_AGG(DISTINCT app_info.version ORDER BY app_info.version LIMIT 4) versions,
  MIN(_TABLE_SUFFIX) first_day,
  MAX(_TABLE_SUFFIX) last_day,
  COUNT(DISTINCT _TABLE_SUFFIX) days,
  COUNTIF(event_name = 'level_clear') clears,
  COUNTIF(event_name = 'purchase') purchases,
  MAX((SELECT value.int_value FROM UNNEST(event_params) WHERE key = 'level')) max_level
FROM {t}
WHERE _TABLE_SUFFIX >= '{w}' AND _TABLE_SUFFIX NOT LIKE 'intraday%'
GROUP BY user_pseudo_id
ORDER BY clears DESC
LIMIT 50
""".format(t=TABLE, w=WIN)


def main() -> None:
    rows = [dict(r) for r in client.query(SQL).result()]
    if not rows:
        print("데이터가 없다 — GA4 내보내기가 켜진 뒤 하루는 지나야 테이블이 생긴다")
        return
    print("%-34s %-14s %-4s %-6s %6s %6s %7s %5s  %s"
          % ("user_pseudo_id", "기기", "국가", "일수", "클리어", "최고판", "결제", "판/일", "의심"))
    for r in rows:
        days = max(1, int(r["days"] or 1))
        per_day = (r["clears"] or 0) / days
        why = []
        if (r["versions"] or "").startswith("dbg") or "dbg" in (r["versions"] or ""):
            why.append("디버그빌드")              # 확정
        if per_day >= 30:
            why.append("판/일 과다")
        if not (r["country"] or ""):
            why.append("지역없음(봇)")
        print("%-34s %-14s %-4s %6s %6s %6s %7s %5.1f  %s"
              % (r["user_pseudo_id"], (r["model"] or "?")[:14], (r["country"] or "-")[:4],
                 days, r["clears"], r["max_level"], r["purchases"], per_day,
                 " ".join(why) if why else ""))
    print("\n★위에서 본인 기기를 골라 Actions 시크릿/환경변수 EXCLUDE_USERS 에 쉼표로 넣는다.")
    print("  디버그빌드·지역없음은 ingame.py 가 **이미 자동으로** 뺀다 — 여기엔 참고로만 보인다.")


if __name__ == "__main__":
    main()
