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
  // ⑦ 리텐션 히트맵 — 세로로 코호트 편차, 가로로 감쇠를 본다.
  // ★색은 0%→옅은 노랑, 높을수록 주황→빨강(50%에서 포화). 파랑 농도보다 눈이 빨리 읽는다.
  // ★"아직 안 온 날"은 **·** 로 둔다. 0% 로 그리면 어제 깐 코호트가 D2~D14 전부 0 인
  //   급락 그래프가 돼서, 멀쩡한 코호트가 망한 것처럼 보인다.
  const ret = d.retention || [];
  const RN = 14;
  const dayNum = s => Date.UTC(+s.slice(0, 4), +s.slice(4, 6) - 1, +s.slice(6, 8)) / 864e5;
  const today = d.updated ? dayNum(d.updated.slice(0, 10).replace(/-/g, "")) : 0;
  const heat = p => {
    const t = Math.min(p / 50, 1);                 // 50% 에서 포화
    return `hsl(${(55 - 55 * t).toFixed(0)},95%,${(90 - 42 * t).toFixed(0)}%)`;
  };
  if (!ret.length) {
    $("retChart").innerHTML = "<tbody><tr><td>아직 코호트가 없습니다</td></tr></tbody>";
  } else {
    let h = '<thead><tr><th class="stick">설치일</th><th>신규</th>';
    for (let k = 1; k <= RN; k++) h += `<th>D${k}</th>`;
    h += "</tr></thead><tbody>";
    for (const r of ret) {                          // 수집기가 이미 최신순으로 준다
      const age = today - dayNum(r.cohort);
      h += `<tr><td class="stick">${r.cohort.slice(4, 6)}-${r.cohort.slice(6, 8)}</td>` +
           `<td class="num">${n(r.size)}</td>`;
      for (let k = 1; k <= RN; k++) {
        if (k > age) { h += '<td class="num coh-na" title="아직 안 온 날">·</td>'; continue; }
        // ★k === age 면 **그 날이 지금 지나는 중**이다. D1 은 설치 다음 날이 다 가야
        //   확정인데, 오늘이 바로 그 다음 날이면 아직 차는 중이다(형 지적 2026-10-12).
        //   확정값과 같은 모양으로 그리면, 옛 코호트의 완결된 수와 나란히 놓여
        //   "떨어졌다"로 읽힌다. 지금 값은 **바닥값**이라 + 를 붙이고 흐리게 둔다.
        const live = k === age;
        const x = (r.d || []).find(y => y.n === k);
        // ★표시는 **소수 1째자리**(형 요청 2026-10-13). 정수로 반올림하면 38.0 과 38.4 가
        //   같은 칸으로 보여서, 코호트 간 차이를 읽을 수 없다 — 지금처럼 코호트가
        //   수십 명 규모면 한 명이 1.4%p 라 반올림이 그 한 명을 통째로 지운다.
        //   색·대비 계산은 숫자(p)로, 글자는 문자열(ps)로 나눈다.
        const p = (x ? x.rate : 0) * 100;               // 그 날이 다 지났는데 없으면 진짜 0
        const ps = p.toFixed(1);
        const lg = 90 - 42 * Math.min(p / 50, 1);
        h += `<td class="num fcell${live ? " live" : ""}" ` +
             `style="background:${heat(p)};color:${lg < 55 ? "#fff" : "#333"}"` +
             ` title="${r.cohort} D${k} — ${x ? x.u : 0}명 / ${r.size}명` +
             `${live ? " · 오늘이 그 날이라 아직 차는 중(최소값)" : ""}">${ps}%${live ? "+" : ""}</td>`;
      }
      h += "</tr>";
    }
    $("retChart").innerHTML = h + "</tbody>";
  }
  $("retNote").innerHTML =
    `설치일 코호트 × D1~D${RN} 복귀율 · 셀 = 그 코호트 중 <b>정확히 n일 뒤</b> 접속한 비율 · ` +
    `<span class="coh-na">·</span> = 아직 안 온 날(0% 아님) · ` +
    `<b>N%+</b> = 오늘이 그 날이라 <b>아직 차는 중</b>(최소값, 자정에 확정) · 최신 설치일이 위`;

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
  // ★VPN 칸은 숨기지 않는다. 이란은 Play 가 공식 서비스하지 않아 VPN 이 기본이고,
  //   그래서 "브라질 유저"의 상당수가 사실 이란 사람이다. 그걸 모르면 시장을 잘못 읽는다.
  table($("ctryTable"), d.countries || [], [
    ["국가", r => r.country || "–"], ["명", r => n(r.users)],
    ["VPN", r => r.vpn ? `<span class="dim">${n(r.vpn)}</span>` : ""],
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
  // ★막대와 **같은 수의 칸**을 깔고 눈금에만 글자를 넣는다.
  //   좌표로 계산해 얹으면 폭이 바뀔 때마다 어긋난다 — 같은 flex 에 태우면 저절로 맞는다.
  // ★간격은 **레벨 수에 따라 벌린다.** 5 로 고정하면 1200판에서 글자가 240개 겹쳐
  //   까만 띠가 된다. 화면에 20개쯤만 남도록 5→10→25→50→100 으로 올린다.
  const step = [5, 10, 25, 50, 100, 250].find(s => lv.length / s <= 20) || 500;
  $("levelAxis").innerHTML = lv.map(r =>
    `<i>${r.lv % step === 0 || r.lv === 1 ? r.lv : ""}</i>`).join("");

  table($("levelTable"), lv, [
    ["레벨", r => "L" + r.lv], ["시작", r => n(r.started)], ["클리어", r => n(r.cleared)],
    ["클리어율", r => pct(r.rate)], ["시도", r => r.attempts ?? "–"],
    ["초과 수", r => r.over_moves ?? "–"], ["아이템", r => r.items ?? "–"],
    ["초", r => r.secs ?? "–"],
  ]);

  // ★수 제한 — 실패율이 10%를 넘으면 조여야 하고, 2% 아래면 풀어도 된다.
  //   색으로 표시해 둔다. 숫자만 늘어놓으면 어느 판이 문제인지 눈에 안 들어온다.
  table($("failTable"), d.fails, [
    ["레벨", r => "L" + r.lv],
    ["막힌 사람", r => n(r.users)],
    ["건수", r => n(r.n)],
    ["시작(전체)", r => n(r.started)],
    ["시작(제한O)", r => n(r.started_lim)],
    // ★실패율은 **제한이 있는 버전**만으로 잰다. 제한 없는 옛 버전을 분모에 넣으면
    //   실패할 수 없는 사람들이 섞여 희석된다(lv32 에서 1/1 이 1/44=2.3% 로 보였다).
    ["실패율(제한O)", r => r.rate_lim == null ? "–"
      : `<b class="${r.rate_lim >= 0.10 ? "bad-t" : (r.rate_lim < 0.02 ? "dim" : "")}">${pct(r.rate_lim)}</b>`],
    ["참고: 전체", r => r.rate == null ? "–" : `<span class="dim">${pct(r.rate)}</span>`],
    ["평균 수", r => r.moves ?? "–"],
    ["제한", r => r.lim ?? "–"]]);
  {
    const fs = (d.fail_summary && d.fail_summary[0]) || null;
    const el = $("failLead");
    if (el) {
      if (!fs || !fs.players) el.textContent = "아직 데이터 없음 — v46 이 유저에게 닿아야 찍힌다";
      else {
        const rate = fs.players ? fs.fail_users / fs.players : 0;
        el.innerHTML = `한 번이라도 막힌 사람 <b>${n(fs.fail_users)}</b>/${n(fs.players)}`
          + ` (<b>${pct(rate)}</b>) · 실패 ${n(fs.fails)}건`
          + ` · 빠져나간 방법 — 💎 ${n(fs.buy_gem)}회(젬 ${n(fs.gems_spent)})`
          + ` · 📺 ${n(fs.buy_ad)}회`;
      }
    }
  }

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
  // ★'사람'은 human 딱지만이다. 내 기기·디버그 빌드를 사람으로 세면 숫자가 거짓이 된다.
  const kk = d.kinds || {};
  kpiBox("rt-kpi", [
    ["오늘 사람", n(d.humans), "바깥에서 들어온 사람"],
    ["봇·스캔", n(d.bots), "업로드마다 도는 구글 스캔"],
    ["내 기기·디버그", n((kk.me || 0) + (kk.dbg || 0)), "숫자에서 뺀 것"],
    ["기준일", d.day || "–"],
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
  // ★목록에는 사람만 온다(realtime.py 가 거기서 거른다). 딱지 열이 전부 "사람"이면
  //   자리만 먹으므로 뺐다 — 몇 개를 걸렀는지는 위 KPI 가 말한다.
  // ★'신규' 칸을 뺐더니 "왜 다 구버전이지?" 를 읽을 수 없었다(형 질문 2026-10-13).
  //   이 목록은 **오늘 접속한 사람 전부**(복귀 포함)라, 신규인지 복귀인지를 안 보여 주면
  //   복귀 유저의 옛 버전이 "신규가 구버전을 받았다"로 읽힌다.
  //   ★'분' 은 플레이 시간이 아니라 **첫 이벤트~마지막 이벤트 간격**이다. 중간에
  //     몇 시간 쉬어도 그만큼 길어진다 — 그래서 제목에 표시해 둔다.
  table($("rt-users"), d.users || [], [
    ["시각", r => r.t0],
    ["신규", r => r.new ? "<b>신규</b>" : `<span class="dim">복귀</span>`],
    ["체류(간격)", r => r.mins],
    ["기기", r => r.model || "–"],
    ["지역", r => (r.country || "–") + (r.vpn ? ` <span class="dim" title="오늘 나라가 둘 이상 찍혔다">VPN</span>` : "")],
    ["버전", r => r.ver || "–"],
    ["도달", r => far(r)], ["깬 판", r => n(r.clears)],
    ["막힘", r => n(r.stuck)], ["광고", r => n(r.ads)], ["상점", r => n(r.shops)],
    ["결제", r => n(r.buys)], ["삭제", r => r.removed ? "예" : ""],
  ]);
  table($("rt-ver"), d.versions || [], [["버전", r => r.ver], ["사람", r => n(r.users)], ["설치", r => n(r.installs)]]);
  table($("rt-ctry"), d.countries || [], [["국가", r => r.country], ["사람", r => n(r.users)],
    ["VPN", r => r.vpn ? `<span class="dim">${n(r.vpn)}</span>` : ""]]);
  table($("rt-fail"), d.purchase_fail || [], [["사유", r => r.reason || "–"], ["건", r => n(r.n)], ["사람", r => n(r.users)]]);
  table($("rt-abuse"), d.abuse || [], [["사유", r => r.reason || "–"], ["지급됨", r => n(r.granted)], ["건", r => n(r.n)]]);
};

// ── 아이템(주력 BM) ───────────────────────────────────────────────────
VIEW.items = async () => {
  const d = await get("data/ingame.json");
  if (!d) { $("it-kpi").innerHTML = "<p class='why'>데이터가 없습니다.</p>"; return; }
  const src = d.item_source || [], lvl = d.item_level || [];
  const first = d.item_first || [], wall = d.wall_sales || [];
  // ★유료만 센다. free/ad/perk 는 공짜로 받은 것이라 매출이 아니다.
  const PAID = new Set(["paw", "gem"]);
  const paid = src.filter(r => PAID.has(r.source));
  const gems = paid.reduce((a, r) => a + (r.source === "gem" ? r.spent : 0), 0);
  const paws = paid.reduce((a, r) => a + (r.source === "paw" ? r.spent : 0), 0);
  const buyers = Math.max(0, ...paid.map(r => r.users), 0);
  kpiBox("it-kpi", [
    ["유료 사용", n(paid.reduce((a, r) => a + r.uses, 0)), "발바닥·젬으로 산 것"],
    ["산 사람", n(buyers)],
    ["쓴 젬", n(gems)],
    ["쓴 발바닥", n(paws)],
  ]);
  table($("it-wall"), wall, [
    ["구간", r => `${r.band}~${r.band + 9}`],
    ["플레이어", r => n(r.players)],
    ["막힘", r => r.stuck ? `<b class="bad-t">${n(r.stuck)}</b>` : "0"],
    ["하트고갈", r => n(r.out_of_hearts)],
    ["유료 사용", r => r.buys ? `<b>${n(r.buys)}</b>` : "0"],
    ["쓴 젬", r => n(r.gems)],
  ]);
  const KN = { hint: "💡 힌트", undo: "↩️ 되돌리기", tow: "🧹 치우기", heart: "❤️ 하트" };
  const SN = { paw: "🐾 발바닥", gem: "💎 젬", ad: "📺 광고", free: "무료", perk: "혜택" };
  table($("it-source"), src, [
    ["아이템", r => KN[r.kind] || r.kind],
    ["지불", r => `<span class="${PAID.has(r.source) ? "" : "dim"}">${SN[r.source] || r.source}</span>`],
    ["횟수", r => n(r.uses)], ["사람", r => n(r.users)],
    ["쓴 값", r => PAID.has(r.source) ? n(r.spent) : "<span class='dim'>–</span>"],
  ]);
  table($("it-shop"), d.shop_kinds || [], [
    ["상점", r => ({ gem: "💎 젬", heart: "❤️ 하트", paw: "🐾 발바닥" })[r.kind] || r.kind],
    ["연 횟수", r => n(r.opens)], ["사람", r => n(r.users)],
  ]);
  table($("it-level"), lvl, [
    ["구간", r => `${r.band}~${r.band + 9}`], ["사람", r => n(r.users)],
    ["유료", r => n(r.paid_uses)], ["무료", r => `<span class="dim">${n(r.free_uses)}</span>`],
    ["젬", r => n(r.gems)], ["발바닥", r => n(r.paws)],
  ]);
  table($("it-first"), first, [
    ["구간", r => `${r.band}~${r.band + 9}`], ["사람", r => n(r.users)],
  ]);
};

// ── 광고 ──────────────────────────────────────────────────────────────
VIEW.ads = async () => {
  const [ig, cfg, dy] = await Promise.all(
    [get("data/ingame.json"), get("data/config.json"), get("data/daily.json")]);
  // ★전면과 보상을 **나눠서** 본다. 한 표에 섞으면 "광고가 잘 나온다"가
  //   전면 때문인지 보상 때문인지 알 수 없고, 둘은 고치는 법이 다르다.
  //   가르는 규칙은 쿼리(queries.AD_KIND)가 단일 출처다 — 여기선 kind 만 읽는다.
  const ads = (ig && ig.ads) || [];
  const sum = (ig && ig.ad_summary) || [];
  const pick = k => sum.find(r => r.kind === k) || {};
  const iv = pick("inter"), rw = pick("reward");
  kpiBox("ad-kpi", [
    ["전면 노출", n(iv.shows || 0), iv.users ? `${n(iv.users)}명` : ""],
    ["보상 노출", n(rw.shows || 0), rw.users ? `${n(rw.users)}명` : ""],
    ["전면 실패율", iv.shows ? pct(iv.fail_rate) : "–"],
    ["보상 실패율", rw.shows ? pct(rw.fail_rate) : "–"],
  ]);
  const KIND = { inter: "🎬 전면", reward: "🎁 보상" };
  table($("ad-summary"), sum, [
    ["종류", r => KIND[r.kind] || r.kind], ["노출", r => n(r.shows)],
    ["사람", r => n(r.users)], ["실패", r => n(r.failed)],
    ["실패율", r => pct(r.fail_rate)],
  ]);
  const cols = [["자리", r => r.placement || "–"], ["결과", r => r.result || "–"],
                ["건수", r => n(r.n)], ["사람", r => n(r.users)]];
  table($("ad-inter"), ads.filter(r => r.kind === "inter"), cols);
  table($("ad-reward"), ads.filter(r => r.kind === "reward"), cols);
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
