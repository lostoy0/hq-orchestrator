# 原型清单格式（manifest.js）— hq-prototype/1

可点击原型的单一清单：页面、演示账号、流程都写在 `design/prototype/manifest.js` 里。原型运行时（`assets/app.js`）、静态检查（`scripts/prototype-check.py`）、自动走查（`scripts/prototype-walk.mjs`）都读它。

文件写成 `window.PROTOTYPE = { … };`，等号右边是**严格 JSON**（双引号、无注释、无尾逗号）。这样原型直接双击打开也能用（浏览器不允许 `file://` 页面读本地 JSON 文件），脚本也能当 JSON 解析。

## 顶层

| 字段 | 必填 | 含义 |
|---|---|---|
| schema | 是 | `"hq-prototype/1"` |
| product | 是 | 产品名 |
| platform | 是 | `web` / `ios` / `android` / `mini`（小程序）。不是 `web` 时页面在桌面上按手机宽度居中显示，走查截图用手机尺寸 |
| entry | 是 | 入口页面编号（“开始体验”进入的页面） |
| login | 有需要登录的页面时必填 | 登录页编号；未登录打开需登录的页面会跳到这里 |
| accounts | 有需要登录的页面时至少 1 个 | 演示账号：`id`、`email`、`password`、`name`、`role`、`note`（给人看的说明，如“付费会员”），可选 `first: true`（首次使用的新用户） |
| pages | 是 | 页面，见下 |
| flows | 是 | 流程，见下 |

## pages

| 字段 | 必填 | 含义 |
|---|---|---|
| id | 是 | `P-01`…，和 `design/screens.md` 一致 |
| title | 是 | 页面名 |
| file | 是 | 相对原型根目录的路径，如 `pages/login.html`。文件名不以 `_` 开头 |
| requirements | 是 | 这页服务哪些需求（`F-xxx`）；纯导航页可为空数组 |
| auth | 是 | 是否需要登录 |
| states | 是 | 这页做了哪些状态：`default`、`empty`、`loading`、`error`、`forbidden`、`first`。必须含 `default` |
| na | 是 | 没做的状态及原因，如 `{"forbidden": "公开页面"}`。六种状态要么在 `states`，要么在 `na` |

页面文件里：`<body data-hq-page="P-xx">`；`states` 里的每种状态都要有 `data-hq-state` 区块（一个区块可以属于几种状态，空格分开）；引入 `../manifest.js`、`../data/seed.js`、`../assets/app.js`，以及 `../assets/tokens.css`、`../assets/base.css`。

## flows

| 字段 | 必填 | 含义 |
|---|---|---|
| id | 是 | `FL-01`… |
| title | 是 | 流程名，如“注册到完成第一笔记账” |
| requirements | 是 | 覆盖哪些需求 |
| account | 否 | 流程开始前先登录的演示账号 `id`；不写就以未登录状态开始 |
| steps | 是 | 按顺序执行的步骤，第一步必须是 `goto` |

步骤（每步一个对象，只用一种动作）：

| 动作 | 写法 | 含义 |
|---|---|---|
| goto | `{"goto": "P-01"}` | 打开页面 |
| click | `{"click": "[data-testid=submit]"}` | 点击 |
| fill | `{"fill": "[data-testid=email]", "value": "a@b.com"}` | 输入 |
| select | `{"select": "[data-testid=plan]", "value": "year"}` | 下拉选择 |
| expect | `{"expect": "P-02"}` | 断言当前在某页（等 `body[data-hq-page]` 变成它，最多 5 秒） |
| see | `{"see": "[data-testid=item-list]"}` 或 `{"see": "text=已保存"}` | 断言某元素或文字可见 |

选择器一律用 `[data-testid=…]`（`see` 也可以用 `text=…`），静态检查会核对 testid 在页面里存在。

## 检查

```bash
python3 <hq 技能目录>/scripts/prototype-check.py design/prototype [--prd docs/product/prd.md]
node <hq 技能目录>/scripts/prototype-walk.mjs design/prototype --out design/screens
```

- `prototype-check.py`（只读，只要 Python）：清单格式、文件存在、状态区块齐全、本地链接都能打开、页面都能从入口走到、流程引用的页面和 testid 存在、没有引用外部网络资源、页面里没写死颜色；带 `--prd` 时检查每个有界面的 P0/P1 功能都有页面、P0 功能都有流程覆盖。
- `prototype-walk.mjs`（需要 Node 和 Playwright）：启动本地服务，逐页逐状态打开并截图到 `--out`，记录控制台报错，按 `flows` 逐步执行。退出码 0 = 全部通过，1 = 有失败，2 = 参数错误或清单、脚本读不了，3 = 没有 Playwright（跳过走查，在评审记录里写明）。

## 外来格式原型

接管的原型如果只是一组普通 .html 文件（自带状态切换，没有 `manifest.js`），两个脚本自动进入外来格式模式（也可加 `--foreign` 强制），报告开头会写明模式：

```bash
python3 <hq 技能目录>/scripts/prototype-check.py <原型目录> [--prd <需求文档>] [--allow-external] [--id-prefixes REQ,NFR]
node <hq 技能目录>/scripts/prototype-walk.mjs <原型目录> [--pages a.html,b.html] [--max-views 200] [--script .hq/prototype-flows.mjs] [--viewport 390x844] [--out <截图目录>]
```

- `prototype-check.py`：列出所有 .html；本地的 `href`/`src`（`#` 锚点、`data:`、`mailto:`、`tel:` 除外）都要指向存在的文件；`script`、`link`、`img` 等引用 http/https 外部资源算错误（`--allow-external` 降为警告）。带 `--prd` 时从需求文档里收集编号（标题、列表、表格开头的“大写前缀-数字”，或 `--id-prefixes` 指定的前缀），在哪个 HTML 里都没出现的给警告：这只是覆盖信号，不代表没做。
- `prototype-walk.mjs`：打开顶层每个 .html（或 `--pages` 指定的），跟着页内 `a[href^="#"]` 和 `[data-page]` 发现的 `#` 路由逐个打开，最多 `--max-views` 个；记录控制台报错、页面异常、失败的请求和 HTTP ≥400；有 `--out` 时每个视图截一张图。
- `--script <file.mjs>`：项目自己的状态和流程。走查器负责本地服务、报错收集和报告，脚本只写操作：

```js
// .hq/prototype-flows.mjs
export default async ({ page, context, baseUrl, step, check, shot }) => {
  await step("打开购物车", () => page.goto(baseUrl + "cart.html"));
  await step("加入商品甲", () => page.click("#add"));
  await check(async () => (await page.textContent("#count")) === "1", "购物车数量是 1");
  await shot("cart-after-add");
};
```

`step(名称[, 函数])` 开始一步（之后收集到的报错算在这一步；给了函数就执行它，抛错记为这一步失败）；`check(条件, 名称)` 记一条断言（条件可以是值、Promise 或函数）；`shot(名称)` 截当前页（没有 `--out` 时不截）。脚本运行期间收集到的报错都算失败。报告列出视图、步骤、断言、失败和全部报错；退出码同上。
