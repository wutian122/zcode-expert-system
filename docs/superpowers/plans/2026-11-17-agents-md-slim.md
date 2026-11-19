# AGENTS.md 瘦身计划（保留至任务完成）

> 任务日期：2026-11-17 ｜ 规模：中任务 ｜ 执行模式：apply-change 直行（老板批准）
> 备份：`~/.zcode/AGENTS.md.bak-2026-11-17-before-slim`（381 行，可一键回滚）

## Goal

消除插件工作流与全局 AGENTS.md 的 9 条冲突中的 C1/C2/C3/C4/C7/C9，把流程层（约 140 行）改为指向插件的指针，让 AGENTS.md 只管「环境与红线」。

## 已批准决策（老板 2026-11-17）

| 决策 | 内容 |
|---|---|
| 删除范围 | 删流程层留指针（约 140 行）：二/三/六章 + 七章流程类 R 条款 + 十二章 B/C 段 + 五章流程描述 |
| 轻量任务 C2 | **按插件口径**：轻量也须一页最小计划 + 基线两行（trim_matrix.light 的 S3/S4/S7=必） |
| OpenSpec 路径 | 简化路径：本计划文档代替 OpenSpec 产物（插件项目无 openspec root，按双分支规则静默放弃） |

## 不变量（验证时逐条核对）

- [ ] 铁律 11 编号原样保留（插件 `workflow_check.py:795,809,851,865` 引用）
- [ ] 〇/一/八/九/十 五节零改动
- [ ] 删除处留指针，不留白
- [ ] 插件 451 测试全绿

## Tasks

### Task 1: 备份
`cp ~/.zcode/AGENTS.md ~/.zcode/AGENTS.md.bak-2026-11-17-before-slim`（381 行校验一致）

### Task 2: 本计划文档
写 `docs/superpowers/plans/2026-11-17-agents-md-slim.md`

### Task 3: 迁 B7 进插件
`AGENTS.md:217` 的 update-change 同步义务（改 tasks.md 须同回合同步修计划文档并记 Ruling）补进 `references/stage-S2-spec.md`——先迁再删，防真丢。

### Task 4: 改二章（C2）
删 Step 1 分类表 + Step 1.5 模糊检测 + Step 2 路由（141 行），保留 142 行拦截规则与 144-147 行 Step 3 行为门禁。

### Task 5: 改三章
压缩为指针：指向 `references/workflow-tree.md:15` B0 分支。

### Task 6: 改四章（C2）
删「可跳过 brainstorming、OpenSpec、writing-plans」，改为「轻量也须一页最小计划 + 基线两行 + TDD 不可跳」。

### Task 7: 改五章
删与 `templates/bug-report.md` 逐字重复的流程编号描述，保留 7 类分诊表与取证工具库（qwen-mm/find-polluter/双引擎）。

### Task 8: 改六章（C1/C4/C9）
192-279 行删除，换 8 行指针指向 `config/workflow.json` 与 `references/stage-S*.md`。

### Task 9: 改七章（C7）
删 R1-R7/R10/R14（9 条流程类），保留 R8/R9/R11/R12/R13/R15（6 条红线类）。R11 改写「/opsx 6 个实存」。

### Task 10: 改〇章（C1/C3）
:49 删 worktree 强制；:54 非 git 改「走快照证据 + L1」，不再禁 SDD。

### Task 11: 改一章（C4）
:86 executing-plans 行删除；:88 改为「见插件 W1」。

### Task 12: 改八章
:310/:320 引用改为指向插件 S5/S8。

### Task 13: 改十一章（C1）
铁律 5 改「并行实施已取消」；铁律 6/11 的「R1、6.4/6.7」引用改为插件 INV/S7。

### Task 14: 改十二章（C5）
B/C 段改为指针指向插件 S5/S6/S7/S8 退出条件。

### Task 15: 验证
grep 悬空引用（6.4/6.5/6.7/第六章/executing-plans）→ 行数 381→~240 → 451 测试 → 铁律 11 编号在位 → 零引用断链。

## 交叉引用修复清单（12 处，最大风险）

| 行号 | 原引用 | 改法 |
|---|---|---|
| 49 | 「(6.4/6.5)」 | 随内容改写消失 |
| 68 | 「见 R4」 | 删 |
| 86 | 「见 R4」 | 整行删 |
| 88 | 「见 R2/R14」 | 改「见插件 W1」 |
| 141 | 「第六章主管道」 | 改「references/stage-S*.md」 |
| 142 | 「第六章阶段 0-3」 | 改「S0-S3」 |
| 181 | 「按 R2 派子代理」 | 改「只读并行，见插件 W1」 |
| 310 | 「(6.4)」 | 改「插件 S5」 |
| 320 | 「6.7 的 sync→archive」 | 改「插件 S8」 |
| 349 | 「R1、6.4 约束 2」 | 改「插件 INV2/INV3」 |
| 354 | 「6.4 SDD 循环第 7 条 / 6.7」 | 改「插件 S7 workspace 导出」 |
| 296 | R11「ZCode 无 /opsx」 | 实测改写 |

## Review Focus

- 第 3 步是否在删六章之前完成（先迁后删顺序不能乱）
- 十二处引用修复是否有遗漏（grep 验证是硬判据）
- 铁律编号是否原样保留（插件 4 处引用）
- 〇/一/八/九/十 五节是否零改动

## Global Constraints

- 不改 `~/.zcode/AGENTS.md.bak-*`（备份不得动）
- 插件 Python 文件本轮零改动（B7 迁移只动 references/stage-S2-spec.md）
- 改后用 grep 实测，禁止口头声称
