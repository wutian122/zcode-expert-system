---
description: S4 环境准备与基线测试 —— 只做基线，不建 worktree
name: wf-env
---

# /wf:env

## 说明

**本体系不使用 Git Worktree**（老板决策）。本命令只做：环境探测 + 账本初始化 + 基线测试。

并行实施的代价必须知情：**无隔离工作区 ⇒ 实施永远串行**。保留只读调查并行与审查并行。

## 1. 环境探测（只读）

```bash
git rev-parse --is-inside-work-tree
```

- 有 git → diff 追溯路径
- 无 git → 快照证据路径

**不擅自 `git init`。**

## 2. 账本初始化

```bash
bash "${CLAUDE_PLUGIN_ROOT:-${ZCODE_PLUGIN_ROOT:-$QODER_PLUGIN_ROOT}}/skills/zcode-expert-system/scripts/sdd/sdd-workspace" <plan.md>
```

生成 `.superpowers/sdd/<plan-basename>/`。**路径以脚本为准**。

首行必须是：

```
# SDD ledger — plan: <计划路径>
```

首行不匹配 → 不是本计划的账本，**另建，不动原文件**。

模板：`templates/progress.md`

## 3. 基线测试（核心）

```bash
<全量测试命令>
```

记录四件：命令 / 退出码 / 通过失败数 / 失败清单。

**双写**：

1. **主副本** → 计划文档 `## Baseline`（P3，删 workspace 不丢）
2. **过程副本** → ledger `## Baseline`

只写 ledger = 终审删 workspace 时基线证据整体消失。

## 基线红的三条纪律（W4）

1. 不阻断开工，但**必须落基线失败清单**
2. 此后每个红项比对：**清单内=既存**，**清单外=本次引入**
3. 交付报告列出全部既存红项

唯一目的：**不把既存失败归因给本次任务，也不把本次引入的失败混进"一直是红的"。**

## 退出条件（G4）

- [ ] 基线命令 + 退出码 + 计数已记录
- [ ] 失败清单已落盘（若有）
- [ ] **主副本已写入计划 `## Baseline`**
- [ ] ledger 首行为身份行

## 失败返回点

| 失败 | 返回 |
|---|---|
| 基线红 | **停**，问老板带病开工否 |
| 非 git | 降级快照 + 自审（记 L1），交付声明 |
| 账本首行不匹配 | 另建，不覆盖 |

下一阶段：`/wf:implement`
