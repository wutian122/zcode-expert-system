# OpenSpec CLI 完全内置（P3）实施计划

## Goal
将 OpenSpec CLI 的全部功能内置为插件 Python 模块 `scripts/openspec_engine.py`，实现“完全不依赖 OpenSpec CLI”，无 CLI 环境下 S2/S8 阶段可正常完成。

## Architecture
- 单模块 `scripts/openspec_engine.py`，提供 7 个子命令：list / new-change / status / instructions / validate / sync-specs / archive-change
- 数据目录结构与 OpenSpec 完全兼容：`openspec/changes/<change>/` + `openspec/specs/` + `openspec/changes/archive/`
- `workflow_check.py` 集成内置模块，替代对 openspec CLI 的调用
- `spec_mode: manual` / `validate: skipped` 证据降级口径，账本与计划文档 `## Baseline` 段记录

## Tech Stack
Python 3 标准库（json/os/re/sys/io/argparse/datetime/pathlib），无第三方依赖

## Spec
- S2：无 CLI 时，`openspec_engine.py` 承担 `new-change` / `status` / `instructions` / `validate`
- S8：无 CLI 时，`openspec_engine.py` 承担 `sync-specs` / `archive-change` / `validate-specs`
- 变更集与 delta 合并逻辑与 OpenSpec CLI 保持语义一致
- 无 openspec root 时：老板点名才三选一（init/store/不用），否则静默放弃（S0 既有约束，不改）

## Review Focus
- 无 CLI 环境下 S2/S8 能否完整走通
- `spec_mode: manual` / `validate: skipped` 证据降级是否正确落盘到账本与计划文档 `## Baseline`
- `component_registry` 是否需要新增内置模块条目
- `openspec_engine.py` 生成的产物与 OpenSpec CLI 产物格式是否兼容

## Global Constraints
- 纯 Python 标准库，无第三方依赖
- 数据目录结构与 OpenSpec CLI 完全兼容，可无缝切换
- 不打包 OpenSpec CLI（保持原有体积策略）
- 绝不自动建根（S0 约束）

## Dependencies
- 无新外部依赖

## File Scope
- 新建：`scripts/openspec_engine.py`、`tests/test_openspec_engine.py`
- 修改：`scripts/workflow_check.py`、`SKILL.md`、`config/workflow.json`（可选）、`references/stage-S2-spec.md`、`references/stage-S8-sync-archive.md`

### Task 1: openspec_engine.py 核心命令（new-change / status / instructions）
### Task 2: openspec_engine.py 继续（validate / sync-specs / archive-change / validate-specs）
### Task 3: workflow_check.py 集成内置模块（check_S2/check_S8）
### Task 4: stage-S2/S8 文档更新（无 CLI 模式章节）
### Task 5: 测试 + 全量回归 + 端到端验收
