#!/usr/bin/env node
// Walk a clickable prototype with Playwright.
//
// hq format (manifest.js present): open every page in every declared state, screenshot it, record console
// errors, and run every flow in manifest.js step by step.
//   node prototype-walk.mjs <prototype dir> [--out <dir>] [--format md|json] [--scale 1|2]
//
// Foreign format (no manifest.js, or --foreign): an adopted folder of plain .html files. Serve it, open each
// top-level .html (or --pages a.html,b.html), record console errors, page errors, failed requests and
// HTTP >= 400, follow in-page hash routes (a[href^="#"], [data-page]) up to --max-views, and optionally run
// a project script for states and flows:
//   node prototype-walk.mjs <dir> --foreign [--pages a.html,b.html] [--max-views 200] [--script flows.mjs]
//        [--viewport 390x844] [--out <dir>] [--format md|json] [--scale 1|2]
// The script's default export is `async ({ page, context, baseUrl, step, check, shot }) => {}`:
//   step(label[, fn])  start a named step (errors captured from now on are attributed to it); with fn, run it
//                      and record a thrown error as a failure of that step
//   check(cond, label) record an assertion (cond may be a value, a promise or a function)
//   shot(name)         screenshot the current page into --out (no-op without --out)
// Errors captured while the script runs count as failures.
//
// Exit codes: 0 all passed, 1 failures, 2 bad arguments / unreadable manifest or script, 3 Playwright not available.
// Format: skills/hq-design/prototype-schema.md
import { createRequire } from "node:module";
import { createServer } from "node:http";
import { readFileSync, existsSync, mkdirSync, statSync, readdirSync } from "node:fs";
import { join, resolve, extname, normalize, sep } from "node:path";
import { pathToFileURL } from "node:url";
import vm from "node:vm";

const args = process.argv.slice(2);
const opt = (name, dflt) => { const i = args.indexOf(name); return i >= 0 ? args.splice(i, 2)[1] : dflt; };
const flag = (name) => { const i = args.indexOf(name); if (i >= 0) args.splice(i, 1); return i >= 0; };
const out = opt("--out", null);
const format = opt("--format", "md");
const scale = Number(opt("--scale", "2"));
const pagesOpt = opt("--pages", null);
const maxViews = Number(opt("--max-views", "200"));
const scriptOpt = opt("--script", null);
const viewportOpt = opt("--viewport", null);
const foreignFlag = flag("--foreign");
const root = args[0] ? resolve(args[0]) : null;
const USAGE = "用法: node prototype-walk.mjs <原型目录> [--out <截图目录>] [--format md|json] [--scale 1|2]\n" +
  "      外来格式（没有 manifest.js 或加 --foreign）: [--pages a.html,b.html] [--max-views 200] [--script <flows.mjs>] [--viewport 390x844]";
if (!root || !existsSync(root) || !statSync(root).isDirectory() || !["md", "json"].includes(format) ||
    !(maxViews > 0) || (viewportOpt && !/^\d+x\d+$/.test(viewportOpt))) {
  console.error(USAGE);
  process.exit(2);
}
const foreign = foreignFlag || !existsSync(join(root, "manifest.js"));

let man = null;
let foreignPages = [];
let scriptPath = null;
if (!foreign) {
  try {
    const ctx = { window: {} };
    vm.runInNewContext(readFileSync(join(root, "manifest.js"), "utf8"), ctx, { timeout: 1000 });
    man = ctx.window.PROTOTYPE;
    if (!man || !Array.isArray(man.pages)) throw new Error("window.PROTOTYPE.pages 缺失");
  } catch (e) {
    console.error("错误: 读不了 manifest.js: " + e.message);
    process.exit(2);
  }
} else {
  foreignPages = pagesOpt
    ? pagesOpt.split(",").map((x) => x.trim()).filter(Boolean)
    : readdirSync(root).filter((f) => /\.html?$/i.test(f) && statSync(join(root, f)).isFile()).sort();
  const missing = foreignPages.filter((f) => !existsSync(join(root, f)));
  if (!foreignPages.length || missing.length) {
    console.error(missing.length ? "错误: 页面不存在：" + missing.join(", ") : "错误: 目录顶层没有 .html 文件（可用 --pages 指定）");
    process.exit(2);
  }
  if (scriptOpt) {
    scriptPath = resolve(scriptOpt);
    if (!existsSync(scriptPath)) { console.error("错误: 脚本不存在：" + scriptOpt); process.exit(2); }
  }
}
let scriptFn = null;
if (scriptPath) {
  try {
    scriptFn = (await import(pathToFileURL(scriptPath).href)).default;
  } catch (e) {
    console.error("错误: 载入脚本失败：" + e.message.split("\n")[0]);
    process.exit(2);
  }
  if (typeof scriptFn !== "function") { console.error("错误: 脚本必须 export default 一个 async 函数"); process.exit(2); }
}

function loadPlaywright() {
  const bases = [import.meta.url, join(process.cwd(), "noop.js"), join(root, "noop.js")];
  for (const b of bases) {
    try { return createRequire(b)("playwright"); } catch { /* try next */ }
  }
  return null;
}
const pw = loadPlaywright();
if (!pw) {
  console.error("没有找到 Playwright（require('playwright') 失败），跳过自动走查。");
  process.exit(3);
}

const TYPES = { ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
  ".json": "application/json", ".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
  ".webp": "image/webp", ".gif": "image/gif", ".woff2": "font/woff2", ".woff": "font/woff", ".ico": "image/x-icon" };
const server = createServer((req, res) => {
  let p = normalize(join(root, decodeURIComponent(new URL(req.url, "http://x").pathname)));
  if ((p === root || p.startsWith(root + sep)) && existsSync(p) && statSync(p).isDirectory()) p = join(p, "index.html");
  if (!(p === root || p.startsWith(root + sep)) || !existsSync(p) || statSync(p).isDirectory()) { res.writeHead(404); res.end(); return; }
  res.writeHead(200, { "content-type": TYPES[extname(p).toLowerCase()] || "application/octet-stream" });
  res.end(readFileSync(p));
});
await new Promise((r) => server.listen(0, "127.0.0.1", r));
const base = `http://127.0.0.1:${server.address().port}/`;
if (out) mkdirSync(out, { recursive: true });
if (foreign) process.exit(await walkForeign());

const mobile = man.platform && man.platform !== "web";
const viewport = mobile ? { width: 390, height: 844 } : { width: 1440, height: 900 };
const key = "hq.proto." + (man.product || "app") + ".";
const pageById = Object.fromEntries(man.pages.map((p) => [p.id, p]));
const results = { pages: [], flows: [], screenshots: 0 };

const browser = await pw.chromium.launch();
async function newContext(account) {
  const ctx = await browser.newContext({ viewport, deviceScaleFactor: scale, isMobile: mobile, hasTouch: mobile });
  await ctx.addInitScript(({ key, acc }) => {
    try {
      localStorage.setItem(key + "toolbar", JSON.stringify("off"));
      if (acc && !localStorage.getItem(key + "session")) {
        localStorage.setItem(key + "session", JSON.stringify({ id: acc.id, email: acc.email, name: acc.name || acc.email, role: acc.role || "user", first: !!acc.first }));
      }
    } catch { /* ignore */ }
  }, { key, acc: account || null });
  return ctx;
}
function watch(page, sink) {
  page.on("console", (m) => { if (m.type() === "error") sink.push("console: " + m.text()); });
  page.on("pageerror", (e) => sink.push("pageerror: " + e.message));
}

// 1. every page x every declared state
const regular = (man.accounts || []).find((a) => !a.first) || (man.accounts || [])[0];
for (const p of man.pages) {
  for (const state of p.states || ["default"]) {
    const ctx = await newContext(p.auth ? regular : null);
    const page = await ctx.newPage();
    const errors = [];
    watch(page, errors);
    let ok = true;
    try {
      await page.goto(base + p.file + "?state=" + state, { waitUntil: "load", timeout: 10000 });
      await page.waitForTimeout(state === "default" ? 900 : 300); // let mock API calls settle
      const shown = await page.evaluate((s) => {
        const nodes = [...document.querySelectorAll("[data-hq-state]")].filter((n) => n.getAttribute("data-hq-state").split(/\s+/).includes(s));
        return nodes.some((n) => !n.hidden && n.getClientRects().length > 0);
      }, state);
      if (!shown) { ok = false; errors.push(`状态 ${state} 的区块没有显示出来`); }
      const at = await page.getAttribute("body", "data-hq-page");
      if (at !== p.id) { ok = false; errors.push(`打开后停在 ${at}，不是 ${p.id}（被跳转了？）`); }
      if (out) { await page.screenshot({ path: join(out, `${p.id}-${state}.png`), fullPage: true }); results.screenshots++; }
    } catch (e) { ok = false; errors.push(e.message.split("\n")[0]); }
    if (errors.length) ok = false;
    results.pages.push({ page: p.id, state, ok, errors });
    await ctx.close();
  }
}

// 2. flows
for (const f of man.flows || []) {
  const acc = f.account ? (man.accounts || []).find((a) => a.id === f.account) : null;
  const ctx = await newContext(acc);
  const page = await ctx.newPage();
  const errors = [];
  watch(page, errors);
  let failedAt = null;
  const steps = f.steps || [];
  for (let i = 0; i < steps.length; i++) {
    const s = steps[i];
    try {
      if (s.goto) await page.goto(base + pageById[s.goto].file, { waitUntil: "load", timeout: 10000 });
      else if (s.click) await page.click(s.click, { timeout: 5000 });
      else if (s.fill) await page.fill(s.fill, s.value ?? "", { timeout: 5000 });
      else if (s.select) await page.selectOption(s.select, s.value ?? "", { timeout: 5000 });
      else if (s.expect) await page.waitForSelector(`body[data-hq-page="${s.expect}"]`, { timeout: 5000 });
      else if (s.see) await page.locator(s.see).first().waitFor({ state: "visible", timeout: 5000 });
      else throw new Error("未知动作 " + JSON.stringify(s));
    } catch (e) {
      failedAt = i + 1;
      errors.push(`第 ${i + 1} 步 ${JSON.stringify(s)}：${e.message.split("\n")[0]}`);
      if (out) await page.screenshot({ path: join(out, `${f.id}-failed-step${i + 1}.png`), fullPage: true }).catch(() => {});
      break;
    }
  }
  if (out && failedAt === null) { await page.screenshot({ path: join(out, `${f.id}-end.png`), fullPage: true }); results.screenshots++; }
  results.flows.push({ flow: f.id, title: f.title, ok: failedAt === null && errors.length === 0, failed_step: failedAt, errors });
  await ctx.close();
}

await browser.close();
server.close();

const bad = results.pages.filter((r) => !r.ok).length + results.flows.filter((r) => !r.ok).length;
if (format === "json") {
  console.log(JSON.stringify(results, null, 2));
} else {
  console.log(`# 原型走查：${root}\n`);
  console.log(`页面状态 ${results.pages.length} 个（失败 ${results.pages.filter((r) => !r.ok).length}），流程 ${results.flows.length} 条（失败 ${results.flows.filter((r) => !r.ok).length}），截图 ${results.screenshots} 张${out ? "，在 " + out : ""}\n`);
  for (const r of results.pages.filter((r) => !r.ok)) console.log(`- ✗ ${r.page} ${r.state}：${r.errors.join("；")}`);
  for (const r of results.flows) console.log(`- ${r.ok ? "✓" : "✗"} ${r.flow} ${r.title}${r.ok ? "" : "：" + r.errors.join("；")}`);
}
process.exit(bad ? 1 : 0);


// ---- foreign format: a folder of plain .html files, no manifest.js ----
async function walkForeign() {
  const [vw, vh] = (viewportOpt || "1440x900").split("x").map(Number);
  const mobile = vw < 600;
  const browser = await pw.chromium.launch();
  const context = await browser.newContext({ viewport: { width: vw, height: vh }, deviceScaleFactor: scale, isMobile: mobile, hasTouch: mobile });
  const res = { mode: "foreign", root, pages: foreignPages, views: [], truncated: false, script: scriptPath, steps: [], assertions: [],
    errors: [], failures: [], screenshots: 0 };
  let sink = null; // where captured errors go right now
  const record = (m) => { if (sink) sink(m); };
  const watchAll = (page) => {
    page.on("console", (m) => { if (m.type() === "error" && !/^Failed to load resource/.test(m.text())) record("console: " + m.text()); });
    page.on("pageerror", (e) => record("pageerror: " + e.message));
    page.on("requestfailed", (r) => { const t = r.failure()?.errorText || ""; if (!/ERR_ABORTED/.test(t)) record(`requestfailed: ${r.url()} (${t})`); });
    page.on("response", (r) => { if (r.status() >= 400 && !/\/favicon\.ico$/.test(r.url())) record(`HTTP ${r.status()}: ${r.url()}`); });
  };
  const used = new Set();
  const shotName = (raw) => {
    let n = raw.replace(/[^\p{L}\p{N}_.-]+/gu, "_").replace(/^_+|_+$/g, "").slice(0, 80) || "view";
    for (let i = 2; used.has(n); i++) n = n.replace(/~\d+$/, "") + "~" + i;
    used.add(n);
    return join(out, n + ".png");
  };

  // 1. every top-level page plus the hash routes it links to
  const page = await context.newPage();
  page.setDefaultTimeout(5000);
  watchAll(page);
  const discover = () => page.evaluate(() => {
    const found = [...document.querySelectorAll('a[href^="#"]')].map((a) => a.getAttribute("href"));
    for (const n of document.querySelectorAll("[data-page]")) {
      const v = (n.getAttribute("data-page") || "").trim();
      if (v) found.push(v.startsWith("#") ? v : "#" + v);
    }
    return found.filter((h) => h && h.length > 1 && h !== "#!");
  }).catch(() => []);
  outer: for (const file of foreignPages) {
    const queue = [""];
    const seen = new Set(queue);
    while (queue.length) {
      if (res.views.length >= maxViews) { res.truncated = true; break outer; }
      const hash = queue.shift();
      const v = { page: file, view: hash, ok: true, errors: [], screenshot: null };
      res.views.push(v);
      sink = (m) => v.errors.push(m);
      try {
        await page.goto("about:blank");
        await page.goto(base + file + hash, { waitUntil: "load", timeout: 10000 });
        await page.waitForTimeout(hash ? 250 : 500);
        if (out) { v.screenshot = shotName(file.replace(/\.html?$/i, "") + (hash ? "--" + hash.slice(1) : "")); await page.screenshot({ path: v.screenshot, fullPage: true }); res.screenshots++; }
        for (const h of await discover()) if (!seen.has(h)) { seen.add(h); queue.push(h); }
      } catch (e) { v.errors.push(e.message.split("\n")[0]); }
      sink = null;
      v.ok = v.errors.length === 0;
    }
  }
  await page.close();

  // 2. project script: states and flows
  if (scriptFn) {
    const sp = await context.newPage();
    sp.setDefaultTimeout(5000);
    watchAll(sp);
    let cur = null;
    const start = (label) => { cur = { label, ok: true, errors: [] }; res.steps.push(cur); return cur; };
    sink = (m) => { if (!cur) start("（脚本开始）"); cur.errors.push(m); cur.ok = false; };
    const shot = async (name) => {
      if (!out) return null;
      const p = shotName("script-" + String(name));
      await sp.screenshot({ path: p, fullPage: true });
      res.screenshots++;
      return p;
    };
    const step = async (label, fn) => {
      const s = start(String(label));
      if (!fn) return undefined;
      try { return await fn(); } catch (e) { s.errors.push("异常: " + e.message.split("\n")[0]); s.ok = false; return undefined; }
    };
    const check = async (cond, label) => {
      const a = { label: String(label), ok: false, step: cur ? cur.label : null };
      try { a.ok = !!(await (typeof cond === "function" ? cond() : cond)); } catch (e) { a.error = e.message.split("\n")[0]; }
      res.assertions.push(a);
      if (!a.ok && out) await shot("failed-" + a.label).catch(() => {});
      return a.ok;
    };
    try {
      await scriptFn({ page: sp, context, baseUrl: base, step, check, shot });
      await sp.waitForTimeout(200); // late errors
    } catch (e) {
      if (!cur) start("（脚本）");
      cur.errors.push("脚本异常: " + e.message.split("\n")[0]);
      cur.ok = false;
    }
    sink = null;
    await sp.close();
  }
  await browser.close();
  server.close();

  for (const v of res.views) for (const e of v.errors) res.errors.push(`${v.page}${v.view}: ${e}`);
  for (const s of res.steps) for (const e of s.errors) res.errors.push(`脚本「${s.label}」: ${e}`);
  for (const v of res.views.filter((v) => !v.ok)) res.failures.push(`视图 ${v.page}${v.view}：${v.errors.join("；")}`);
  for (const s of res.steps.filter((s) => !s.ok)) res.failures.push(`步骤「${s.label}」：${s.errors.join("；")}`);
  for (const a of res.assertions.filter((a) => !a.ok)) res.failures.push(`断言「${a.label}」不成立${a.step ? "（步骤「" + a.step + "」）" : ""}${a.error ? "：" + a.error : ""}`);

  if (format === "json") {
    console.log(JSON.stringify(res, null, 2));
  } else {
    const nf = (xs) => xs.filter((x) => !x.ok).length;
    console.log(`# 原型走查（外来格式，无 manifest.js）：${root}\n`);
    console.log(`页面 ${foreignPages.length} 个，视图 ${res.views.length} 个（失败 ${nf(res.views)}）${res.truncated ? "，已达 --max-views " + maxViews + " 上限" : ""}；` +
      `脚本${scriptPath ? ` 步骤 ${res.steps.length} 个（失败 ${nf(res.steps)}），断言 ${res.assertions.length} 条（失败 ${nf(res.assertions)}）` : "：未提供 --script"}；` +
      `截图 ${res.screenshots} 张${out ? "，在 " + out : ""}\n`);
    console.log(`## 失败（${res.failures.length}）`);
    console.log(res.failures.map((x) => "- ✗ " + x).join("\n") || "- 无");
    if (res.assertions.length) {
      console.log("\n## 断言");
      for (const a of res.assertions) console.log(`- ${a.ok ? "✓" : "✗"} ${a.label}`);
    }
    console.log("\n## 视图");
    for (const v of res.views) console.log(`- ${v.ok ? "✓" : "✗"} ${v.page}${v.view}`);
  }
  return res.failures.length ? 1 : 0;
}
