# S8 · 规格同步与归档

**门禁**：G8b（**停老板**）｜ **证据级**：P2 ｜ **角色**：Orchestrator
**组件**：zes-openspec-sync-specs、zes-openspec-archive-change（见 config/workflow.json 的 component_registry）

## 顺序（不可颠倒）

```
验证 + 审查通过  →  S7 交付（老板选方式）  →  S8 同步 → 归档
```

archive **不依赖** merge 完成，但依赖验证 + 审查 + 同步通过。

## 一、规格同步（openspec_engine.py sync-specs）

### delta 唯一来源（硬约束）

```bash
python scripts/openspec_engine.py status --change <n>
```

读取 JSON 输出中的 `artifactPaths.specs.existingOutputPaths` 字段，**只认这个。** 绝不从 `design.md` / `proposal.md` 推断——推断会同步了不该同步的能力。

### 智能合并规则

| 情形 | 处理 |
|---|---|
| ADDED 已存在 | 视为隐式 MODIFIED |
| MODIFIED | 保留 delta 未提及的既有场景 |
| REMOVED | 整块移除 |
| RENAMED | FROM/TO 对应 |
| 主 spec 的 `## Purpose` | **权威，不动** |
| 能力退役 | 须满足边界条件（含 `retire_capabilities: true`），**永不留下空 `## Requirements`** |

第一次主 spec 写入前取一次 `openspec_engine.py instructions specs` 的 rules 快照，失败即停。

### 校验

```bash
python scripts/openspec_engine.py validate-specs
```

幂等。调用方收窄的 delta 子集不得再扩大。

## 二、归档（openspec_engine.py archive-change）

### 三情形提示（按 sync 状态）

| 情形 | 给出选项 |
|---|---|
| 任一能力 sync-blocked | **只给** "Archive without syncing / Cancel"，**不得启动任何 sync** |
| 有未同步变更 | "Sync now (recommended) / Archive without syncing" |
| 已全部同步 | "Archive now / Sync anyway / Cancel" |

选 Sync now → **内联执行**（不得后台）→ 逐能力复验：

- ADDED 在
- MODIFIED 带新场景且旧场景在
- REMOVED 消失
- 退役能力 `spec.md` 已删

**复验不过不得归档。**

### 归档七条件（逐条为真）

- [ ] 所有必须完成的任务已完成
- [ ] 规格与实现一致
- [ ] 测试验证通过
- [ ] 代码审查通过
- [ ] 无未解决阻断问题
- [ ] Git/交付状态符合要求
- [ ] 必要文档已更新

> **I-05：七条件不是全部。** `archive-change` 在七标志之外**强制核对 `tasks.md` 实际勾选**——
> 只要存在未勾选任务（`- [ ]`），即使 `.status.json` 七个标志全为 true 也拒绝归档（rc≠0）。
> 七个标志是手工维护的元数据，会与真实进度脱钩；`tasks.md` 勾选才是账本真相。
> `tasks.md` 不存在时不额外校验（无账本可查，沿用七标志）。

### 完成度口径

只认 `python scripts/openspec_engine.py list` 输出的任务完成数（`tasks.md` 的 `- [x]` / `- [X]`），**仅 `x`/`X` 算完成**，空框 `[ ]` 与异形标记（`[~]` 等）一律算未完成。

### 归档动作

移至 `openspec/changes/archive/YYYY-MM-DD-<name>/`（**不叠日期**）。

## 三、PARKED 处理（W8）

| 情形 | 处理 |
|---|---|
| 存在 PARKED | **默认禁止归档** |
| 终审裁决"已完成可接受" | 走状态机 T10 勾选后归档 |
| 终审裁决"接受但不修" | **不得在原 change 内勾选**；必须 `new change "deferred-<topic>"` 把任务迁出 |

归档警告必须**逐条列出并给出修复动作**，禁止"看一眼就确认"。

## 退出条件（G8b）

- [ ] 七条件逐条为真
- [ ] `completedTasks == totalTasks`（只认 x/X）
- [ ] delta 逐能力复验通过
- [ ] `openspec_engine.py validate-specs` 通过
- [ ] 归档目录存在且日期未叠
- [ ] `openspec/` 下无未提交制品

## 失败返回点

| 失败 | 返回 |
|---|---|
| sync 报阻塞 | **立即停止归档**，changeRoot 不动 |
| 有未完成任务 | 警告 + 老板确认——**不得为清目录提前归档** |
| 归档目标已存在 | 报错，改名或换日期（不叠日期） |

## 无 OpenSpec CLI 环境下的 S8 归档（手工模式）

当环境未安装 OpenSpec CLI 时，S8 阶段的规格同步与归档可手工完成，产物格式与 OpenSpec CLI 生成的完全一致，可无缝切换。

### 前置条件

- `openspec/changes/<change>/` 目录存在且四件产物齐全（proposal.md / design.md / tasks.md / specs/<capability>/spec.md）
- `openspec/specs/<capability>/spec.md` 主 spec 已存在（或需手工创建）

### 手工执行 delta 合并（sync-specs）

将 `openspec/changes/<change>/specs/<capability>/spec.md` 中的增量内容合并进 `openspec/specs/<capability>/spec.md`，遵循：

| 合并情形 | 处理 |
|---|---|
| ADDED 已存在 | 视为隐式 MODIFIED |
| MODIFIED | 保留 delta 未提及的既有场景 |
| REMOVED | 整块移除 |
| RENAMED | FROM/TO 对应 |
| 主 spec 的 `## Purpose` | 权威不动 |
| 能力退役 | 须满足边界条件，永不留下空 `## Requirements` |

### 手工执行归档（archive-change）

归档前必须满足归档七条件：

- 所有必须完成的任务已完成
- 规格与实现一致
- 测试验证通过
- 代码审查通过
- 无未解决阻断问题
- Git/交付状态符合要求
- 必要文档已更新

### 证据降级（记账）

无 CLI 时无法运行 `openspec_engine.py validate-specs`，在账本与计划文档 `## Baseline` 段记录：

- `spec_mode: manual`
- `validate: skipped`

这不构成伪证据：`spec_mode: manual` 明确声明产物由人工创建，未声称 CLI 验证通过。

### 归档动作

将 `openspec/changes/<change>/` 移动至 `openspec/changes/archive/YYYY-MM-DD-<change>/`（日期不叠）。归档目标若已存在，报错并改名或换日期。

### PARKED 处理

存在 PARKED 任务时，默认禁止归档（W8）。「接受但不修」必须迁出到新 change，不得在原 change 内勾选。

### 铁律（不得为了清理目录而提前归档）

**不得为了清理目录而提前归档。** 归档是诚实记录，不是收尾动作。

