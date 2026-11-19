# Design: fix-audit-defects

## 架构

本次修复是**文档命令前缀化 + 两处工具内部小修**，不改整体架构：

```
commands/wf/*.md ──┐
references/stage-S*.md ──┤── 统一改为 python "$ZCODE_PLUGIN_ROOT/.../openspec_engine.py" 前缀
                         │      消除对外部 openspec CLI 与 jq 的依赖
                         │
scripts/workflow_check.py ── detect_env() 的 git 判定复用 detect_git 逻辑（HEAD 存在）
scripts/install.js ──────── SKIP_NAMES 加 '.superpowers'
references/stage-S2-spec.md ── Planning boundary 正文从文件末尾移回 :88 标题下
```

## 模块职责

| 模块 | 职责 | 本次改动 |
|---|---|---|
| `commands/wf/archive.md` | S8 归档命令文档 | `:20` 的 `openspec status \| jq` 改为 `python .../openspec_engine.py status` + python 内联解析 |
| `commands/wf/spec.md` | S2 规格命令文档 | `:10, :24-26, :67` 的裸 `openspec` 加前缀 |
| `commands/wf/resume.md` | 恢复命令文档 | `:14-15` 的裸 `openspec` 加前缀 |
| `commands/wf/triage.md` | S0 分诊命令文档 | `:42` 的 `openspec list --json` 加前缀 |
| `references/stage-S2-spec.md` | S2 阶段规格 | `:52` 的 `openspec validate` 加前缀；`:88-135` Planning boundary 正文归位 |
| `references/stage-S8-sync-archive.md` | S8 阶段规格 | `:75` 的 `openspec list --json` 加前缀 |
| `scripts/workflow_check.py` | 机械核对 | `detect_env()` 的 git 判定改为复用 `detect_git` 逻辑 |
| `scripts/install.js` | 部署脚本 | `SKIP_NAMES` 加 `.superpowers` |

## 数据结构

无数据结构变化。仅文档文本与两处工具内部逻辑修正。

## 核心流程

1. 老板在没装 openspec CLI 的电脑上跑 `/wf:spec`：
   - 旧：`openspec new change "xxx"` → command not found
   - 新：`python "$ZCODE_PLUGIN_ROOT/skills/zcode-expert-system/scripts/openspec_engine.py" new-change "xxx"` → 成功
2. 老板跑 `/wf:archive`：
   - 旧：`openspec status --change xxx --json | jq -r '.artifactPaths.specs.existingOutputPaths[]'` → jq not found
   - 新：`python .../openspec_engine.py status --change xxx` + python 内联读 JSON → 成功（不依赖 jq）
3. `workflow_check.py` 与 `zcode_dev_workflow.py` 对同一项目（含空 `.git` 目录）的 git 判定一致

## 安全兼容

- 纯文档与工具内部修正，无公开 CLI 参数变化
- 不触碰 `openspec_engine.py` 的输出 schema，避免回归
- `install.js` 的 `SKIP_NAMES` 加 `.superpowers` 只影响打包分发，不影响已部署环境

## 风险

| 风险 | 缓解 |
|---|---|
| 文档命令前缀在 user-scope 命令目录（`~/.zcode/commands/wf/`）下 `$ZCODE_PLUGIN_ROOT` 不展开 | 文档头部注明「若变量未展开，替换为插件实际安装路径」；install.js 已把命令同步到 user 目录，路径可用 |
| `workflow_check.py` 复用 `detect_git` 逻辑时若 `zcode_dev_workflow` 不可导入 | `detect_git` 是纯函数（只依赖 os.path），可在 `workflow_check.py` 内复制一份实现，不引入模块依赖 |
| `stage-S2-spec.md` 移动段落时破坏其他引用 | 移动前后跑 `workflow_check.py --self-check` 验证 |