# Tasks: fix-audit-defects

## 1. 文档命令前缀化（消除外部 CLI 与 jq 依赖）

- [x] 1.1 `commands/wf/archive.md:20` 把 `openspec status --change <n> --json | jq -r '.artifactPaths.specs.existingOutputPaths[]'` 改为 `python "$ZCODE_PLUGIN_ROOT/skills/zcode-expert-system/scripts/openspec_engine.py" status --change <n>` + python 内联解析（不依赖 jq）
- [x] 1.2 `commands/wf/spec.md` 把 `:10` 的 `openspec list --json`、`:24-26` 的 `openspec new change` / `status` / `instructions`、`:67` 的 `openspec validate` 全部加 `python "$ZCODE_PLUGIN_ROOT/skills/zcode-expert-system/scripts/openspec_engine.py"` 前缀
- [x] 1.3 `commands/wf/resume.md` 把 `:14-15` 的 `openspec status` / `openspec instructions` 加前缀
- [x] 1.4 `commands/wf/triage.md` 把 `:42` 的 `openspec list --json` 加前缀
- [x] 1.5 `references/stage-S2-spec.md:52` 把 `openspec validate --change <n>` 加前缀
- [x] 1.6 `references/stage-S8-sync-archive.md:75` 把 `openspec list --json` 加前缀

## 2. git 判定统一

- [x] 2.1 `scripts/workflow_check.py:1288` 把 `os.path.exists(.git)` 改为复用 `zcode_dev_workflow.detect_git` 逻辑（要求 `.git` 为目录含 HEAD，或文件以 `gitdir:` 开头），统一两工具的 git 结论
- [x] 2.2 验证：对本项目（无 `.git`）跑 `workflow_check.py --self-check` 与 `zcode_dev_workflow.py triage`，git 结论一致为「无」

## 3. stage-S2-spec.md 段落归位

- [x] 3.1 `references/stage-S2-spec.md` 把孤悬文件末尾（:135 附近）的 `## 关键约束：Planning boundary` 正文移回 `:88` 标题下，消除段落割裂
- [x] 3.2 验证：`workflow_check.py --self-check` rc=0，文档结构完整

## 4. install.js 排除 .superpowers

- [x] 4.1 `scripts/install.js:94-104` 的 `SKIP_NAMES` 加 `.superpowers`
- [x] 4.2 验证：`node scripts/install.js --dry-run` 输出不包含 `.superpowers` 路径

## 5. 回归验证

- [x] 5.1 `python -m pytest tests/ -q` 保持 496 passed, 1 skipped
- [x] 5.2 `python scripts/workflow_check.py --self-check` rc=0，无漂移
- [x] 5.3 `commands/wf/archive.md` 不再出现裸 `jq`
- [x] 5.4 全仓搜索确认无残留裸 `openspec xxx` 命令（`grep -rn "openspec new change\|openspec status\|openspec list\|openspec instructions\|openspec validate\|openspec archive" commands/ references/ SKILL.md templates/` 仅命中带 python 前缀的）

## 6. openspec_engine.py list 崩溃修复（审查 Important）

- [x] 6.1 `scripts/openspec_engine.py` 的 `list` 子命令 `--root` default None fallback cwd，修复 `Path(None).resolve()` 崩溃
- [x] 6.2 验证：`python scripts/openspec_engine.py list` rc=0，正确输出 change 列表

## 验收条件

- 别的电脑没装 openspec CLI、没装 jq，只装 Python 3 + Node.js，能跑通 `/wf:spec` → `/wf:archive` 全流程
- `pytest tests/ -q` 496 绿
- `workflow_check.py --self-check` rc=0
- 两工具的 git 判定一致