---
description: 派发计划 —— 生成角色×专家的二维派发指令
name: wf-dispatch
---

# /wf:dispatch

生成派发计划：每条含 role / subagent_type / 角色契约前置段。

## 执行

```bash
python "${CLAUDE_PLUGIN_ROOT:-$ZCODE_PLUGIN_ROOT}/skills/zcode-expert-system/zcode_dev_workflow.py" plan "<任务描述>" --files N
```

## 输出结构

```json
{
  "domain": { "category": "...", "expert_name": "..." },
  "dispatches": [
    { "role": "implementer", "subagent_type": "<域专家>", "prompt_prefix": "<契约>" },
    { "role": "reviewer",    "subagent_type": "代码审查员", "independence": "L0" }
  ],
  "parallel": { "implementation": "serial", "reason": "无 worktree..." }
}
```

## 派发公式

```python
Agent(
  subagent_type = "<专家中文名>",          # 域轴：从 zcode_expert_system 取
  prompt = "<references/roles/<role>.md 契约原文>\n\n"
           "【契约优先级】流程契约优先于专家人格。\n---\n"
           "<task-N-brief.md 路径>\n"
)
```

## 为什么角色不能做成子代理（三条，任一即否决）

1. **平台事实**：插件 `agents` 字段 recorded-but-not-executed。实测：`documents` 插件声明了 `"agents": "agents"` 且有 `agents/visual-judge.md`，但 `~/.zcode/agents/` 中并无该文件。
2. **SDD 契约**：implementer 禁止派子代理。做成"会派专家"的子代理 → 违约；做成"不派专家"的 → 空壳。
3. **人格冲突**：331 专家人格里没有工作流纪律。`多智能体系统架构师` 拿到 brief 会自己重新设计架构。

所以：**角色进 prompt 前置段，领域进 `subagent_type`。**

## Reviewer 独立性（三重）

- `type ≠` 不与 Implementer 同专家
- `instance ≠` 独立派发、独立上下文
- `input 隔离` 只给 brief / report / 变更集

落盘：`independence: L0 | L1 | L2`。L2 禁止交付。

## 并行边界

| 允许 | 禁止 |
|---|---|
| ✅ 只读调查并行（多域取证） | ❌ **多 Agent 实施并行** |
| ✅ 审查并行（只读无冲突） | — |

**无 Git Worktree ⇒ 无隔离工作区 ⇒ 实施永远串行。** 这是守恒，不是保守。

## 域路由失败时

显式降级三件套（不得静默）：`domain.degraded=true` + `plan.blocking` 非空 + 派发行 note 如实陈述。
`general-purpose` 只承接机械执行——**领域结论禁由通用代理产出**（W10），
须问老板澄清领域，或用 `build_dispatch_for_expert(专家名, task)` 指定后重跑。

## 语义精判分级处置（I-02 / I-03）

`semantic_selection_required=true`（Python 侧 `selection_basis=heuristic`，专家由词元计数选出）时，按**分类置信度**分两档：

| 条件 | 处置 |
|---|---|
| `confidence < 0.5`（`LOW_CONFIDENCE_THRESHOLD`） | **阻断实施者派发**：plan 含 `action: blocked_low_confidence`，不派 implementer/reviewer；`plan.blocking` 强制。分类本身不可靠，词元兜底专家与任务语义无关（如「支付幂等性」落 hr「招聘专家」）。必须先向老板澄清领域 |
| `confidence >= 0.5` | **保留派发**，但 plan 含 `action: semantic_recheck`——主控**必须**复核 `domain.top_candidates[].score_detail`，按业务语义定夺；要改判用 `build_dispatch_for_expert(专家名, task)` |

> 词元巧合实例：「修复用户登录接口的鉴权 bug」→ 后端架构 conf=1.0，却因 prompt 里出现过「登录」二字选中「飞书集成开发工程师」。
> 这正是 `semantic_recheck` 存在的理由——conf=1.0 只说明**领域**判对，不说明**专家**选对。
>
> `token`/`jwt`/`oauth` 按声明序落 security-compliance；若实为「实现/刷新/接入」等功能开发，应改判 backend-architecture。

## 只读任务为什么没有 reviewer

只读任务派 **analyst**（领域专家只读分析，四段式「现象→原因→影响→建议」输出），不进实施流程——
没有变更集就没有审查对象，reviewer 的三元输入（brief / report / 变更集）不成立。
analyst 产物由主控在会话内直接消费；其只读边界由角色契约（`references/roles/analyst.md`）约束，
落盘锚点是 `.superpowers/sdd/dispatch-<ts>/dispatch.json`（readonly 域路由成功时自动写）。
