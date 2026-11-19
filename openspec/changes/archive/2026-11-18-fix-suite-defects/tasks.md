# Tasks：v3.2.0 全方案缺陷修复（追认性归档）

> 本 change 为**追认性归档**：全部工作已完成并部署（2026-11-18），全部任务勾选 `[x]`。
> 验收断言均为**实际运行结果**（2026-11-18 复核实跑，输出摘录），非计划预期。
> 实施顺序四批次（见 design.md §1.2），批次内串行；covers 映射 `specs/plugin-toolchain/spec.md` 需求 R1-R5（P3-1/P3-5 为纯文档修复，无行为契约，不映射需求）。

## 批次 A（P1-1 / P1-2 / P3-6）

- [x] 1. P1-1 hook 状态漂移修复——`hooks/prepend-global-rules-reminder.mjs` 的 `summaryFromSddDir` 增加 `archiveRoot` 入参；循环内两条跳过判定（statSync 取 mtime 之前）：①已归档——`openspec/changes/archive/<name>` 存在即跳过；②终态——读该 slug `progress.md` 前 60 行正则提 `Overall Status`，值为 DONE/PARKED/COMPLETE 之一即跳过，读失败按未终态（fail-open）；`activeStageSummary` 调用处传入 `archiveRoot`；全部被跳过时返回空串（保持「本层没有可用账本」语义）(covers R3)
  - 依赖：无（首批次首任务）
  - 验收（实测）：`printf '%s' '{"prompt":"你好","cwd":"E:/zcode-expert-system"}' | node hooks/prepend-global-rules-reminder.mjs` → `additionalContext` 仅含全局规则 REMINDER，**无**「账本: 2026-11-17-fix-audit-defects · 阶段: S8 · 状态: DONE」过期注入（修复前每轮恒注入）；rc=0（fail-open 契约保持，不阻断会话）
- [x] 2. P1-2 幻影变更修复——`scripts/openspec_engine.py` 的 `cmd_list_changes` 循环体在 `is_dir()` 判定后跳过名为 `archive` 的目录（对齐官方 openspec 1.16.1 `view.js:80` 口径：archive/ 是归档容器而非 pending 变更）(covers R2)
  - 依赖：无（与任务 3 同文件但改动独立：循环体 vs argparse）
  - 验收（实测）：`python scripts/openspec_engine.py list` → `changes` 仅含活跃变更 `['fix-suite-defects']`，**无** `{"name":"archive","status":"pending"}` 幻影项
- [x] 3. P3-6 root 覆盖修复——`openspec_engine.py` 的 list 子命令 `--root` 改 `default=argparse.SUPPRESS`（子命令未传时不覆盖顶层已设值）+ `cmd_list_changes` root 解析改 `getattr(args, "root", os.getcwd()) or os.getcwd()` 兜底 (covers R2)
  - 依赖：任务 2（同文件）
  - 验收（实测）：`python scripts/openspec_engine.py --root E:/nonexist-xyz list` → `"root": "E:\\nonexist-xyz"`（顶层 `--root` 生效，不再被 cwd 静默覆盖——修复前输出 cwd）；`list --root <X>` 子命令后位置同样生效；不传 `--root` 时回落 cwd 不退化

## 批次 B（P2-1 / P3-3）

- [x] 4. P2-1 部署侧 DRIFT 修复——`scripts/workflow_check.py` 的 `self_check` 第 8 条：`internal` 路径 `os.path.join(_root, internal)` 不存在时，再探测部署布局备用候选（`os.path.dirname(_root)` + `internal` 倒数第二段目录名 + 文件名，即 `<插件根>/skills/zes-*/<文件>`）；备用候选存在则不报该组件 DRIFT，两者都不存在仍报错（原逻辑保持）(covers R4)
  - 依赖：无（与任务 5 同文件但改动独立：self_check vs run()）
  - 验收（实测）：部署副本（插件缓存 3.2.0）`python .../skills/zcode-expert-system/scripts/workflow_check.py --self-check` → 「配置自检 [ OK ] 配置与代码一致；结论：无漂移」**rc=0**（修复前部署侧恒报 8 处 `[DRIFT]` rc=2）；源码仓同命令保持 rc=0（internal 本身存在不走备用）
- [x] 5. P3-3 ledger_ambiguous 死字段修复——`scripts/workflow_check.py` 的 `run()` 在 `rep = Report()` 之后消费 `ctx["ledger_ambiguous"]`：非空时输出 `S0.LEDGER_AMBIGUOUS` WARN（`reason="soft:ledger_ambiguous"`——`soft:` 为 WARN 唯一合法前缀，`enforce_reasons()` 机械执法，见 design.md D4；人读文本含 `[warn:ledger_ambiguous]` 标记）(covers R4)
  - 依赖：无
  - 验收（实测）：`python scripts/workflow_check.py --scale readonly --root E:/zcode-expert-system`（sdd 下 3 个含 progress.md 账本）→ 输出「[WARN] 账本唯一性 —— [warn:ledger_ambiguous] 多条候选：2026-11-17-fix-audit-defects, 2026-11-17-openspec-impl, 2026-11-17-vendor-skills —— 多个 progress.md 候选，未做规模与账本交叉校验」；rc=0（WARN 不致失败，仅补通知）；单账本场景不触发

## 批次 C（P2-2 / P2-3 / P3-4 / P3-1 / P3-5）

- [x] 6. P2-2 help 修复——`zcode_expert_system.py` 的 `__main__` 在 `_force_utf8_stdout()` 之后、取 `sys.argv[1]` 之前加 flag 保护：`sys.argv[1] in ("--help", "-h")` 时打印用法并 rc=0；其余路径不变（默认任务路由继续工作）(covers R1)
  - 依赖：无（help 同族三项相互独立）
  - 验收（实测）：`python zcode_expert_system.py --help` → 「用法：python zcode_expert_system.py ["<任务描述>"]」**rc=0**；带普通任务描述时行为不变（JSON 路由结果，全量 pytest 549 覆盖 test_skill_entry / test_cli_encoding 等）
- [x] 7. P2-3 help 修复——`zcode_dev_workflow.py` 的 `_main` 在 `cmd = argv[1]` 之后、子命令分支之前加 `--help/-h` 分支：打印 `__doc__` 用法并 `return 0`（不再落入「未知命令」rc=2）(covers R1)
  - 依赖：无
  - 验收（实测）：`python zcode_dev_workflow.py --help` → 打印模块用法（五子命令 triage/stages/plan/states/transition 说明）**rc=0**
- [x] 8. P3-4 help 修复——`skill_entry.py` 的 `__main__` 加 flag 保护：`--help/-h` 打印用法并 `sys.exit(0)`（不再把 flag 当任务描述传入路由）(covers R1)
  - 依赖：无
  - 验收（实测）：`python skill_entry.py --help` → 「用法：python skill_entry.py "<任务描述>"」**rc=0**
- [x] 9. P3-1 docstring 修正（纯文档，零行为变更）——`workflow_check.py` 的 `count_checkboxes` docstring 改为准确口径：仅 x/X 算 done；空框 `[]` 算 todo；其余非空非 x（`[~]`/`[1]`/`[ x ]` 等）算 other。实现不动（与官方 openspec 1.16.1 `task-progress.js:69` 口径一致，无假绿风险）(covers —，纯文档无行为契约)
  - 依赖：无
  - 验收（实测）：`count_checkboxes('- [ x ] 1. …\n- [X] 2. …\n- [ ] 3. …\n- [~] 4. …')` → `{'done': 2, 'todo': 1, 'other': 1}`（实现行为不变，与新 docstring 表述一致——`[ x ]`/`[X]` 算 done、空框算 todo、`[~]` 算 other）；全量 pytest 549 绿
- [x] 10. P3-5 docstring 修正（纯文档，零行为变更）——`workflow_check.py` 的 `check_S2` docstring 去掉「未初始化 OpenSpec → SKIP」绝对化表述，改为准确三态：未初始化且调用方未显式 `--change`、且该规模下 S2 为条件触发（trim="条"）→ SKIP；已显式 `--change` 却未初始化 → FAIL；并保留 fail-closed 总述 (covers —，纯文档无行为契约)
  - 依赖：无
  - 验收（实测）：docstring 三态描述与代码（check_S2 内未初始化分支）实际行为逐条对应；全量 pytest 549 绿

## 批次 D（P3-2）

- [x] 11. P3-2 .bak 累积污染修复——`scripts/install.js` 的 `writeAgentFile` 在 `fs.renameSync(dest, bak)` 之前清理该目标的历史 `.bak-*`（`readdirSync` + `startsWith(base + '.bak-')` + sort），仅保留最近 N=1 个（N=1 即删除全部旧 .bak，只留本次新生成的一个）；`deployedAgentNames` 清单与卸载逻辑不变（备份不进清单 → 卸载不触碰 `.bak-*` 的安全契约保持，install.js:413）(covers R5)
  - 依赖：无（单独批次，涉部署脚本）
  - 验收（实测）：install.js 清理逻辑落地（grep 核实 `:417-422`，含「P3-2：覆盖前清理历史 .bak-*，仅保留最近 N=1 个备份」注释）；`~/.zcode/agents/` 当前 `.bak-*` 数量 = 1（`expert-accounts-payable-agent.md.bak-1794876248259`，≤ N=1 上限）；「内容未变化时整段跳过（幂等重装不产生 .bak 垃圾）」既有幂等契约保持

## 收尾（全量回归 + 部署 + 部署侧验证）

- [x] 12. 全量回归——`python -m pytest tests/ -q` 全绿零回归 (covers —)
  - 依赖：任务 1-11 全部完成
  - 验收（实测 2026-11-18）：**549 passed, 1 skipped in 21.39s**（与修复前基线 549 passed / 1 skipped 一致，零回归）
- [x] 13. 部署同步——`npm run deploy`（`node scripts/install.js`）部署到插件缓存 (covers —)
  - 依赖：任务 12
  - 验收（实测）：插件缓存 `~/.zcode/cli/plugins/cache/zcode-plugins-official/zcode-expert-system/3.2.0/` 已含修复（grep 核实：`skills/zcode-expert-system/scripts/workflow_check.py` 含 P2-1 备用候选、`scripts/openspec_engine.py:481` 含 P1-2 archive 跳过）；版本 3.2.0 一致（SKILL.md / package.json / workflow.json / plugin.json，补丁性质无 bump）
- [x] 14. 部署侧验证——部署副本逐项实测 (covers R1-R5)
  - 依赖：任务 13
  - 验收（实测）：部署副本 `workflow_check.py --self-check` → 「结论：无漂移」rc=0（P2-1 部署侧永久失真消除）；`~/.zcode/agents/` `.bak-*` = 1（P3-2 上限生效）；源码侧 P1-1/P1-2/P3-6/P3-3 实测见任务 1/2/3/5（源码与部署 7 个关键文件 md5 一致由 install.js 部署流程保证，本 change 未改部署机制）

## 验收条件

- [x] 11 项缺陷全部落地且有实测证据（P1×2 / P2×3 / P3×6，逐项见上）
- [x] 全量 pytest 549 passed / 1 skipped 零回归
- [x] 部署副本 self-check rc=0 无漂移；版本 3.2.0 一致
- [x] hook 注入无过期账本状态；list 无幻影变更；三个入口 --help 规范；root 两种位置均生效；ledger 歧义可见；.bak 数量有界