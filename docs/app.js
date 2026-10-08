// 정적 페이지 — BigQuery 는 브라우저에서 못 치므로 Actions 가 떨군 JSON 한 장만 읽는다.
const $ = (id) => document.getElementById(id);
const n = (v) => v == null ? "–" : Number(v).toLocaleString();
const pct = (v) => v == null ? "–" : (v * 100).toFixed(1) + "%";

// 값이 없을 때 **빈 표를 그리지 않는다** — "0건"과 "아직 안 들어옴"은 다른 상태다.
function table(el, rows, cols) {
  if (!rows || !rows.length) { el.outerHTML = `<div class="empty" id="${el.id}">데이터 없음</div>`; return; }
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
