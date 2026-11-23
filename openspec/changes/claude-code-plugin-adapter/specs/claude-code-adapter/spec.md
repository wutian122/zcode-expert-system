# claude-code-adapter 规格

## Purpose

定义 zcode-expert-system 同时作为 Claude Code 插件运行的契约：插件清单必须可被 Claude Code 识别，子代理派发在两种平台下各自使用正确的 `subagent_type` 形式，hook 配置按平台分文件，且 ZCode 侧部署与行为保持不变。

## ADDED Requirements

### Requirement: 提供 Claude Code 插件清单

仓库根 MUST 提供 `.claude-plugin/plugin.json`，使 Claude Code 能将其识别为插件。

清单 MUST 满足以下约束：

- `name` MUST 为 `zcode-expert-system`，不得使用 `claude-`、`anthropic-`、`cc-plugin-` 等 Anthropic 保留前缀
- 路径字段 MUST 以 `./` 开头
- MUST 显式声明 `commands` 与 `hooks`（commands 无自动发现机制）
- MUST NOT 声明 `agents` 字段（该字段只接受 `.md` 文件路径，指向目录会导致校验错误）
- MUST NOT 声明 `skills` 字段（源码仓库无 `skills/` 目录，声明会导致校验错误）

#### Scenario: 校验插件清单
- WHEN 在仓库根执行 `claude plugin validate .`
- THEN 校验结果不含任何 error
- AND 输出列出 363 个 agent、12 个 command、1 个 skill

#### Scenario: 源码仓库直接加载
- WHEN 用户以仓库根目录作为插件目录加载
- THEN `agents/*.md` 通过自动发现全部载入
- AND `commands/**/*.md` 因显式声明而载入
- AND `skills/` 目录缺失不产生错误

### Requirement: hook 配置按平台分文件

Claude Code 的 hook 配置 MUST 独立于 ZCode 的 `hooks/hooks.json`，存放于 `hooks/claude-hooks.json`。

该文件 MUST 满足：

- `type` MUST 为 `command`（Claude Code 不支持 `process`）
- `command` MUST 为单条字符串，不使用 `args` 数组
- `timeout` MUST 以秒为单位（非 `timeoutMs`）
- 路径变量 MUST 使用 `${CLAUDE_PLUGIN_ROOT}`

#### Scenario: Claude Code 下注入专家体系规则
- WHEN 用户在 Claude Code 中输入任意 prompt
- THEN `UserPromptSubmit` hook 执行 `prepend-global-rules-reminder.mjs`
- AND 其输出的 `hookSpecificOutput.additionalContext` 被注入模型上下文

#### Scenario: ZCode 侧 hook 不受影响
- WHEN 在 ZCode 中安装插件
- THEN 仍读取 `hooks/hooks.json`（`type` 为 `process`）
- AND `hooks/claude-hooks.json` 被忽略

### Requirement: 子代理派发名按平台区分

`dispatch_expert()` MUST 根据运行平台输出不同的 `subagent_type`：

- Claude Code 环境：MUST 为 `<插件名>:<frontmatter.name>` 形式，如 `zcode-expert-system:代码审查员`
- ZCode 环境：MUST 保持专家中文裸名，如 `代码审查员`

平台判据 MUST 为环境变量 `CLAUDE_PLUGIN_ROOT` 是否注入。

#### Scenario: Claude Code 下派发专家
- WHEN 运行环境注入了 `CLAUDE_PLUGIN_ROOT`
- THEN 派发单的 `subagent_type` 为 `zcode-expert-system:<专家中文名>`
- AND 主控按该值调用 Agent 工具成功

#### Scenario: ZCode 下派发专家
- WHEN 运行环境未注入 `CLAUDE_PLUGIN_ROOT`
- THEN 派发单的 `subagent_type` 为专家中文名裸名
- AND 行为与改造前完全一致

#### Scenario: hook 提示文案与派发格式一致
- WHEN hook 注入的提示文本要求主控填写 `subagent_type`
- THEN Claude Code 环境下提示的格式与 `dispatch_expert()` 实际输出一致
- AND 不出现提示要求中文裸名、实际却需限定名的矛盾

### Requirement: Claude Code 部署产物包含子代理

`scripts/install.js` 的 Claude Code 部署分支 MUST 将 `agents/` 目录复制进部署产物。

部署产物 MUST 包含：`.claude-plugin/`、`agents/`、`commands/`、`skills/`、`hooks/`。

部署完成后 MUST 校验 agent 数量为 363，不足即报错并停止。

#### Scenario: 部署后子代理可用
- WHEN 执行 Claude Code 部署
- THEN 部署目录内存在 `agents/` 且含 363 个 `.md` 文件
- AND Claude Code 加载后可见全部专家

#### Scenario: 部署不完整时快速失败
- WHEN 部署产物的 agent 数量少于 363
- THEN 部署脚本报错退出
- AND 不留下半成品状态

### Requirement: ZCode 侧行为保持不变

本次适配 MUST NOT 改变 ZCode 的任何既有行为。以下内容 MUST 保持原样：

- `.zcode-plugin/plugin.json` 的内容
- `hooks/hooks.json` 的内容与 `type: process` 取值
- `~/.zcode/agents/` 的部署位置与 363 个文件
- `commands/wf/*.md` 的 12 个文件及其 33 处 `$ZCODE_PLUGIN_ROOT` 引用
- `agents/*.md` 的 frontmatter（中文 `name` 不改）

#### Scenario: ZCode 部署计划无变化
- WHEN 改动后执行 `npm run deploy:dry`
- THEN 计划动作与改动前逐条一致
- AND `~/.zcode/agents/` 仍为 363 个子代理

#### Scenario: ZCode 端到端派发可用
- WHEN 在 ZCode 中以 Claude Code 无关的方式执行工作流
- THEN 专家派发成功，`subagent_type` 为中文裸名

### Requirement: ZCode 跨机器安装不受影响

本次适配 MUST 保证 ZCode 在其他电脑上的安装行为零变化。具体约束：

- **npm 发布包白名单不变**：`package.json` 的 `files` 字段 MUST NOT 加入 `.claude-plugin/` 或 `openspec/changes/`。Claude Code 适配层 MUST NOT 进入发布包。
- **install.js 零改动**：`preflight()` 校验逻辑 MUST NOT 引用 `.claude-plugin/` 或 `hooks/claude-hooks.json`。ZCode 部署分支 MUST 保持现状。
- **运行时隔离**：`dispatch_expert()` 在 ZCode 环境（无 `CLAUDE_PLUGIN_ROOT`）MUST 走原路径，输出中文裸名。
- **hook 隔离**：ZCode 只读 `hooks/hooks.json`，MUST NOT 读取 `hooks/claude-hooks.json`。

#### Scenario: ZCode 用户在干净机器上安装
- WHEN 一台没有 `.claude-plugin/` 的干净机器执行 `npm install` + `npm run deploy`
- THEN ZCode 安装成功，功能与 today 完全一致
- AND 不依赖任何 Claude Code 专属文件

#### Scenario: 发布包不包含 Claude Code 适配层
- WHEN 执行 `npm pack` 或 `npm publish`
- THEN 发布包内不包含 `.claude-plugin/` 目录
- AND 发布包内 `hooks/` 仅含 `hooks.json` 与 hook 脚本

### Requirement: 测试兼容两种子代理命名

4 处现有测试硬断言 `subagent_type` 必须等于中文专家名，实施前 MUST 改造为兼容两种形式：

- ZCode 环境（无 `CLAUDE_PLUGIN_ROOT`）：MUST 接受中文裸名
- Claude Code 环境（有 `CLAUDE_PLUGIN_ROOT`）：MUST 接受 `zcode-expert-system:<中文名>`

改造范围：
- `tests/test_semantic_selection.py:95`
- `tests/test_dispatch_plan.py:152`
- `tests/test_domain_routing_mandatory.py:165`
- `tests/test_domain_routing_mandatory.py:188`

#### Scenario: ZCode 环境下测试仍通过
- WHEN 在 ZCode 环境（无 `CLAUDE_PLUGIN_ROOT`）跑 `pytest tests/`
- THEN 改造后的测试 100% 通过
- AND 失败断言数 = 0

#### Scenario: Claude Code 环境下测试也通过
- WHEN 在 Claude Code 环境（有 `CLAUDE_PLUGIN_ROOT`）跑 `pytest tests/`
- THEN 改造后的测试 100% 通过
- AND 接受 `zcode-expert-system:<名>` 形式

### Requirement: 基线测试必须全绿

实施前 MUST 修复 8 个既有失败测试，使 `pytest tests/` 100% 通过。

失败测试列表：
- `test_component_registry.py::test_self_check_缺失项失败`
- `test_p5_install_safety.py::test_missing_agents_fails_before_touching_disk`
- `test_p5_install_safety.py::test_dry_run_deletes_nothing`
- `test_workflow_check_openspec.py` × 5

#### Scenario: 基线测试全绿
- WHEN 在实施第 1 组任务前跑 `pytest tests/`
- THEN 失败数 = 0，通过数 ≥ 597
- AND 无新增失败