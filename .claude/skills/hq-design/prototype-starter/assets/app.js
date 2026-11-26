/* 原型运行时：模拟登录、模拟数据、界面状态、页面跳转、原型工具条。
   每个页面按顺序引入 ../manifest.js、../data/seed.js、../assets/app.js，<body data-hq-page="P-xx">。
   页面里的每种状态写成一个 <section data-hq-state="default|empty|loading|error|forbidden|first">
   （一个区块属于几种状态时用空格分开，如 data-hq-state="default error"），由 HQ.show(状态) 切换；地址栏 ?state=<状态> 可以强制显示某种状态（评审和自动走查用）。 */
(function () {
  "use strict";
  var M = window.PROTOTYPE || { pages: [], accounts: [] };
  var KEY = "hq.proto." + (M.product || "app") + ".";
  var store = {
    get: function (k, d) { try { var v = localStorage.getItem(KEY + k); return v === null ? d : JSON.parse(v); } catch (e) { return d; } },
    set: function (k, v) { try { localStorage.setItem(KEY + k, JSON.stringify(v)); } catch (e) { /* 隐私模式等 */ } },
    del: function (k) { try { localStorage.removeItem(KEY + k); } catch (e) { /* ignore */ } },
  };
  var params = new URLSearchParams(location.search);
  var forced = params.get("state");
  var here = document.body ? document.body.getAttribute("data-hq-page") : null;
  var pageOf = function (id) { return M.pages.filter(function (p) { return p.id === id; })[0]; };
  var root = location.pathname.indexOf("/pages/") >= 0 ? "../" : "";

  function url(id, query) {
    var p = pageOf(id);
    if (!p) { console.error("[hq] 未知页面 " + id); return "#"; }
    return root + p.file + (query ? "?" + query : "");
  }

  // ---------- 模拟数据：首次打开时从 data/seed.js 复制一份到 localStorage，之后增删改都写在这里 ----------
  var db = {
    all: function (name) {
      var data = store.get("db", null);
      if (!data) { data = JSON.parse(JSON.stringify(window.SEED || {})); store.set("db", data); }
      return data[name] || [];
    },
    save: function (name, rows) {
      var data = store.get("db", null) || JSON.parse(JSON.stringify(window.SEED || {}));
      data[name] = rows; store.set("db", data);
    },
    insert: function (name, row) {
      var rows = db.all(name); row.id = row.id || name + "-" + Date.now(); rows.unshift(row); db.save(name, rows); return row;
    },
    update: function (name, id, patch) {
      var rows = db.all(name).map(function (r) { return r.id === id ? Object.assign({}, r, patch) : r; }); db.save(name, rows);
    },
    remove: function (name, id) { db.save(name, db.all(name).filter(function (r) { return r.id !== id; })); },
    reset: function () { store.del("db"); store.del("session"); store.del("users"); },
  };

  // ---------- 模拟登录：manifest.accounts 里的演示账号 + 原型里注册的账号 ----------
  var auth = {
    users: function () { return (M.accounts || []).concat(store.get("users", [])); },
    current: function () { return store.get("session", null); },
    signIn: function (email, password) {
      var u = auth.users().filter(function (a) { return a.email === email && a.password === password; })[0];
      if (!u) return null;
      store.set("session", { id: u.id, email: u.email, name: u.name || u.email, role: u.role || "user", first: !!u.first });
      return auth.current();
    },
    signInAs: function (accountId) {
      var u = auth.users().filter(function (a) { return a.id === accountId; })[0];
      return u ? auth.signIn(u.email, u.password) : null;
    },
    register: function (user) {
      if (auth.users().some(function (a) { return a.email === user.email; })) return { error: "该邮箱已注册" };
      var u = Object.assign({ id: "u-" + Date.now(), role: "user", first: true }, user);
      store.set("users", store.get("users", []).concat([u]));
      return { user: auth.signIn(u.email, u.password) };
    },
    signOut: function () { store.del("session"); },
    markOnboarded: function () { var s = auth.current(); if (s) { s.first = false; store.set("session", s); } },
  };

  // ---------- 界面状态 ----------
  function show(state) {
    var want = forced || state;
    var nodes = document.querySelectorAll("[data-hq-state]");
    var has = function (n, s) { return n.getAttribute("data-hq-state").split(/\s+/).indexOf(s) >= 0; };
    var hit = false;
    nodes.forEach(function (n) { if (has(n, want)) hit = true; });
    if (!hit) want = "default";
    nodes.forEach(function (n) { n.hidden = !has(n, want); });
    document.body.setAttribute("data-hq-current-state", want);
    return want;
  }

  // 模拟接口：延迟 300–700ms；?state=error 时失败，?state=empty 时返回空数组
  function api(fn, opts) {
    opts = opts || {};
    return new Promise(function (resolve, reject) {
      var delay = opts.delay != null ? opts.delay : 300 + Math.round(Math.random() * 400);
      if (forced === "loading") return; // 一直加载，便于查看加载态
      setTimeout(function () {
        if (forced === "error") return reject(new Error("网络异常，请稍后重试"));
        try { var r = fn(); resolve(forced === "empty" && Array.isArray(r) ? [] : r); } catch (e) { reject(e); }
      }, delay);
    });
  }

  function toast(msg, ms) {
    var t = document.createElement("div"); t.className = "toast"; t.setAttribute("role", "status"); t.textContent = msg;
    document.body.appendChild(t); setTimeout(function () { t.remove(); }, ms || 2200);
  }

  function go(id, query) { location.href = url(id, query); }

  // 需要登录的页面：未登录跳到登录页（manifest.login）
  function guard() {
    var p = pageOf(here);
    if (p && p.auth && !auth.current() && !forced && M.login && M.login !== here) { go(M.login, "next=" + encodeURIComponent(here)); return false; }
    return true;
  }

  // data-hq-nav="P-xx" 的元素点击即跳转（a 标签用 href 指向页面文件更好，静态检查能顺着链接走）
  document.addEventListener("click", function (e) {
    var el = e.target.closest ? e.target.closest("[data-hq-nav]") : null;
    if (el) { e.preventDefault(); go(el.getAttribute("data-hq-nav")); }
  });

  // ---------- 原型工具条：页面目录、状态切换、切换账号、重置数据 ----------
  function toolbar() {
    if (store.get("toolbar", "on") === "off" || params.get("toolbar") === "0") return;
    var wrap = document.createElement("div"); wrap.className = "hq-toolbar"; wrap.setAttribute("data-hq-toolbar", "");
    var panel = document.createElement("div"); panel.className = "panel"; panel.hidden = true;
    var p = pageOf(here);
    var h = "<h4>当前页 " + (p ? p.id + " " + p.title : "") + "</h4>";
    if (p) h += (p.states || []).map(function (s) { return '<a href="?state=' + s + '">状态：' + s + "</a>"; }).join("");
    h += "<h4>页面</h4>" + M.pages.map(function (x) { return '<a href="' + url(x.id) + '">' + x.id + " " + x.title + "</a>"; }).join("");
    h += "<h4>账号</h4>" + (M.accounts || []).map(function (a) { return '<button class="link" data-as="' + a.id + '">' + (a.note || a.email) + "</button>"; }).join("");
    h += '<h4>数据</h4><button class="link" data-reset>重置模拟数据并退出登录</button>';
    panel.innerHTML = h;
    var btn = document.createElement("button"); btn.type = "button"; btn.textContent = "原型";
    btn.onclick = function () { panel.hidden = !panel.hidden; };
    panel.addEventListener("click", function (e) {
      var as = e.target.getAttribute("data-as");
      if (as) { auth.signInAs(as); location.reload(); }
      if (e.target.hasAttribute("data-reset")) { db.reset(); location.reload(); }
    });
    wrap.appendChild(panel); wrap.appendChild(btn); document.body.appendChild(wrap);
  }

  window.HQ = { manifest: M, page: pageOf(here), state: forced, url: url, go: go, show: show, api: api, toast: toast, db: db, auth: auth, store: store };
  if (M.platform && M.platform !== "web") document.body.classList.add("platform-mobile");
  if (guard()) {
    show(forced || "default");
    document.addEventListener("DOMContentLoaded", toolbar);
    if (document.readyState !== "loading") toolbar();
  }
})();
