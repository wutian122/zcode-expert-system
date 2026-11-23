---
description: 会话恢复 —— 从账本与事实层恢复中断的开发进度
name: wf-resume
---

# /wf:resume

中断或切换会话后，按严格读序恢复进度。**不能依赖聊天记录作为状态来源。**

## 严格读序（不可跳）

| # | 读什么 | 为什么这个位置 |
|---|---|---|
| 1 | 项目 `AGENTS.md` + 本地偏离登记 | 偏离项改变后续一切解释 |
| 2 | `python "${CLAUDE_PLUGIN_ROOT:-$ZCODE_PLUGIN_ROOT}/skills/zcode-expert-system/scripts/openspec_engine.py" status --change <n>` | **唯一合法路径来源**，禁自己拼 |
| 3 | `python "${CLAUDE_PLUGIN_ROOT:-$ZCODE_PLUGIN_ROOT}/skills/zcode-expert-system/scripts/openspec_engine.py" instructions apply --change <n>` | 拿 contextFiles + progress + sourcePath |
| 4 | `tasks.md` | 只做勾选快照，**不作结论** |
| 5 | `progress.md` **首行** | 归属确认；不匹配 → 不是你的账本，另建 |
| 6 | `progress.md` 全文 | 阶段/任务表/Blockers/最后修复轮/全部 Ruling |
| 7 | 计划 `## Rulings` | ADR 级理由（workspace 已删时唯一决策来源） |
| 8 | 计划 `## Baseline` / `## Review` / `## Integration Verification` | P3 持久证据 |
| 9 | 事实层（git log 或快照差集） | 不可争辩 |
| 10 | 三方核验 → 修正 → 记 Ruling → 继续 | 收尾 |

## 三方核验表

**优先级：事实 > ledger > tasks.md**

| 现象 | 裁决 | 动作 |
|---|---|---|
| ledger 说 complete，但无对应变更 | **ledger 错** | 回 IN_PROGRESS，记 Ruling |
| ledger 无记录，但有 commit | **完成候选**，≠完成 | 补审查才能 DONE |
| tasks.md 勾了，ledger 无记录 | **脏勾选** | 回退 `- [ ]`，记 Ruling |
| ledger 有记录，tasks.md 未勾 | **回写遗漏** | 补勾，记 Ruling |
| 最后一行是 `fix round R/5` | **修复轮中断** | 恢复第 R+1 轮 |
| 最后一行是 complete | **正常推进点** | 从下一任务开始 |
| 无 progress.md | **全新** | 预检后再派 Task 1 |

## 断点识别

```
会话启动
 ├─ git 探测失败 → 走快照路径，不阻断
 ├─ openspec root:null → 老板点名则停三选一；否则静默放弃
 ├─ workspace 存在？
 │   ├─ 否 → 新建 ledger（首行身份）→ 预检 → 派 Task 1
 │   └─ 是 → 首行 plan 匹配？
 │           ├─ 否 → 不是本计划账本，另建（不动原文件）
 │           └─ 是 → 断点识别 → 三方核验 → 修正 → 继续
 └─ 继续前先做「状态—tasks.md 一致性校验」，不一致先修再派
```

## 铁律

- **不得直接相信账本里的 DONE**——先核事实
- **不得重派已完成任务**（这是 SDD 最贵的失败）
- 不匹配的账本**不覆盖**，另建

核对：`${CLAUDE_PLUGIN_ROOT:-$ZCODE_PLUGIN_ROOT}/skills/zcode-expert-system/scripts/workflow_check.py --change <n> --plan <plan.md>`
