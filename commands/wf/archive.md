---
description: S8 规格同步与归档 —— delta 合并进主 spec 并归档变更
name: wf-archive
---

# /wf:archive

## 顺序

```
验证+审查通过 → /wf:deliver（老板选方式）→ 本命令（sync → archive）
```

archive **不依赖** merge 完成，但依赖验证 + 审查 + 同步通过。

## 一、同步（`zes-openspec-sync-specs`）

### delta 唯一来源（硬约束）

```bash
python "${CLAUDE_PLUGIN_ROOT:-$ZCODE_PLUGIN_ROOT}/skills/zcode-expert-system/scripts/openspec_engine.py" status --change <n>
```

读 JSON 输出的 `artifactPaths.specs.existingOutputPaths` 字段。**只认这个。** 绝不从 `design.md` / `proposal.md` 推断——推断会同步了不该同步的能力。

> **无 jq 也能用**：上面的命令直接输出 JSON，用 Python 一行内联即可提取字段（不依赖 jq）：
> ```bash
> python "${CLAUDE_PLUGIN_ROOT:-$ZCODE_PLUGIN_ROOT}/skills/zcode-expert-system/scripts/openspec_engine.py" status --change <n> \
>   | python -c "import json,sys; d=json.load(sys.stdin); print('\n'.join(d.get('artifactPaths',{}).get('specs',{}).get('existingOutputPaths',[])))"
> ```

### 合并规则

| 情形 | 处理 |
|---|---|
| ADDED 已存在 | 视为隐式 MODIFIED |
| MODIFIED | 保留 delta 未提及的既有场景 |
| REMOVED | 整块移除 |
| RENAMED | FROM/TO 对应 |
| 主 spec `## Purpose` | **权威，不动** |
| 能力退役 | 须满足边界条件（含 `retire_capabilities: true`），**永不留下空 `## Requirements`** |

首次写主 spec 前取一次 `python "${CLAUDE_PLUGIN_ROOT:-$ZCODE_PLUGIN_ROOT}/skills/zcode-expert-system/scripts/openspec_engine.py" instructions specs` rules 快照，失败即停。

```bash
python "${CLAUDE_PLUGIN_ROOT:-$ZCODE_PLUGIN_ROOT}/skills/zcode-expert-system/scripts/openspec_engine.py" validate-specs
```

幂等。调用方收窄的 delta 子集不得再扩大。

## 二、归档（`zes-openspec-archive-change`）

### 三情形提示

| 情形 | 选项 |
|---|---|
| 任一能力 sync-blocked | **只给** "Archive without syncing / Cancel"，**不得启动任何 sync** |
| 有未同步变更 | "Sync now (recommended) / Archive without syncing" |
| 已全部同步 | "Archive now / Sync anyway / Cancel" |

选 Sync now → **内联执行**（不得后台）→ 逐能力复验：
ADDED 在 / MODIFIED 带新场景且旧场景在 / REMOVED 消失 / 退役能力 spec.md 已删。

**复验不过不得归档。**

### 归档七条件

- [ ] 所有必须完成的任务已完成
- [ ] 规格与实现一致
- [ ] 测试验证通过
- [ ] 代码审查通过
- [ ] 无未解决阻断问题
- [ ] 交付状态符合要求
- [ ] 必要文档已更新

> **I-05：七条件之外，引擎强制核对 `tasks.md` 勾选。** 存在未勾选任务时
> `archive-change` 直接 rc≠0 拒绝，即使七标志全 true——标志是手工元数据、
> 会与真实进度脱钩，`tasks.md` 才是账本真相。`tasks.md` 不存在时不额外校验。

### 完成度口径

只认 `python "${CLAUDE_PLUGIN_ROOT:-$ZCODE_PLUGIN_ROOT}/skills/zcode-expert-system/scripts/openspec_engine.py" list` 输出的任务完成数（`tasks.md` 的 `- [x]` / `- [X]`），**仅 `x`/`X` 算完成**，空框与 `[~]` 等异形标记一律算未完成。

### 动作

移至 `openspec/changes/archive/YYYY-MM-DD-<name>/`（**不叠日期**）。

## 三、PARKED（W8）

| 情形 | 处理 |
|---|---|
| 存在 PARKED | **默认禁止归档** |
| 终审裁决"已完成可接受" | 勾选后归档 |
| 终审裁决"接受但不修" | **不得原地勾选**；`new change "deferred-<topic>"` 迁出 |

归档警告必须逐条列出并给出修复动作，禁止"看一眼就确认"。

## 退出条件（G8b）

- [ ] 七条件逐条为真
- [ ] `completedTasks == totalTasks`（只认 x/X）
- [ ] delta 逐能力复验通过
- [ ] `python "${CLAUDE_PLUGIN_ROOT:-$ZCODE_PLUGIN_ROOT}/skills/zcode-expert-system/scripts/openspec_engine.py" validate-specs` 通过
- [ ] 归档目录存在且日期未叠
- [ ] `openspec/` 下无未提交制品

## 铁律

**不得为了清理目录而提前归档。** 归档是诚实记录，不是收尾动作。

核对：`${CLAUDE_PLUGIN_ROOT:-$ZCODE_PLUGIN_ROOT}/skills/zcode-expert-system/scripts/workflow_check.py --change <n> --scale <scale>`
