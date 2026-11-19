
# plugin-toolchain 规格

## Purpose

定义 zcode-expert-system 插件工具链的可用性契约：三个 CLI 入口（zcode_expert_system.py / zcode_dev_workflow.py / skill_entry.py）的 `--help` 分流、内置引擎 openspec_engine.py 的 change 枚举与 `--root` 语义、hook 账本注入跳过归档与终态账本、workflow_check 的部署布局兼容与账本歧义通知、install.js 的备份保留上限——保证工具链在源码仓与部署布局两种形态下行为一致、fail-open 不阻断会话。规格真相源：change `2026-11-18-fix-suite-defects`（2026-11-18 归档）；修复依据为该项目内部测试报告（不随仓库分发）。

## ADDED Requirements

### Requirement: CLI 入口帮助与任务分流

三个 CLI 入口（`zcode_expert_system.py`、`zcode_dev_workflow.py`、`skill_entry.py`）收到 `--help` / `-h` 时 MUST 打印用法并以 rc=0 退出，MUST NOT 将 flag 当任务描述路由、MUST NOT 落入「未知命令」报错；不带 flag 的任务参数行为 MUST 保持不变。

#### Scenario: zcode_expert_system.py --help 打印用法
- WHEN 运行 `python zcode_expert_system.py --help`
- THEN 输出用法文本（含调用形态）且退出码为 0
- AND 不输出任务路由 JSON（不把 `--help` 当任务描述）

#### Scenario: zcode_dev_workflow.py --help 打印用法
- WHEN 运行 `python zcode_dev_workflow.py --help`
- THEN 输出模块用法（五子命令 triage/stages/plan/states/transition 说明）且退出码为 0
- AND 不打印「未知命令：--help」

#### Scenario: skill_entry.py --help 打印用法
- WHEN 运行 `python skill_entry.py --help`
- THEN 输出用法文本且退出码为 0
- AND `--help` 不被当任务描述传入路由

#### Scenario: 普通任务参数行为不变
- WHEN 三个入口收到普通任务描述参数（不带 flag）
- THEN 行为与修复前一致（zcode_expert_system / skill_entry 输出 JSON 路由结果；zcode_dev_workflow 执行五子命令）

### Requirement: 内置引擎 change 枚举与 root 语义

`openspec_engine.py` 的 `list` 子命令枚举 `changes/` 时 MUST 跳过名为 `archive` 的目录（归档容器非 pending 变更，对齐官方 openspec 口径）；`--root` 无论位于顶层（子命令前）还是 `list` 子命令后 MUST 均生效，未传时 MUST 回落 cwd。

#### Scenario: list 不含 archive 幻影变更
- WHEN 运行 `python scripts/openspec_engine.py list` 且 root 下存在 `openspec/changes/archive/`
- THEN 输出 `changes` 数组不含 `name == "archive"` 的项
- AND 仅含真实活跃变更

#### Scenario: 顶层 --root 生效
- WHEN 运行 `python scripts/openspec_engine.py --root <X> list`
- THEN 输出 `"root": "<X>"`（而非 cwd）

#### Scenario: 子命令 --root 生效且不退化
- WHEN 运行 `python scripts/openspec_engine.py list --root <X>`
- THEN 输出 `"root": "<X>"`
- AND 不传 `--root` 时输出 `"root": "<cwd>"`

### Requirement: hook 账本注入跳过归档与终态

UserPromptSubmit hook（`prepend-global-rules-reminder.mjs`）的 `summaryFromSddDir` 选择账本时 MUST 跳过已归档 slug（`openspec/changes/archive/<name>` 存在）与终态 slug（`progress.md` 的 `Overall Status` ∈ {DONE, PARKED, COMPLETE}）；读 `progress.md` 失败 MUST 按未终态处理（fail-open，hook 不阻断）；全部被跳过时 MUST 返回空摘要不抛异常。

#### Scenario: 已归档账本不被注入
- WHEN sdd 账本对应变更已归档，且该账本 mtime 最新（修复前恒被选中注入）
- THEN hook `additionalContext` 不含该账本的「账本 / 阶段 / 状态」注入行

#### Scenario: 终态账本不被注入
- WHEN sdd 账本的 `Overall Status` 为 DONE / PARKED / COMPLETE（尚未归档）
- THEN 该账本不被选为注入摘要

#### Scenario: 活跃账本正常注入
- WHEN 仅存在非终态且未归档的账本（如 IN_PROGRESS）
- THEN 仍按 mtime 选最新注入其摘要（既有行为保持）

#### Scenario: 全部跳过时 fail-open
- WHEN 所有候选账本均被跳过（全部归档或终态）
- THEN hook 返回空摘要、退出码 0，不抛异常

### Requirement: workflow_check 部署布局兼容与账本歧义通知

`workflow_check.py` 的 `self_check` 对 component_registry `internal` 路径 MUST 在源码布局缺失时探测部署布局备用候选（父目录 + `internal` 倒数第二段目录名 + 文件名），存在则不报 DRIFT，两者均缺失仍报 DRIFT；`run()` MUST 消费 `ctx["ledger_ambiguous"]`，非空时输出 `S0.LEDGER_AMBIGUOUS` WARN（reason 以 `soft:` 开头，WARN 不致 rc≠0）。

#### Scenario: 部署侧 self-check 无 DRIFT
- WHEN 部署副本（`<插件根>/skills/zcode-expert-system/`）运行 `workflow_check.py --self-check`
- THEN 输出「结论：无漂移」且退出码为 0
- AND 源码仓运行同命令保持 OK（`internal` 本身存在，不走备用候选）

#### Scenario: 多账本歧义可见
- WHEN readonly 任务关联到多个含 `progress.md` 的 sdd 候选账本
- THEN 输出含 `[warn:ledger_ambiguous]`「多个 progress.md 候选」的 WARN（id=`S0.LEDGER_AMBIGUOUS`）
- AND 退出码保持 0（WARN 不致失败）

#### Scenario: 单账本不触发歧义 WARN
- WHEN 仅一个含 `progress.md` 的 sdd 子目录
- THEN 不输出 `S0.LEDGER_AMBIGUOUS` WARN

#### Scenario: 备用候选缺失仍报 DRIFT
- WHEN 组件 `internal` 路径与部署备用候选均不存在
- THEN self_check 仍报该组件 DRIFT（原逻辑保持，不漏报真实漂移）

### Requirement: install.js 备份保留上限

`scripts/install.js` 的 `writeAgentFile` 覆盖目标 agent 文件前 MUST 清理该文件的历史 `.bak-*` 备份并仅保留最近 N=1 个；「备份不进 `deployedAgentNames` 清单、卸载不触碰 `.bak-*`」的既有安全契约 MUST 保持。

#### Scenario: 反复部署 .bak 数量有界
- WHEN 同一 agent 文件在多次部署中内容反复变化
- THEN 该文件的 `.bak-*` 数量 ≤ 1（仅最近一次备份，不再随部署次数累积）

#### Scenario: 覆盖前生成备份（用户定制可恢复）
- WHEN 部署覆盖内容有变化的 agent 文件
- THEN 覆盖前仍生成 `.bak-<ts>` 备份（上一版可恢复，安全网不失）

#### Scenario: 卸载不触碰备份
- WHEN 执行卸载（按 `deployedAgentNames` 清单删除）
- THEN `.bak-*` 文件不被删除（既有契约保持）
