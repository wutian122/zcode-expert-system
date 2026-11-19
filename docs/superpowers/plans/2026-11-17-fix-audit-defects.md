# 实施计划：fix-audit-defects

## Goal

修复 zcode-expert-system v3.1.0 审计发现的 5 处缺陷，使插件在**未安装外部 openspec CLI、未安装 jq** 的环境下仍可完整使用，并统一 workflow_check 与 zcode_dev_workflow 的 git 判定口径。验收：别的电脑只装 Python 3 + Node.js 能跑通 `/wf:spec` → `/wf:archive` 全流程。

## Architecture

纯文档命令前缀化 + 两处工具内部小修，不改整体架构：

- `commands/wf/*.md` 与 `references/stage-S*.md`：所有裸 `openspec xxx` 改为 `python "$ZCODE_PLUGIN_ROOT/skills/zcode-expert-system/scripts/openspec_engine.py" xxx` 前缀，消除对外部 CLI 与 jq 的依赖；
- `scripts/workflow_check.py`：`detect_env()` 的 git 判定复用 `detect_git` 逻辑（HEAD 存在）；
- `references/stage-S2-spec.md`：Planning boundary 正文从文件末尾移回标题下；
- `scripts/install.js`：`SKIP_NAMES` 加 `.superpowers`。

## Tech Stack

- Python 3（内置引擎 `openspec_engine.py`、`workflow_check.py`）
- Node.js（`install.js`）
- Markdown（命令文档、阶段规格）
- 无新依赖

## Spec

指向 `openspec/changes/fix-audit-defects/`，四件产物齐备（proposal/design/tasks/specs），老板已审阅通过（S2 G2 门禁已过）。

## Review Focus

- 文档命令前缀是否在所有裸 `openspec` 出现处一致应用（grep 零残留）；
- `workflow_check.py` 的 git 判定改动是否与 `zcode_dev_workflow.detect_git` 语义一致（空 `.git` 目录假阳性消除）；
- `stage-S2-spec.md` 段落归位后 `--self-check` rc=0；
- `install.js --dry-run` 不包含 `.superpowers` 路径；
- 回归：`pytest tests/ -q` 496 绿。

## Global Constraints

- 不改 `openspec_engine.py` 的输出 schema（保持现状，避免引入回归）；
- 不修 `openspec_engine.py list --root None` 崩溃（独立 Bug，记 Ruling 后单独处理）；
- 不删 `~/.zcode/agents/*.bak-*`（P3，无害）；
- 不改 `build_dispatch_plan` 的 `sys.path.insert`（P3，无功能影响）；
- 不改 AGENTS.md（老板未要求）；
- 文档命令前缀统一用 `python "$ZCODE_PLUGIN_ROOT/skills/zcode-expert-system/scripts/openspec_engine.py"`，文档头部注明「若变量未展开，替换为插件实际安装路径」；
- 无 git 仓库（本项目非 git），走快照证据 + 主控自审（L1）。

## Dependencies

- Task 1（文档前缀化）与 Task 2/3/4（工具小修）相互独立，可任意顺序；
- Task 5（回归验证）依赖 Task 1-4 全部完成；
- SDD 脚本工具链（`scripts/sdd/task-brief`、`review-package`）在 `.superpowers/sdd/` 下，需 S4 初始化。

## File Scope

允许修改的文件白名单：

- `commands/wf/archive.md`
- `commands/wf/spec.md`
- `commands/wf/resume.md`
- `commands/wf/triage.md`
- `references/stage-S2-spec.md`
- `references/stage-S8-sync-archive.md`
- `scripts/workflow_check.py`
- `scripts/install.js`
- `tests/test_workflow_check.py`（新增 git 判定统一测试）
- `tests/test_install_safety.py`（新增 .superpowers 排除测试）
- `.superpowers/sdd/fix-audit-defects/`（SDD workspace）

## 执行模式

**sdd**（有子代理，任务可独立拆分）。账本 = `.superpowers/sdd/fix-audit-defects/progress.md` + 原子回写 `openspec/changes/fix-audit-defects/tasks.md`。

## Tasks

### Task 1: 文档命令前缀化（消除外部 CLI 与 jq 依赖）

**Files**:
- `commands/wf/archive.md`
- `commands/wf/spec.md`
- `commands/wf/resume.md`
- `commands/wf/triage.md`
- `references/stage-S2-spec.md`
- `references/stage-S8-sync-archive.md`

**Interfaces**:
- Consumes: 现有文档内容（已知行号：archive.md:20, spec.md:10/24-26/67, resume.md:14-15, triage.md:42, stage-S2:52, stage-S8:75）
- Produces: 所有裸 `openspec xxx` 改为 `python "$ZCODE_PLUGIN_ROOT/skills/zcode-expert-system/scripts/openspec_engine.py" xxx`

**Steps**:
1. 写失败测试：grep 确认当前存在裸 `openspec` 命令（RED）
2. 逐文件替换 6 处裸 `openspec` 为带前缀形式
3. archive.md:20 的 `| jq -r ...` 改为 python 内联解析
4. 跑 grep 确认零残留（GREEN）
5. 文档头部注明 `$ZCODE_PLUGIN_ROOT` 未展开时的替换说明

**covers**: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6

### Task 2: git 判定统一

**Files**:
- `scripts/workflow_check.py`
- `tests/test_workflow_check.py`

**Interfaces**:
- Consumes: `detect_env()` 当前用 `os.path.exists(.git)`（:1288）
- Produces: 复用 `detect_git` 逻辑（HEAD 存在或 gitdir: 文件）

**Steps**:
1. 写失败测试：空 `.git` 目录应判定 git=无（RED）
2. 在 `workflow_check.py` 内复制 `detect_git` 实现（避免模块依赖）
3. `detect_env()` 调用新实现
4. 跑测试确认空 `.git` 判定 git=无（GREEN）
5. 验证 `workflow_check.py --self-check` rc=0

**covers**: 2.1, 2.2

### Task 3: stage-S2-spec.md 段落归位

**Files**:
- `references/stage-S2-spec.md`

**Interfaces**:
- Consumes: 当前 `:88` 空标题 + `:135` 孤悬正文
- Produces: Planning boundary 正文在 `:88` 标题下

**Steps**:
1. 读取当前 stage-S2-spec.md 确认段落位置
2. 把孤悬的 `## 关键约束：Planning boundary` 正文从文件末尾移回 `:88` 标题下
3. 跑 `workflow_check.py --self-check` 确认 rc=0

**covers**: 3.1, 3.2

### Task 4: install.js 排除 .superpowers

**Files**:
- `scripts/install.js`
- `tests/test_install_safety.py`

**Interfaces**:
- Consumes: `SKIP_NAMES` Set（:94-104）
- Produces: `SKIP_NAMES` 含 `.superpowers`

**Steps**:
1. 写失败测试：`node scripts/install.js --dry-run` 输出含 `.superpowers` 路径（RED，因当前未排除）
2. `SKIP_NAMES` 加 `.superpowers`
3. 跑 dry-run 确认输出不含 `.superpowers`（GREEN）

**covers**: 4.1, 4.2

### Task 5: 回归验证

**Files**: 无新改动，只跑验证

**Steps**:
1. `python -m pytest tests/ -q` 确认 496 passed
2. `python scripts/workflow_check.py --self-check` 确认 rc=0
3. grep 确认 `commands/wf/archive.md` 无裸 `jq`
4. grep 确认全仓无残留裸 `openspec xxx` 命令（带 python 前缀的除外）
5. 记录验证证据到计划文档 `## Integration Verification`

**covers**: 5.1, 5.2, 5.3, 5.4

## Baseline

- command: python -m pytest tests/ -q
- exit: 0
- passed: 496, failed: 0, skipped: 1
- tree: E:\zcode-expert-system（无 git 仓库，走快照证据）
- spec_mode: manual
- validate: skipped

## Review

spec: ✅（6 处裸 openspec 全改 python 前缀；archive.md jq 消除；stage-S2 Planning boundary 正文归位；workflow_check git 判定与 detect_git 同口径；install.js SKIP_NAMES 含 .superpowers）
quality: APPROVED（审查 Important：openspec_engine.py list --root default None 崩溃 → 已修，fallback cwd；pytest 496 绿）
independence: L0（代码审查员独立子代理审查）
findings: 无 Critical；1 Important（list 崩溃）已修；无 Minor
reviewer: 代码审查员
review_report: .superpowers/sdd/2026-11-17-fix-audit-defects/review-1.md

## Rulings

1. 保留 openspec-manual-mode.md:58 的「openspec list --json」描述性引用不改 — 它说明的是勾选口径与外部 CLI 一致，不是可执行命令 — 若改反而会让读者以为内置引擎也输出 totalTasks/completedTasks（实际不输出）。
2. 修 openspec_engine.py list 的 --root default（审查 Important）而非改文档加 --root 参数 — default fallback cwd 与父 --root 语义一致，且不改输出 schema，符合禁改清单；改文档加 --root 会让三处命令更冗长且掩盖引擎缺陷 — 错了的代价：若 fallback 引入回归，pytest 会抓到（已验证 496 绿）。

## Integration Verification

- command: python -m pytest tests/ -q
- exit: 0
- passed: 496, failed: 0, skipped: 1
- tree: E:\zcode-expert-system（无 git，改动清单验收）
- self-check: rc=0
- 改动清单：
  1. commands/wf/archive.md（delta 来源改 python 前缀 + 内联解析，去 jq）
  2. commands/wf/spec.md（裸 openspec 加 python 前缀）
  3. commands/wf/resume.md（裸 openspec 加 python 前缀）
  4. commands/wf/triage.md（裸 openspec 加 python 前缀）
  5. references/stage-S2-spec.md（:52 加前缀；Planning boundary 正文归位）
  6. references/stage-S8-sync-archive.md（:75 加前缀）
  7. scripts/workflow_check.py（_detect_git_repo，detect_env 复用）
  8. scripts/install.js（SKIP_NAMES 加 .superpowers）
  9. scripts/openspec_engine.py（list --root default fallback cwd，修审查 Important）