// 原型清单：页面、演示账号、流程。等号右边必须是严格 JSON（双引号、无注释、无尾逗号），
// scripts/prototype-check.py 和 prototype-walk.mjs 都读这个文件。格式见 skills/hq-design/prototype-schema.md
window.PROTOTYPE = {
  "schema": "hq-prototype/1",
  "product": "示例产品",
  "platform": "web",
  "entry": "P-01",
  "login": "P-01",
  "accounts": [
    {"id": "demo", "email": "demo@example.com", "password": "Demo1234", "name": "林晓", "role": "user", "note": "有数据的老用户"},
    {"id": "new", "email": "new@example.com", "password": "Demo1234", "name": "新用户", "role": "user", "first": true, "note": "首次使用的新用户"}
  ],
  "pages": [
    {"id": "P-01", "title": "登录", "file": "pages/login.html", "requirements": [], "auth": false,
     "states": ["default", "loading", "error"],
     "na": {"empty": "登录页没有列表数据", "forbidden": "公开页面", "first": "首次使用引导在首页"}},
    {"id": "P-02", "title": "首页", "file": "pages/home.html", "requirements": [], "auth": true,
     "states": ["default", "empty", "loading", "error", "forbidden", "first"], "na": {}}
  ],
  "flows": [
    {"id": "FL-01", "title": "演示账号登录后看到首页", "requirements": [],
     "steps": [
       {"goto": "P-01"},
       {"fill": "[data-testid=email]", "value": "demo@example.com"},
       {"fill": "[data-testid=password]", "value": "Demo1234"},
       {"click": "[data-testid=submit]"},
       {"expect": "P-02"},
       {"see": "[data-testid=item-list]"}
     ]}
  ]
};
