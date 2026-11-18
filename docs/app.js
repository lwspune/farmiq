/* FarmIQ Price Patterns: renders precomputed summaries from data/*.json. */
(() => {
  "use strict";

  const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const FOCUS = ["Ahmednagar", "Narayangaon", "Pimpalgaon", "Pune", "Rahuri", "Shrirampur", "Newasa", "Aurangabad"];
  const REASONS = {
    missing_price: "with no price", non_positive_price: "with a zero or negative price",
    min_gt_max: "with minimum above maximum", modal_outside_range: "with modal price outside the min–max range",
    duplicate: "duplicate market-days",
  };
  const state = { commodity: "tomato", market: null, data: {}, meta: null, compare: new Map() };
  const $ = (id) => document.getElementById(id);
  const fmt = {
    inr: (v) => (v == null ? "–" : "₹" + v.toLocaleString("en-IN", { maximumFractionDigits: 1 })),
    x: (v) => (v == null ? "–" : v.toFixed(2)),
    int: (v) => (v == null ? "–" : v.toLocaleString("en-IN")),
    months: (ms) => ms.map((m) => MONTHS[m - 1]).join(", "),
  };

  function css(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  }
  function palette() {
    return {
      ink: css("--text-primary"), ink2: css("--text-secondary"), muted: css("--muted"),
      axis: css("--axis"), surface: css("--surface-1"),
      s: [css("--series-1"), css("--series-2"), css("--series-3"), css("--series-4")],
      low: css("--div-low"), mid: css("--div-mid"), high: css("--div-high"),
    };
  }

  // ---------- helpers ----------
  function clear(el) { while (el.firstChild) el.removeChild(el.firstChild); }
  function el(tag, attrs = {}, text) {
    const e = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
    if (text != null) e.textContent = text;
    return e;
  }
  function table(target, headers, rows) {
    const box = $(target); clear(box);
    const wrap = el("div", { class: "table-scroll" });
    const t = el("table");
    const thead = el("thead"); const hr = el("tr");
    headers.forEach((h) => hr.appendChild(el("th", { scope: "col" }, h)));
    thead.appendChild(hr); t.appendChild(thead);
    const tb = el("tbody");
    rows.forEach((r) => { const tr = el("tr"); r.forEach((c) => tr.appendChild(el("td", {}, c))); tb.appendChild(tr); });
    t.appendChild(tb); wrap.appendChild(t); box.appendChild(wrap);
  }
  function mount(id, node) { const box = $(id); clear(box); box.appendChild(node); }
  function width(id) { return Math.max(300, $(id).clientWidth || 600); }
  function base(p, w) {
    return {
      width: w,
      style: { background: "transparent", color: p.ink2, fontSize: "12px", fontFamily: "system-ui, sans-serif" },
    };
  }
  const monthAxis = { label: null, tickFormat: (m) => MONTHS[m - 1] };

  // ---------- data ----------
  async function load(commodity) {
    if (!state.data[commodity]) {
      const r = await fetch(`data/${commodity}.json`);
      if (!r.ok) throw new Error(`Could not load ${commodity} data (${r.status})`);
      state.data[commodity] = await r.json();
    }
    return state.data[commodity];
  }
  function markets() { return state.data[state.commodity].markets; }
  function current() { return markets()[state.market]; }

  function defaultMarket(ms) {
    const names = Object.keys(ms);
    const ranked = names.sort((a, b) => ms[b].full_years - ms[a].full_years);
    const home = ranked.find((n) => /ahmednagar|ahmadnagar/i.test(n) && ms[n].full_years >= 8);
    return home || ranked[0];
  }

  function fillMarketSelect() {
    const ms = markets(); const sel = $("market"); clear(sel);
    const byDistrict = {};
    for (const [name, m] of Object.entries(ms)) (byDistrict[m.district || "Other"] ||= []).push(name);
    const order = Object.keys(byDistrict).sort((a, b) =>
      (a.startsWith("Ahmad") ? -1 : b.startsWith("Ahmad") ? 1 : a.localeCompare(b)));
    for (const d of order) {
      const g = el("optgroup", { label: `${d} district` });
      byDistrict[d].sort((a, b) => ms[b].full_years - ms[a].full_years).forEach((n) => {
        const o = el("option", { value: n }, `${n} (${ms[n].full_years} full yrs)`);
        if (n === state.market) o.selected = true;
        g.appendChild(o);
      });
      sel.appendChild(g);
    }
  }

  // ---------- verdicts ----------
  function verdictCards(m) {
    const box = $("verdicts"); clear(box);
    const sv = m.season_verdict, bb = m.boom_bust, ap = m.arrivals_price;
    const rules = state.meta.rules;
    const cards = [];

    if (sv.verdict === "clear") {
      cards.push(["Seasonal pattern?", "Yes, a reliable one",
        `Dearer than the year's average in ${fmt.months(sv.high_months)}, cheaper in ${fmt.months(sv.low_months)}, in at least ${Math.round(rules.reliable_share * 100)}% of ${sv.n_years} years.`]);
    } else if (sv.verdict === "weak") {
      const hi = sv.high_months.length ? ` ${fmt.months(sv.high_months)} reliably dear.` : "";
      const lo = sv.low_months.length ? ` ${fmt.months(sv.low_months)} reliably cheap.` : "";
      cards.push(["Seasonal pattern?", "Only a weak one",
        `Over ${sv.n_years} years, months were not reliably high and low together.${hi}${lo}`]);
    } else {
      cards.push(["Seasonal pattern?", "Not enough data",
        `Only ${sv.n_years} full years here; ${rules.min_years_for_verdict} needed for a verdict.`]);
    }

    const bbText = {
      boom_bust: ["Yes, a tendency", `After a year when prices rose, the next year tended to fall, and vice versa (r = ${bb.r}, ${bb.n_pairs} year pairs).`],
      momentum: ["Rises follow rises", `A rising year tended to be followed by another rise (r = ${bb.r}, ${bb.n_pairs} year pairs).`],
      none: ["No clear cycle", `One year's change says little about the next (r = ${bb.r}, ${bb.n_pairs} year pairs).`],
      insufficient: ["Not enough data", "Needs at least 6 pairs of consecutive full years."],
    }[bb.verdict];
    cards.push(["Boom then bust?", ...bbText]);

    if (!ap) {
      cards.push(["More arrivals, lower price?", "Not enough data", "Needs at least 24 months with both arrivals and prices."]);
    } else if (ap.r <= -0.3) {
      cards.push(["More arrivals, lower price?", "Yes", `Months with more produce arriving had lower prices (r = ${ap.r}, ${ap.n_months} months).`]);
    } else if (ap.r >= 0.3) {
      cards.push(["More arrivals, lower price?", "No, the opposite", `Arrivals and prices rose together (r = ${ap.r}, ${ap.n_months} months).`]);
    } else {
      cards.push(["More arrivals, lower price?", "Only weakly", `The link is weak here (r = ${ap.r}, ${ap.n_months} months).`]);
    }

    const peak = m.volatility.length ? m.volatility.reduce((a, b) => (b[1] > a[1] ? b : a)) : null;
    cards.push(["Riskiest month", peak ? MONTHS[peak[0] - 1] : "–",
      peak ? `Prices swing most within ${MONTHS[peak[0] - 1]} (typically ${Math.round(peak[1] * 100)}% around the month's average).` : "Not enough data."]);

    for (const [h, a, p] of cards) {
      const c = el("article", { class: "verdict" });
      c.appendChild(el("h3", {}, h)); c.appendChild(el("p", { class: "answer" }, a)); c.appendChild(el("p", {}, p));
      box.appendChild(c);
    }
  }

  // ---------- charts ----------
  function seasonChart(m, p) {
    const data = m.season.map((s) => ({ ...s, label: MONTHS[s.month - 1] }));
    const w = width("chart-season");
    mount("chart-season", Plot.plot({
      ...base(p, w), height: 300, marginLeft: 44,
      x: { ...monthAxis, domain: d3.range(1, 13), type: "band" },
      y: { label: "× year's average", grid: true, domain: [0, Math.max(2, d3.max(data, (d) => d.p90 ?? d.median) * 1.05)] },
      marks: [
        Plot.ruleY([1], { stroke: p.axis, strokeWidth: 1.5 }),
        Plot.ruleX(data.filter((d) => d.p10 != null), { x: "month", y1: "p10", y2: "p90", stroke: p.s[0], strokeWidth: 6, strokeOpacity: 0.3, strokeLinecap: "round" }),
        Plot.dot(data, {
          x: "month", y: "median", r: 6, fill: p.s[0], stroke: p.surface, strokeWidth: 2,
          channels: { Month: "label", "Years above average": (d) => `${d.years_above} of ${d.n_years}` },
          tip: { format: { x: false, y: (v) => v.toFixed(2) + "×" } },
        }),
        Plot.text(data, { x: "month", y: () => 0, dy: -8, text: (d) => `${d.years_above}/${d.n_years}`, fill: p.muted, fontSize: 10 }),
      ],
    }));
    table("table-season", ["Month", "Typical (× avg)", "Low (P10)", "High (P90)", "Years above avg"],
      data.map((d) => [d.label, fmt.x(d.median), fmt.x(d.p10), fmt.x(d.p90), `${d.years_above} of ${d.n_years}`]));
  }

  function heatChart(m, p) {
    const data = m.index.map(([year, month, idx]) => ({ year, month, idx }));
    // Show every year in the range so missing years appear as blank rows, not silently skipped.
    const ys = data.map((d) => d.year);
    const years = ys.length ? d3.range(d3.min(ys), d3.max(ys) + 1) : [];
    const color = d3.scaleDivergingLog([0.4, 1, 2.5], d3.piecewise(d3.interpolateLab, [p.low, p.mid, p.high])).clamp(true);
    const legend = $("heat-legend"); clear(legend);
    const bar = el("span", { class: "bar" });
    bar.style.background = `linear-gradient(90deg, ${p.low}, ${p.mid}, ${p.high})`;
    legend.append(el("span", {}, "0.4× cheaper"), bar, el("span", {}, "2.5× dearer"));
    const w = width("chart-heat");
    mount("chart-heat", Plot.plot({
      ...base(p, w), height: 40 + years.length * 18, marginLeft: 44,
      x: { ...monthAxis, domain: d3.range(1, 13), type: "band", axis: "top" },
      y: { label: null, domain: years, type: "band", tickFormat: (y) => String(y) },
      marks: [
        Plot.cell(data, {
          x: "month", y: "year", fill: (d) => color(d.idx), inset: 1, rx: 3,
          channels: { Year: "year", Month: (d) => MONTHS[d.month - 1], "× year's average": (d) => d.idx.toFixed(2) },
          tip: { format: { x: false, y: false, fill: false } },
        }),
      ],
    }));
    const byYear = d3.group(data, (d) => d.year);
    table("table-heat", ["Year", ...MONTHS], years.map((y) => {
      const row = new Map((byYear.get(y) || []).map((d) => [d.month, d.idx]));
      return [String(y), ...d3.range(1, 13).map((mo) => fmt.x(row.get(mo)))];
    }));
  }

  function historyChart(m, p) {
    // Fill every month in the range; months with no data stay empty so the line breaks at gaps.
    const have = new Map(m.monthly.map(([y, mo, v, n]) => [y * 12 + mo - 1, { v, n }]));
    const keys = [...have.keys()];
    const data = keys.length ? d3.range(d3.min(keys), d3.max(keys) + 1).map((k) => ({
      date: new Date(Math.floor(k / 12), k % 12, 15), v: have.get(k)?.v ?? NaN, n: have.get(k)?.n ?? 0,
    })) : [];
    const w = width("chart-history");
    mount("chart-history", Plot.plot({
      ...base(p, w), height: 280, marginLeft: 48,
      x: { label: null },
      y: { label: "₹/kg", grid: true },
      marks: [
        Plot.ruleY([0], { stroke: p.axis }),
        Plot.lineY(data, { x: "date", y: "v", stroke: p.s[0], strokeWidth: 2, curve: "monotone-x" }),
        Plot.tip(data.filter((d) => !Number.isNaN(d.v)), Plot.pointerX({
          x: "date", y: "v",
          channels: { "Reporting days": "n" },
          format: { x: (d) => d.toLocaleDateString("en-IN", { month: "short", year: "numeric" }), y: (v) => fmt.inr(v) + "/kg" },
        })),
        Plot.dot(data.filter((d) => !Number.isNaN(d.v)), Plot.pointerX({ x: "date", y: "v", r: 5, fill: p.s[0], stroke: p.surface, strokeWidth: 2 })),
      ],
    }));
    table("table-history", ["Month", "Median ₹/kg", "Reporting days"],
      m.monthly.slice().reverse().map(([y, mo, v, n]) => [`${MONTHS[mo - 1]} ${y}`, fmt.inr(v), String(n)]));
  }

  function annualChart(m, p) {
    const data = m.annual.map(([year, v]) => ({ year, v }));
    const yrs = data.map((d) => d.year);
    const domain = yrs.length ? d3.range(d3.min(yrs), d3.max(yrs) + 1) : [];  // gaps stay visible
    const w = width("chart-annual");
    mount("chart-annual", Plot.plot({
      ...base(p, w), height: 260, marginLeft: 48,
      x: { label: null, type: "band", domain, tickFormat: (y) => (domain.length > 12 && y % 2 ? "" : String(y)) },
      y: { label: "₹/kg", grid: true },
      marks: [
        Plot.barY(data, { x: "year", y: "v", fill: p.s[0], rx: 3, insetLeft: 1, insetRight: 1,
          tip: { format: { x: (y) => String(y), y: (v) => fmt.inr(v) + "/kg" } } }),
        Plot.ruleY([0], { stroke: p.axis }),
      ],
    }));
    table("table-annual", ["Year", "Average ₹/kg"], data.map((d) => [String(d.year), fmt.inr(d.v)]));
  }

  function arrivalsChart(m, p) {
    const idx = new Map(m.index.map(([y, mo, v]) => [`${y}-${mo}`, v]));
    const byYear = d3.rollup(m.arrivals, (v) => d3.mean(v, (d) => d[2]), (d) => d[0]);
    const data = m.arrivals
      .map(([y, mo, a]) => ({ y, mo, arr: a / byYear.get(y), price: idx.get(`${y}-${mo}`), a }))
      .filter((d) => d.price != null && d.arr > 0);
    const box = "chart-arrivals";
    if (data.length < 12) {
      const box_ = $(box); clear(box_); box_.appendChild(el("p", { class: "muted" }, "Not enough months with both arrivals and prices at this market."));
      table("table-arrivals", ["Month", "Arrivals vs year avg", "Price vs year avg"], []);
      return;
    }
    const w = width(box);
    mount(box, Plot.plot({
      ...base(p, w), height: 320, marginLeft: 48, marginTop: 28, marginRight: 28,
      x: { type: "log", label: "Arrivals (× year's average) →", grid: true, ticks: [0.25, 0.5, 1, 2, 4], tickFormat: (v) => v + "×" },
      y: { type: "log", label: "↑ Price (× year's average)", grid: true, ticks: [0.25, 0.5, 1, 2], tickFormat: (v) => v + "×" },
      marks: [
        Plot.ruleX([1], { stroke: p.axis }), Plot.ruleY([1], { stroke: p.axis }),
        Plot.dot(data, {
          x: "arr", y: "price", r: 4, fill: p.s[0], fillOpacity: 0.55, stroke: p.surface, strokeWidth: 1,
          channels: { Month: (d) => `${MONTHS[d.mo - 1]} ${d.y}` },
          tip: { format: { x: (v) => v.toFixed(2) + "×", y: (v) => v.toFixed(2) + "×" } },
        }),
      ],
    }));
    table("table-arrivals", ["Month", "Arrivals", "Arrivals vs year avg", "Price vs year avg"],
      data.map((d) => [`${MONTHS[d.mo - 1]} ${d.y}`, fmt.int(Math.round(d.a)), fmt.x(d.arr), fmt.x(d.price)]));
  }

  function volChart(m, p) {
    const data = m.volatility.map(([month, cv, n]) => ({ month, cv, n }));
    const w = width("chart-vol");
    mount("chart-vol", Plot.plot({
      ...base(p, w), height: 240, marginLeft: 44,
      x: { ...monthAxis, domain: d3.range(1, 13), type: "band" },
      y: { label: "Typical swing", grid: true, tickFormat: (v) => Math.round(v * 100) + "%" },
      marks: [
        Plot.barY(data, { x: "month", y: "cv", fill: p.s[0], rx: 3, insetLeft: 4, insetRight: 4,
          channels: { "Years": "n" },
          tip: { format: { x: (mo) => MONTHS[mo - 1], y: (v) => Math.round(v * 100) + "%" } } }),
        Plot.ruleY([0], { stroke: p.axis }),
      ],
    }));
    table("table-vol", ["Month", "Typical swing", "Years"], data.map((d) => [MONTHS[d.month - 1], Math.round(d.cv * 100) + "%", String(d.n)]));
  }

  // ---------- weather ----------
  function weatherCard(m, p) {
    const vbox = $("wx-verdict"); clear(vbox);
    const wx = m.weather;
    if (!wx) {
      vbox.textContent = "Not enough price history at this market to compare with weather.";
      ["chart-wx", "chart-rain", "chart-tmax"].forEach((id) => clear($(id)));
      table("table-wx", [], []);
      return;
    }
    const v = wx.verdict;
    const name = { rain: "rainfall", heat: "heat" };
    const when = (lag) => (lag === 0 ? "the same month" : `${lag} month${lag > 1 ? "s" : ""} later`);
    if (v.verdict === "insufficient") {
      vbox.textContent = "Not enough months with both prices and weather to say.";
    } else if (v.verdict === "link") {
      vbox.textContent = `Possibly: unusual ${name[v.var]} lined up with price surprises ${when(v.lag)} (r = ${v.r}, ${v.n} months). Eight combinations were tested, so treat a single result near ±0.3 as a hint, not proof.`;
    } else {
      vbox.textContent = `Only weakly. The strongest link is unusual ${name[v.var]} with prices ${when(v.lag)} (r = ${v.r}, ${v.n} months). Local weather explains little; prices are mostly set by supply from across India.`;
    }

    const corr = wx.corr.filter((c) => c.r != null).map((c) => ({ ...c, label: name[c.var] }));
    const series = ["rainfall", "heat"];
    const w = width("chart-wx");
    mount("chart-wx", Plot.plot({
      ...base(p, w), height: 240, marginLeft: 44, marginBottom: 40,
      x: { domain: [0, 1, 2, 3], type: "band", label: "Price surprise this many months after the weather →", labelAnchor: "right", labelOffset: 34,
        tickFormat: (l) => (l === 0 ? "same month" : `+${l}`) },
      y: { domain: [-0.6, 0.6], label: "↑ Correlation", grid: true },
      color: { domain: series, range: [p.s[0], p.s[1]], legend: true },
      marks: [
        Plot.ruleY([0], { stroke: p.axis, strokeWidth: 1.5 }),
        Plot.ruleY([-0.3, 0.3], { stroke: p.axis, strokeOpacity: 0.6 }),
        ...[["rain", -8], ["heat", 8]].map(([v, dx]) => Plot.dot(corr.filter((c) => c.var === v), {
          x: "lag", y: "r", fill: "label", r: 6, stroke: p.surface, strokeWidth: 2, dx,
          channels: { Weather: "label", Months: "n" },
          tip: { format: { x: (l) => (l === 0 ? "same month" : `+${l} months`), y: (r) => r.toFixed(2), fill: false } } })),
      ],
    }));

    const normals = wx.normals.map(([month, rain, tmax]) => ({ month, rain, tmax }));
    const half = width("chart-rain");
    mount("chart-rain", Plot.plot({
      ...base(p, half), height: 200, marginLeft: 40,
      x: { ...monthAxis, domain: d3.range(1, 13), type: "band", tickFormat: (mo) => MONTHS[mo - 1][0] },
      y: { label: null, grid: true },
      marks: [
        Plot.barY(normals, { x: "month", y: "rain", fill: p.s[0], rx: 2, insetLeft: 2, insetRight: 2,
          tip: { format: { x: (mo) => MONTHS[mo - 1], y: (v) => `${Math.round(v)} mm` } } }),
        Plot.ruleY([0], { stroke: p.axis }),
      ],
    }));
    mount("chart-tmax", Plot.plot({
      ...base(p, width("chart-tmax")), height: 200, marginLeft: 40,
      x: { ...monthAxis, domain: d3.range(1, 13), tickFormat: (mo) => MONTHS[mo - 1][0] },
      y: { label: null, grid: true },
      marks: [
        Plot.lineY(normals, { x: "month", y: "tmax", stroke: p.s[0], strokeWidth: 2, curve: "monotone-x" }),
        Plot.dot(normals, { x: "month", y: "tmax", r: 3.5, fill: p.s[0], stroke: p.surface, strokeWidth: 1.5,
          tip: { format: { x: (mo) => MONTHS[mo - 1], y: (v) => `${v.toFixed(1)} °C` } } }),
      ],
    }));
    table("table-wx", ["Weather", "Months later", "Correlation", "Months compared"],
      wx.corr.map((c) => [name[c.var], String(c.lag), c.r == null ? "–" : c.r.toFixed(2), String(c.n)]));
    const t = $("table-wx");
    const extra = el("div");
    t.appendChild(extra);
    const wrap = el("div", { class: "table-scroll" });
    const tb = el("table");
    const hr = el("tr");
    ["Month", "Usual rain (mm)", "Usual daytime high (°C)"].forEach((h) => hr.appendChild(el("th", { scope: "col" }, h)));
    const thead = el("thead"); thead.appendChild(hr); tb.appendChild(thead);
    const body = el("tbody");
    normals.forEach((n) => {
      const tr = el("tr");
      [MONTHS[n.month - 1], String(Math.round(n.rain)), n.tmax.toFixed(1)].forEach((c) => tr.appendChild(el("td", {}, c)));
      body.appendChild(tr);
    });
    tb.appendChild(body); wrap.appendChild(tb); extra.appendChild(wrap);
    extra.appendChild(el("p", { class: "note" }, `Weather at the ${m.district} district centre, ${wx.years[0]}–${wx.years[1]}.`));
  }

  // ---------- planner ----------
  const plan = { month: ((new Date().getMonth() + 1) % 12) + 1, first: null, length: null, years: "recent" };

  function fillSelect(sel, values, label, current) {
    clear(sel);
    values.forEach((v) => {
      const o = el("option", { value: String(v) }, label(v));
      if (String(v) === String(current)) o.selected = true;
      sel.appendChild(o);
    });
  }

  function initPlanner(m) {
    const form = $("planner");
    if (!m.planner) { form.hidden = true; return; }
    form.hidden = false;
    const t = m.planner.timing;
    if (!t.first.includes(plan.first)) plan.first = t.default[0];
    if (!t.length.includes(plan.length)) plan.length = t.default[1];
    fillSelect($("pl-month"), d3.range(1, 13), (v) => MONTHS[v - 1], plan.month);
    fillSelect($("pl-first"), t.first, (v) => `${v} days`, plan.first);
    fillSelect($("pl-length"), t.length, (v) => `${v} days`, plan.length);
    $("pl-recent-n").textContent = m.planner.recent_years;
  }

  function readNumber(id, { min, allowEmpty }) {
    const input = $(id); const raw = input.value.trim();
    input.removeAttribute("aria-invalid");
    if (raw === "") return allowEmpty ? null : undefined;
    const v = Number(raw);
    if (!Number.isFinite(v) || v < min || (min > 0 && v === 0)) { input.setAttribute("aria-invalid", "true"); return NaN; }
    return v;
  }

  function renderPlanner(m, p) {
    const out = $("pl-result"); clear(out);
    if (!m.planner) {
      out.appendChild(el("p", { class: "warn" }, `Not enough history at ${state.market} for the planner (needs ${5}+ full years). Pick a market with more years.`));
      clear($("chart-plan")); table("table-plan", [], []);
      return;
    }
    const grid = m.planner.grid[`${plan.first}-${plan.length}`];
    const which = plan.years;
    const latest = parseInt(m.last.slice(0, 4), 10);
    const inWindow = (y) => which === "all" || y > latest - m.planner.recent_years;
    const cell = grid[plan.month];
    const s = cell[which];
    const harvest = cell.harvest_months.map((h) => MONTHS[h - 1]).join("–");

    const cost = readNumber("pl-cost", { min: 1, allowEmpty: true });
    const yld = readNumber("pl-yield", { min: 1, allowEmpty: true });
    const sell = readNumber("pl-sell", { min: 0, allowEmpty: true }) ?? 0;
    let be = null;
    if ([cost, yld, sell].some((v) => Number.isNaN(v))) {
      out.appendChild(el("p", { class: "warn", role: "alert" }, "Cost and yield must be numbers above zero; selling cost can be zero."));
    } else if (cost != null && yld != null) {
      be = cost / yld + sell;  // same rule as farmiq_data.planner.break_even_price
    }

    const span = which === "all" ? "all years" : `the last ${m.planner.recent_years} years`;
    out.appendChild(el("p", {}, `Transplant in ${MONTHS[plan.month - 1]} → harvest in ${harvest}.`));
    if (!s) {
      out.appendChild(el("p", { class: "warn" }, `Not enough ${which === "all" ? "" : "recent "}years with prices in ${harvest} at this market to say (needs 5).${which === "recent" ? " Try “All years”." : ""}`));
    } else {
      const ptxt = el("p");
      ptxt.append(`In ${span} (${s.n} years, ${s.first_year}–${s.last_year}), the mandi price in those months was `,
        el("strong", {}, fmt.inr(s.p10)), " in a bad year, ", el("strong", {}, fmt.inr(s.p50)), " typically, and ",
        el("strong", {}, fmt.inr(s.p90)), " in a good year (per kg).");
      out.appendChild(ptxt);
      if (be != null) {
        const ys = cell.years.filter(([y]) => inWindow(y)).map(([, v]) => v);
        const k = ys.filter((v) => v >= be).length;
        const bp = el("p");
        bp.append("Your break-even: ", el("strong", {}, fmt.inr(be) + "/kg"),
          `. Harvest-window prices were at or above it in `, el("strong", {}, `${k} of ${ys.length} years`), ".");
        out.appendChild(bp);
      } else {
        out.appendChild(el("p", { class: "warn" }, "Enter your cost per acre and marketable yield to see your break-even price."));
      }
    }

    // Chart: every transplant month; the chosen one emphasised, the rest muted.
    const data = d3.range(1, 13).map((tm) => ({ tm, ...(grid[tm][which] || {}), harvest: grid[tm].harvest_months.map((h) => MONTHS[h - 1]).join("–") }))
      .filter((d) => d.p50 != null);
    const w = width("chart-plan");
    const top = d3.max([...data.map((d) => d.p90), be || 0]) * 1.1 || 10;
    const chosen = data.filter((d) => d.tm === plan.month);
    const others = data.filter((d) => d.tm !== plan.month);
    const tipOpts = {
      channels: {
        Transplant: (d) => MONTHS[d.tm - 1], Harvest: "harvest",
        "Bad year": (d) => fmt.inr(d.p10) + "/kg", Typical: (d) => fmt.inr(d.p50) + "/kg",
        "Good year": (d) => fmt.inr(d.p90) + "/kg", Years: "n",
      },
      tip: { format: { x: false, y: false } },
    };
    mount("chart-plan", Plot.plot({
      ...base(p, w), height: 310, marginLeft: 48, marginBottom: 44,
      x: { ...monthAxis, domain: d3.range(1, 13), type: "band", label: "Transplant month →", labelAnchor: "right", labelOffset: 38 },
      y: { label: "↑ Harvest-window price, ₹/kg", grid: true, domain: [0, top] },
      marks: [
        Plot.ruleY([0], { stroke: p.axis }),
        Plot.ruleX(others, { x: "tm", y1: "p10", y2: "p90", strokeWidth: 6, strokeLinecap: "round", stroke: p.muted, strokeOpacity: 0.3 }),
        Plot.ruleX(chosen, { x: "tm", y1: "p10", y2: "p90", strokeWidth: 6, strokeLinecap: "round", stroke: p.s[0], strokeOpacity: 0.45 }),
        ...(be != null ? [
          Plot.ruleY([be], { stroke: p.ink, strokeWidth: 1.5 }),
          Plot.text([be], { frameAnchor: "left", y: (d) => d, text: () => `Your break-even ${fmt.inr(be)}`,
            dx: 4, dy: -9, textAnchor: "start", fill: p.ink, fontSize: 11, stroke: p.surface, strokeWidth: 3, paintOrder: "stroke" }),
        ] : []),
        Plot.dot(others, { x: "tm", y: "p50", r: 5, fill: p.muted, stroke: p.surface, strokeWidth: 2, ...tipOpts }),
        Plot.dot(chosen, { x: "tm", y: "p50", r: 7, fill: p.s[0], stroke: p.surface, strokeWidth: 2, ...tipOpts }),
      ],
    }));
    table("table-plan", ["Transplant", "Harvest", "Bad year (P10)", "Typical (P50)", "Good year (P90)", "Years"],
      d3.range(1, 13).map((tm) => {
        const c = grid[tm]; const v = c[which];
        return [MONTHS[tm - 1], c.harvest_months.map((h) => MONTHS[h - 1]).join("–"),
          fmt.inr(v?.p10), fmt.inr(v?.p50), fmt.inr(v?.p90), v ? String(v.n) : "too few"];
      }));
  }

  function bindPlanner() {
    const rerender = () => { const m = current(); if (m) renderPlanner(m, palette()); };
    $("pl-month").addEventListener("change", (e) => { plan.month = +e.target.value; rerender(); });
    $("pl-first").addEventListener("change", (e) => { plan.first = +e.target.value; rerender(); });
    $("pl-length").addEventListener("change", (e) => { plan.length = +e.target.value; rerender(); });
    document.querySelectorAll('input[name="pl-years"]').forEach((r) =>
      r.addEventListener("change", (e) => { plan.years = e.target.value; rerender(); }));
    ["pl-cost", "pl-yield", "pl-sell"].forEach((id) => $(id).addEventListener("input", rerender));
    $("planner").addEventListener("submit", (e) => e.preventDefault());
  }

  // ---------- compare ----------
  function initCompare() {
    const ms = markets();
    state.compare = new Map();
    const eligible = Object.keys(ms).filter((n) => ms[n].full_years >= 5);
    const wanted = [state.market, ...FOCUS.flatMap((f) => eligible.filter((n) => n.includes(f)))];
    for (const n of wanted) {
      if (state.compare.size >= 4) break;
      if (eligible.includes(n) && !state.compare.has(n)) state.compare.set(n, nextSlot());
    }
    const picker = $("compare-picker"); clear(picker);
    eligible.sort((a, b) => a.localeCompare(b)).forEach((n) => {
      const lab = el("label");
      const cb = el("input", { type: "checkbox", value: n });
      cb.checked = state.compare.has(n);
      cb.addEventListener("change", () => {
        if (cb.checked) {
          if (state.compare.size >= 4) { cb.checked = false; return; }
          state.compare.set(n, nextSlot());
        } else state.compare.delete(n);
        renderCompare();
      });
      lab.append(cb, document.createTextNode(n));
      picker.appendChild(lab);
    });
  }
  function nextSlot() {
    const used = new Set(state.compare.values());
    return [0, 1, 2, 3].find((s) => !used.has(s));
  }
  function renderCompare() {
    const p = palette(); const ms = markets();
    const rows = [];
    for (const [n, slot] of state.compare) for (const s of ms[n].season) rows.push({ market: n, slot, month: s.month, v: s.median });
    const names = [...state.compare.keys()];
    const w = width("chart-compare");
    mount("chart-compare", Plot.plot({
      ...base(p, w), height: 300, marginLeft: 44, marginRight: 16,
      x: { ...monthAxis, domain: d3.range(1, 13) },
      y: { label: "× year's average", grid: true },
      color: { domain: names, range: names.map((n) => p.s[state.compare.get(n)]), legend: true },
      marks: [
        Plot.ruleY([1], { stroke: p.axis }),
        Plot.lineY(rows, { x: "month", y: "v", stroke: "market", strokeWidth: 2, curve: "monotone-x" }),
        Plot.dot(rows, { x: "month", y: "v", fill: "market", r: 3.5, stroke: p.surface, strokeWidth: 1.5,
          tip: { format: { x: (mo) => MONTHS[mo - 1], y: (v) => v.toFixed(2) + "×" } } }),
      ],
    }));
    // swatches on the picker follow the same entity colors
    document.querySelectorAll("#compare-picker label").forEach((lab) => {
      lab.querySelector(".swatch")?.remove();
      const n = lab.querySelector("input").value;
      if (state.compare.has(n)) {
        const sw = el("span", { class: "swatch", "aria-hidden": "true" });
        sw.style.background = p.s[state.compare.get(n)];
        lab.appendChild(sw);
      }
    });
    table("table-compare", ["Month", ...names], d3.range(1, 13).map((mo) =>
      [MONTHS[mo - 1], ...names.map((n) => fmt.x(ms[n].season.find((s) => s.month === mo)?.median))]));
  }

  // ---------- page ----------
  function about() {
    const m = state.meta; const box = $("about"); clear(box);
    const items = [
      `Daily wholesale (mandi) prices for ${m.districts.join(", ")} districts, ${m.date_range[0]} to ${m.date_range[1]}: ${fmt.int(m.n_price_days)} market-days after cleaning.`,
      `Records removed (counted, not hidden): ${Object.entries(m.rejected).map(([k, v]) => `${fmt.int(v)} ${REASONS[k] || k.replaceAll("_", " ")}`).join("; ") || "none"}.`,
      `A month counts only with at least ${m.rules.min_days_per_month} reporting days, and a year only with at least ${m.rules.min_months_per_year} such months. A verdict needs ${m.rules.min_years_for_verdict}+ years; a month is "reliably" dear or cheap if it was so in ${Math.round(m.rules.reliable_share * 100)}% of years.`,
      "Prices are nominal (not adjusted for inflation); the month-vs-year comparisons remove inflation within each year.",
      "Modal price is the most common wholesale price at the mandi that day. A farmer's own realisation is lower after transport, commission, grading and rejection.",
    ];
    if (m.source_check && m.source_check.n_matched) {
      const s = m.source_check;
      items.push(`Cross-check: on ${fmt.int(s.n_matched)} market-days found in both CEDA and our own Agmarknet downloads, ${Math.round(s.share_equal * 100)}% of modal prices match exactly (median difference ₹${s.median_abs_diff_inr_quintal}/quintal).`);
    }
    const ul = el("ul");
    items.forEach((t) => ul.appendChild(el("li", {}, t)));
    box.appendChild(ul);
    box.appendChild(el("p", { class: "note" }, `Data built ${m.generated_at.slice(0, 10)}.`));
    $("credit").textContent = m.credit;
  }

  function renderAll() {
    const m = current(); if (!m) return;
    const p = palette();
    $("coverage").textContent =
      `${state.market} · ${m.district} district · ${fmt.int(m.n_days)} price days, ${m.first.slice(0, 4)}–${m.last.slice(0, 4)} · ${m.full_years} full years usable`;
    verdictCards(m);
    initPlanner(m); renderPlanner(m, p);
    seasonChart(m, p); heatChart(m, p); historyChart(m, p); annualChart(m, p); arrivalsChart(m, p); weatherCard(m, p); volChart(m, p);
    renderCompare();
    document.querySelectorAll("#arr-h").forEach((h) => (h.textContent =
      `More ${state.commodity === "onion" ? "onions" : "tomatoes"} arriving, lower price?`));
  }

  async function selectCommodity(c) {
    state.commodity = c;
    const d = await load(c);
    if (!d.markets[state.market]) state.market = defaultMarket(d.markets);
    fillMarketSelect(); initCompare(); renderAll();
  }

  async function init() {
    try {
      const r = await fetch("data/meta.json");
      if (!r.ok) throw new Error(`Could not load metadata (${r.status})`);
      state.meta = await r.json();
      // Crops still being collected stay listed but disabled, so nobody lands on an empty page.
      const ready = new Set(state.meta.commodities || ["tomato"]);
      for (const o of $("commodity").options) {
        if (!ready.has(o.value)) { o.disabled = true; o.textContent += " (coming soon)"; }
      }
      about();
      await selectCommodity("tomato");
    } catch (err) {
      const box = $("verdicts"); clear(box);
      box.appendChild(el("p", { role: "alert" }, `Sorry, the data could not be loaded. ${err.message}`));
      return;
    }
    bindPlanner();
    $("commodity").addEventListener("change", (e) => selectCommodity(e.target.value));
    $("market").addEventListener("change", (e) => {
      state.market = e.target.value;
      if (!state.compare.has(state.market) && state.compare.size < 4) state.compare.set(state.market, nextSlot());
      initCompareChecks(); renderAll();
    });
    let t; window.addEventListener("resize", () => { clearTimeout(t); t = setTimeout(renderAll, 200); });
    window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", renderAll);
  }
  function initCompareChecks() {
    document.querySelectorAll("#compare-picker input").forEach((cb) => (cb.checked = state.compare.has(cb.value)));
  }

  init();
})();
