#!/usr/bin/env python3
"""Configure hq assist workers (calibration.md rule 10) and read a CLI's model catalog.

  assist-config.py models  [--cli codex] [--catalog FILE] [--json]
  assist-config.py suggest [--cli codex] [--catalog FILE] [--json | --model-map]
  assist-config.py show    [--project DIR] [--json]
  assist-config.py check   [--project DIR] [--catalog FILE] [--json]
  assist-config.py set     --scope user|project [--project DIR] [--use codex,kimi|off] [--max-tier T0|T1|T2]
                           [--max-failures N] [--profile NAME [--cli CLI] [--models T0=m,T1=m,T2=m]
                           [--effort T0=low,...] [--env-file PATH]] [--auto-models] [--catalog FILE]

Where settings live (later wins, field by field):
  user    ${HQ_HOME:-~/.hq}/config.yaml        all projects
  project <project>/.hq/PLAYBOOK.md, assist:   this project only
  /hq --assist ...                             this run only (handled by the /hq skill, not here)
`use: []` and `<placeholder>` values count as "not set", so a PLAYBOOK made from the template does not hide
the user-level settings; `use: off` turns assist off for the project.

Model catalog (only codex for now): `codex debug models`, falling back to ${CODEX_HOME:-~/.codex}/models_cache.json.
`suggest` maps T0–T4 from the models' descriptions; it is a guess to confirm once, never a fact.

Exit codes: 0 ok, 1 check found errors, 2 bad arguments / unreadable file, 4 catalog unavailable.
"""
import argparse
import copy
import json
import os
import re
import shutil
import subprocess
import sys

TIERS = ["T0", "T1", "T2", "T3", "T4"]
ASSIST_TIERS = TIERS[:3]
EFFORTS = ["minimal", "low", "medium", "high", "xhigh", "max", "ultra"]
# Default thinking depth per tier, same as adapters/tiers.tsv.
TIER_EFFORT = {"T0": "low", "T1": "low", "T2": "medium", "T3": "medium", "T4": "high"}
KNOWN_CLIS = ["codex", "claude", "opencode", "gemini", "cursor"]
CATALOG_CLIS = ["codex"]
SMALL_WORDS = ("affordable", "easier", "simpler", "easy tasks", "lightweight", "mini", "small", "cheap")
STRONG_WORDS = ("most capable", "complex", "frontier", "hardest")
OLD_WORDS = ("legacy", "previous generation", "deprecated")
PLACEHOLDER = re.compile(r"^<.*>$")
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(SCRIPT_DIR, "..", "references", "playbook-template.md")


def die(msg, code=2):
    print("assist-config: " + msg, file=sys.stderr)
    sys.exit(code)


# ---------- tiny YAML subset: nested maps, {a: b} flow maps, [a, b] flow lists, scalars, # comments ----------

def _strip_comment(line):
    if line.lstrip().startswith("#"):
        return ""
    i = line.find(" #")
    return line if i < 0 else line[:i]


def _scalar(v):
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
        return v[1:-1]
    if v in ("null", "~", ""):
        return None
    if re.fullmatch(r"-?\d+", v):
        return int(v)
    return v


def _value(v):
    v = v.strip()
    if v.startswith("{") and v.endswith("}"):
        out = {}
        for part in v[1:-1].split(","):
            if part.strip():
                k, _, x = part.partition(":")
                out[k.strip()] = _scalar(x)
        return out
    if v.startswith("[") and v.endswith("]"):
        return [_scalar(x) for x in v[1:-1].split(",") if x.strip()]
    return _scalar(v)


def parse_yaml(text):
    root = {}
    stack = [(-1, root)]
    for raw in text.splitlines():
        line = _strip_comment(raw).rstrip()
        if not line.strip() or line.strip().startswith("```"):
            continue
        ind = len(line) - len(line.lstrip())
        key, sep, val = line.strip().partition(":")
        if not sep:
            continue
        while stack[-1][0] >= ind:
            stack.pop()
        parent = stack[-1][1]
        if val.strip() == "":
            parent[key.strip()] = {}
            stack.append((ind, parent[key.strip()]))
        else:
            parent[key.strip()] = _value(val)
    return root


# ---------- assist settings ----------

def _set(v):
    """None for 'not set': empty, placeholder, empty list/map."""
    if v is None:
        return None
    if isinstance(v, str) and (not v.strip() or PLACEHOLDER.match(v.strip())):
        return None
    if isinstance(v, (list, dict)) and not v:
        return None
    return v


def normalize(a):
    a = a if isinstance(a, dict) else {}
    out = {}
    use = a.get("use")
    if isinstance(use, str):
        use = [x.strip() for x in use.split(",") if x.strip()]
    if isinstance(use, list):
        use = [str(x) for x in use if _set(x) is not None]
        if use == ["off"]:
            out["use"] = "off"
        elif use:
            out["use"] = use
    for k in ("max_tier", "max_failures"):
        if _set(a.get(k)) is not None:
            out[k] = a[k]
    profs = {}
    for name, p in (a.get("profiles") or {}).items():
        if not isinstance(p, dict):
            continue
        q = {}
        for k in ("cli", "env_file"):
            if _set(p.get(k)) is not None:
                q[k] = str(p[k])
        for k in ("models", "effort"):
            m = {t: str(v) for t, v in (p.get(k) or {}).items() if _set(v) is not None} if isinstance(p.get(k), dict) else {}
            if m:
                q[k] = m
        if q:
            profs[str(name)] = q
    if profs:
        out["profiles"] = profs
    return out


def merge(layers):
    """layers: [(source, assist)], later wins. Returns (effective, sources)."""
    eff, src = {}, {}
    for source, a in layers:
        for k in ("use", "max_tier", "max_failures"):
            if k in a:
                eff[k], src[k] = a[k], source
        for name, p in a.get("profiles", {}).items():
            base = eff.setdefault("profiles", {}).setdefault(name, {})
            for k, v in p.items():
                if isinstance(v, dict):
                    base.setdefault(k, {}).update(v)
                    for t in v:
                        src["profiles.%s.%s.%s" % (name, k, t)] = source
                else:
                    base[k] = v
                    src["profiles.%s.%s" % (name, k)] = source
    return eff, src


def user_path():
    return os.path.join(os.path.expanduser(os.environ.get("HQ_HOME") or "~/.hq"), "config.yaml")


def playbook_path(project):
    return os.path.join(project, ".hq", "PLAYBOOK.md")


def _read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return None
    except OSError as e:
        die("读不了 %s: %s" % (path, e))


def _assist_span(lines):
    """(start, end) line indexes of the top-level `assist:` block inside a ```yaml fence, or None."""
    fence = False
    for i, l in enumerate(lines):
        if l.strip().startswith("```"):
            fence = not fence
            continue
        if fence and re.match(r"^assist:", l):
            j = i + 1
            while j < len(lines):
                s = lines[j]
                if s.strip().startswith("```") or (s and not s[0].isspace() and not s.startswith("#")):
                    break
                j += 1
            return i, j
    return None


def load_user():
    text = _read(user_path())
    return normalize(parse_yaml(text).get("assist")) if text else {}


def load_project(project):
    text = _read(playbook_path(project))
    if not text:
        return {}
    lines = text.splitlines()
    span = _assist_span(lines)
    if not span:
        return {}
    return normalize(parse_yaml("\n".join(lines[span[0]:span[1]])).get("assist"))


def effective(project):
    return merge([("user", load_user()), ("project", load_project(project))])


def _flow(m):
    return "{" + ", ".join("%s: %s" % (k, m[k]) for k in sorted(m)) + "}"


def render(a):
    use = a.get("use")
    use_s = "off" if use == "off" else "[" + ", ".join(use or []) + "]"
    out = ["assist:                   # 辅助执行者（calibration.md 规则 10），由 scripts/assist-config.py 维护；/hq --assist … 可在单次运行覆盖",
           "  use: %s%s" % (use_s, "" if use else "                 # [] = 沿用用户级 ~/.hq/config.yaml；off = 关闭")]
    for k in ("max_tier", "max_failures"):
        if k in a:
            out.append("  %s: %s" % (k, a[k]))
    if a.get("profiles"):
        out.append("  profiles:")
        for name in a["profiles"]:
            p = a["profiles"][name]
            out.append("    %s:" % name)
            for k in ("cli", "env_file"):
                if k in p:
                    out.append("      %s: %s" % (k, p[k]))
            for k in ("models", "effort"):
                if k in p:
                    out.append("      %s: %s" % (k, _flow(p[k])))
    return out


# ---------- model catalog ----------

def load_catalog(cli, catalog_file=None):
    if cli not in CATALOG_CLIS:
        return None, "unsupported_cli"
    data, source = None, None
    if catalog_file:
        try:
            with open(catalog_file, encoding="utf-8") as f:
                data, source = json.load(f), catalog_file
        except (OSError, ValueError) as e:
            die("读不了模型目录 %s: %s" % (catalog_file, e))
    else:
        exe = shutil.which("codex")
        if exe:
            try:
                r = subprocess.run([exe, "debug", "models"], capture_output=True, text=True, timeout=60)
                if r.returncode == 0:
                    data, source = json.loads(r.stdout), "codex debug models"
            except (subprocess.TimeoutExpired, ValueError, OSError):
                data = None
        if data is None:
            cache = os.path.join(os.path.expanduser(os.environ.get("CODEX_HOME") or "~/.codex"), "models_cache.json")
            try:
                with open(cache, encoding="utf-8") as f:
                    data, source = json.load(f), cache
            except (OSError, ValueError):
                return None, "codex_not_found" if not exe else "catalog_unreadable"
    models = []
    for m in (data.get("models") if isinstance(data, dict) else data) or []:
        if not isinstance(m, dict) or not m.get("slug"):
            continue
        desc = m.get("description") or ""
        low = desc.lower()
        efforts = [x.get("effort") for x in m.get("supported_reasoning_levels") or [] if isinstance(x, dict)]
        up = m.get("upgrade") if isinstance(m.get("upgrade"), dict) else None
        models.append({
            "slug": m["slug"], "name": m.get("display_name") or m["slug"], "description": desc,
            "listed": m.get("visibility", "list") == "list", "priority": m.get("priority", 999),
            "efforts": [e for e in efforts if e], "default_effort": m.get("default_reasoning_level"),
            "retires_at": (up or {}).get("retirement_at"), "replaced_by": (up or {}).get("model"),
            "old": any(w in low for w in OLD_WORDS),
            "class": "small" if any(w in low for w in SMALL_WORDS) else "strong" if any(w in low for w in STRONG_WORDS) else "mid",
        })
    models.sort(key=lambda m: (m["priority"] if isinstance(m["priority"], int) else 999, m["slug"]))
    return {"cli": cli, "source": source, "models": models}, None


def fit_effort(want, supported):
    """The supported effort closest to `want`, preferring one at or below it."""
    if not supported or want in supported:
        return want
    order = {e: i for i, e in enumerate(EFFORTS)}
    w = order.get(want, 1)
    known = [e for e in supported if e in order]
    if not known:
        return want
    below = [e for e in known if order[e] <= w]
    return max(below, key=order.get) if below else min(known, key=order.get)


def suggest(cat):
    usable = [m for m in cat["models"] if m["listed"]]
    fresh = [m for m in usable if not m["retires_at"] and not m["old"]] or [m for m in usable if not m["retires_at"]] or usable
    by = {c: [m for m in fresh if m["class"] == c] for c in ("small", "mid", "strong")}
    want = {"T0": ("small", "mid", "strong"), "T1": ("mid", "small", "strong"), "T2": ("mid", "strong", "small"),
            "T3": ("strong", "mid", "small"), "T4": ("strong", "mid", "small")}
    out = {}
    for t in TIERS:
        pick = next((by[c][0] for c in want[t] if by[c]), None)
        if not pick:
            continue
        out[t] = {"model": pick["slug"], "effort": fit_effort(TIER_EFFORT[t], pick["efforts"]),
                  "basis": "%s：%s" % (pick["class"], pick["description"] or "无说明")}
    return out


# ---------- commands ----------

def cmd_models(args):
    cat, err = load_catalog(args.cli, args.catalog)
    if not cat:
        die("拿不到 %s 的模型目录（%s）" % (args.cli, err), 4)
    ms = cat["models"] if args.all else [m for m in cat["models"] if m["listed"]]
    if args.json:
        print(json.dumps({"cli": cat["cli"], "source": cat["source"], "models": ms}, ensure_ascii=False, indent=2))
        return 0
    print("来源：%s" % cat["source"])
    for m in ms:
        tag = "（%s 下线，改用 %s）" % (m["retires_at"][:10], m["replaced_by"]) if m["retires_at"] else ""
        print("%-18s %-6s %-28s %s%s" % (m["slug"], m["class"], ",".join(m["efforts"]), m["description"], tag))
    return 0


def cmd_suggest(args):
    cat, err = load_catalog(args.cli, args.catalog)
    if not cat:
        die("拿不到 %s 的模型目录（%s）" % (args.cli, err), 4)
    s = suggest(cat)
    mm = ",".join("%s=%s" % (t, s[t]["model"]) for t in TIERS if t in s)
    if args.model_map:
        print(mm)
    elif args.json:
        print(json.dumps({"cli": args.cli, "source": cat["source"], "tiers": s, "model_map": mm,
                          "note": "按模型说明里的关键词推断，需确认一次"}, ensure_ascii=False, indent=2))
    else:
        print("来源：%s（按模型说明推断，确认一次后保存）" % cat["source"])
        for t in TIERS:
            if t in s:
                print("%s  %-18s %-7s %s" % (t, s[t]["model"], s[t]["effort"], s[t]["basis"]))
        print("\n保存为所有项目的辅助执行者：\n  python3 %s set --scope user --use %s --auto-models" % (os.path.abspath(__file__), args.cli))
    return 0


def cmd_show(args):
    eff, src = effective(args.project)
    if args.json:
        print(json.dumps({"effective": eff, "sources": src, "files": {"user": user_path(), "project": playbook_path(args.project)}},
                         ensure_ascii=False, indent=2))
        return 0
    print("用户级：%s\n项目级：%s\n" % (user_path(), playbook_path(args.project)))
    print("\n".join(render(eff)) if eff else "assist: 未配置（关闭）")
    if src:
        print("\n来源：" + ", ".join("%s=%s" % (k, v) for k, v in sorted(src.items()) if "." not in k or k.count(".") <= 2))
    return 0


def check(eff, catalog_file=None):
    errors, warnings, fills = [], [], {}
    use = eff.get("use")
    if eff.get("max_tier") is not None and eff["max_tier"] not in ASSIST_TIERS:
        errors.append("max_tier 只能是 T0、T1、T2：%s" % eff["max_tier"])
    if not use or use == "off":
        return errors, warnings, fills
    cats = {}
    for name in use:
        p = eff.get("profiles", {}).get(name, {})
        cli = p.get("cli") or (name if name in KNOWN_CLIS else None)
        if not cli:
            errors.append("%s：没有 profile 也不是已知 CLI，本次不可用" % name)
            continue
        if cli not in KNOWN_CLIS:
            errors.append("%s：cli 必须是 %s 之一：%s" % (name, "、".join(KNOWN_CLIS), cli))
            continue
        exe = "cursor-agent" if cli == "cursor" else cli
        if not shutil.which(exe):
            warnings.append("%s：PATH 上没有 %s" % (name, exe))
        ef = p.get("env_file")
        if ef:
            fp = os.path.expanduser(ef)
            if not os.path.isfile(fp):
                errors.append("%s：env_file 不存在：%s" % (name, ef))
            elif os.stat(fp).st_mode & 0o077:
                errors.append("%s：env_file 权限必须是 600：%s" % (name, ef))
        if cli not in CATALOG_CLIS:
            missing = [t for t in ASSIST_TIERS if t not in p.get("models", {})]
            if missing:
                warnings.append("%s：%s 没填模型，按 hosts/%s 第 3 节映射选" % (name, ",".join(missing), cli))
            continue
        if cli not in cats:
            cats[cli] = load_catalog(cli, catalog_file)
        cat, err = cats[cli]
        if not cat:
            warnings.append("%s：拿不到模型目录（%s），模型和思考深度未校验" % (name, err))
            continue
        idx = {m["slug"]: m for m in cat["models"]}
        sug = suggest(cat)
        for t in ASSIST_TIERS:
            model = p.get("models", {}).get(t)
            effort = p.get("effort", {}).get(t) or TIER_EFFORT[t]
            if not model:
                if t in sug:
                    fills.setdefault(name, {})[t] = sug[t]
                    warnings.append("%s：%s 没填模型，本次用推荐的 %s/%s" % (name, t, sug[t]["model"], sug[t]["effort"]))
                continue
            m = idx.get(model)
            if not m:
                errors.append("%s：%s 的模型 %s 不在 %s 的模型目录里" % (name, t, model, cli))
                continue
            if m["retires_at"]:
                warnings.append("%s：%s 的模型 %s 将于 %s 下线，建议换成 %s" % (name, t, model, m["retires_at"][:10], m["replaced_by"]))
            if m["efforts"] and effort not in m["efforts"]:
                errors.append("%s：%s 的模型 %s 不支持思考深度 %s（支持 %s）" % (name, t, model, effort, ",".join(m["efforts"])))
    return errors, warnings, fills


def cmd_check(args):
    eff, _ = effective(args.project)
    errors, warnings, fills = check(eff, args.catalog)
    if args.json:
        print(json.dumps({"ok": not errors, "errors": errors, "warnings": warnings, "fills": fills, "effective": eff},
                         ensure_ascii=False, indent=2))
    else:
        if not eff.get("use") or eff.get("use") == "off":
            print("assist: 关闭")
        for e in errors:
            print("错误：" + e)
        for w in warnings:
            print("提醒：" + w)
        if not errors and eff.get("use") and eff.get("use") != "off":
            print("assist: %s ≤%s，检查通过" % (",".join(eff["use"]), eff.get("max_tier", "T2")))
    return 1 if errors else 0


def _kv(s, what, keys, values=None):
    out = {}
    for part in s.split(","):
        if not part.strip():
            continue
        k, sep, v = part.partition("=")
        k, v = k.strip(), v.strip()
        if not sep or not v:
            die("%s 写成 T0=<值>,T1=<值>：%s" % (what, part))
        if k not in keys:
            die("%s 的键只能是 %s：%s" % (what, "、".join(keys), k))
        if values and v not in values:
            die("%s 的值只能是 %s：%s" % (what, "、".join(values), v))
        if re.search(r"[\s\"'{}\[\],:#\\]", v):
            die("%s 的值不能含空白、引号、括号、逗号、冒号或 #：%s" % (what, v))
        out[k] = v
    return out


def cmd_set(args):
    if args.scope == "user":
        path = user_path()
        text = _read(path) or ""
        cur = normalize(parse_yaml(text).get("assist"))
    else:
        path = playbook_path(args.project)
        text = _read(path)
        if text is None:
            text = _read(TEMPLATE)
            if text is None:
                die("没有 %s，也找不到模板 %s" % (path, TEMPLATE))
        cur = load_project(args.project) if os.path.exists(path) else {}
    new = copy.deepcopy(cur)
    if args.use is not None:
        use = [x.strip() for x in args.use.split(",") if x.strip()]
        if use == ["off"]:
            new["use"] = "off"
        elif use:
            bad = [x for x in use if not re.fullmatch(r"[A-Za-z][\w-]*", x) or x == "off"]
            if bad:
                die("--use 写成 codex,kimi 或 off：%s" % args.use)
            new["use"] = use
        else:
            new.pop("use", None)
    if args.max_tier is not None:
        if args.max_tier not in ASSIST_TIERS:
            die("--max-tier 只能是 T0、T1、T2")
        new["max_tier"] = args.max_tier
    if args.max_failures is not None:
        if args.max_failures < 1:
            die("--max-failures 至少为 1")
        new["max_failures"] = args.max_failures
    profs = new.setdefault("profiles", {})
    if args.profile:
        if not re.fullmatch(r"[A-Za-z][\w-]*", args.profile):
            die("--profile 名字只能含字母、数字、下划线和短横线")
        p = profs.setdefault(args.profile, {})
        if args.cli:
            if args.cli not in KNOWN_CLIS:
                die("--cli 只能是 " + "、".join(KNOWN_CLIS))
            p["cli"] = args.cli
        if args.env_file:
            if re.search(r"[\s\"'#]", args.env_file):
                die("--env-file 路径不能含空白、引号或 #")
            p["env_file"] = args.env_file
        if args.models:
            p.setdefault("models", {}).update(_kv(args.models, "--models", ASSIST_TIERS))
        if args.effort:
            p.setdefault("effort", {}).update(_kv(args.effort, "--effort", ASSIST_TIERS, EFFORTS))
    elif args.cli or args.models or args.effort or args.env_file:
        die("--cli/--models/--effort/--env-file 要配合 --profile")
    use = new.get("use") if isinstance(new.get("use"), list) else []
    for name in use:
        if name in KNOWN_CLIS and name not in profs:
            profs[name] = {"cli": name}
    if args.auto_models:
        targets = [args.profile] if args.profile else use
        filled = False
        for name in targets:
            p = profs.get(name, {})
            cli = p.get("cli") or (name if name in KNOWN_CLIS else None)
            if cli not in CATALOG_CLIS:
                print("提醒：%s 用的 %s 拿不到模型目录，--auto-models 跳过" % (name, cli), file=sys.stderr)
                continue
            cat, err = load_catalog(cli, args.catalog)
            if not cat:
                die("拿不到 %s 的模型目录（%s）" % (cli, err), 4)
            s = suggest(cat)
            for t in ASSIST_TIERS:
                if t in s and t not in p.get("models", {}):
                    p.setdefault("models", {})[t] = s[t]["model"]
                    p.setdefault("effort", {})[t] = s[t]["effort"]
                    filled = True
            profs[name] = p
        if not filled and targets:
            print("提醒：没有需要自动填的模型（已经填过的不会覆盖）", file=sys.stderr)
    if not profs:
        new.pop("profiles", None)
    errors = [e for e in check(merge([("new", new)])[0], args.catalog)[0] if "env_file" not in e]
    if errors and not args.force:
        die("没有保存：\n  " + "\n  ".join(errors) + "\n  确认无误可加 --force", 1)
    block = render(new)
    if args.scope == "user":
        body = "# hq 用户级配置：所有项目共用；项目 .hq/PLAYBOOK.md 里写了的项优先。由 assist-config.py 维护。\n" + "\n".join(block) + "\n"
    else:
        lines = text.splitlines()
        span = _assist_span(lines)
        if span:
            lines[span[0]:span[1]] = block
        else:
            fence = next((i for i, l in enumerate(lines) if l.strip() == "```yaml"), None)
            if fence is None:
                lines += ["", "## 授权", "", "```yaml"] + block + ["```"]
            else:
                end = next((i for i in range(fence + 1, len(lines)) if lines[i].strip().startswith("```")), len(lines))
                lines[end:end] = block
        body = "\n".join(lines) + "\n"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(body)
    os.replace(tmp, path)
    print("已写入 %s\n" % path + "\n".join(block))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="hq 辅助执行者配置与模型目录")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("models", "suggest"):
        s = sub.add_parser(name)
        s.add_argument("--cli", default="codex")
        s.add_argument("--catalog")
        s.add_argument("--json", action="store_true")
        if name == "models":
            s.add_argument("--all", action="store_true", help="包括隐藏的模型")
        else:
            s.add_argument("--model-map", action="store_true", help="只输出 T0=…,T4=…（给 install.sh --model-map）")
    for name in ("show", "check"):
        s = sub.add_parser(name)
        s.add_argument("--project", default=".")
        s.add_argument("--json", action="store_true")
        if name == "check":
            s.add_argument("--catalog")
    s = sub.add_parser("set")
    s.add_argument("--scope", choices=["user", "project"], required=True)
    s.add_argument("--project", default=".")
    s.add_argument("--use")
    s.add_argument("--max-tier")
    s.add_argument("--max-failures", type=int)
    s.add_argument("--profile")
    s.add_argument("--cli")
    s.add_argument("--models")
    s.add_argument("--effort")
    s.add_argument("--env-file")
    s.add_argument("--auto-models", action="store_true", help="没填的 T0–T2 按模型目录推荐填上")
    s.add_argument("--catalog")
    s.add_argument("--force", action="store_true", help="校验有错误也保存")
    args = ap.parse_args(argv)
    return {"models": cmd_models, "suggest": cmd_suggest, "show": cmd_show, "check": cmd_check, "set": cmd_set}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
