# Claude Code 适配方案

> 目标：让 `zcode-expert-system` 在 **不改变 ZCode 现有部署形态** 的前提下，额外作为一个 Claude Code 插件工作。
>
> 本文档为**方案**，不含实施。所有事实均来自 2026-11-20 本机实测（Claude Code 2.1.329 + 本仓库源码 + `npm run deploy:dry` 产物勘察）。

---

## 一、结论摘要

能做到双平台并存。**ZCode 侧零改动**，Claude Code 侧全部为新增（加法式适配）。

唯一无法共用的是 `hooks.json` 的格式——两个平台的 `type` 取值互斥，必须各放一份。其余组件（agents / commands / scripts / config）源码层面完全共用。

---

## 一点五、探针实测结果（2026-11-20，`claude plugin validate`）

用临时探针插件实测，**推翻了初版方案的三个假设**，以下为修正后的定论：

| # | 验证项 | 实测结果 | 对方案的影响 |
|---|---|---|---|
| 1 | `skills` 指向不存在目录 | **error**，提示「runtime loader will report this as a load failure」 | 不能声明 `skills` 字段；改为依赖 `skills/<name>/SKILL.md` 自动发现 |
| 2 | `agents` 字段指向目录 | **error**：`Invalid string: must end with ".md"` | `agents` 字段只能指 `.md` 文件；**目录级靠自动发现** |
| 3 | `title` 自定义字段 | **零告警**，被静默忽略 | 方案可行，中文可安全放 `title` |
| 4 | `name` 与文件名不一致 | 正常工作，用 frontmatter `name` | 331 个中文名**不改也能跑** |
| 5 | 中文 `name` | **正常工作**（`adapter-probe:代码审查员`） | 中文名技术可行 |
| 6 | 363 个 agent 同时加载 | **363/363 全部加载，零截断零告警** | 无数量上限问题 |
| 7 | 项目真实 hook 脚本 | 输出契约完全兼容 | **脚本一行不用改** |
| 8 | 插件名 `cc-plugin-` 前缀 | **保留名，被拒** | 只能用 `zcode-expert-system` |

**第 5 项的关键发现**：`subagent_type` 的真实取值是 **`插件名:agent的name`**。

```
agent frontmatter name: expert-slug-ok
→ 实际 subagent_type: adapter-probe:expert-slug-ok
```

这意味着：**即使把 `name` 改成英文 slug，派发时也必须带插件前缀**。`dispatch_expert()` 的改造不能只换 slug，必须输出完整限定名。

---

## 二、两个平台的契约差异（实测）

### 2.1 Hook 配置（唯一必须分叉处）

| 项 | ZCode（现状，不动） | Claude Code（要求） |
|---|---|---|
| 事件容器 | `{"description": ..., "hooks": {...}}` | 同左（一致） |
| `type` | `process` | **`command`** |
| 命令形态 | `command` + `args: []` 分离 | **单条 `command` 字符串** |
| 超时 | `timeoutMs: 3000` | **`timeout: 3`**（秒） |
| 路径变量 | `${ZCODE_PLUGIN_ROOT}` | **`${CLAUDE_PLUGIN_ROOT}`** |
| 其它字段 | `statusMessage` | 同名字段存在，可用 |

> **证据**：Claude Code 二进制内嵌的 hook schema 中，`type` 枚举为 `command | prompt | agent | http | mcp_tool | script | function`，**不含 `process`**。

### 2.2 Hook 输出契约（已兼容，无需改脚本）

`hooks/prepend-global-rules-reminder.mjs` 当前输出：

```js
{
  hookSpecificOutput: {
    hookEventName: "UserPromptSubmit",
    additionalContext: "<规则文本>"
  }
}
```

Claude Code 的 `UserPromptSubmit` 正是读取 `hookSpecificOutput.additionalContext`。**脚本一行不用改。**

### 2.3 Agent 发现机制（关键差异）

Claude Code 的 agent 解析逻辑（从二进制提取）：

```js
let { name, description } = frontmatter
if (!name || typeof name !== "string") return null   // 无 name → 整个 agent 被丢弃
...
agentType: name                                        // subagent_type 的值 = frontmatter.name
```

**实测事实：**

| 项 | 结果 |
|---|---|
| agent 文件位置 | 插件根 `agents/*.md` |
| `name` 字段 | **必需**，缺失则该 agent 完全不加载 |
| 名称字符限制 | 仅"不能以 `-` 开头"，**中文合法** |
| `subagent_type` 取值 | = frontmatter 的 `name` |
| 当前仓库 363 个 agent | 331 个 `name` 为中文，与文件名不一致；32 个 `manager-*` 为英文 |

**结论**：中文 `name` 技术上可用，但跨模型 tokenize 行为不确定、日志难排查、与 32 个英文 manager 语义不统一。采用英文 slug 作 `name`，中文降级到自定义 `title` 字段。

### 2.4 组件类型全集（Claude Code 支持但项目未用的）

Claude Code manifest 支持的路径字段实测为：
`commands` · `agents` · `skills` · `hooks` · `mcpServers` · `lspServers` · `themes` · `workflows` · `monitors` · `outputStyles` · `channels` · `bin` · `keybindings`

本项目当前只需 `commands` / `agents` / `skills` / `hooks` 四项。

### 2.5 部署产物勘察（`npm run deploy:dry` 实测）

`scripts/install.js` 目前产出**两个**目标：

| 目标路径 | 结构 | 说明 |
|---|---|---|
| `~/.zcode/skills/zcode-expert-system/` | 扁平全量：`SKILL.md` + `scripts/` + `agents/` + `config/` … 全在根 | ZCode 技能目录 |
| `~/.zcode/cli/plugins/cache/zcode-plugins-official/zcode-expert-system/3.2.1/` | **仅 `commands/` `hooks/` `skills/`** | ZCode 插件缓存 |
| `~/.zcode/agents/` | 363 个子代理 | ZCode 全局 agent 目录 |

**三项关键发现：**

1. **`commands/wf/*.md` 中 33 处 `$ZCODE_PLUGIN_ROOT/skills/zcode-expert-system/scripts/...` 引用是正确的** —— 它指向部署后的插件缓存目录，该路径下 `scripts/` 真实存在。源码仓库中不成立，但部署后成立。**无需修改。**

2. **ZCode 插件缓存目录内没有 `agents/`** —— 363 个 agent 被部署到 ZCode 全局目录 `~/.zcode/agents/`，不在插件内。

3. **ZCode 插件缓存目录内没有 `.claude-plugin/`** —— Claude Code 直接加载该目录会跳过。

> **推论**：Claude Code **不能复用** ZCode 的部署产物，必须有自己的部署目标，且**必须包含 `agents/`**。

---

## 三、适配架构

### 3.1 原则

- **ZCode 侧零改动**：`.zcode-plugin/`、`hooks/hooks.json`、`~/.zcode/agents/`、install.js 的 ZCode 分支全部保持原样。
- **Claude Code 侧全部新增**：不修改任何现有 ZCode 依赖的文件，只做加法。
- 共享源码目录：`agents/` `commands/` `scripts/` `config/` `references/` `templates/`。

### 3.2 源码仓库新增文件

```
zcode-expert-system/
├── .zcode-plugin/plugin.json          ← 保持不动（ZCode）
├── .claude-plugin/plugin.json         ← 【新增】Claude Code manifest
├── hooks/
│   ├── hooks.json                     ← 保持不动（ZCode，type: process）
│   ├── claude-hooks.json              ← 【新增】Claude Code 版（type: command）
│   └── prepend-global-rules-reminder.mjs  ← 保持不动（输出格式两边通用）
├── agents/*.md                        ← 【改】仅 frontmatter 调整
├── commands/wf/*.md                   ← 保持不动
└── scripts/install.js                 ← 【改】新增 Claude Code 部署分支
```

### 3.3 `.claude-plugin/plugin.json`

**修正版**（依据实测：不声明 `skills`/`agents` 字段，靠自动发现）：

```json
{
  "name": "zcode-expert-system",
  "description": "ZCode Expert System v3.2 - 331 experts in 32 top-level categories with two-axis routing (scale -> nine-stage workflow, domain -> expert). Fuses OpenSpec + Superpowers + multi-agent + TDD.",
  "version": "3.2.1",
  "author": { "name": "wutian122" },
  "license": "MIT",
  "repository": "https://github.com/wutian122/zcode-expert-system",
  "commands": "./commands",
  "hooks": "./hooks/claude-hooks.json",
  "keywords": ["expert-system", "routing", "agents", "workflow", "openspec", "superpowers", "tdd", "zcode"]
}
```

**为什么去掉 `skills` 和 `agents`：**

- `"skills": "./skills"` → 源码仓库无此目录 → **error**；去掉后靠 `skills/<name>/SKILL.md` 自动发现，目录不存在时不报错
- `"agents": "./agents"` → 目录不是 `.md` → **error**；去掉后靠 `agents/*.md` 自动发现（363 个已验证全量加载）
- `"commands": "./commands"` → 保留（commands 无自动发现，必须显式声明）

**注意**：Claude Code 要求路径以 `./` 开头。

### 3.4 `hooks/claude-hooks.json`

```json
{
  "description": "Claude Code adapter — 在每次用户输入前注入专家体系自动触发规则。",
  "hooks": {
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "node \"${CLAUDE_PLUGIN_ROOT}/hooks/prepend-global-rules-reminder.mjs\"",
            "timeout": 3
          }
        ]
      }
    ]
  }
}
```

### 3.5 Agent frontmatter 改造

**实测结论：中文 `name` 完全可用，改造并非必需。**

探针测试证实：
```
agent frontmatter name: 代码审查员
→ 实际 subagent_type: zcode-expert-system:代码审查员   ✅ 正常工作
```

因此有两种可选路径：

#### 路径 A：零改造（推荐先行）

331 个 agent **一个文件都不动**。中文名直接可用，`subagent_type` = `zcode-expert-system:代码审查员`。

- 优点：零风险、零工作量、中文人设完整保留
- 缺点：跨模型 tokenize 不确定；`dispatch_expert()` 仍需加上插件前缀

#### 路径 B：改英文 slug（可选优化）

```yaml
---
name: expert-engineering-code-reviewer   # 派发用（= 文件名）
title: 代码审查员                          # 中文人设名
description: 专业代码审查专家，...
emoji: 👀                                 # 保留（两边都忽略）
color: purple                             # 保留
---
```

- 优点：日志可读、跨模型稳定、与 32 个英文 manager 命名统一
- 缺点：363 个文件要改；`title` 是自定义字段（实测零告警，但非标准）

> **建议**：先走路径 A 打通全链路，验证端到端可用后再决定是否做路径 B。这样任何问题都能归因到"适配层"而不是"331 个文件的批量改动"。

### 3.6 路由代码改造（1 处，**两条路径都必须改**）

`zcode_expert_system.py:787`：

```python
# 当前（ZCode 侧正确，Claude Code 侧缺前缀）
"subagent_type": expert_name,          # 「代码审查员」

# Claude Code 侧需要插件限定名
"subagent_type": f"zcode-expert-system:{selected_expert.get('id')}",  # 路径 B
"subagent_type": f"zcode-expert-system:{expert_name}",                # 路径 A
```

> **实测依据**：探针中 agent 的 `name` 为 `expert-slug-ok`，`claude plugin validate` 报告的可派发类型是 `adapter-probe:expert-slug-ok`。**插件前缀是强制要求。**

**双平台处理**：`dispatch_expert()` 需要能区分当前运行平台。建议增加一个开关：

```python
def _qualified_subagent_type(expert):
    if _running_under_claude_code():          # 探测 CLAUDE_PLUGIN_ROOT 环境变量
        return f"zcode-expert-system:{expert['id']}"
    return expert["name"]                      # ZCode 保持原样（中文名）
```

### 3.7 `scripts/install.js` 新增 Claude Code 部署分支

新增第三个部署目标（**ZCode 的两个目标保持不动**）：

```
~/.claude/plugins/cache/<marketplace>/zcode-expert-system/<version>/
├── .claude-plugin/plugin.json
├── agents/                        ← 必须包含（ZCode 侧没有）
├── commands/
├── skills/zcode-expert-system/
├── scripts/
├── config/
├── references/
├── templates/
└── hooks/
    ├── hooks.json                 ← 保留（ZCode 格式）
    └── claude-hooks.json          ← 新增
```

**关键**：该分支必须复制 `agents/`，这是与 ZCode 部署产物的核心差异。

---

## 四、改动清单（按实测修正）

| # | 文件/目录 | 动作 | 数量 | 风险 |
|---|---|---|---|---|
| 1 | `.claude-plugin/plugin.json` | 新增 | 1 | 无 |
| 2 | `hooks/claude-hooks.json` | 新增 | 1 | 无 |
| 3 | `zcode_expert_system.py:787` | 改（加平台探测 + 前缀） | 1 处 | 中（需回归） |
| 4 | `scripts/install.js` | 新增 Claude Code 部署分支（**必须含 `agents/`**） | 1 | 中（需实测） |
| 5 | `agents/*.md` frontmatter | **可选**（路径 B 才改） | 0 或 363 | 路径 A 为零 |
| 6 | `commands/wf/*.md` | **不动** | 0 | — |
| 7 | `hooks/hooks.json` | **不动** | 0 | — |
| 8 | `hooks/prepend-*.mjs` | **不动**（实测输出契约兼容） | 0 | — |

---

## 五、待验证事项

~~1. `skills` 字段指向不存在目录的行为~~ → **已验证：error，改为不声明该字段**
~~2. `title` 自定义字段是否触发告警~~ → **已验证：零告警**
~~3. 363 个 agent 同时加载是否有上限~~ → **已验证：363/363 全量加载，无截断**

**新增待验证项**：

1. **`dispatch_expert()` 输出前缀后，ZCode 侧是否受影响** —— 需回归 ZCode 端到端派发。
2. **hook 文案需同步修正**：`hooks/prepend-global-rules-reminder.mjs` 的提示文本写着"subagent_type 填专家中文名"，在 Claude Code 下需改为带插件前缀的完整名。这是**运行期文案**，不改会导致主控按错误格式派发。

---

## 六、实施顺序建议（按实测修正）

| 阶段 | 内容 | 可独立验证 | 风险 |
|---|---|---|---|
| 1 | 新增 `.claude-plugin/plugin.json` + `hooks/claude-hooks.json` | `claude plugin validate .` 通过；组件可见 | 低 |
| 2 | 平台探测 + `dispatch_expert()` 加前缀 | 派发单 `subagent_type` 格式正确 | 中 |
| 3 | 修正 hook 运行期文案（中文名 → 带前缀完整名） | 主控按新文案派发成功 | 低 |
| 4 | `install.js` 增加 Claude Code 部署分支（含 `agents/`） | 部署产物结构正确 | 中 |
| 5 | 回归验证 ZCode 侧未受影响 | ZCode 功能如常 | 中 |
| 6 | （可选）363 个 agent 改英文 slug | 日志可读性提升 | 低 |

**阶段 1 可立即验证**：两个纯新增文件，跑一次 `claude plugin validate .` 就能确认插件可被识别。

### 已知的验证命令

```bash
claude plugin validate .          # 校验 manifest 与组件
claude --plugin-dir . --debug     # 从本地目录直接加载（开发调试）
```

---

## 七、附：不可行方案的记录

| 方案 | 不可行原因 |
|---|---|
| 单一 `hooks.json` 兼容两平台 | `type` 取值 `process` 与 `command` 互斥，无交集写法 |
| 直接复用 ZCode 插件缓存目录 | 该目录无 `agents/`、无 `.claude-plugin/`，Claude Code 无法识别 |
| 修改 ZCode 部署形态以统一 | 老板明确要求 ZCode 侧不改动 |
| `"agents": "./agents"` 指目录 | **实测 error**：`Invalid string: must end with ".md"` |
| `"skills": "./skills"` 声明源码中不存在的目录 | **实测 error**：runtime load failure |
| 插件名使用 `cc-plugin-` / `claude-` 前缀 | **实测 error**：保留给 Anthropic 官方 |
| 中文 `name` 直接作 `subagent_type`（不带前缀） | **实测 error**：必须为 `插件名:name` 形式 |