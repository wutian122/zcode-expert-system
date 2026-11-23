# 设计：Claude Code 插件适配

## 一、实测基线

以下数据来自 2026-11-20 用临时探针插件 + `claude plugin validate` 实测（Claude Code 2.1.329）。

| # | 验证项 | 结果 |
|---|---|---|
| 1 | `skills` 字段指向不存在目录 | **error**：`Path not found`，运行时 load failure |
| 2 | `agents` 字段指向目录 | **error**：`Invalid string: must end with ".md"` |
| 3 | `title` 自定义字段 | 零告警，静默忽略 |
| 4 | `name` 与文件名不一致 | 正常，以 frontmatter `name` 为准 |
| 5 | 中文 `name` | 正常，派发类型为 `插件名:中文名` |
| 6 | 363 个 agent 同时加载 | 363/363 全量，无截断无告警 |
| 7 | 项目真实 hook 脚本输出 | 契约完全兼容，脚本无需改动 |
| 8 | 插件名 `cc-plugin-` 前缀 | **error**：保留给 Anthropic 官方 |

## 二、关键机制

### 2.1 子代理限定名

Claude Code 的可派发子代理类型为 **`<插件名>:<frontmatter.name>`**。

```
agent 文件: agents/expert-engineering-code-reviewer.md
frontmatter name: 代码审查员
可派发类型: zcode-expert-system:代码审查员
```

因此 `dispatch_expert()` 在 Claude Code 环境下必须输出限定名，而 ZCode 环境保持中文裸名。

### 2.2 组件发现策略

| 组件 | 发现方式 | manifest 字段 |
|---|---|---|
| agents | 自动扫描 `agents/*.md` | **不声明**（声明目录会报错） |
| skills | 自动扫描 `skills/<name>/SKILL.md` | **不声明**（源码无此目录，声明会报错） |
| commands | **必须显式声明**，无自动发现 | `"commands": "./commands"` |
| hooks | 显式声明文件路径 | `"hooks": "./hooks/claude-hooks.json"` |

### 2.3 平台探测

`dispatch_expert()` 用环境变量区分运行平台：

```
CLAUDE_PLUGIN_ROOT 存在 → Claude Code 环境 → 输出限定名
否则                    → ZCode 环境      → 保持原行为
```

该变量由 Claude Code 在 hook 与子进程中注入，ZCode 不设置，可作可靠判据。

### 2.4 部署产物差异

`scripts/install.js` 现有两个 ZCode 目标：

| 目标 | 结构 |
|---|---|
| `~/.zcode/skills/zcode-expert-system/` | 扁平全量（SKILL.md + scripts + agents + config …） |
| `~/.zcode/cli/plugins/cache/.../3.2.1/` | 仅 `commands/` `hooks/` `skills/` |
| `~/.zcode/agents/` | 363 个子代理（**插件外**） |

**Claude Code 部署目标必须包含 `agents/`**，这是与 ZCode 缓存目录的核心差异。

### 2.5 跨机器安装影响（关键约束）

本次适配 MUST 保证 **ZCode 在其他电脑上的安装行为零变化**：

1. **npm 发布包白名单**：`package.json` 的 `files` 字段（列出发布包内容）当前为：
   ```
   .zcode-plugin/ scripts/ vendor/ config/ agents/ references/
   templates/ commands/ docs/ context/ bin/ hooks/ ...
   ```
   **未列出 `.claude-plugin/` 与 `openspec/changes/`**，因此新增的 Claude Code 适配层（`.claude-plugin/plugin.json`、`hooks/claude-hooks.json`）**不会进入 npm 发布包**。
   - `.zcode-plugin/plugin.json` 仍是 ZCode 的唯一清单来源
   - ZCode 用户 `npm install` 后只拿到 `.zcode-plugin/`，与今天完全一致

2. **install.js 零改动**：`preflight()` 校验逻辑只读 `SKILL.md`、`config`、`agents`、`commands` 等 ZCode 核心文件，**从不碰 `.claude-plugin/`**。新增的 Claude Code 部署分支（如果实施）也不读取 ZCode 任何文件。

3. **运行时隔离**：
   - `dispatch_expert()` 改造后，ZCode 环境下 `CLAUDE_PLUGIN_ROOT` 不存在，走原路径，输出中文裸名（与今天一致）
   - `hooks/hooks.json` 的 `type: process` 保持不变
   - 363 个 agent 的 `frontmatter` 保持不变（中文 `name`）

4. **发布流程零影响**：`npm publish` 时只打包 `files` 列出的内容，Claude Code 适配层不会被发布。ZCode 用户在 GitHub 或 npm 上拿到的包结构不变。

## 三、文件设计

### 3.1 `.claude-plugin/plugin.json`

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

**要点**：不声明 `agents` 与 `skills`（走自动发现）；路径必须以 `./` 开头。

### 3.2 `hooks/claude-hooks.json`

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

与 ZCode 版 `hooks/hooks.json` 的差异：`type` 为 `command`、命令为单字符串、`timeout` 单位为秒、变量为 `CLAUDE_PLUGIN_ROOT`。

### 3.3 `dispatch_expert()` 改造

位置：`zcode_expert_system.py:787`

```python
def _qualified_subagent_type(expert_name, expert_id):
    """按运行平台决定子代理派发名。

    Claude Code 要求 <插件名>:<frontmatter.name> 的限定形式；
    ZCode 使用中文裸名。用 CLAUDE_PLUGIN_ROOT 是否注入作判据。
    """
    if os.environ.get("CLAUDE_PLUGIN_ROOT"):
        return "zcode-expert-system:%s" % expert_name
    return expert_name
```

调用处：

```python
"subagent_type": _qualified_subagent_type(expert_name, selected_expert.get("id")),
```

### 3.4 hook 文案修正

`hooks/prepend-global-rules-reminder.mjs` 的提示文本当前写「subagent_type 填专家中文名」。

实际派发时 Claude Code 需要 `zcode-expert-system:中文名`。改为按平台输出：

- Claude Code 环境：提示写「填 `zcode-expert-system:<专家名>`」
- ZCode 环境：保持「填专家中文名」

## 四、测试兼容策略

现有 4 处测试硬断言 `subagent_type` 必须等于中文专家名，需在实施前改造为兼容两种形式：

| 文件 | 行号 | 当前断言 | 兼容改法 |
|---|---|---|---|
| `tests/test_semantic_selection.py` | 95 | `== "后端架构师"` | 改成 `in _valid_subagent_types()` |
| `tests/test_dispatch_plan.py` | 152 | `in _expert_names()` | 改成 `in _valid_subagent_types()` |
| `tests/test_domain_routing_mandatory.py` | 165 | `in _expert_names()` | 改成 `in _valid_subagent_types()` |
| `tests/test_domain_routing_mandatory.py` | 188 | `in _expert_names()` | 改成 `in _valid_subagent_types()` |

**`_valid_subagent_types()` 定义**（各测试文件内）：

```python
def _valid_subagent_types():
    """子代理派发名的合法集合（中文裸名 + Claude Code 限定名）。"""
    names = _expert_names()
    return names | {f"zcode-expert-system:{n}" for n in names}
```

这样无论运行在哪个环境（CI / ZCode / Claude Code），测试都能通过。

## 五、基线测试状态（实施前必须先修）

当前 `pytest tests/` 结果：**8 failed, 589 passed, 1 skipped**。

这 8 个失败与本次适配无关（是 `install.js` 与 `workflow_check.py` 的既有问题），但按铁律 5「基线测试绿才进实施」，**必须先修**。

失败列表：
- `test_component_registry.py::test_self_check_缺失项失败` (TypeError)
- `test_p5_install_safety.py::test_missing_agents_fails_before_touching_disk` (TypeError)
- `test_p5_install_safety.py::test_dry_run_deletes_nothing` (TypeError)
- `test_workflow_check_openspec.py` × 5 (TypeError / FAIL)

修复方案：逐个定位 TypeError 根因（大概率是 Windows 编码或路径问题），补测试。这是实施阶段的前置任务。

## 六、风险与对策

| 风险 | 对策 |
|---|---|
| `dispatch_expert()` 改动影响 ZCode 派发 | 平台探测分支隔离；ZCode 分支代码路径与现状完全一致 |
| 两套 manifest 版本号漂移 | `install.js` 统一从同一版本源写入两个 manifest |
| Claude Code 部署漏 `agents/` | 部署后校验 agent 数量，不足 363 即报错 |
| hook 文案与派发格式不同步 | 文案由同一函数生成，避免两处硬编码 |

## 七、验收标准

1. `claude plugin validate .` 通过，无 error
2. 插件加载后可见 363 个 agent、12 个 command、1 个 skill
3. `UserPromptSubmit` hook 在 Claude Code 中实际执行并注入 `additionalContext`
4. 派发单的 `subagent_type` 在 Claude Code 下为 `zcode-expert-system:<专家名>`
5. ZCode 侧 `npm run deploy` 行为与改动前一致，派发仍用中文裸名
6. **基线测试 100% 绿**（8 个失败已修复）
7. **4 处测试断言已改造为兼容两种 `subagent_type`**
8. **跨机器验证**：在另一台干净机器上 `npm install` + `npm run deploy`，ZCode 安装正常，无 `.claude-plugin/` 依赖