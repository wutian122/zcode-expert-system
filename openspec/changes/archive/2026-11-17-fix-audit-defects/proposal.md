# Proposal: fix-audit-defects

## Why

zcode-expert-system v3.1.0 审计发现 5 处影响「无 openspec CLI 环境下的可用性」与「两工具判定一致性」的缺陷：

1. `commands/wf/archive.md:20` 用裸 `jq` 解析 `openspec status` 输出，本机无 jq，S8 的「delta 唯一来源」命令必失败；
2. `commands/wf/spec.md` / `resume.md` / `triage.md` 多处使用裸 `openspec xxx` 命令，别的电脑没装 openspec CLI 时全部 command not found；
3. `scripts/workflow_check.py:1288` 用 `os.path.exists(.git)` 判 git 仓库，与 `zcode_dev_workflow.detect_git`（要求 HEAD 存在）口径不一致，空 `.git` 目录会假阳性；
4. `references/stage-S2-spec.md:88-135` 的 `## 关键约束：Planning boundary` 标题下正文为空，真正约束文本孤悬文件末尾（B7 迁移时插入位置错误）；
5. `scripts/install.js:94-104` 的 `SKIP_NAMES` 未排除 `.superpowers/`，开发账本会随插件分发到别的电脑。

## What Changes

- **不新增功能**，只修断点与统一口径：
  - 文档命令前缀化：所有 `openspec xxx` 改为 `python "$ZCODE_PLUGIN_ROOT/skills/zcode-expert-system/scripts/openspec_engine.py" xxx`（或相对路径），消除对外部 CLI 与 jq 的依赖；
  - `workflow_check.py` 的 git 判定复用 `detect_git` 逻辑；
  - `stage-S2-spec.md` 把孤悬的 Planning boundary 正文移回标题下；
  - `install.js` 的 `SKIP_NAMES` 加 `.superpowers`。
- **不改 `openspec_engine.py` 的输出 schema**（保持现状，避免引入回归；`applyRequires` 空、`artifactPaths` 从 `artifacts/` 读、`totalTasks/completedTasks` 缺失是已知限制，不影响核心流程）。

## Impact

- 受影响规格：`plugin-commands`（commands/wf/*.md 与 references/stage-S*.md 的命令口径）
- 受影响代码：`scripts/workflow_check.py`、`scripts/install.js`、`references/stage-S2-spec.md`
- 不影响：专家路由（331 专家）、规模分诊（zcode_dev_workflow.py）、agent 人格、hooks、context-manager
- 兼容性：纯文档与工具内部修正，无公开 CLI 参数变化，无数据迁移

## 不包含

- 不重写 `openspec_engine.py` 的输出 schema（方案 B 留给后续）
- 不修 `openspec_engine.py list --root None` 崩溃（本次新发现的独立 Bug，记 Ruling 后单独处理）
- 不删 `~/.zcode/agents/*.bak-*`（P3，无害）
- 不改 `build_dispatch_plan` 的 `sys.path.insert`（P3，无功能影响）
- 不改 AGENTS.md（老板未要求）