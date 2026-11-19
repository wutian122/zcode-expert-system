# 工作流树与故障恢复

## 一、正常路径

```
S0 分诊（规模+域双轴） → S1 设计 →[老板批准]→ S2 规格 →[老板审产物]→ S3 计划
   → S4 环境+基线 → S5 逐任务(brief→实施→变更集→审查→修复≤5轮)
   → S6 终审+五层验证 → S7 交付+集成后重测 →[老板选]→ S8 同步 → 归档
```

## 二、分支路径（五类任务）

| 分支 | 触发 | 路径 |
|---|---|---|
| **B0 只读** | 分类=只读 | S0（双轴分诊）→ 派 analyst（领域专家只读分析）→ 输出 → 结束（结构：现象→原因→影响→建议） |
| **B1 无 git** | `git rev-parse` 失败 | 全流程，但变更集用**快照差集**，审查记 L1 降级声明 |
| **B2 Bug** | 分类=Bug | S0 → Bug 专项（Phase1-4 + 双确认）→ 条件回 S2/S3 → S5-S7 |
| **B3 轻量** | ≤3 文件 | S0必(双轴分诊) → S1简 → S5必(TDD) → S6简 → 收尾 |
| **B4 大任务** | 跨模块/架构 | 九阶段完整（但实施仍串行，见 W1） |

## 三、各阶段故障模式

| 阶段 | 故障长相 | 恢复 |
|---|---|---|
| S0 | 分类说不出口 | 停，回问；不得自定规模 |
| S0 | `root: null` 非老板点名 | 静默放弃 OpenSpec，不提 setup |
| S0 | `Declared in` 错误 | 停，展示 message+fix——**≠未初始化** |
| S1 | 老板否决 | 重出方案 |
| S1 | 范围扩大 | 回 S0 重分诊（ratchet） |
| S2 | CLI 不可用 | 如实报告并停，**禁伪造** |
| S2 | 产物 blocked | 按 requires 边补依赖 |
| S3 | 计划与 spec 矛盾 | 以 spec 为准；或回 S2 |
| S4 | 基线红 | 停，问老板带病开工否 |
| S5 | BLOCKED | 换上下文/换专家/拆小/裁决重派 |
| S5 | 5 轮仍 open | park + Ruling |
| S5 | 报告与变更集不符 | 判 BLOCKED（隐瞒变更） |
| S6 | Critical | 一轮修复 wave + scoped 重审 |
| S6 | 证据缺失 | 不得声明完成，回 S5 |
| S7 | 集成后红 | 停，原地保留，回 S5/S6 |
| S8 | sync 阻塞 | 立即停归档 |

## 四、跨会话恢复（严格读序）

| # | 读什么 | 为什么这个位置 |
|---|---|---|
| 1 | 项目 `AGENTS.md` + 本地偏离登记 | 偏离项改变后续一切解释 |
47	| 2 | `python scripts/openspec_engine.py status --change <n>` | **唯一合法路径来源**，禁自己拼 |
48	| 3 | `python scripts/openspec_engine.py instructions apply --change <n> --json` | 拿 contextFiles + progress + sourcePath |
| 4 | `tasks.md` | 只做勾选快照，**不作结论** |
| 5 | `progress.md` **首行** | 归属确认；不同 → 不是你的账本，另建 |
| 6 | `progress.md` 全文 | 阶段/任务表/Blockers/最后修复轮/全部 Ruling |
| 7 | 计划文档 `## Rulings` | ADR 级理由（workspace 已删时唯一决策来源） |
| 8 | 计划文档 `## Baseline` / `## Review` / `## Integration Verification` | P3 持久证据 |
| 9 | 变更集实际状态（git log 或快照差集） | 事实层 |
| 10 | 三方核验 → 修正 → 记 Ruling → 继续 | 收尾 |

## 五、三方核验表（账本与事实不一致）

**优先级：事实 > ledger > tasks.md**

| 现象 | 裁决 | 动作 |
|---|---|---|
| ledger 说 complete，但无对应 commit/变更集 | **ledger 错** | 状态回 IN_PROGRESS，记 Ruling |
| ledger 无记录，但有 commit | **完成候选**，≠完成 | 补一次审查才能进 DONE |
| tasks.md 勾了，ledger 无记录 | **脏勾选** | 回退 `- [ ]`，记 Ruling |
| ledger 有记录，tasks.md 未勾 | **回写遗漏** | 补勾，记 Ruling |
| ledger 最后一行是 `fix round R/5` | **修复轮中断** | 恢复第 R+1 轮 |
| ledger 最后一行是 complete | **正常推进点** | 从下一任务开始 |
| 无 progress.md | **全新** | 预检扫描后再派 Task 1 |
| readonly 任务无账本 / 无派发行 | **正常**（D4：readonly 按裁剪不产生账本） | S0.DOMAIN 判 SKIP；analyst 产物不落 task-report，核会话内四段式输出与 dispatch.json |

## 六、断点识别（决策树）

```
会话启动
 ├─ git 探测失败 → 走快照路径（B1），不阻断
 ├─ openspec root:null → 老板点名则停三选一；否则静默放弃
 ├─ 分类=只读 → 走 B0：S0 双轴分诊 → 派 analyst → 四段式输出 → 结束（无账本，D4）
 ├─ workspace 存在？
 │   ├─ 否 → 新建 ledger（首行身份）→ 预检 → 派 Task 1
 │   └─ 是 → 首行 plan 匹配？
 │           ├─ 否 → 不是本计划账本，另建（不动原文件）
 │           └─ 是 → 断点识别 → 三方核验 → 修正 → 继续
 └─ 继续前先做「状态—tasks.md 一致性校验」，不一致先修再派
```

## 七、可观测性最小集

平台无跨子代理 trace_id，关联键用三元合成：

> **关联键 = `(change-name, task-id, 变更集标识)`**

| 粒度 | 必记 |
|---|---|
| 每次派发 | task-id / role / agent / instance / 输入三件路径 |
| 每个任务 | 状态 / 测试命令与结果 / 审查双结论 / 修复轮次 / parked 原因 |
| 每个 change | change 名 / 基线清单 / 全部 Ruling / 派发次数 |
| 每个门禁 | 门禁 ID / 通过否 / 证据位置 / 是否停老板 |
