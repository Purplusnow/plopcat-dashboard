#!/usr/bin/env python3
"""퍼널 정의 — **실시간·가입자·인게임 세 화면이 이걸 같이 쓴다.**

★정의를 각자 들고 있으면 세 화면이 서로 다른 퍼널을 말하게 되고, 그 순간
  비교가 불가능해진다(인생 2막에서 realtime↔users 가 같은 이유로 공유한다).

척추는 게임이 정한다 — scripts/autoload/analytics.gd 의 ONB_STEPS 가 단일 출처다.
여기 순서가 그쪽과 어긋나면 화면이 조용히 거짓말한다. tools/selftest.py 가 대조한다.
"""

#: 온보딩 척추. (키, 사람이 읽는 이름) — analytics.gd ONB_STEPS 와 **같은 순서**
ONB_STEPS = [
    ("game_open",     "게임 진입"),
    ("first_move",    "첫 수"),
    ("lv1_clear",     "1판 클리어"),
    ("lv3_clear",     "3판"),
    ("album_first",   "미술관 열기"),
    ("first_piece",   "첫 조각"),
    ("lv10_clear",    "10판"),
    ("first_picture", "첫 그림 완성"),
    ("lv20_clear",    "20판"),
    ("lv50_clear",    "50판"),
]

#: 곁가지 — 평생 1회지만 척추가 아니다(퍼널 분모에 넣으면 왜곡된다)
SIDE_STEPS = [
    ("tut_hand",      "튜토리얼 손"),
    ("first_hint",    "힌트 처음"),
    ("first_tow",     "치우기 처음"),
    ("first_restart", "다시하기 처음"),
    ("first_ad",      "광고 처음"),
    ("first_heart",   "하트 충전 처음"),
    ("first_skip",    "건너뛰기 처음"),
    ("heart_inf",     "하트무한 안내"),
    ("lang_change",   "언어 바꿈"),
]

STEP_KEYS = [k for k, _ in ONB_STEPS]
STEP_LABELS = dict(ONB_STEPS)
