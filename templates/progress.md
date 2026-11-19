# SDD ledger — plan: <计划文件路径>

> 首行身份行不可改。路径不匹配即不是本计划的账本，另建，不动原文件。

## Project
<项目名>

## Change
<OpenSpec change 名>

## Current Phase
<S0..S8>

## Overall Status
<PENDING | IN_PROGRESS | REVIEW | NEEDS_FIX | BLOCKED | DONE | PARKED>

> 七态完整枚举。**PARKED 尤其不能省**：它表示「已知问题但本轮不修」，
> `workflow_check` 的归档门禁据此直接 FAIL（W8 默认禁归档）。
> 模板不提供这个值，执行者用 BLOCKED 代替就绕过了该拦截。

## Scale
<只读 | 轻量 | 中任务 | 大任务 | Bug>

## Triage
| 项 | 值 |
|---|---|
| 任务名 | |
| 类型 | |
| 用户目标 | |
| 涉及模块 | |
| 预估影响范围 | |
| 是否改数据库 | |
| 是否改 API | |
| 是否需多 Agent | |
| 是否需老板确认 | |
| 是否需隔离 | |
| 验收标准 | |
| 领域（category） | |
| 专家（name/basis） | |

> 「是否需隔离」是 W1「无 worktree 即无实施并行」的决策依据：
> 填「否」意味着本计划的实施必须串行，不得派多个写者。

## Baseline
| 项 | 值 |
|---|---|
| 命令 | |
| 退出码 | |
| 通过/失败 | |
| 失败清单 | |

> 主副本必须同时写入计划文档 `## Baseline`——ledger 会在终审后被删。

## Tasks

| Task | 说明 | Role | Agent | Instance | Status | 变更集 |
|---|---|---|---|---|---|---|
| 1 | | implementer | | 1 | PENDING | - |

## Dispatches

<!-- 每次派发一行，格式固定。这是根因回溯的唯一索引。 -->
<!-- dispatch <task> role=<Role> agent="<专家名>" category=<域> instance=<N> base=<标识> brief=<path> report=<path> changeset=<path> -->
<!-- readonly/analyst 派发例（无 report/changeset，产物在会话内）：
     dispatch 任务分析 role=analyst agent="软件架构师" category=backend-architecture instance=1 base=- brief=- report=- changeset=- -->

## Fix Rounds

<!-- Task N: fix round R/5 — <本轮改了什么> -->

## Rulings

<!-- Ruling: <决断> — <理由> — <错了的代价> -->
<!-- 每条 Ruling 同时必须导出到计划文档 ## Rulings -->

## Review
- independence: <L0 | L1 | L2>
- reviewer: <专家名>
- spec: <✅ SPEC-OK | ❌ SPEC-FAIL>
- quality: <APPROVED | NEEDS_FIX | BLOCKED>

## Blockers
<当前阻断问题>

## Next Actions
<下一步>

## Last Updated
<时间>
