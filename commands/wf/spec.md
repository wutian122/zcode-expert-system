---
description: S2 OpenSpec 规格规划 —— 生成 proposal/design/tasks/specs
name: wf-spec
---

# /wf:spec

## 前置检查（不可跳）

```bash
python "$ZCODE_PLUGIN_ROOT/skills/zcode-expert-system/scripts/openspec_engine.py" list      # 读 root；null 属正常返回，读 JSON 不重试
```

| 情形 | 处理 |
|---|---|
| `root: null` + 我自选 | 静默放弃 OpenSpec，按普通请求作答，**不提 setup** |
| `root: null` + 老板点名/主管道已启动 | 停，三选一：`init` / `--store <id>` / 不用 |
| `status` 报 `Declared in` / `Invalid store declaration in` | **store 声明错误，不是未初始化**，停并展示 message + fix |

> **绝不副作用建根**：不自动 `init`、不手建 `openspec/`、不让命令顺手建。

## 执行

```bash
ENGINE="python $ZCODE_PLUGIN_ROOT/skills/zcode-expert-system/scripts/openspec_engine.py"
$ENGINE new-change "<kebab-case>"
$ENGINE status --change "<name>"
$ENGINE instructions <artifact-id> --change "<name>"
```

对每个 ready 产物：读磁盘依赖产物 → 写文件 → **重跑 status**。

必需集 = `applyRequires` 及沿 `requires` 边**可达**的全部产物。status 只判文件存在，别被 `done` 误导。

## 产物

| 文件 | 职责 |
|---|---|
| `proposal.md` | 为什么做 / 现状问题 / 目标 / 影响范围 / 不包含什么 |
| `design.md` | **唯一设计真相**：架构 / 模块职责 / 数据结构 / API / 流程 / 安全兼容 / 风险 |
| `specs/<capability>/spec.md` | 可验证需求（Requirement + Scenario） |
| `tasks.md` | 可执行任务 + 依赖 + 验收条件 |
| `.openspec.yaml` | CLI 生成，**禁手建** |

### 规格写法

```markdown
## Requirement: User Authentication

### Scenario: Successful Login
- WHEN 用户提交有效账号密码
- THEN 系统验证身份
- AND 返回有效凭证
```

## 七项规格审查

- [ ] 需求完整
- [ ] 无歧义
- [ ] 设计覆盖所有需求
- [ ] 数据库/接口变化明确
- [ ] 任务覆盖全部规格
- [ ] 每项任务有验收条件
- [ ] 无相互矛盾的需求

## 退出条件（G2）

- [ ] 可达产物全 `done`/`skipped`
- [ ] `python "$ZCODE_PLUGIN_ROOT/skills/zcode-expert-system/scripts/openspec_engine.py" validate --change <n>` 通过
- [ ] 七项审查勾完
- [ ] `artifactPaths.specs.existingOutputPaths` 已记录（**S8 的唯一 delta 来源**）
- [ ] **老板已审阅产物**
- [ ] 未在同一响应内实施

## Planning boundary

**产物齐备即停，不得在同一响应内实施**（即使请求里写了 build/fix）。

## 失败返回点

| 失败 | 返回 |
|---|---|
| 审查不过 | `zes-openspec-update-change` 修订**既有产物**——绝不新建整产物 |
| 意图变了 | 另起 `new change` |
| 产物 blocked | 按 requires 边补依赖 |
| CLI 不可用 | 如实报告并停——**禁伪造** |

下一阶段：`/wf:plan`
