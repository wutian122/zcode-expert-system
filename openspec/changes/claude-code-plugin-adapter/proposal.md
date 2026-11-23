# Claude Code 插件适配

## 为什么

`zcode-expert-system` 目前是 ZCode 平台插件，其 331 位专家、九阶段工作流、OpenSpec 体系无法在 Claude Code 中使用。Claude Code 与 ZCode 的插件运行时契约存在差异（manifest 目录名、hook 的 `type` 取值、路径变量、子代理限定名），直接安装不会被识别。

目标是**在不改变 ZCode 现有部署形态的前提下**，额外让本仓库作为 Claude Code 插件工作。

## 改什么

### 新增（Claude Code 专属，不影响 ZCode）

- `.claude-plugin/plugin.json` — Claude Code 插件清单
- `hooks/claude-hooks.json` — Claude Code 格式的 hook 配置（`type: command`）
- `scripts/install.js` 增加 Claude Code 部署分支

### 修改（双平台共用，需保证 ZCode 不回归）

- `zcode_expert_system.py` — `dispatch_expert()` 输出带插件限定名的 `subagent_type`
- `hooks/prepend-global-rules-reminder.mjs` — 修正运行期提示文案中的派发名格式
- 4 处测试断言 — 改造为兼容两种 `subagent_type` 形式

### 前置修复（实施前必须完成）

- 8 个基线测试失败（与本次适配无关，但按铁律 5 必须先修，修复后全量测试需 100% 绿）

### 不改动（明确边界）

- `.zcode-plugin/plugin.json` — ZCode 清单
- `hooks/hooks.json` — ZCode hook 配置
- `~/.zcode/agents/` — ZCode 全局子代理目录
- `commands/wf/*.md` — 12 个命令文件及其 33 处 `$ZCODE_PLUGIN_ROOT` 引用
- `agents/*.md` — 363 个子代理定义（中文 `name` 在 Claude Code 下实测可用）

## 影响

- **ZCode 用户**：无感知，部署形态与行为保持不变（跨机器安装行为零变化，npm 发布包不包含 `.claude-plugin/`）
- **Claude Code 用户**：安装后获得 331 位专家、12 个工作流命令、专家体系自动注入 hook
- **维护成本**：两套 manifest 与两套 hook 配置需同步版本号

## 已排除的方案

| 方案 | 排除原因 |
|---|---|
| 单一 `hooks.json` 兼容两平台 | `type` 取值 `process` 与 `command` 互斥，无交集写法 |
| 直接复用 ZCode 插件缓存目录 | 该目录无 `agents/`、无 `.claude-plugin/`，Claude Code 不识别 |
| 修改 ZCode 部署形态以统一 | 需求方明确要求 ZCode 侧不改动 |
| 331 个 agent 批量改英文 slug | 实测中文 `name` 可正常派发，改造非必需 |