// 정적 페이지 — BigQuery 는 브라우저에서 못 치므로 Actions 가 떨군 JSON 한 장만 읽는다.
const $ = (id) => document.getElementById(id);
const n = (v) => v == null ? "–" : Number(v).toLocaleString();
const pct = (v) => v == null ? "–" : (v * 100).toFixed(1) + "%";

// 값이 없을 때 **빈 표를 그리지 않는다** — "0건"과 "아직 안 들어옴"은 다른 상태다.
function table(el, rows, cols) {
  // ★element 를 **바꿔치지 않는다.** 예전엔 outerHTML 로 통째로 갈았는데, 그러면
  //   다시 그릴 때 $(id) 가 <table> 이 아닌 <div> 를 돌려줘 두 번째 렌더가 깨진다
  //   (가입자 뷰에서 날짜를 바꾸면 바로 터진다).
  if (!rows || !rows.length) {
    el.classList.add("empty"); el.innerHTML = "<tbody><tr><td>데이터 없음</td></tr></tbody>"; return;
  }
  el.classList.remove("empty");
  el.innerHTML =
    "<thead><tr>" + cols.map(c => `<th>${c[0]}</th>`).join("") + "</tr></thead><tbody>" +
    rows.map(r => "<tr>" + cols.map(c => `<td>${c[1](r)}</td>`).join("") + "</tr>").join("") +
    "</tbody>";
}

fetch("data/ingame.json?" + Date.now()).then(r => r.json()).then(d => {
  const ex = d.excluded_users ? ` · 제외한 기기 ${d.excluded_users}개` : "";
  $("meta").textContent = `${d.updated || "–"} · 최근 ${d.window_days || "–"}일`
    + (d.last_table ? ` · 마지막 데이터 ${d.last_table}` : "") + ex;
  $("foot").textContent = `${d.project || ""} / ${d.dataset || ""}`
    + " — 지표 정의의 단일 출처는 게임 레포의 docs/ANALYTICS.md";

  const k = (d.kpi && d.kpi[0]) || {};
  $("kpi").innerHTML = [
    ["DAU", n(k.dau)], ["WAU", n(k.wau)],
    ["신규(기간)", n(k.new_users)], ["누적(기간)", n(k.users)],
  ].map(([a, b]) => `<div class="box"><div class="k">${a}</div><div class="v">${b}</div></div>`).join("");

  // ── ⑦~⑩ 더한 섹션들 ──────────────────────────────────────────────
  // 리텐션은 **가로가 Day n** 인 표다. 코호트마다 길이가 달라(어린 코호트는 짧다)
  // 열을 고정하고 빈 칸은 비워 둔다 — 없는 걸 0%로 그리면 "이탈했다"로 읽힌다.
  const ret = d.retention || [];
  const maxN = ret.reduce((a, r) => Math.max(a, ...(r.d || []).map(x => x.n)), 0);
  table($("retTable"), ret, [
    ["설치일", r => r.cohort], ["명", r => n(r.size)],
    ...Array.from({ length: maxN }, (_, i) => ["D" + (i + 1), r => {
      const x = (r.d || []).find(y => y.n === i + 1);
      return x ? `${pct(x.rate)}<span class="dim"> ${x.u}</span>` : "";
    }]),
  ]);
  table($("verTable"), d.versions || [], [
    ["버전", r => r.ver], ["명", r => n(r.users)],
    ["1시간 내 최고판", r => r.avg_lv_1h ?? "–"],
    ["1시간 내 클리어", r => r.avg_clears_1h ?? "–"],
    ["1판 돌파율", r => pct(r.lv1_rate)],
    ["삭제율", r => pct(r.remove_rate)],
    ["체류(분)", r => r.avg_mins ?? "–"],
  ]);
  table($("paceTable"), d.pacing || [], [
    ["구간", r => `${r.band}~${r.band + 9}`], ["명", r => n(r.users)],
    ["클리어", r => n(r.clears)], ["중앙 초", r => n(r.median_secs)],
    ["초과 수", r => r.over_moves ?? "–"],
  ]);
  table($("ctryTable"), d.countries || [], [
    ["국가", r => r.country || "–"], ["명", r => n(r.users)],
    ["평균 레벨", r => r.avg_lv ?? "–"], ["1판이라도", r => n(r.cleared_any)],
    ["결제", r => n(r.buys)],
  ]);
  table($("riskTable"), d.risk || [], [
    ["사유", r => r.reason || "–"],
    ["지급됨", r => r.granted ? `<b class="bad-t">${n(r.granted)}</b>` : "0"],
    ["건", r => n(r.n)], ["사람", r => n(r.users)],
  ]);
  table($("sideTable"), d.side_steps || [], [
    ["기능", r => r.step || "–"], ["사람", r => n(r.users)],
  ]);

  // ★뺀 것들. 지금은 모수의 대부분이 사람이 아니다 — 그걸 숨기면 "유저가 없다"가
  //   버그로 읽히고, 반대로 안 빼면 "유저가 많다"는 거짓이 된다. 둘 다 보여 준다.
  const fl = d.filtered || [];
  const flSum = fl.reduce((a, r) => a + (r.users || 0), 0);
  $("filtered").innerHTML = fl.length
    ? fl.map(r => `<span class="chip"><b>${n(r.users)}</b> ${r.reason}</span>`).join("")
      + `<span class="chip tot">합계 <b>${n(flSum)}</b></span>`
    : "<span class='chip'>뺀 것 없음</span>";

  // ① 클리어율 — 막대 색으로 벽을 눈에 띄게 한다(80%↓ 주의, 50%↓ 위험)
  const lv = d.levels || [];
  $("levelChart").innerHTML = lv.map(r => {
    const v = r.rate == null ? 0 : r.rate;
    const cls = v < .5 ? "bad" : v < .8 ? "warn" : "";
    return `<i class="${cls}" style="height:${Math.max(1, v * 100)}%" title="L${r.lv} ${pct(v)} (${r.cleared}/${r.started})"></i>`;
  }).join("");
  table($("levelTable"), lv, [
    ["레벨", r => "L" + r.lv], ["시작", r => n(r.started)], ["클리어", r => n(r.cleared)],
    ["클리어율", r => pct(r.rate)], ["시도", r => r.attempts ?? "–"],
    ["초과 수", r => r.over_moves ?? "–"], ["아이템", r => r.items ?? "–"],
    ["초", r => r.secs ?? "–"],
  ]);

  table($("stuckTable"), d.stuck, [
    ["레벨", r => "L" + r.lv], ["건수", r => n(r.n)],
    ["평균 시도", r => r.attempts ?? "–"], ["평균 힌트", r => r.hints ?? "–"]]);

  table($("heartTable"), d.out_of_hearts, [["레벨", r => "L" + r.lv], ["건수", r => n(r.n)]]);

  const al = (d.album && d.album[0]) || {};
  const conv = al.opened ? al.finished / al.opened : null;
  $("album").innerHTML = [
    ["조립 진입(명)", n(al.opened)], ["그림 완성(명)", n(al.finished)],
    ["완성 전환", pct(conv)], ["완성 그림(건)", n(al.pictures)],
  ].map(([a, b]) => `<div class="box"><div class="k">${a}</div><div class="v">${b}</div></div>`).join("");

  // 상점 퍼널은 **정해진 순서**로 보여야 읽힌다(알파벳순이면 의미가 사라진다)
  const order = ["shop_open", "purchase_start", "purchase", "purchase_fail"];
  const label = {shop_open: "상점 열기", purchase_start: "결제 시작",
                 purchase: "결제 완료", purchase_fail: "결제 실패"};
  const fun = order.map(s => (d.shop_funnel || []).find(r => r.step === s)).filter(Boolean);
  table($("shopTable"), fun, [
    ["단계", r => label[r.step] || r.step], ["인원", r => n(r.users)], ["건수", r => n(r.n)]]);

  table($("adTable"), d.ads, [
    ["자리", r => r.placement || "–"], ["결과", r => r.result || "–"], ["건수", r => n(r.n)]]);
  table($("boostTable"), d.boosters, [
    ["아이템", r => r.kind || "–"], ["조달", r => r.source || "–"], ["건수", r => n(r.n)]]);
  table($("onbTable"), d.onboard, [
    ["단계", r => r.step], ["인원", r => n(r.users)]]);
}).catch(e => { $("meta").textContent = "불러오기 실패: " + e; });

// ══════════════════════════════════════════════════════════════════════
//  뷰 전환 + 매출·실시간·광고·가입자  (2026-10-11, 인생 2막 보드 수준으로)
// ══════════════════════════════════════════════════════════════════════

// ★뷰는 **지연 로딩**한다. 다섯 장의 JSON 을 첫 화면에서 다 받으면 느리고,
//   대부분은 한두 뷰만 본다. 탭을 처음 누를 때 그 뷰의 데이터만 받는다.
const loaded = {};
function show(v) {
  document.querySelectorAll(".view").forEach(e =>
    e.classList.toggle("off", e.dataset.view !== v));
  document.querySelectorAll(".vtab").forEach(e =>
    e.classList.toggle("is-on", e.dataset.view === v));
  if (!loaded[v] && VIEW[v]) { loaded[v] = 1; VIEW[v](); }
  try { location.hash = v; } catch (e) {}
}
document.querySelectorAll(".vtab").forEach(b =>
  b.addEventListener("click", () => show(b.dataset.view)));

const won = n => (n == null ? "–" : "₩" + Math.round(n).toLocaleString());
const get = u => fetch(u + "?" + Date.now()).then(r => r.ok ? r.json() : null).catch(() => null);
function kpiBox(el, pairs) {
  $(el).innerHTML = pairs.map(([a, b, c]) =>
    `<div class="box"><div class="k">${a}</div><div class="v">${b}</div>` +
    (c ? `<div class="s">${c}</div>` : "") + "</div>").join("");
}

const VIEW = {};

// ── 매출 ──────────────────────────────────────────────────────────────
// ★계산 규칙은 인생 2막 보드와 같다: 표시가 ÷ (1+부가세) × (1−스토어수수료).
//   광고매출은 이미 실수령액이라 수수료를 떼지 않는다(fee_applies_to 가 정한다).
VIEW.revenue = async () => {
  const [cfg, d] = await Promise.all([get("data/config.json"), get("data/daily.json")]);
  if (!cfg || !d) return;
  const days = d.daily || [];
  const fx = v => {                       // 숫자면 원화, {USD:8.97} 이면 폴백 환율로
    if (v == null) return 0;
    if (typeof v === "number") return v;
    const [c, x] = Object.entries(v)[0];
    return x * (cfg.fx_fallback[c] || 0);
  };
  const net = (key, v) => {
    const raw = fx(v);
    if (!(cfg.fee_applies_to || []).includes(key)) return raw;   // 광고매출 = 실수령
    const tax = cfg.tax_rates._default || 0;                     // 원화 표시가 기준
    return raw / (1 + tax) * (1 - (cfg.store_fee || 0));
  };
  let ad = 0, iap = 0, spend = 0;
  const rows = days.map(r => {
    const a = net("admob", r.admob), i = net("iap", r.iap), s = fx(r.ads);
    ad += a; iap += i; spend += s;
    return { date: r.date, admob: a, iap: i, ads: s, net: a + i, cum: ad + iap - spend };
  });
  const rev = ad + iap;
  kpiBox("rev-kpi", [
    ["누적 매출(실수령)", won(rev)],
    ["누적 마케팅비", won(spend)],
    ["순이익", won(rev - spend)],
    ["ROAS", spend ? (rev / spend).toFixed(2) + "×" : "–", spend ? "" : "마케팅비 0"],
  ]);
  table($("rev-table"), [
    { k: "광고매출(AdMob)", v: ad }, { k: "인앱매출", v: iap },
    { k: "마케팅비", v: -spend }, { k: "합계", v: rev - spend },
  ], [["항목", r => r.k], ["원화", r => won(r.v)]]);
  table($("rev-ledger"), rows.slice().reverse(), [
    ["날짜", r => r.date], ["광고", r => won(r.admob)], ["인앱", r => won(r.iap)],
    ["마케팅비", r => won(r.ads)], ["그날 순", r => won(r.net - r.ads)],
    ["누적", r => won(r.cum)],
  ]);
  $("rev-chart").innerHTML = rows.length
    ? rows.map(r => {
        const h = Math.max(1, Math.abs(r.cum) / Math.max(1, Math.max(...rows.map(x => Math.abs(x.cum)))) * 100);
        return `<i class="${r.cum < 0 ? "bad" : ""}" style="height:${h}%" title="${r.date} ${won(r.cum)}"></i>`;
      }).join("")
    : "<p class='why'>아직 기록이 없습니다 — data/daily.json 에 하루 한 줄씩 쌓입니다.</p>";
};

// ── 실시간 ────────────────────────────────────────────────────────────
VIEW.realtime = async () => {
  const d = await get("data/realtime.json");
  if (!d) { $("rt-kpi").innerHTML = "<p class='why'>실시간 데이터가 아직 없습니다.</p>"; return; }
  kpiBox("rt-kpi", [
    ["오늘 사람", n(d.humans)], ["봇·스캔", n(d.bots)],
    ["전체 줄", n((d.users || []).length)], ["기준일", d.day || "–"],
  ]);
  const top = (d.reach && d.reach[0] && d.reach[0].users) || 0;
  table($("rt-reach"), d.reach || [], [
    ["단계", r => r.label], ["사람", r => n(r.users)],
    ["1단계 대비", r => top ? pct(r.users / top) : "–"],
  ]);
  // ★척추 도달은 비트로 접혀 온다 — 여기서 푼다(users.py/realtime.py 와 같은 순서)
  const names = (d.steps || []).map(s => s.label);
  const far = r => {
    for (let i = names.length - 1; i >= 0; i--) if (r.reached & (1 << i)) return names[i];
    return "–";
  };
  const TAG = { human: "사람", bot: "봇·스캔", dbg: "디버그", me: "내 기기" };
  table($("rt-users"), d.users || [], [
    ["", r => `<span class="tag t-${r.kind}">${TAG[r.kind] || r.kind}</span>`],
    ["시각", r => r.t0], ["분", r => r.mins],
    ["기기", r => r.model || "–"], ["지역", r => r.country || "–"],
    ["버전", r => r.ver || "–"],
    ["도달", r => far(r)], ["깬 판", r => n(r.clears)],
    ["막힘", r => n(r.stuck)], ["광고", r => n(r.ads)], ["상점", r => n(r.shops)],
    ["결제", r => n(r.buys)], ["삭제", r => r.removed ? "예" : ""],
  ]);
  table($("rt-ver"), d.versions || [], [["버전", r => r.ver], ["사람", r => n(r.users)], ["설치", r => n(r.installs)]]);
  table($("rt-ctry"), d.countries || [], [["국가", r => r.country], ["사람", r => n(r.users)]]);
  table($("rt-fail"), d.purchase_fail || [], [["사유", r => r.reason || "–"], ["건", r => n(r.n)], ["사람", r => n(r.users)]]);
  table($("rt-abuse"), d.abuse || [], [["사유", r => r.reason || "–"], ["지급됨", r => n(r.granted)], ["건", r => n(r.n)]]);
};

// ── 광고 ──────────────────────────────────────────────────────────────
VIEW.ads = async () => {
  const [ig, cfg, dy] = await Promise.all(
    [get("data/ingame.json"), get("data/config.json"), get("data/daily.json")]);
  const ads = (ig && ig.ads) || [];
  const shown = ads.reduce((a, r) => a + (r.n || r.events || 0), 0);
  kpiBox("ad-kpi", [
    ["리워드 광고 결과", n(ads.length)],
    ["총 건수", n(shown)],
    ["AdMob 수집", (dy && dy.synced && dy.synced.admob) ? "켜짐" : "아직 없음"],
  ]);
  table($("ad-reward"), ads, Object.keys(ads[0] || {}).map(k => [k, r => fmt(r[k])]));
  const rows = ((dy && dy.daily) || []).filter(r => r.admob);
  $("ad-note").textContent = rows.length
    ? "AdMob API 에서 받은 일별 광고매출이다."
    : "아직 비어 있다 — AdMob API 자격증명(퐁당냥 전용)을 넣으면 여기가 찬다. README 참고.";
  table($("ad-admob"), rows.slice().reverse(),
    [["날짜", r => r.date], ["광고매출", r => fmt(r.admob)]]);
};

// ── 가입자 ────────────────────────────────────────────────────────────
VIEW.users = async () => {
  const idx = await get("data/users/index.json");
  if (!idx || !(idx.days || []).length) {
    $("us-kpi").innerHTML = "<p class='why'>아직 가입자 데이터가 없습니다.</p>"; return;
  }
  kpiBox("us-kpi", [["가입자(누적)", n(idx.total)], ["코호트 일수", n(idx.days.length)]]);
  const draw = async day => {
    const d = await get("data/users/" + day + ".json");
    document.querySelectorAll(".daypills button").forEach(b =>
      b.classList.toggle("is-on", b.dataset.d === day));
    table($("us-table"), (d && d.users) || [], [
      ["uid", r => r.uid], ["기기", r => r.model || "–"], ["지역", r => r.country || "–"],
      ["버전", r => r.ver || "–"], ["접속일", r => n(r.days)],
      ["최고 레벨", r => n(r.lv)], ["깬 판", r => n(r.clears)],
      ["막힘", r => n(r.stuck)], ["광고", r => n(r.ads)],
      ["결제", r => n(r.buys)], ["그림", r => n(r.pics)],
      ["삭제", r => r.removed ? "예" : ""],
    ]);
  };
  $("us-days").innerHTML = idx.days.map(d =>
    `<button data-d="${d}" type="button">${d.slice(5)}</button>`).join("");
  $("us-days").querySelectorAll("button").forEach(b =>
    b.addEventListener("click", () => draw(b.dataset.d)));
  draw(idx.days[0]);
};

function fmt(v) {
  if (v == null) return "–";
  if (typeof v === "object") return Object.entries(v).map(([k, x]) => k + " " + x).join(" ");
  return typeof v === "number" ? n(v) : v;
}

show((location.hash || "#ingame").slice(1) || "ingame");
