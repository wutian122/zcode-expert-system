# Design：v3.2.0 全方案缺陷修复（唯一设计真相）

> 本文是本变更的唯一设计真相。素材：`docs/test-reports/2026-11-18-v3.2.0-full-suite-test.md`（缺陷清单，11 项含根因 path:line）与 `docs/test-reports/2026-11-18-fix-plan.md`（修复方案，逐项 TDD 与风险回滚）。
> 本 change 为**追认性归档**：设计在实施前已经老板批准（方案审批 = 设计批准，见 proposal 老板裁决记录 #3），实施已完成并部署（2026-11-18）；本文补写固化设计决策、实施与实际偏差，全部验收断言为实际运行结果（2026-11-18 复核实跑，摘录见 tasks.md）。

## 1. 缺陷分级与批次分组

### 1.1 定级口径（三轮复核收敛）

初版定级「P1×2 + P2×5 + P3×3」；第三轮代码审查员复核对照官方 `@fission-ai/openspec` 1.16.1 源码后收敛为 **P1×2 + P2×3 + P3×6**：

- P2-4（现 P3-1）：`count_checkboxes` 的 `[ x ]` 口径——官方 `task-progress.js:69`（`done: (match[1] ?? '').toLowerCase() === 'x'`，注释明言 Only x/X means done）与 `workflow_check.py:201` 的 `_TASK_LINE_PATTERN` 逐字一致，实现无假绿风险，过时的是 docstring → 降 P3；
- P2-5（现 P3-2）：agents `.bak` 残留——`install.js:413` 注释明言备份是安全网设计、卸载不触碰 `.bak-*` 是有意为之，真实问题只是累积污染 → 降 P3；
- 补入第三轮遗漏项 P3-6（顶层 `--root` 被 cwd 静默覆盖，审查员发现、主控复现）。

### 1.2 批次分组原则（D1）

**同文件同批次**，批次间串行（实施永远串行），批次内项之间无跨项依赖：

| 批次 | 包含项 | 分组依据 |
|---|---|---|
| A | P1-1、P1-2、P3-6 | P1-2 与 P3-6 同在 `openspec_engine.py`（改动独立：循环体 vs argparse）；P1-1 独立文件（hook）；三项均极小 |
| B | P2-1、P3-3 | 同在 `workflow_check.py`（改动独立：self_check 第 8 条 vs run() 消费） |
| C | P2-2、P2-3、P3-4、P3-1、P3-5 | 三个 help 同族（P2-2/P2-3/P3-4，各自最小 flag 保护）+ 两个纯 docstring（P3-1/P3-5）；方案建议拆两提交：help 同族一提交、docstring 两项一提交 |
| D | P3-2 | 独立部署脚本 `install.js`，涉部署行为，单独批次审查更严 |

同文件同批次的理由：避免同文件多批次交叉造成审查边界混乱与实施期互相踩；每项改动局限于单文件单处或数处，同批合并审查可一次核清全貌。全部 11 项均有最小修法，无一回退为「不修」。

## 2. 关键设计决策（D1-D8）

| # | 决策 | 理由 |
|---|---|---|
| D1 | 批次分组 = 同文件聚合（§1.2） | 审查边界清晰；实施串行不并行（插件 W1） |
| D2 | **P3-1/P3-5 降为文档缺陷，改 docstring 不改实现** | P3-1：实现对齐官方 openspec 1.16.1 `task-progress.js:69` 口径（仅 x/X 算 done），运行时无假绿风险，过时的是 docstring；P3-5：`check_S2` 的 fail-closed（未初始化 OpenSpec + 显式 `--change` → FAIL）是 AGENTS.md「自选 OpenSpec 走普通请求不进九阶段」契约的正确保守行为，docstring「未初始化 OpenSpec → SKIP」的绝对化表述失准。两项纯文字改动、零行为变更，TDD 不适用（无行为可先红），验证 = 全量 pytest 绿证明无断言受影响 |
| D3 | **P3-2 保留 N=1 备份（不清零）** | `install.js:413` 安全契约：覆盖前备份防用户定制内容静默丢失；备份不进 deployedAgentNames 清单 → 卸载按清单删、不触碰 `.bak-*`（有意为之）。修复目标是**累积污染**（每次内容变化产生新 .bak），不是备份本身——保留最近 1 个：覆盖时删除全部旧 .bak 只留新生成的一个，既有「上一版可恢复」的安全网不失 |
| D4 | **P3-3 的 reason 前缀用 `soft:`（方案原写 `warn:`）** | `workflow_check.py:76` 契约：「soft: → WARN 唯一合法前缀」；`Report.enforce_reasons()`（:114）机械执法「WARN 而理由码不以 `soft:` 开头 → 改判 FAIL」。方案原写 `warn:ledger_ambiguous` 会被 enforce_reasons 改判 FAIL（rc≠0），破坏「WARN 不致失败、仅补通知」的设计意图；实施修正为 `reason="soft:ledger_ambiguous"`，人读输出文本仍含 `[warn:ledger_ambiguous]` 标记便于识别 |
| D5 | **hook 终态判定 fail-open** | hook 是 UserPromptSubmit 注入层，既有契约：13 种输入变异 + 非法 JSON + 空 stdin + EPIPE 全部 rc=0 不阻断。P1-1 新增的终态判定读 progress.md 失败按未终态处理（return false）；全部候选被跳过时返回空串（保持「本层没有可用账本」语义，继续上溯或返回空）。注入缺失的代价远小于阻断会话——hook 绝不可因账本状态异常阻断用户输入 |
| D6 | **root 覆盖 bug 用 argparse SUPPRESS 方案** | 根因：顶层 `--root default=os.getcwd()`（:513）与 list 子命令 `--root default=None`（:552）同名冲突——argparse 子命令解析时子 parser 的 `default=None` 覆盖顶层已设的 `args.root`，`cmd_list_changes` 回落 cwd。方案：子命令 `--root` 改 `default=argparse.SUPPRESS`（子命令未传 --root 时该属性不出现、不覆盖顶层已设值）+ `cmd_list_changes` 改 `getattr(args, "root", os.getcwd()) or os.getcwd()` 兜底（SUPPRESS 下属性可能不存在）。效果：`--root X list` 与 `list --root X` 两种用法均生效，不传时 root=cwd 不退化。SUPPRESS 是 argparse 官方机制，比在 cmd 内区分参数来源更稳 |
| D7 | **P1-2 对齐官方口径：跳过 archive 名称目录** | 官方 `@fission-ai/openspec` 1.16.1 `dist/core/view.js:80`：`if (entry.isDirectory() && entry.name !== 'archive')`——archive/ 是归档容器不是变更。最小改动 = `cmd_list_changes` 循环体在 `is_dir()` 判定后加一行跳过。`validate --change archive` 行为不动（该命令自身契约：存在目录 valid:false + rc=0，不存在 rc=1） |
| D8 | **P2-1 双候选探测而非改配置** | component_registry 的 internal 路径是源码布局声明（`vendor/skills/zes-*`），改配置声明会破坏源码侧自检；`self_check` 第 8 条在 `os.path.join(_root, internal)` 不存在时，再探测部署布局备用候选 `dirname(_root) + internal 倒数第二段目录名 + 文件名`（即 `<插件根>/skills/zes-*/<文件>`，install.js 步骤 1c' 的实际部署布局），存在则不报 DRIFT；两者都不存在仍报错（原逻辑保持，不漏报真实漂移）。源码仓 internal 本身存在，不走备用，保持 OK |

## 3. 实施与实际偏差

| # | 项 | 方案原文 | 实际实施 | 原因 |
|---|---|---|---|---|
| 1 | P3-3 reason 码 | `reason="warn:ledger_ambiguous"`（修复方案 §P3-3 代码示例） | `reason="soft:ledger_ambiguous"`（`workflow_check.py:1708`，人读文本仍含 `[warn:ledger_ambiguous]`） | enforce_reasons 契约（D4）：WARN 唯一合法前缀是 `soft:`，`warn:` 会被机械改判 FAIL、破坏「WARN 不致失败」意图 |
| 2 | P2-1 部署侧验证方式 | RED：在部署侧运行 self-check 断言 8 处 DRIFT rc=2，GREEN：部署侧再跑断言 rc=0 | 源码侧改 self_check 逻辑（备用候选探测）+ 全量 pytest 绿 → `npm run deploy` → **部署后**在部署副本实测 `--self-check` 输出「结论：无漂移」rc=0 | 部署副本由 install.js 管理，为造 RED 手工改动部署副本会造成源码/部署漂移；部署侧验证统一放部署后实测（部署副本 `workflow_check.py` 含 P2-1 标记，grep 核实） |
| 3 | P1-1 测试载体 | 临时 Node 脚本（方案已声明不落盘到源码，仅会话临时目录运行） | 同方案执行：构造最小伪造目录结构验证跳过逻辑 + CLI 级实测（stdin 灌入验证无过期注入、rc=0 fail-open） | 与方案一致；11 项修复均未新增专项 pytest 回归测试，零回归由全量 549 passed / 1 skipped（与修复前基线一致）承担 |

**如实声明**：以上为全部已知偏差，无其他未记录的实施偏离。11 项修复的验收证据均为 2026-11-18 实际运行的命令输出（tasks.md 各任务验收行）。

## 4. 风险与回滚（汇总）

- 全部 11 项改动局限于单文件单处或数处（改动规模：极小 ×8、小 ×3），逐项回滚 = 还原对应代码段（本仓库非 git，按文件级快照回滚）；
- 最高风险项 P3-2（涉部署脚本 `install.js`）单独批次 D，且保留 N=1 而非清零，回滚 = 删除清理逻辑恢复原状；
- P2-1 备用候选推断错误的漏报风险，由「两者都不存在时报 DRIFT」的原逻辑兜底（备用候选只是补充探测，不替代原判定）；
- P1-1 误跳过未归档但已 DONE 账本的风险：终态（DONE/PARKED/COMPLETE）本就无活跃工作流可注入，跳过不影响正确会话；回滚 = 去掉终态判定仅保留归档判定。

## 5. 验收索引（covers 映射 specs/plugin-toolchain/spec.md）

| 需求 | 覆盖项 | 验收锚点（实测） |
|---|---|---|
| R1 CLI 入口帮助与任务分流 | P2-2 / P2-3 / P3-4 | 三入口 `--help` rc=0 输出用法；普通任务参数行为不变（pytest 549 覆盖） |
| R2 内置引擎 change 枚举与 root 语义 | P1-2 / P3-6 | list 输出无 archive 项；`--root X list` 与 `list --root X` 均输出 root=X |
| R3 hook 账本注入跳过归档与终态 | P1-1 | stdin 灌入实测无「账本: 2026-11-17-fix-audit-defects」过期注入，rc=0 |
| R4 workflow_check 部署布局兼容与账本歧义通知 | P2-1 / P3-3 | 部署副本 self-check「无漂移」rc=0；readonly 多账本输出 S0.LEDGER_AMBIGUOUS WARN、rc=0 |
| R5 install.js 备份保留上限 | P3-2 | install.js 清理逻辑落地（grep 核实）；~/.zcode/agents/ .bak-* = 1（≤ N=1） |
| —（纯文档，无行为契约） | P3-1 / P3-5 | docstring 与实现/官方口径一致（`count_checkboxes` 行为实测 + 全量 pytest 绿） |
| —（收尾） | 全量回归 + 部署 + 部署侧验证 | pytest 549 passed / 1 skipped（21.39s）；部署副本含修复、版本 3.2.0 一致 |