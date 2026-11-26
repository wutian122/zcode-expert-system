---
description: S5 代码实施 —— 串行 TDD + 独立变更集 + 异域审查
name: wf-implement
---

# /wf:implement

## 前置

- S3 计划已批准，执行模式已声明
- S4 基线已记录（主副本在计划 `## Baseline`）

## 执行模式（互斥）

| 模式 | 账本 |
|---|---|
| **SDD**（默认） | ledger + 原子回写 tasks.md |
| **apply-change 直行** | **无 ledger**，tasks.md 即账本 |

同 change 同一时刻只允许一种。切换须记 Ruling，**不得回退已勾选任务**。

## 每任务循环

```
1. 记基线（快照哈希 或 BASE）
2. task-brief 抽任务原文
3. 派实施者（域专家 + 角色契约前置）
4. 四态处理
5. 主控独立计算变更集
6. 派审查者（异域专家）
7. 修复循环 ≤5 轮
8. 原子回写 ledger + tasks.md
```

### 3. 派实施者

```python
Agent(
  subagent_type = "<域专家>",
  description = "专家：<域专家>",
  prompt = "<references/roles/implementer.md>\n\n"
           "【契约优先级】流程契约优先于专家人格。\n---\n"
           "读：<task-N-brief.md>\n报告写到：<task-N-report.md>\n"
)
```

报告只回 6 行：STATUS / COMMIT / TESTS / CONCERNS / REPORT。**实施者禁派子代理。**

### 4. 四态

| 状态 | 处理 |
|---|---|
| DONE | 进第 5 步 |
| DONE_WITH_CONCERNS | concerns 写入 report，审查者必读 |
| NEEDS_CONTEXT | 补上下文重派，**不换人** |
| BLOCKED | 换上下文 / 换专家 / 拆小 / 裁决重派 |

### 5. 独立计算变更集（主控亲为）

| 环境 | 方式 |
|---|---|
| 有 git | `review-package <plan> <BASE> <HEAD>`（BASE **禁用 `HEAD~1`**） |
| 无 git | 重算 sha256 → 差集 + 变更文件**全文** |

与实施者声明的文件清单比对：**不符即判 BLOCKED（隐瞒变更）**。

### 6. 派审查者

只给三件：brief / report / 变更集。**不给实施者对话上下文。必须给 spec + 质量双结论。**

### 7. 修复循环 ≤5

- 轮 1–3 恢复原实施者；轮 4–5 换更专专家（"升档"= 换专家，不是换 model）
- 每轮 scoped 重审（逐条 ADDRESSED / NOT ADDRESSED，不扩审）
- 5 轮仍 open → 裁决 park 或 Ruling

**主控绝不在自己会话里替实施者改码。**

### 8. 原子回写

同一消息完成：ledger `## Dispatches` 派发行（implementer + reviewer）+ ledger 完成行
+ `tasks.md` `- [x]` + todo 勾选。缺一不进下一任务。

派发行格式见 `templates/progress.md`：**未写派发行 = 未派发**（`S5.DISPATCH_IMPLEMENTER`
/ `S6.L0_REQUIRES_DISPATCH` 会 FAIL）；`agent` 必须是 `config/experts.json` 里的专家名，
`category` 必须与注册表一致；**implementer 不得填主控**。

## TDD 铁律

RED（看它因预期原因失败）→ GREEN（最小实现）→ REFACTOR（不新增行为）。

代码先于测试 = 删除重来。任何"这次跳过"即停止。

## 退出条件（G5，每任务）

- [ ] brief + report + 变更集三件齐备
- [ ] ledger `## Dispatches` 有 implementer 行（S5.DISPATCH_IMPLEMENTER）与 reviewer 行（S6.REVIEWER_DISPATCH）
- [ ] 审查双结论齐备
- [ ] ledger 有完成行
- [ ] tasks.md 已勾选
- [ ] 偏离已记 Ruling

下一阶段：`/wf:verify`
