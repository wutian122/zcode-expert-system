# S5 · 代码实施与多 Agent 协作

**门禁**：G5（每任务）｜ **证据级**：P4 → P2 ｜ **角色**：Implementer（域专家，串行）
**组件**：zes-openspec-apply-change（见 config/workflow.json 的 component_registry）

## 执行模式（互斥，不可混用）

| 模式 | 触发 | 账本 |
|---|---|---|
| **SDD**（默认） | 有子代理，任务可独立拆分 | ledger + 原子回写 tasks.md |
| **apply-change 直行** | 未写计划文档的小中任务 | **无 ledger**，tasks.md 即账本 |

同一 change 在同一时刻只允许一种模式，必须在 S3 声明。切换须记 Ruling，且不得回退已勾选任务。

## 每任务循环（SDD）

```
1. 记 BASE / 快照基线
2. task-brief 抽任务原文 → task-<N>-brief.md
3. 派实施者（gap: subagent_type = 域专家，prompt 前置角色契约）
4. 四态处理
5. 独立计算变更集
6. 派审查者（异域专家）
7. 修复循环 ≤5 轮
8. 原子回写：ledger + tasks.md
```

### 1. 快照基线（无 git 时的证据来源）

派发前对任务 Files 清单每个文件记录 sha256：

```json
{ "files": { "src/a.py": "<sha256>", "src/b.py": null } }
```

`null` = 文件不存在（预期新增）。

### 2. 任务 brief

```bash
bash "${CLAUDE_PLUGIN_ROOT:-${ZCODE_PLUGIN_ROOT:-$QODER_PLUGIN_ROOT}}/skills/zcode-expert-system/scripts/sdd/task-brief" <plan.md> <N>
```

brief 是实施者**唯一**的任务信息来源。不往派发 prompt 灌历史摘要——文件交接。

### 3. 派发实施者

```python
Agent(
  subagent_type = "<域专家名>",              # 来自 zcode_expert_system
  prompt = "<references/roles/implementer.md 全文>\n\n"
           "【契约优先级】流程契约优先于专家人格。\n---\n"
           "读这个文件：<task-N-brief.md>\n"
           "先前的接口：<Consumes>\n"
           "主控裁决：<load-bearing Ruling>\n"
           "报告写到：<task-N-report.md>\n"
)
```

**实施者禁派子代理。** 报告只回 6 行：STATUS / COMMIT / TESTS / CONCERNS / REPORT。

### 4. 四态处理

| 状态 | 处理 |
|---|---|
| `DONE` | 进第 5 步 |
| `DONE_WITH_CONCERNS` | concerns 写入 report，审查者必读；正确性/范围类先处置 |
| `NEEDS_CONTEXT` | 补上下文后重派，**不换人** |
| `BLOCKED` | 换上下文 / 换更专专家 / 拆小 / 计划错则裁决后重派 |

### 5. 独立计算变更集（主控亲为）

**不由实施者自述**——这是无 git 环境仍可信的关键。

| 环境 | 方式 |
|---|---|
| 有 git | `review-package <plan> <BASE> <HEAD>`（BASE 禁用 `HEAD~1`，多提交任务会被截断） |
| 无 git | 重算 sha256 → 差集 = 新增/修改/删除 → 附变更文件**全文** |

与实施者报告的"改了哪些文件"比对：**不符即判 BLOCKED**（隐瞒变更）。

### 6. 派发审查者

```python
Agent(
  subagent_type = "<异域专家>",              # ≠ 实施者
  prompt = "<references/roles/reviewer.md 全文>\n---\n"
           "brief: <path>\nreport: <path>\n变更集: <path>\n"
)
```

只给三件。不给实施者对话上下文。**必须给 spec + 质量双结论。**

### 7. 修复循环（≤5 轮）

- 轮 1–3：`SendMessage` 恢复原实施者
- 轮 4–5：换更专专家（"升档"= 换专家，不是换 model）
- 每轮结束做 **scoped 重审**（逐条 ADDRESSED / NOT ADDRESSED，不得扩审）
- 5 轮仍 open → 主控裁决 park 或 Ruling，全记账

**主控绝不在自己会话里替实施者改码**——那会跳过审查。

### 8. 原子回写（同一消息完成）

- ledger `## Dispatches`：本任务的 implementer 派发行（第 3 步）与 reviewer 派发行（第 6 步）
- ledger：`Task N: complete (commits …)` 或 `Task N: parked (reason)`
- `tasks.md`：对应条目 `- [x]`
- todo 勾选

缺一即不得进下一任务（INV2 / INV6）。

**派发行是完成态证据的一部分**：没写派发行 = 没派发。`workflow_check` 对
「有完成行但没有 implementer 派发行」判 `S5.DISPATCH_IMPLEMENTER` FAIL；
`agent` 必须是 `config/experts.json` 里的专家名，`category` 必须与注册表一致；
**主控不得把自己写成 implementer**（自己改码 = 跳过审查）。

## TDD 铁律（贯穿所有模式）

1. **RED**：先写失败测试，**看见它因预期原因失败**——失败原因必须是功能缺失，不是笔误
2. **GREEN**：恰好让测试通过的最小实现
3. **REFACTOR**：绿后清理，不新增行为

代码先于测试 = 删除重来。任何"这次跳过"即停止。

### 写测试三条

1. 命名它要抓的破坏
2. 驱动真实行为（期望值手推，mock 只在慢/外部层）
3. 变色检查：故意改坏实现，测试必须变红

## 退出条件（G5，每任务）

- [ ] brief + report + 变更集三件齐备
- [ ] ledger `## Dispatches` 有本任务的 implementer 行与 reviewer 行（未写=未派发）
- [ ] 审查双结论齐备（spec ✅/❌ + 质量）
- [ ] ledger 有完成行
- [ ] tasks.md 对应条目已勾选
- [ ] 每条偏离记 Ruling

## 三个铁律

| 铁律 | 后果 |
|---|---|
| 实施者禁派子代理 | 重复审查席位、成本翻倍、结论不计 |
| 主控禁替实施者改码 | 跳过审查 |
| 禁采信自报成功 | 无证据完成 |
