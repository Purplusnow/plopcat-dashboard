// 페이지가 **실제로 그려지는지** 본다 — 브라우저 없이.
//
// 왜 있나: Pages 가 200 을 준다고 화면이 그려지는 건 아니다. app.js 가 한 줄에서
// 터지면 흰 화면이 뜨고, 배포는 "성공"으로 남는다. 조용한 거짓 성공이다.
// 그래서 최소 DOM 을 만들어 app.js 를 **진짜 데이터로** 끝까지 돌려 본다.
//
//   node tools/pagetest.js
const fs = require("fs"), path = require("path"), vm = require("vm");
const DOCS = path.join(__dirname, "..", "docs");
const html = fs.readFileSync(path.join(DOCS, "index.html"), "utf8");

const ids = [...html.matchAll(/id="([\w-]+)"/g)].map(m => m[1]);
const views = [...html.matchAll(/data-view="([\w-]+)"/g)].map(m => m[1]);
let fails = [];

function el(id) {
  return {
    id, innerHTML: "", textContent: "", outerHTML: "", _cls: new Set(),
    dataset: {}, classList: {
      add: c => this, remove: c => this, toggle: () => {},
    },
    querySelectorAll: () => [], addEventListener: () => {},
  };
}
const store = {};
ids.forEach(i => (store[i] = el(i)));

global.document = {
  getElementById: id => store[id] || (store[id] = el(id)),
  querySelectorAll: sel => {
    if (sel === ".view" || sel === ".vtab")
      return views.map(v => ({ dataset: { view: v }, classList: { toggle: () => {} },
                               addEventListener: () => {} }));
    return [];
  },
};
global.location = { hash: "" };
// MODE=empty 면 **모든 데이터를 비워** 준다.
//
// ★이게 더 중요한 검사다. 지금 퐁당냥은 유저가 몇 명뿐이고 매출은 0이라,
//   대부분의 섹션이 빈 배열로 온다. 빈 데이터에서 터지면 평소 화면이 통째로
//   흰 종이가 된다 — 그런데 배포는 "성공"으로 남는다.
//   수집기가 하루 실패해도 같은 일이 난다.
const EMPTY = process.env.MODE === "empty";
global.fetch = (u) => {
  const rel = u.split("?")[0];
  const f = path.join(DOCS, rel);
  if (EMPTY) {
    if (rel.endsWith("config.json") && fs.existsSync(f))
      return Promise.resolve({ ok: true, json: () => JSON.parse(fs.readFileSync(f, "utf8")) });
    return Promise.resolve({ ok: false, json: () => null });   // 아예 못 받은 상태
  }
  if (!fs.existsSync(f)) return Promise.resolve({ ok: false, json: () => null });
  return Promise.resolve({ ok: true, json: () => JSON.parse(fs.readFileSync(f, "utf8")) });
};

process.on("unhandledRejection", e => { fails.push("비동기 예외: " + e.message); });

try {
  // ★new Function 으로 감싸면 안 된다 — 그건 함수 스코프라 `function show(){}` 가
  //   전역에 안 올라간다. 브라우저에서 classic script 는 전역에 올린다.
  //   하네스가 실제와 다른 스코프를 쓰면 "전역에 없다"는 가짜 실패가 난다(실제로 났다).
  vm.runInThisContext(fs.readFileSync(path.join(DOCS, "app.js"), "utf8"));
} catch (e) {
  fails.push("app.js 가 즉시 터졌다: " + e.message);
}

setTimeout(() => {
  // 뷰마다 한 번씩 열어 본다 — 지연 로딩이라 탭을 눌러야 코드가 돈다
  const show = global.show;
  if (typeof show === "function") {
    for (const v of [...new Set(views)]) {
      try { show(v); } catch (e) { fails.push(`뷰 '${v}' 가 터졌다: ${e.message}`); }
    }
  } else {
    fails.push("show() 가 전역에 없다 — 뷰 전환을 확인할 수 없다");
  }
  setTimeout(() => {
    // 내용이 **실제로 채워졌는지**. 빈 문자열이면 그린 게 없다는 뜻이다.
    // 빈 데이터 모드에서는 "안 그려짐"이 정상이다 — **터지지만 않으면** 통과.
    if (!EMPTY) {
      // ★실시간 목록에는 **사람만** 있어야 한다. 봇·내 기기가 한 줄이라도 섞이면
      //   형이 그걸 실유저로 읽는다(실제로 '한국 유저 10명'이 전부 내 기기였다).
      try {
        const rt = JSON.parse(fs.readFileSync(path.join(DOCS, "data/realtime.json"), "utf8"));
        const bad = (rt.users || []).filter(u => u.kind !== "human");
        if (bad.length) fails.push(`실시간 목록에 사람 아닌 줄 ${bad.length}개 (${bad.map(u => u.kind).join(",")})`);
        if (!rt.kinds) fails.push("걸러낸 수(kinds)가 없다 — 조용히 지우면 안 된다");
      } catch (e) { fails.push("realtime.json 을 못 읽는다: " + e.message); }
      // ★리텐션 칸이 **세 상태**로 그려지는지 — 그려진 결과로 본다.
      //   소스를 글자로 뒤지면 **주석에 걸려 통과한다**(실제로 그랬다).
      //   D1 은 설치 다음 날이 다 가야 확정인데 오늘이 그 날이면 차는 중이다.
      //   확정값처럼 그리면 옛 코호트의 완결된 수와 나란히 놓여 "떨어졌다"로 읽힌다.
      const rc = (store["retChart"] || {}).innerHTML || "";
      try {
        const ig = JSON.parse(fs.readFileSync(path.join(DOCS, "data/ingame.json"), "utf8"));
        const dn = s => Date.UTC(+s.slice(0, 4), +s.slice(4, 6) - 1, +s.slice(6, 8)) / 864e5;
        const td = dn(ig.updated.slice(0, 10).replace(/-/g, ""));
        const ret = ig.retention || [];
        // 오늘이 'D n 당일'인 코호트가 하나라도 있으면 그 칸은 미완성 표시여야 한다
        const anyLive = ret.some(r => td - dn(r.cohort) >= 1);
        const anyNA = ret.some(r => td - dn(r.cohort) < 14);
        if (anyLive && !/class="num fcell live"/.test(rc))
          fails.push("리텐션에 '아직 차는 중' 칸 표시가 없다 — 미완성 값이 확정으로 보인다");
        if (anyLive && !/%\+/.test(rc))
          fails.push("리텐션 미완성 칸에 + 가 없다 — 최소값임을 알 수 없다");
        if (anyNA && !/coh-na/.test(rc))
          fails.push("리텐션에 '아직 안 온 날' 칸이 없다 — 0% 로 그리면 급락으로 보인다");
      } catch (e) { fails.push("리텐션 검사 실패: " + e.message); }
      // ★DAU 선차트도 **그려진 결과**로 본다. 형 요청(2026-10-17)이 "선차트 + Y축 숫자"라,
      //   그 둘이 실제로 출력에 들어갔는지 확인한다. 소스를 뒤지면 주석에 걸려 통과한다.
      const dc = (store["dauChart"] || {}).innerHTML || "";
      try {
        const ig = JSON.parse(fs.readFileSync(path.join(DOCS, "data/ingame.json"), "utf8"));
        const da = ig.daily_active || [];
        if (da.length) {
          if (!/<svg/.test(dc)) fails.push("DAU 차트가 SVG 가 아니다 — 선차트로 안 그려졌다");
          if (!/<polyline/.test(dc)) fails.push("DAU 차트에 선(polyline)이 없다");
          if (!/<text[^>]*font-size="11"[^>]*>\d/.test(dc))
            fails.push("DAU 차트에 **Y축 눈금 숫자**가 없다");
          // 꼭대기 눈금이 최댓값보다 **작으면** 선이 차트를 뚫고 나간다
          const maxV = Math.max(...da.map(r => Math.max(r.dau || 0, r.new_users || 0)));
          const ticks = [...dc.matchAll(/text-anchor="end"[^>]*>([\d,]+)</g)]
            .map(m => +m[1].replace(/,/g, ""));
          if (ticks.length < 2) fails.push("Y축 눈금이 2개 미만이다");
          else if (Math.max(...ticks) < maxV)
            fails.push(`Y축 꼭대기(${Math.max(...ticks)})가 최댓값(${maxV})보다 작다 — 선이 잘린다`);
        }
      } catch (e) { fails.push("DAU 차트 검사 실패: " + e.message); }

      const want = ["kpi", "levelTable", "retChart", "verTable", "rt-reach", "rev-table",
                    "dauChart", "dauTable"];
      for (const id of want) {
        const e = store[id];
        if (!e || (!e.innerHTML && !e.textContent))
          fails.push(`#${id} 가 비어 있다 — 그 섹션이 안 그려졌다`);
      }
    }
    if (fails.length) {
      fails.forEach(f => console.log("  ❌ " + f));
      console.log("❌ pagetest FAIL — %d건", fails.length);
      process.exit(1);
    }
    console.log("✅ pagetest PASS (%s) — 뷰 %d개가 끝까지 돈다",
                EMPTY ? "데이터 없음" : "실데이터", [...new Set(views)].length);
  }, 300);
}, 300);
