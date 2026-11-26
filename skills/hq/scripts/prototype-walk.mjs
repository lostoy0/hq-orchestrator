#!/usr/bin/env node
// Walk a /hq-design clickable prototype with Playwright: open every page in every declared state,
// screenshot it, record console errors, and run every flow in manifest.js step by step.
//
//   node prototype-walk.mjs <prototype dir> [--out <dir>] [--format md|json] [--scale 1|2]
//
// Exit codes: 0 all passed, 1 failures, 2 bad arguments / unreadable manifest, 3 Playwright not available.
// Format: skills/hq-design/prototype-schema.md
import { createRequire } from "node:module";
import { createServer } from "node:http";
import { readFileSync, existsSync, mkdirSync, statSync } from "node:fs";
import { join, resolve, extname, normalize, sep } from "node:path";
import vm from "node:vm";

const args = process.argv.slice(2);
const opt = (name, dflt) => { const i = args.indexOf(name); return i >= 0 ? args.splice(i, 2)[1] : dflt; };
const out = opt("--out", null);
const format = opt("--format", "md");
const scale = Number(opt("--scale", "2"));
const root = args[0] ? resolve(args[0]) : null;
if (!root || !existsSync(join(root, "manifest.js"))) {
  console.error("用法: node prototype-walk.mjs <原型目录（含 manifest.js）> [--out <截图目录>] [--format md|json] [--scale 1|2]");
  process.exit(2);
}

let man;
try {
  const ctx = { window: {} };
  vm.runInNewContext(readFileSync(join(root, "manifest.js"), "utf8"), ctx, { timeout: 1000 });
  man = ctx.window.PROTOTYPE;
  if (!man || !Array.isArray(man.pages)) throw new Error("window.PROTOTYPE.pages 缺失");
} catch (e) {
  console.error("错误: 读不了 manifest.js: " + e.message);
  process.exit(2);
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
  const p = normalize(join(root, decodeURIComponent(new URL(req.url, "http://x").pathname)));
  if (!(p === root || p.startsWith(root + sep)) || !existsSync(p) || statSync(p).isDirectory()) { res.writeHead(404); res.end(); return; }
  res.writeHead(200, { "content-type": TYPES[extname(p).toLowerCase()] || "application/octet-stream" });
  res.end(readFileSync(p));
});
await new Promise((r) => server.listen(0, "127.0.0.1", r));
const base = `http://127.0.0.1:${server.address().port}/`;

const mobile = man.platform && man.platform !== "web";
const viewport = mobile ? { width: 390, height: 844 } : { width: 1440, height: 900 };
const key = "hq.proto." + (man.product || "app") + ".";
const pageById = Object.fromEntries(man.pages.map((p) => [p.id, p]));
const results = { pages: [], flows: [], screenshots: 0 };
if (out) mkdirSync(out, { recursive: true });

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
