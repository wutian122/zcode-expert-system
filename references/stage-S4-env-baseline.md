# S4 · 环境准备与基线测试

**门禁**：G4 ｜ **证据级**：P3 + P4 ｜ **角色**：Orchestrator
**组件**：baseline-test（见 config/workflow.json 的 component_registry）

> **本体系不使用 Git Worktree**（老板决策）。本阶段只做环境探测 + 基线测试 + 账本初始化。
> 并行实施能力因此取消——见 SKILL.md 第六章守恒关系。

## 动作

### 1. 环境探测（只读）

```bash
git rev-parse --is-inside-work-tree   # 有 git → diff 追溯路径
```

**不擅自 `git init`**。无 git 走快照路径（见 S5）。

### 2. 账本初始化

```bash
bash "${CLAUDE_PLUGIN_ROOT:-${ZCODE_PLUGIN_ROOT:-$QODER_PLUGIN_ROOT}}/skills/zcode-expert-system/scripts/sdd/sdd-workspace" <plan.md>
```

生成 `.superpowers/sdd/<plan-basename>/`。**路径以脚本为准**（脚本是 `task-brief` / `review-package` 的唯一目录解析器）。

账本 `progress.md` 首行必须是：

```
# SDD ledger — plan: <计划路径>
```

首行不匹配 → 不是本计划的账本，**另建，不动原文件**。

### 3. 基线测试（本阶段核心）

```bash
<项目的测试命令>       # 全量，不是抽样
```

记录四件：

| 项 | 例 |
|---|---|
| 命令 | `pytest -q` |
| 退出码 | `0` |
| 通过/失败数 | `142 passed, 3 failed` |
| 失败清单 | 文件 + 测试名 + 失败摘要 |

**双写**（防丢的关键）：

1. **主副本** → 计划文档 `## Baseline` 段（P3，随仓库，删 workspace 不会丢）
2. **过程副本** → ledger `## Baseline`

只写 ledger = 终审删 workspace 时基线证据整体消失。

## 退出条件（G4）

- [ ] 基线命令 + 退出码 + 计数已记录
- [ ] 基线失败清单已落盘（若有失败）
- [ ] **主副本已写入计划文档 `## Baseline`**
- [ ] ledger 首行为账本身份

## 失败返回点

| 失败 | 返回 |
|---|---|
| 基线测试红 | **停**，问老板：先修基线 / 带着已知失败开工（记 W4） |
| 非 git 仓库 | 降级：走快照证据 + 主控自审（记 L1），交付中声明 |
| 账本已存在但首行不匹配 | 另建，不覆盖 |
| 基线红且老板未表态 | 不得进 S5 |

## 基线红的三条纪律（W4）

1. 基线红**不阻断**开工，但开工前必须落**基线失败清单**
2. 此后每次全量测试的每个红项，先与清单比对：
   - **清单内 = 既存**（记 `pre-existing`）
   - **清单外 = 本次引入**（进修复循环）
3. 交付报告必须列出全部既存红项

这条纪律的唯一目的：**不把既存失败归因给本次任务，也不把本次引入的失败混进"一直是红的"。**
