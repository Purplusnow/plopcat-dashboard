#!/usr/bin/env python3
"""워크플로가 **제 일을 하는지** 본다.

왜 있나: realtime.yml 이 realtime.py 가 아니라 **ingame.py 를 돌리고 있었다**
(2026-10-11). 실행은 매번 success 였고, 커밋 메시지도 "실시간 갱신"이었다.
realtime.json 은 하루 종일 그대로였는데 아무도 몰랐다 — 조용한 거짓 성공이다.
원인은 워크플로를 다른 워크플로에서 복사해 만들면서 치환 하나가 안 먹은 것이다.

규칙 하나다: **이름이 X 인 워크플로는 tools/X.py 를 돌리고 data/X.json 을 커밋한다.**
"""
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
WF = ROOT / ".github" / "workflows"
# 이름 → (돌려야 하는 스크립트들, 커밋해야 하는 경로들)
#: 어느 워크플로에서 돌아도 되는 것 — 수집이 아니라 **검사**다.
#: ★이름으로 가른다. 목록으로 두면 검사를 하나 더 만들 때마다 여기도 고쳐야 하고,
#:   실제로 이 가드가 **자기 자신을** 남의 스크립트라고 잡았다.
def is_check(path: str) -> bool:
    return path.endswith("test.py") or path.endswith("test.js")
WANT = {
    "ingame": (["tools/ingame.py", "tools/users.py"], ["docs/data/ingame.json", "docs/data/users"]),
    "realtime": (["tools/realtime.py"], ["docs/data/realtime.json"]),
}


def main() -> int:
    bad = []
    for name, (scripts, paths) in WANT.items():
        f = WF / (name + ".yml")
        if not f.exists():
            bad.append("%s.yml 이 없다" % name)
            continue
        s = f.read_text(encoding="utf-8")
        runs = set(re.findall(r"python3 (tools/\w+\.py)", s))
        adds = set(re.findall(r"git add ([^\n]+)", s))
        adds = {p for line in adds for p in line.split()}
        for sc in scripts:
            if sc not in runs:
                bad.append("%s.yml 이 %s 를 안 돌린다 (돌리는 것: %s)" % (name, sc, sorted(runs) or "없음"))
        for extra in runs - set(scripts):
            if is_check(extra):
                continue
            bad.append("%s.yml 이 남의 스크립트 %s 를 돌린다" % (name, extra))
        for p in paths:
            if p not in adds:
                bad.append("%s.yml 이 %s 를 커밋 안 한다 (하는 것: %s)" % (name, p, sorted(adds) or "없음"))
        for extra in adds - set(paths):
            bad.append("%s.yml 이 남의 파일 %s 를 커밋한다" % (name, extra))
        # 스크립트가 실제로 있는지까지
        for sc in scripts:
            if not (ROOT / sc).exists():
                bad.append("%s 파일이 없다" % sc)

    if bad:
        for b in bad:
            print("  ❌ %s" % b)
        print("❌ wftest FAIL — %d건" % len(bad))
        return 1
    print("✅ wftest PASS — 워크플로 %d개가 제 스크립트를 돌리고 제 파일을 커밋한다" % len(WANT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
