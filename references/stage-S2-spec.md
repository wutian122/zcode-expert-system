# S2 · OpenSpec 规格规划

**门禁**：G2（**停老板审产物**）｜ **证据级**：P2 ｜ **角色**：Orchestrator + 领域专家

## 前置（不可跳过）

```bash
python scripts/openspec_engine.py list --root <项目根>   # 读 root；null 属正常返回，读 JSON 不要重试
```

- `root: null` + 我自选 → 静默放弃，不提 setup
- `root: null` + 老板点名/主管道启动 → 停，三选一
- `status` 报 `Declared in` / `Invalid store declaration in` → **store 声明错误，不是未初始化**，停并展示 message + fix

## 动作

```bash
python scripts/openspec_engine.py new-change <kebab-case>   # 生成 .openspec.yaml，禁手建
python scripts/openspec_engine.py status --change "<name>"   # 解析 applyRequires + requires 边 + artifactPaths
python scripts/openspec_engine.py instructions <artifact-id> --change "<name>"   # 取 template / resolvedOutputPath
```

对每个 ready 产物：读磁盘上依赖产物 → 写文件 → **重跑 status**。

**必需集 = `applyRequires` 及沿 `requires` 边可达的全部产物**。status 只判文件存在，别被 `done` 误导。

## 产物（路径一律以 CLI 返回为准）

| 产物 | 职责 |
|---|---|
| `proposal.md` | 为什么做、现状问题、目标、影响范围、不包含什么 |
| `design.md` | **唯一设计真相**：架构、模块职责、数据结构、API、核心流程、安全兼容、风险 |
| `specs/<capability>/spec.md` | 可验证需求（Requirement + Scenario） |
| `tasks.md` | 可执行任务 + 依赖 + 验收条件 |
| `.openspec.yaml` | CLI 生成 |

### 规格写法（可验证）

```markdown
## Requirement: User Authentication

### Scenario: Successful Login
- WHEN 用户提交有效账号密码
- THEN 系统验证身份
- AND 返回有效凭证
- AND 记录登录状态
```

## 退出条件（G2）

- [ ] `applyRequires` 及可达产物全 `done`/`skipped`
- [ ] `python scripts/openspec_engine.py validate --change <n>` 通过
- [ ] 七项规格审查逐条勾选
- [ ] `artifactPaths.specs.existingOutputPaths` 已记录（S8 的唯一 delta 来源）
- [ ] **老板已完成产物审阅**
- [ ] 未在同一响应内开始实施

### 七项规格审查

- [ ] 需求是否完整
- [ ] 规格是否存在歧义
- [ ] 设计是否覆盖所有需求
- [ ] 数据库/接口变化是否明确
- [ ] 任务是否覆盖全部规格
- [ ] 每项任务是否具备验收条件
- [ ] 是否存在相互矛盾的需求

## 失败返回点

| 失败 | 返回 |
|---|---|
| 规格审查不过 | `zes-openspec-update-change` 修订**既有产物**——绝不新建整产物 |
| 需求"意图"变了 | 另起 `new change "<新名>"` |
| 产物 blocked | 按 `requires` 边补依赖产物 |
| CLI 不可用 | 如实报告并停——**禁伪造** |

## 修订同步义务（B7 迁移自全局 AGENTS.md）

`zes-openspec-update-change` 增删改 `tasks.md` 任务后，**同回合**必须：

1. 同步修订计划文档（按 writing-plans 格式，`### Task N:` 与 tasks.md 一一对应）
2. 在 ledger 记 Ruling（改了什么、为何）
3. 纯规划期 SDD ledger 尚未创建时：Ruling 暂记于变更产物，SDD setup 预检时补录入账
4. 中断恢复时若账本旧完成序列与修订后 tasks.md 失配：**以 tasks.md 为验收真相**对齐账本并记 Ruling，不得按旧账本重派已修订掉的任务

理由：双账本（tasks.md 与计划文档）的漂移防线只有这一条，不同步会导致实施者照改后的计划干活、验收却按旧 tasks.md。

## 关键约束：Planning boundary

**产物齐备即停，不得在同一响应内实施**（即使请求里写了 build/fix）。

## 无 OpenSpec CLI 环境下的 S2 规格规划（手工模式）

当环境未安装 OpenSpec CLI 时，S2 阶段的四件产物可手工创建，产物格式与 OpenSpec CLI 生成的完全一致，可无缝切换。

### 前置条件

- `openspec/` 根目录已存在（或老板点名后三选一创建：init / `--store <id>` / 不用，否则静默放弃）
- 变更名（change name）已确定，采用 kebab-case，例如 `add-user-auth`

### 手工创建四件产物

在 `openspec/changes/<change>/` 目录下依次创建：

| 产物 | 路径 | 必备内容 |
|---|---|---|
| proposal.md | `openspec/changes/<change>/proposal.md` | `## Why`（≥50 字）、`## What Changes` |
| design.md | `openspec/changes/<change>/design.md` | 系统架构变化、模块职责、数据结构、API、核心流程、安全兼容、风险 |
| specs/<capability>/spec.md | `openspec/changes/<change>/specs/<capability>/spec.md` | `## ADDED Requirements`、`### Requirement:`（含 SHALL/MUST）、`#### Scenario:` + WHEN/THEN/AND |
| tasks.md | `openspec/changes/<change>/tasks.md` | `- [ ]` 勾选框，每项有验收条件 |

### 元数据（无 CLI 时）

在 `openspec/changes/<change>/.openspec.yaml` 手写简单键值对（不依赖第三方 YAML 库）：

```yaml
schema: spec-driven
name: <change>
created: <YYYY-MM-DD>
status: pending
```

### 证据降级（记账）

无 CLI 时无法运行 `openspec validate --change`，在账本与计划文档 `## Baseline` 段记录：

- `spec_mode: manual`
- `validate: skipped`

这不构成伪证据：`spec_mode: manual` 明确声明产物由人工创建，未声称 CLI 验证通过。

### 与 CLI 模式的兼容性

四件产物的格式、命名、位置与 OpenSpec CLI 生成的完全一致，工作流机械核对（`workflow_check.py` check_S2）不区分产物来源，可无缝切换。
