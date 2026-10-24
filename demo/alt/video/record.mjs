// Record the demo video frame by frame with headless Chrome over the DevTools protocol.
//   node record.mjs <base url> <durations.json> <out dir>
// Each scene lasts exactly as long as its voice-over (durations.json from the voice-over skill);
// the scripted actions run at the start of the scene and the last frame holds until it ends.
// Frames land in <out dir>/frames/scene_<id>/NNNNN.jpg with a frames.txt (ffmpeg concat list).
import fs from "node:fs";
import path from "node:path";

const [BASE, DUR_FILE, OUT] = process.argv.slice(2);
if (!BASE || !DUR_FILE || !OUT) { console.error("usage: node record.mjs <base url> <durations.json> <out dir>"); process.exit(2); }
const DUR = JSON.parse(fs.readFileSync(DUR_FILE, "utf8"));
const dur = id => { const d = DUR[String(id)] ?? DUR[id] ?? (DUR.scenes || []).find(s => String(s.id) === String(id))?.seconds; if (!d) throw new Error("no duration for scene " + id); return +d; };
const W = 1920, H = 1080;

// ---------- devtools plumbing ----------
const dbg = "http://127.0.0.1:9334";
const tab = await (await fetch(`${dbg}/json/new?about:blank`, {method: "PUT"})).json();
const ws = new WebSocket(tab.webSocketDebuggerUrl);
let mid = 0; const pending = new Map(); const handlers = {};
const send = (method, params = {}) => new Promise((res, rej) => { const i = ++mid; pending.set(i, [res, rej]); ws.send(JSON.stringify({id: i, method, params})); });
await new Promise(r => ws.onopen = r);
ws.onmessage = e => { const m = JSON.parse(e.data); if (m.id) { const [res, rej] = pending.get(m.id) || []; pending.delete(m.id); m.error ? rej?.(new Error(m.error.message)) : res?.(m.result); } else handlers[m.method]?.(m.params); };
await send("Page.enable"); await send("Runtime.enable");
await send("Emulation.setDeviceMetricsOverride", {width: W, height: H, deviceScaleFactor: 1, mobile: false});
const ev = async (expr) => (await send("Runtime.evaluate", {expression: expr, awaitPromise: true, returnByValue: true})).result?.value;
const sleep = ms => new Promise(r => setTimeout(r, ms));

// ---------- screencast ----------
let frames = [], recording = false, sceneDir = "", frameNo = 0;
handlers["Page.screencastFrame"] = async p => {
  await send("Page.screencastFrameAck", {sessionId: p.sessionId}).catch(() => {});
  if (!recording) return;
  const f = path.join(sceneDir, String(frameNo++).padStart(5, "0") + ".jpg");
  fs.writeFileSync(f, Buffer.from(p.data, "base64")); frames.push([f, p.metadata.timestamp]);
};
async function startRec(id) { sceneDir = path.join(OUT, "frames", `scene_${id}`); fs.mkdirSync(sceneDir, {recursive: true}); frames = []; frameNo = 0; recording = true;
  await send("Page.startScreencast", {format: "jpeg", quality: 85, maxWidth: W, maxHeight: H, everyNthFrame: 1}); }
async function stopRec(id, seconds) {
  recording = false; await send("Page.stopScreencast");
  if (!frames.length) throw new Error("no frames for scene " + id);
  const t0 = frames[0][1], lines = [];
  for (let i = 0; i < frames.length; i++) {
    const t = frames[i][1] - t0, next = i + 1 < frames.length ? frames[i + 1][1] - t0 : seconds;
    const d = Math.max(0.01, Math.min(next, seconds) - t); if (t >= seconds) break;
    lines.push(`file '${path.resolve(frames[i][0])}'\nduration ${d.toFixed(3)}`);
  }
  lines.push(`file '${path.resolve(frames[frames.length - 1][0])}'`);
  fs.writeFileSync(path.join(sceneDir, "frames.txt"), lines.join("\n") + "\n");
  console.log(`scene ${id}: ${frames.length} frames, ${seconds.toFixed(1)} s`);
}

// ---------- page helpers: a drawn cursor, smooth scroll, clicks ----------
const CURSOR = `(() => { if (document.getElementById("__cur")) return; const c = document.createElement("div"); c.id = "__cur";
  c.style.cssText = "position:fixed;left:0;top:0;width:22px;height:22px;z-index:99999;pointer-events:none;transform:translate(-3px,-2px);transition:left .55s cubic-bezier(.3,.7,.3,1),top .55s cubic-bezier(.3,.7,.3,1)";
  c.innerHTML = '<svg viewBox="0 0 24 24" width="22" height="22"><path d="M4 2l14 11-6 1 4 7-3 1-4-7-5 5z" fill="#fff" stroke="#111" stroke-width="1.6" stroke-linejoin="round"/></svg>';
  document.body.appendChild(c); c.style.left = "960px"; c.style.top = "600px"; })()`;
const ensureCursor = () => ev(CURSOR);
let cur = {x: 960, y: 600};
async function moveTo(x, y, ms = 600) { cur = {x, y}; await ev(`(() => { const c = document.getElementById("__cur"); if (c) { c.style.left = "${x}px"; c.style.top = "${y}px"; } })()`); await send("Input.dispatchMouseEvent", {type: "mouseMoved", x, y}); await sleep(ms); }
async function rectOf(sel, nth = 0) { return ev(`(() => { const el = document.querySelectorAll(${JSON.stringify(sel)})[${nth}]; if (!el) return null; const r = el.getBoundingClientRect(); return {x: r.left + r.width / 2, y: r.top + r.height / 2, w: r.width, h: r.height, left: r.left, top: r.top}; })()`); }
async function hover(sel, nth = 0, ms = 900) { const r = await rectOf(sel, nth); if (!r) { console.warn("missing", sel); return null; } await moveTo(r.x, r.y, ms); return r; }
async function click(sel, nth = 0, settle = 900) {
  const r = await hover(sel, nth, 650); if (!r) return;
  await ev(`(() => { const c = document.getElementById("__cur"); if (c) { c.style.transform = "translate(-3px,-2px) scale(.8)"; setTimeout(() => c.style.transform = "translate(-3px,-2px)", 160); } })()`);
  await send("Input.dispatchMouseEvent", {type: "mousePressed", x: r.x, y: r.y, button: "left", clickCount: 1});
  await send("Input.dispatchMouseEvent", {type: "mouseReleased", x: r.x, y: r.y, button: "left", clickCount: 1});
  await sleep(settle);
}
async function scrollToSel(sel, offset = 90, ms = 1100) { await ev(`(() => { const el = document.querySelector(${JSON.stringify(sel)}); if (el) window.scrollTo({top: el.getBoundingClientRect().top + window.scrollY - ${offset}, behavior: "smooth"}); })()`); await sleep(ms); }
async function scrollToText(text, offset = 90, ms = 1100) { await ev(`(() => { const el = [...document.querySelectorAll("h2")].find(h => h.textContent.trim().startsWith(${JSON.stringify(text)})); if (el) window.scrollTo({top: el.getBoundingClientRect().top + window.scrollY - ${offset}, behavior: "smooth"}); })()`); await sleep(ms); }
async function goto(url) { await send("Page.navigate", {url}); await new Promise(r => { handlers["Page.loadEventFired"] = () => { handlers["Page.loadEventFired"] = null; r(); }; }); await sleep(900); await ensureCursor(); await ev(`document.fonts && document.fonts.ready`); }
async function select(sel, value) { const r = await hover(sel, 0, 600); await ev(`(() => { const s = document.querySelector(${JSON.stringify(sel)}); s.value = ${JSON.stringify(value)}; s.dispatchEvent(new Event("change")); })()`); await sleep(700); }
async function waitFor(expr, timeout = 15000) { const t0 = Date.now(); while (Date.now() - t0 < timeout) { if (await ev(expr)) return true; await sleep(150); } console.warn("timeout waiting for", expr); return false; }
const runDone = `!document.querySelector("#run").disabled && !!document.querySelector("#diag .verdict")`;

// ---------- scenes ----------
const ABOUT = `${BASE}about.html`, WB = `${BASE}index.html`, END = `${BASE}end.html`;
const scenes = {
  1: async () => { await goto(ABOUT); await ev("window.scrollTo(0,0)"); await moveTo(1500, 700, 100); },
  2: async () => { await scrollToSel("#tSlider", 160); const r = await rectOf("#tSlider");
    const at = v => r.left + 8 + (r.w - 16) * v / 100; const lo = Date.UTC(2017, 8, 1), hi = Date.UTC(2018, 7, 1);
    const toV = iso => Math.round((Date.UTC(...iso) - lo) / (hi - lo) * 100);
    let v = toV([2017, 9, 1]); await ev(`(() => { const s = document.querySelector("#tSlider"); s.value = ${v}; s.dispatchEvent(new Event("input")); })()`); await moveTo(at(v), r.y, 500); await sleep(900);
    const target = toV([2018, 0, 1]);
    for (let i = v; i <= target; i++) { await ev(`(() => { const s = document.querySelector("#tSlider"); s.value = ${i}; s.dispatchEvent(new Event("input")); })()`); await moveTo(at(i), r.y, 0); await sleep(140); }
    await sleep(1200); await hover(".tlpanel table", 0, 800); },
  3: async () => { await scrollToText("Where the future gets in", 110); for (let i = 1; i <= 5; i++) await hover("table tr td b", i - 1, 420); await sleep(700); await scrollToText("One rule for all five", 140); await hover(".rule", 0, 700); },
  4: async () => { await scrollToText("What it needs from you", 110); await sleep(1200); await scrollToText("Results", 110); await hover("table.results tr td", 0, 800); await sleep(2500);
    await ev(`window.scrollTo({top: 0, behavior: "smooth"})`); await sleep(1400); await click(".cta", 0, 400); },
  5: async () => { await goto(WB); await moveTo(400, 400, 900); await moveTo(1250, 300, 900); await moveTo(1250, 700, 900); },
  6: async () => { await click("#run", 0, 300); await waitFor(runDone); await hover("#diag .wit tr.hot", 0, 900); await sleep(600); await hover("#editor .ln.leak", 0, 900); },
  7: async () => { await hover("#applyFix", 0, 700); await click("#applyFix", 0, 1400); await click("#run", 0, 300); await waitFor(runDone); await hover("#diag .wit", 0, 800); },
  8: async () => { await select("#ex", "status"); await click("#run", 0, 300); await waitFor(runDone); await hover("#diag .card .mono", 0, 900); },
  9: async () => { await click("#btnSchema", 0, 900); await click('#schemaMode button[data-mode="llm"]', 0, 900); await click('.tbl[data-name="orders"]', 0, 900); await hover("#reason p", 0, 1200); await hover('.tbl[data-name="orders"] .r-snap', 0, 900); await sleep(400); await click("#schema [data-close]", 0, 500); },
  10: async () => { await select("#db", "f1"); await click("#run", 0, 300); await waitFor(runDone); await hover("#diag .chart circle", 1, 900); await hover("#diag .wit td.full", 0, 900); },
  11: async () => { await select("#db", "event"); await click("#run", 0, 300); await waitFor(runDone); await hover("#diag .wit td.full", 0, 900); await hover("#diag .wit td.full", 2, 700); },
  12: async () => { await goto(END); await moveTo(1700, 1000, 100); },
};

fs.mkdirSync(OUT, {recursive: true});
const ids = (process.env.SCENES ? process.env.SCENES.split(",").map(Number) : Object.keys(scenes).map(Number));
for (const id of ids) {
  const seconds = dur(id);
  const t0 = Date.now(); await startRec(id);
  try { await scenes[id](); } catch (e) { console.warn(`scene ${id} action error:`, e.message); }
  const left = seconds * 1000 - (Date.now() - t0);
  if (left < 0) console.warn(`scene ${id}: actions took ${((Date.now() - t0) / 1000).toFixed(1)} s, longer than the audio (${seconds} s)`);
  await sleep(Math.max(300, left));
  await stopRec(id, seconds);
}
await send("Target.closeTarget", {targetId: tab.id}).catch(() => {}); ws.close(); process.exit(0);
