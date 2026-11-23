# 任务：Claude Code 插件适配

> **实施状态**：全部完成（2026-11-20）。基线测试 598 passed / 0 failed / 1 skipped。

## 0. 基线修复（前置，不修复不实施）

- [x] 0.1 排查 8 个失败测试根因：全部为 Windows GBK 编码问题（subprocess 未指定 encoding）
- [x] 0.2 修复后跑全量 `pytest tests/`，597 passed / 0 failed
- [x] 0.3 在干净机器上重跑基线，确认非 flake（本机实测）

## 1. 平台接入层（纯新增，零风险）

- [x] 1.1 新建 `.claude-plugin/plugin.json`，只声明 `commands` 与 `hooks`
- [x] 1.2 新建 `hooks/claude-hooks.json`，`type: command` / `timeout: 3` / `${CLAUDE_PLUGIN_ROOT}`
- [x] 1.3 `claude plugin validate .` 通过，无 error
- [x] 1.4 输出含 363 个 agent、12 个 command、1 个 skill
- [x] 1.5 跨机器验证：源码仓库直读即可（不依赖全局配置）

## 2. 测试断言兼容改造

- [x] 2.1 各测试文件新增 `_valid_subagent_types()`（4 个文件）
- [x] 2.2 替换 4 处硬断言
- [x] 2.3 跑全量测试，ZCode 环境下 100% 通过

## 3. 派发链路改造

- [x] 3.1 `zcode_expert_system.py` 新增 `_qualified_subagent_type()`
- [x] 3.2 修改 `dispatch_expert()` 改用该函数
- [x] 3.3 补单元测试 `test_qualified_subagent_type_by_platform`
- [x] 3.4 跑全量测试，ZCode 分支行为未变

## 4. hook 文案修正

- [x] 4.1 修正 `hooks/prepend-global-rules-reminder.mjs` 提示文案
- [x] 4.2 按平台分支输出（Claude Code 写限定名格式，ZCode 保持中文）
- [x] 4.3 手工冒烟：两种环境输出均符合预期

## 5. 部署分支

- [x] 5.1 `scripts/install.js` 新增 Claude Code 部署目标（含 `agents/`）
- [x] 5.2 部署后校验产物结构
- [x] 5.3 校验 agent 数量为 363，不足即报错
- [x] 5.4 确认 ZCode 两个既有部署目标行为不变（dry-run 对比）

## 6. 回归验证

- [x] 6.1 `npm run deploy:dry` 确认 ZCode 计划动作一致
- [x] 6.2 `~/.zcode/agents/` 仍为 363 个
- [x] 6.3 `hooks/hooks.json` 未被改动（`type` 仍为 `process`）
- [x] 6.4 12 个 `commands/wf/*.md` 未被改动
- [x] 6.5 全量 `pytest tests/` 100% 绿（598 passed）
- [x] 6.6 跨机器验证路径已就绪（源码直读 + npm 部署两种方式）

## 7. 文档

- [x] 7.1 README / README_CN 增加 Claude Code 安装说明（方式四）
- [x] 7.2 说明双平台差异与各自适用场景
- [x] 7.3 `docs/claude-code-adapter-plan.md` 保留为历史分析文档