# ZCode Expert System v3.2.1 - ZCode 专家体系

[English](README.md) · **简体中文**

## 📋 项目简介

**ZCode Expert System** 是 ZCode 插件系统的专家体系插件，基于 [dsh-agency-agents](https://github.com/MichengAI/dsh-agency-agents) 的 331 位专家完整人格提示词，适配 ZCode 平台实现**两轴正交路由**：规模轴决定流程走多长，域轴决定派哪位专家。

## 🏗️ 架构设计

### 系统概述

ZCode Expert System v3.2.1 是 ZCode 的专家路由插件。它承载来自 [dsh-agency-agents](https://github.com/MichengAI/dsh-agency-agents) 的 331 位专家完整人格提示词，并融合 **Superpowers 工程能力体系** 与 **OpenSpec 规格驱动开发体系**。插件采用**两轴正交路由**：

| 轴 | 回答问题 | 实现 |
|---|---|---|
| **规模轴** | 走不走流程、走多长 | `zcode_dev_workflow.py` → 只读/轻量/中任务/大任务/Bug，决定 `trim_matrix` 与 `minimum_gates` |
| **域轴** | 派哪位专家 | `zcode_expert_system.py` → 32 大类 → 331 位专家，决定 `subagent_type` |

**两轴正交、相互独立**：规模决定阶段裁剪，域决定 `subagent_type`。所有任务（含只读与机械任务）都必须完成两轴分诊，域路由不可跳过（W10）。

```
用户任务
  │
  ├─── 规模轴（zcode_dev_workflow.py）─────────────────────┐
  │    只读 / 轻量 / 中任务 / 大任务 / Bug                  │
  │    → 九阶段里走哪几个（trim_matrix）                    │
  │    → 最少过几道门禁（minimum_gates）                    │
  │                                                        │
  └─── 域轴（zcode_expert_system.py）─────────────────────┐
       32 大类 → 331 位专家                                 │
       → subagent_type（专家中文显示名）                   │
                                                          ▼
                                        二维派发计划（plan）
```

### 域轴内部三层路由

域轴内部仍是三层：

```
用户任务
  │
  ▼
┌─────────────────────────────────┐
│  第一层：任务分类               │
│  32 个一级大类                  │
└──────────┬──────────────────────┘
           │
           ▼
┌─────────────────────────────────┐
│  第二层：领域总经理（32 个）     │
│  负责任务分解与专家派发          │
│  由 slug `manager-<分类>` 派发   │
└──────────┬──────────────────────┘
           │
           ▼
┌─────────────────────────────────┐
│  第三层：领域专家（331 位）      │
│  已注册为 ZCode 子代理          │
│  由专家中文显示名派发           │
└─────────────────────────────────┘
```

**派发流程**：

1. **任务分类** → 归类为 32 个一级大类之一（`zcode_expert_system.classify_task_detailed`）
2. **总经理路由** → 对应的领域总经理（`manager-<分类>`）
3. **专家粗筛** → 从该大类专家中选 Top-5 候选（Embedding 可用时用向量，否则词元重叠打分）
4. **语义精判** → **主控（会话模型）必须亲自做**；Python 的选择只是词元计数，不是语义判断。`semantic_selection_required=true` 时，主控必须查看 `top_candidates[].score_detail` 按业务语义定夺，必要时用 `build_dispatch_for_expert("<专家名>", task)` 改判
5. **专家派发** → `Agent(subagent_type="<专家中文显示名>")`，派发 prompt 首段硬声明流程契约优先于专家人格
6. **上下文传递** → 各阶段结果通过返回值传递

> **语义精判契约**：本插件故意不额外配置 LLM/Embedding 服务，依赖会话中正在运行的模型。`scripts/llm_client.py` 的 `_call_llm` 与 `embedding_client.py` 的 `get_embedding` 恒返回 `None`，粗筛退化为本地词元重叠。当 `semantic_selection_required=true` 时，主控必须复核 `score_detail`，判断 Python 排序是否只是词面巧合（如「飞书集成开发工程师」仅因描述含「登录」二字而胜出），必要时改判。

### 角色 × 专家矩阵（工作流角色）

工作流角色是**职责**，331 位专家是**领域能力**，二者正交组合：

| 角色 | 是否可派 | 核心约束 |
|---|---|---|
| **编排者（Orchestrator）** | ❌ 主控自任 | 唯一状态写者、亲跑验证、裁决记账 |
| **实施者（Implementer）** | ✅ 域专家 | 禁派子代理；不得超 brief 范围；TDD |
| **审查者（Reviewer）** | ✅ **异域专家** | 只读；不采信自评；必须给出 spec 符合性 + 代码质量双结论 |
| **调查者（Investigator）** | ✅ 域专家 | 只读；结论带 `file:line` |
| **分析者（Analyst）** | ✅ 域专家 | 只读分析；四段式「现象→原因→影响→建议」；领域判断不留主控 |

**流程契约优先于专家人格**——派发 prompt 首段必须硬声明这一点，否则架构类专家会自己重新设计架构。

### 审查者独立性（三重保证）

331 位专家里只有 1 位「代码审查员」，独立性不能靠"类型多"：

1. `type ≠` 实施者（不同专家）
2. `instance ≠` 独立派发、独立上下文
3. `input 隔离`——只给 brief / report / 变更集三件，不给对话上下文

必须落盘标记：`independence: L0`（独立子代理，可交付）/ **L1**（主控自审降级，须声明）/ **L2**（无审查，禁止交付）。

### 七态状态机（唯一状态机）

`PENDING → IN_PROGRESS → REVIEW → NEEDS_FIX → DONE`，加 `BLOCKED`、`PARKED`。SDD 的四种状态（`DONE` / `DONE_WITH_CONCERNS` / `NEEDS_CONTEXT` / `BLOCKED`）是**边标签**，不是状态——它们进入状态机后立即转化为状态转移。

关键转移：

| 转移 | 触发条件 | 证据 |
|---|---|---|
| `IN_PROGRESS → REVIEW` | 实施报 DONE / DONE_WITH_CONCERNS | 变更集非空，report 含命令输出退出码 |
| `REVIEW → DONE` | 审查 spec ✅ + 质量通过 | 双结论 + 主控亲跑全量测试见绿 |
| `NEEDS_FIX → PARKED` | 5 轮修复仍 open，主控裁决 | Ruling 行含代价 |
| `DONE → NEEDS_FIX` | 归档前回归发现破坏 | 真实 RED 输出 + tasks.md 回退 |

不变量：一任务同一时刻只有一状态；`DONE` 当且仅当 tasks.md 为 `- [x]`；非 DONE 一律 `- [ ]`（含 PARKED）；ledger 首行必须为 `# SDD ledger — plan: <计划路径>`；任何 DONE 都能反查到非空变更集 + 审查结论。

### 证据分级（防丢的关键）

| 级别 | 位置 | 内容 | 生命周期 |
|---|---|---|---|
| **P1** | 文件快照哈希 或 git commit | 实际改了什么 | 交付后归档 |
| **P2** | `openspec/changes/<n>/tasks.md` + 计划文档 `## Rulings` | 完成度、ADR 决策 | 归档永久 |
| **P3** | 计划文档 `## Baseline` / `## Review` / `## Rulings` / `## Integration Verification` | 基线、审查、裁决、交付重测 | 随仓库 |
| **P4** | `.superpowers/sdd/<plan>/` | ledger / brief / report / 快照 | **终审后删，删前必须导出 P3** |

> **铁律：P4 未导出，禁止删 workspace。** 否则基线、裁决、重测记录整体消失——这是源规范最危险的丢失点。

### 无 Git Worktree 的并行模型（老板决策）

本体系**不使用 Git Worktree**。守恒关系必须讲清：

| 保留的并行 | 取消的并行 |
|---|---|
| ✅ 只读调查并行（多个无关失败分域取证） | ❌ **多 Agent 实施并行** |
| ✅ 审查并行（多位 Reviewer 同批任务，只读无冲突） | — |

**原因**：没有隔离工作区就不能有两个写者。**实施永远串行**——这是守恒，不是保守。

**Git 降为可选增强层**：

| 探测 | 变更集来源 | 收尾 |
|---|---|---|
| 有 git | `review-package` 的 `BASE..HEAD` diff | finishing 三选一 |
| 无 git（默认） | 文件快照 sha256 差集 + 变更文件全文 | 改动清单验收 |

**快照机制**：派发前记录任务 Files 清单每个文件的 sha256；实施后重新计算；差集 = 新增 / 修改 / 删除。**变更集由主控独立计算，不由实施者自述**——这是无 git 环境下仍可信的关键。

不擅自为老板的项目 `git init`。

### 冲突裁决（10 条，`workflow.json` → `conflict_rulings`）

| # | 裁决 |
|---|---|
| W1 | 无 worktree 即无实施并行；保留只读调查与审查并行 |
| W2 | 中/大任务 `design.md` 唯一真相，阶段一不落盘；小任务落 `docs/superpowers/specs/` 且标"非权威" |
| W3 | `apply-change` 直行与 SDD 模式**互斥**，同 change 不得混用 |
| W4 | 基线红不阻断开工，但必须记清单；此后红项比对：清单内=既存，清单外=本次引入 |
| W5 | 三重证据：变更集 + report 含命令输出退出码 + **主控亲跑全量** |
| W6 | 派发 prompt 首段硬声明「流程契约优先于专家人格」 |
| W7 | git 探测失败走快照证据 + 主控自审（记 L1），交付中显式声明 |
| W8 | PARKED 默认**禁归档**；「接受不修」必须迁出到新 change |
| W9 | Agent 派发无 model 参数，用**专家粒度 + 任务颗粒度**控成本；「升档」= 换更专专家 |
| W10 | 两轴强制串行：所有任务（含只读与机械任务）先规模后域，域路由不得跳过；豁免仅两级——闲聊/问候、老板明示且记 Ruling |

### 机械核对（不靠自觉）

```bash
python "$ZCODE_PLUGIN_ROOT/skills/zcode-expert-system/scripts/workflow_check.py" --change <change> --plan <plan.md> --scale medium
```

核对项：环境探测 / 规格产物 / 计划必备段 / 任务标题格式 / 占位符 / 双账本对齐 / 基线双写 / 账本身份 / 三元对齐 / 独立性标记 / Rulings 持久化 / 集成后重测 / 归档完成度。

退出码：`0` 无 FAIL，`1` 有 FAIL（不得进下一阶段）。

> **纯 Markdown 检查表一定会被跳过，所以必须机械可验。**

### 32 个一级大类

| 大类 | 专家数 | 大类 | 专家数 |
|---|---|---|---|
| frontend-client | 8 | supply-chain | 5 |
| backend-architecture | 18 | legal-compliance | 6 |
| data-database | 8 | hr | 7 |
| devops-operations | 7 | finance-tax | 14 |
| ai-llm | 9 | academic-research | 10 |
| embedded-iot | 6 | government-public | 1 |
| network-engineering | 3 | business-support | 6 |
| engineering-quality | 10 | data-knowledge | 2 |
| security-compliance | 19 | game-dev | 21 |
| data-testing | 15 | spatial-computing | 6 |
| design-creative | 14 | gis | 13 |
| marketing-growth | 45 | project-management | 9 |
| paid-media | 7 | product-management | 6 |
| sales-customer | 10 | customer-support | 10 |
| business-strategy | 18 | language-translation | 2 |
| healthcare | 7 | agent-governance | 9 |

## 📦 安装方法

### 方式一：npm 一键安装（推荐）

```bash
# 1. 全局安装
npm install -g zcode-expert-system

# 2. 部署到 ZCode
zcode-expert-system install

# 3. 重启 ZCode（子代理清单在会话启动时加载，必须重启）
```

安装脚本会自动完成：

- 插件缓存目录 + 插件清单（ZCode 靠它识别插件）
- 技能本体到 `~/.zcode/skills/zcode-expert-system/`
- 插件级 hooks 到插件根 `hooks/`
- 32 个总经理 + 331 位专家子代理到 `~/.zcode/agents/`
- 注册到 `~/.zcode/cli/plugins/installed_plugins.json`

### 方式二：GitHub 源码安装

```bash
git clone https://github.com/wutian122/zcode-expert-system.git
cd zcode-expert-system
npm install
zcode-expert-system install
```

> 注：`.zcode-plugin/plugin.json` 的 `skills` 字段仅对**部署后布局**生效
> （install.js 部署之后）；仓库直装（源码方式）请将技能目录指向仓库根。

### 方式三：ZCode 插件市场安装

（尚未上架，当前请用方式一 npm 安装。）在 ZCode 的插件市场中搜索
`zcode-expert-system` 并点击安装。

### 卸载

```bash
zcode-expert-system uninstall
# 或
node scripts/install.js --uninstall
```

## ⚙️ 配置说明

### 无需单独配置 LLM/Embedding 服务

本插件**直接使用会话中正在使用的模型**，无需单独配置：

- **任务分类**：使用当前会话模型
- **专家精判**：使用当前会话模型
- **专家粗筛**：优先 Embedding，不可用时退化为词元重叠打分

> 插件随会话模型升级自动提升精度，无需额外配置。

### 服务不可用时的降级策略

- **LLM 不可用** → 关键词最长匹配 + 词元重叠打分
- **Embedding 不可用** → 词元重叠打分（名称权重 3 倍 + 描述 + 提示词内容）

两类降级都在本机完成，无网络依赖，流程不中断。

## 🚀 使用方法

### 调用专家体系

在 ZCode 会话中直接下达专业任务——`UserPromptSubmit` 钩子会自动注入路由规则，
技能按领域关键词触发。

实际存在的入口：

| 入口 | 作用 |
|---|---|
| `Skill(zcode-expert-system)` | 以任务描述调用技能 |
| `/wf:triage <任务>` | 双轴分诊：规模 + 领域路由一次产出（只读/轻量/中任务/大任务/Bug；只读派 analyst） |
| `/wf:plan <任务>` | 生成二维派发计划（角色 × 专家） |
| `/wf:check` | 对当前变更/计划做机械门禁核对 |

> 注意：**不存在** `/zcode-expert-system` 斜杠命令。插件的 `commands/`
> 命名空间只有 `/wf:*` 一族（`commands/wf/*.md`）。

系统会自动：

1. 分类任务（如 `backend-architecture`）
2. 确定领域总经理（`manager-backend-architecture`）
3. 从该大类专家中选出最匹配的一位
4. 返回可执行派发单（`status: pending_dispatch`）
5. 主控用 `Agent(subagent_type="后端架构师")` 派发执行
6. 上下文在各阶段之间传递

### 支持的全部专家

| 大类 | 说明 |
|---|---|
| frontend-client | 前端与客户端 |
| backend-architecture | 后端与架构 |
| data-database | 数据与数据库 |
| devops-operations | DevOps 与运维 |
| ai-llm | AI 与大模型 |
| embedded-iot | 嵌入式与物联网 |
| network-engineering | 网络工程 |
| engineering-quality | 工程效能与质量 |
| security-compliance | 安全与合规技术 |
| data-testing | 数据与测试 |
| design-creative | 设计与创意 |
| marketing-growth | 营销与增长 |
| paid-media | 付费媒体 |
| sales-customer | 销售与客户 |
| business-strategy | 商业经营与战略 |
| healthcare | 医疗健康 |
| supply-chain | 供应链与物流 |
| legal-compliance | 法务与合规 |
| hr | 人力资源 |
| finance-tax | 财务与税务 |
| academic-research | 学术与研究 |
| government-public | 政企与公共服务 |
| business-support | 商业支持与专业服务 |
| data-knowledge | 学术与知识服务 |
| game-dev | 游戏开发 |
| spatial-computing | 空间计算与 XR |
| gis | 地理信息系统 |
| project-management | 项目管理 |
| product-management | 产品管理 |
| customer-support | 客户支持 |
| language-translation | 语言与跨文化 |
| agent-governance | 身份与智能体治理 |

完整专家名单见各总经理定义中的「管辖范围」表，或 `config/experts.json`。

## 🤖 已注册子代理

安装后 ZCode 可派发 **363 个子代理**：

| 类型 | 数量 | 位置 | 派发方式 |
|---|---|---|---|
| 领域总经理 | 32 | `~/.zcode/agents/manager-*.md` | `Agent(subagent_type="manager-backend-architecture")` |
| 领域专家 | 331 | `~/.zcode/agents/expert-*.md` | `Agent(subagent_type="后端架构师")` |

> 注意：总经理用 **slug**（`manager-<分类>`）派发，因为 `install.js` 写入部署文件的
> `name:` 就是 slug；专家用**中文显示名**派发。两者混淆会导致 `Agent` 调用找不到代理。

> `subagent_type` 填**中文显示名**（专家 md 的 `name:` 字段）。
> 若名字不在会话清单中，回退为读取该专家提示词、代入其人格执行。

⚠️ **改动子代理文件后必须重启 ZCode** —— Agent 清单是会话启动时的快照，中途新增或修改不会生效。

## 📁 目录结构

```
zcode-expert-system/
├── .zcode-plugin/plugin.json          # 插件清单
├── SKILL.md                            # ZCode 技能入口
├── README.md / README_CN.md            # 英文 / 中文文档
├── zcode_expert_system.py              # 域轴（32 大类 → 331 专家）
├── zcode_dev_workflow.py               # 规模轴（分诊 → 阶段 → 派发计划）
├── skill_entry.py                      # 技能调用包装层
├── package.json                        # npm 包配置
├── scripts/
│   ├── install.js                      # 一键部署 / 卸载脚本
│   ├── workflow_check.py               # 门禁机械核对（+ --self-check）
│   ├── llm_client.py                   # LLM 调用辅助
│   └── embedding_client.py             # Embedding 客户端
├── config/
│   ├── experts.json                    # 331 位专家元数据
│   ├── categories.json                 # 32 个一级大类配置
│   └── workflow.json                   # 唯一声明源：阶段/门禁/状态机/裁剪矩阵
├── commands/
│   └── wf/*.md                         # 12 个斜杠命令（/wf:triage、/wf:check …）
├── references/
│   ├── stage-S0..S8*.md                # 9 份阶段规格
│   ├── roles/*.md                      # 5 份角色契约（编排/实施/审查/调查/分析）
│   └── workflow-tree.md                # 工作流树与故障恢复
├── templates/
│   ├── plan-sections.md                # 计划文档模板（12 个必备段）
│   ├── progress.md                     # SDD 账本模板（七态）
│   └── *.md                            # 任务报告 / 审查报告 / Bug 报告 / 最小契约
├── docs/
│   └── workflow-fusion-design.md       # 融合设计基线（为什么这样设计）
├── context/
│   └── context-manager.py              # 上下文管理器（数据落 ~/.zcode/expert-system/context/）
├── tests/                              # 回归测试（pytest）
├── hooks/
│   ├── hooks.json                      # 钩子配置（ZCode 标准 schema）
│   └── prepend-global-rules-reminder.mjs  # 输入前注入触发规则
└── agents/
    ├── manager-*.md                    # 32 个领域总经理定义
    └── expert-*.md                     # 331 位专家人格提示词
```

## 🛠️ 开发指南

### 本地开发

```bash
git clone https://github.com/wutian122/zcode-expert-system.git
cd zcode-expert-system

# 直接运行域路由（只做路由查询，不派发——派发走 /wf:plan 与 Agent 工具）
python zcode_expert_system.py "设计一个支持高并发的后端 API 接口"

# 验证分类准确率
python -c "from zcode_expert_system import zcode_expert_system; print(zcode_expert_system('进行渗透测试')['category'])"
```

### 贡献代码

1. Fork 本仓库
2. 创建特性分支：`git checkout -b feat/your-feature`
3. 提交更改：`git commit -m 'feat: add your feature'`
4. 推送分支：`git push origin feat/your-feature`
5. 提交 Pull Request

提 PR 前请确保全量回归测试为绿：

```bash
python -m pytest tests/ -q   # 末行必须是 "passed"，0 failed
```

## 📄 许可证

本项目基于 [MIT 许可证](LICENSE) 开源。

## 🔗 引用来源与开源依赖

本项目在以下开源项目与能力体系的基础上进行了 ZCode 平台适配与工程化改造：

| 来源 | 用途 | 项目地址 |
|---|---|---|
| **dsh-agency-agents** | 331 位专家完整人格提示词（专家库来源） | https://github.com/MichengAI/dsh-agency-agents |
| **Superpowers** | 工程能力体系（brainstorming、writing-plans、sdd、tdd、verification、code-review、finishing 等能力） | 待项目方补充 GitHub 地址 |
| **OpenSpec** | 规格驱动开发体系（change 提案、规格同步、归档工作流） | 待项目方补充 GitHub 地址 |

本项目在此基础上增加了 ZCode 平台适配与工程化改造：三层路由架构（分类 → 总经理 → 专家）、两轴正交路由（规模轴 + 域轴）、九阶段受控工作流、机械门禁核对、七态状态机、证据分级与冲突裁决。

## 🙏 致谢

专家提示词来自 [dsh-agency-agents](https://github.com/MichengAI/dsh-agency-agents) 开源项目，并在此基础上做了 ZCode 平台适配与工程化改造（三层路由架构、领域总经理任务分解、动态专家派发）。

## 📞 联系方式

如有问题或建议，请通过 GitHub Issues 提交。

---

**ZCode Expert System v3.2.1** - 让 AI 专家协作更智能 🚀
