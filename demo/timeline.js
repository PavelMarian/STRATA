// One Olist product, its orders and reviews, and a slider for t. Shared by
// about.html and the "What is STRATA?" sheet in index.html. Needs TIMELINE from data.js.
function initTimeline(root) {
  const q = s => root.querySelector(s); const svg = q("#timeline"); if (!svg || svg.dataset.ready) return; svg.dataset.ready = "1";
  const css = v => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
  const T = TIMELINE, d = s => new Date(s.replace(" ", "T") + "Z").getTime();
  const lo = d("2017-09-01 00:00:00"), hi = d("2018-08-01 00:00:00"), X = v => 40 + (v - lo) / (hi - lo) * 580;
  const orders = T.orders.map(o => ({...o, t: d(o.ts)})), reviews = T.reviews.map(r => ({...r, c: d(r.created)}));
  const byOrder = Object.fromEntries(orders.map(o => [o.order, o]));
  function draw(tv) {
    let g = `<line x1="40" x2="620" y1="190" y2="190" stroke="${css("--line")}"/>`;
    for (let m = new Date(lo), i = 0; m.getTime() <= hi; m.setUTCMonth(m.getUTCMonth() + 1), i++)
      if (i % 2 === 0) g += `<text x="${X(m.getTime())}" y="210" text-anchor="middle">${m.toISOString().slice(0, 7)}</text>`;
    g += `<text x="40" y="38">orders</text><text x="40" y="118">reviews</text>`;
    orders.forEach(o => g += `<circle cx="${X(o.t)}" cy="60" r="7" fill="${o.t <= tv ? css("--accent") : css("--line")}"><title>order ${o.order}, ${o.ts}</title></circle>`);
    reviews.forEach(r => {
      const o = byOrder[r.order], past = o && o.t <= tv, seen = r.c <= tv;
      const col = !past ? css("--line") : seen ? css("--unk") : css("--leak");
      if (o) g += `<line x1="${X(o.t)}" y1="67" x2="${X(r.c)}" y2="134" stroke="${col}" stroke-dasharray="3 3"/>`;
      g += `<rect x="${X(r.c) - 6}" y="134" width="12" height="12" rx="2" fill="${col}"><title>review of ${r.order}: ${r.score} stars, written ${r.created.slice(0, 10)}</title></rect><text x="${X(r.c)}" y="160" text-anchor="middle">${r.score}★</text>`;
    });
    g += `<line x1="${X(tv)}" x2="${X(tv)}" y1="22" y2="196" stroke="${css("--ink")}" stroke-width="2"/><text x="${X(tv) + 6}" y="30" style="fill:${css("--ink")}">t</text>`;
    svg.innerHTML = g;
    const pastOrders = new Set(orders.filter(o => o.t <= tv).map(o => o.order));
    const naive = reviews.filter(r => pastOrders.has(r.order)), cut = naive.filter(r => r.c <= tv);
    const mean = a => a.length ? (a.reduce((s, r) => s + r.score, 0) / a.length).toFixed(2) : "0";
    const rows = [["review_count", naive.length, cut.length], ["review_mean_score", mean(naive), mean(cut)], ["sales_count", pastOrders.size, pastOrders.size]];
    q("#tTable").innerHTML = rows.map(([n, a, b]) => `<tr><td><code>${n}</code></td><td class="${String(a) !== String(b) ? "diffcell" : ""}">${a}</td><td>${b}</td></tr>`).join("");
    const leak = naive.length !== cut.length, v = q("#tVerdict");
    v.className = "verd " + (leak ? "v-leak" : "v-clean"); v.textContent = leak ? "LEAK" : "CLEAN";
    q("#tNote").textContent = leak ? `${naive.length - cut.length} review${naive.length - cut.length > 1 ? "s" : ""} of past orders ${naive.length - cut.length > 1 ? "were" : "was"} written after t. The program counts them; in the data as of t they do not exist yet. STRATA reports this difference as the witness.`
      : "At this t every review of a past order was already written, so both values agree. At other times they may not.";
    q("#tLabel").textContent = new Date(tv).toISOString().slice(0, 10);
  }
  const slider = q("#tSlider"), start = d("2018-01-01 00:00:00");
  slider.value = Math.round((start - lo) / (hi - lo) * 100);
  const val = () => lo + slider.value / 100 * (hi - lo);
  slider.addEventListener("input", () => draw(val()));
  draw(start); matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => draw(val()));
}
