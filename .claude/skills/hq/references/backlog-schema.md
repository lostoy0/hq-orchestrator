# 计划清单格式（backlog.json）— 格式版本 hq-backlog/1

`/hq-plan` 写，`/hq` 读（按计划执行，见 `SKILL.md`“按计划执行”）。给人看的版本计划在同目录的 `roadmap.md`；两者冲突时以本文件为准，`roadmap.md` 由它生成。

用 JSON 而不是 YAML：标准库就能读写和检查（`scripts/backlog-check.py`），不依赖第三方包。缩进 2 空格，每个任务一个对象，便于看 diff。

## 顶层

| 字段 | 类型 | 必填 | 含义 |
|---|---|---|---|
| schema | `"hq-backlog/1"` | 是 | 格式版本 |
| project | 字符串 | 是 | 项目名 |
| updated | `YYYY-MM-DD` | 是 | 最后修改日期 |
| based_on | 对象 | 是 | 依据的产物及版本，如 `{"prd": "docs/product/prd.md@3", "architecture": "docs/tech/architecture.md@2"}`；没有的项省略 |
| requirements | 数组 | 是 | 需求索引，见下 |
| releases | 数组 | 是 | 版本，按先后排列，见下 |
| tasks | 数组 | 是 | 任务，见下 |
| imported_from | 字符串 | 否 | 由 `/hq-plan` 导入时写原计划路径。有这个字段时，任务超过 120 分钟的警告合并成一条（保留原计划的粒度，`/hq` 派发时再拆） |

## requirements（需求索引）

| 字段 | 类型 | 必填 | 含义 |
|---|---|---|---|
| id | 大写前缀加编号，如 `F-001`、`NFR-001`、`REQ-001` | 是 | 和需求文档一致（需求文档用自己的编号时照用）；需求文档没有编号时由 `/hq-plan` 分配（见 `stages/common.md` 第 3 节） |
| title | 字符串 | 是 | 一句话 |
| priority | `P0` / `P1` / `P2` | 是 | P0 不做就不能上线 |
| release | 版本 id 或 `null` | 是 | 计划在哪个版本交付；`null` 表示暂不安排（P0 不允许 `null`） |
| source | 字符串 | 否 | 出处，如 `docs/product/prd.md#登录` |

## releases（版本）

| 字段 | 类型 | 必填 | 含义 |
|---|---|---|---|
| id | 以字母开头，如 `R1`、`M1` | 是 | 版本编号 |
| name | 字符串 | 是 | 如 `MVP`、`v1.1` |
| goal | 字符串 | 是 | 这个版本交付的用户价值，一两句 |
| exit_criteria | 字符串数组 | 是 | 发布条件（可检验） |

## tasks（任务）

| 字段 | 类型 | 必填 | 含义 |
|---|---|---|---|
| id | 大写前缀加编号，如 `B-001`；导入的计划保留原编号（如 `DF-V1-BASE01`） | 是 | 唯一，发布后不复用 |
| release | 版本 id | 是 | 所属版本 |
| title | 字符串 | 是 | 一句话 |
| kind | `code` / `docs` / `research` / `review` / `config` | 是 | 同 `metrics-schema.md` |
| requirements | 编号数组 | 是 | 实现哪些需求；纯基础设施任务可为空数组，但要在 `notes` 写明为谁服务 |
| depends_on | 任务 id 数组 | 是 | 前置任务；只能依赖同一版本或更早版本的任务 |
| owns | 字符串数组 | 是 | 负责的文件、目录或 glob（如 `src/auth/**`）；还不确定时写模块编号（如 `M-03`），`/hq` 派发时再落到文件 |
| acceptance | 字符串数组 | 是 | 验收标准，至少 1 条，可检验 |
| verify_level | `doc` / `code` / `high` / `e2e` | 是 | 同 `SKILL.md` 第 8 步 |
| verify_cmd | 字符串或 `null` | 否 | 验证命令；`doc`、`e2e` 可为 `null` |
| score | 对象 | 是 | `calibration.md` 5 维打分：`{"scope":0-2,"ambiguity":0-2,"context":0-2,"risk":0-2,"verify":0-2}` |
| tier_score | 整数 0–10 | 是 | 5 维之和 |
| tier | `T0`–`T4` | 是 | 预估档位。按 `calibration.md` 分数线得出，可以按规则 9 上调；低于分数线时必须在 `tier_note` 写依据（例如 PLAYBOOK“选档偏好”里已验证的条目） |
| tier_note | 字符串 | 否 | 选档理由，一句话 |
| est_min | 数字 | 是 | 预计用时（分钟）；超过 120 建议拆分 |
| status | `todo` / `in_progress` / `done` / `blocked` / `dropped` | 是 | 计划时都是 `todo` |
| run_id | 字符串或 `null` | 否 | `/hq` 执行它的 run |
| branch | 字符串或 `null` | 否 | 合并来源分支 |
| notes | 字符串 | 否 | 备注 |

## 示例

```json
{
  "schema": "hq-backlog/1",
  "project": "demo",
  "updated": "2026-11-26",
  "based_on": {"prd": "docs/product/prd.md@3"},
  "requirements": [
    {"id": "F-001", "title": "邮箱注册登录", "priority": "P0", "release": "R1", "source": "docs/product/prd.md#账号"}
  ],
  "releases": [
    {"id": "R1", "name": "MVP", "goal": "新用户能注册并完成第一次记账", "exit_criteria": ["F-001 验收标准全部通过", "e2e 冒烟通过"]}
  ],
  "tasks": [
    {
      "id": "B-001", "release": "R1", "title": "用户表与迁移", "kind": "code",
      "requirements": ["F-001"], "depends_on": [], "owns": ["db/migrations/**", "src/models/user.*"],
      "acceptance": ["迁移可正向和回滚", "邮箱唯一约束有测试"],
      "verify_level": "high", "verify_cmd": "npm test -- models/user",
      "score": {"scope": 1, "ambiguity": 0, "context": 1, "risk": 2, "verify": 0},
      "tier_score": 4, "tier": "T2", "tier_note": "数据迁移，风险 2",
      "est_min": 30, "status": "todo", "run_id": null, "branch": null
    }
  ]
}
```

## 检查

```bash
python3 <hq 技能目录>/scripts/backlog-check.py docs/plan/backlog.json [--prd docs/product/prd.md] [--format json]
```

退出码 0 = 没有错误（可能有警告），1 = 有错误，2 = 参数错误或文件读不了。错误必须改掉；警告要么改，要么在 `notes` 或 `tier_note` 写明理由。

- **错误**：缺必填字段；取值不合法；编号重复；依赖不存在、有环、依赖了更晚的版本；`tier_score` 不等于 5 维之和；档位低于分数线又没写 `tier_note`；P0 需求没有安排版本，或所在版本里没有任务覆盖它；任务引用了不存在的需求或版本。
- **警告**：`est_min` 超过 120；档位低于分数线（已写 `tier_note`）；同一版本里没有依赖关系的两个任务 `owns` 有重复项（并行时会改同一批文件）；`--prd` 给出的需求文档里出现、清单里却没有的 `F-`/`NFR-` 编号；P1 需求没有任务覆盖。
