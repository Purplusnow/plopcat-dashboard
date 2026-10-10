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
      const want = ["kpi", "levelTable", "retTable", "verTable", "rt-reach", "rev-table"];
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
