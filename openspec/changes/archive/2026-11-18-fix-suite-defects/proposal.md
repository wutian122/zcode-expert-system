# Proposal：v3.2.0 全方案缺陷修复（追认性归档）

## Why

v3.2.0 部署后的全方案功能测试（2026-11-18：主控实测 + 2 个只读测试子代理（路由 CLI 语义 10 项 + hooks/门禁 8 组）+ 代码审查员三轮复核收敛定级）发现 **11 项缺陷 = P1×2 + P2×3 + P3×6**（初版「P1×2+P2×5+P3×3」中 P2-4/P2-5 经第三轮对照官方 openspec 1.16.1 源码降 P3，并补入遗漏的 root 覆盖 bug）：

1. **P1-1 hook 状态漂移**：`hooks/prepend-global-rules-reminder.mjs` 的 `summaryFromSddDir` 按 mtime 选最新 sdd 账本，不查归档、不判终态——已归档的 `2026-11-17-fix-audit-defects` 被恒注入为「当前工作流」，每轮 UserPromptSubmit 输出过期状态；
2. **P1-2 幻影变更**：`scripts/openspec_engine.py` 的 `cmd_list_changes` 枚举 `changes/` 只查 `is_dir()`，把 `archive/` 目录当 pending 变更列入 `list --json` 输出，误导九阶段 S8 归档完成度判断（AGENTS.md 以 list 的 totalTasks/completedTasks 为口径）；
3. **P2-1 部署侧 self-check 失真**：`config/workflow.json` 的 component_registry internal 路径按源码布局声明（`vendor/skills/zes-*`），部署布局是 `<插件根>/skills/zes-*`，部署副本 `workflow_check --self-check` 恒报 8 处 DRIFT；
4. **P2-2 / P2-3 / P3-4 CLI help 不规范**：`zcode_expert_system.py --help` 与 `skill_entry.py --help` 把 flag 当任务路由，`zcode_dev_workflow.py --help` 落入「未知命令」rc=2；
5. **P3-6 root 覆盖 bug**：顶层 `--root X list` 被子命令 `default=None` 静默覆盖为 cwd；
6. **P3-1 / P3-5 文档失准**：`count_checkboxes` 与 `check_S2` 的 docstring 与实现（及官方口径）矛盾；
7. **P3-2 .bak 累积污染**：`install.js` 每次部署内容变化产生新 `.bak-*`，agents 目录随部署次数膨胀；
8. **P3-3 死字段**：`workflow_check.py` 的 `ctx["ledger_ambiguous"]` 只写不读，多账本歧义静默跳过交叉校验。

测试基线（修复前）：源码 pytest **549 passed, 1 skipped**；路由引擎（双轴分诊/语义精判/降级兜底/状态机/编码防护）**10/10 通过**；hooks/门禁 fail-open/fail-closed 契约成立——缺陷全部集中在**工具链可用性层**，不影响路由正确性与门禁强度。

老板指令「发现问题先记录」：测试阶段只读，未改任何代码；修复方案经批准后另行实施。

## What Changes

**四批次最小修复**（每批同文件聚合，批次间串行；逐项根因 path:line → 最小改动 → TDD 方案 → 风险回滚见 docs/test-reports/2026-11-18-fix-plan.md）：

- **批次 A**（P1-1 / P1-2 / P3-6）：hook 跳过已归档与终态账本（fail-open）；list 跳过 `archive` 目录（对齐官方 openspec 1.16.1 `view.js:80` 口径）；list 子命令 `--root` 改 `argparse.SUPPRESS` + getattr 兜底，两种 `--root` 位置均生效；
- **批次 B**（P2-1 / P3-3）：self_check 第 8 条加部署布局备用候选探测（存在则不报 DRIFT）；`ledger_ambiguous` 在 run() 消费为 `S0.LEDGER_AMBIGUOUS` WARN（`soft:` 前缀，WARN 不致 rc≠0）；
- **批次 C**（P2-2 / P2-3 / P3-4 / P3-1 / P3-5）：三个入口 `--help/-h` 打印用法 rc=0；两处 docstring 修正对齐实现与官方口径（纯文字，零行为变更）；
- **批次 D**（P3-2）：`install.js` writeAgentFile 覆盖前清理历史 `.bak-*`，仅保留最近 N=1 个（安全网不失，污染止住）；
- **收尾**：全量 pytest 549 零回归 + `npm run deploy` 部署同步 + 部署侧验证。

## 影响范围

- **源码 7 个文件**：`hooks/prepend-global-rules-reminder.mjs`（P1-1）、`scripts/openspec_engine.py`（P1-2/P3-6）、`scripts/workflow_check.py`（P2-1/P3-1/P3-3/P3-5）、`zcode_expert_system.py`（P2-2）、`zcode_dev_workflow.py`（P2-3）、`skill_entry.py`（P3-4）、`scripts/install.js`（P3-2）；
- **测试**：无新增专项回归测试（P1-1 按方案用临时脚本验证，不落盘源码；其余 CLI 级实测），零回归由全量 pytest 549 passed / 1 skipped（与修复前基线一致）证明；
- **规格**：新建能力 `plugin-toolchain`（delta spec 锁插件工具链行为契约，见 specs/plugin-toolchain/spec.md）；
- **版本号**：3.2.0 不变（补丁性质，无 bump；SKILL.md / package.json / workflow.json / plugin.json 一致）。

## 不包含什么

- 不改路由算法（`zcode_expert_system.py` 词元粗筛 + 主控语义精判架构，331 专家 / 32 领域 / categories.json 映射）；
- 不改专家人格与 roles 契约；
- 不改九阶段结构 S1-S8、七态状态机、门禁与裁剪矩阵定义（P2-1 只改 self_check 的路径探测，不改门禁逻辑）；
- 不重新设计任何模块——全部 11 项均为最小改动（单文件单处或数处）；
- 不动 `validate --change archive` 的 rc=0 行为（P1-2 仅修 list 枚举，validate 自身契约保持）；
- 不修观察项（heuristic 弱选择、v3.2 旧账本迁移成本、trim_matrix「条」触发引擎、hook 注入恒定性——均为设计内或已知裁决，见测试报告「观察项」）。

## 老板裁决记录（2026-11-18 全链路逐步拍板）

| # | 裁决项 | 结果 |
|---|---|---|
| 1 | 缺陷处置 | **发现问题先记录**（只读测试，11 项缺陷清单落盘，未改任何代码） |
| 2 | 定级口径 | **三轮代码审查员复核收敛**：11 项 = P1×2 + P2×3 + P3×6（P2-4/P2-5 降 P3 附官方源码证据，补入 root 覆盖 bug） |
| 3 | 修复方案 | **批准 4 批次最小变更方案**（每项根因 path:line + 最小改动 + TDD 方案 + 风险回滚） |
| 4 | 推进方式 | **按批次做**（A→B→C→D，批次内串行实施，同文件同批次） |
| 5 | 部署 | **部署同步**（npm run deploy，源码与插件缓存 3.2.0 一致） |
| 6 | 规格流程 | **补走归档**（追认性 OpenSpec change：四件产物补齐、tasks 全 [x]、delta spec 归档后进主 spec） |