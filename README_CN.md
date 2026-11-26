# ZCode Expert System v3.2.5 - ZCode 专家体系

[English](README.md) · **简体中文**

## 📋 项目简介

**ZCode Expert System** 是**同时适配 ZCode、Claude Code 与 Qoder Desktop 的专家体系**，基于 [dsh-agency-agents](https://github.com/MichengAI/dsh-agency-agents) 的 331 位专家完整人格提示词，实现**两轴正交路由**：规模轴决定流程走多长，域轴决定派哪位专家。

同一个包可部署到三个平台。ZCode 读取 `.zcode-plugin/` 与 `hooks/hooks.json`，Claude Code 读取 `.claude-plugin/` 与 `hooks/claude-hooks.json`，Qoder 使用用户级 Skill / Commands / Agents，并把 Hook 合并进 `settings.json`。三侧完全隔离——安装到任一侧都不会修改另外两侧。

| 平台 | 清单 | 钩子配置 | 子代理位置 | 派发名 |
|---|---|---|---|---|
| ZCode | `.zcode-plugin/plugin.json` | `hooks/hooks.json`（`type: process`） | `~/.zcode/agents/` | `后端架构师`（中文裸名） |
| Claude Code | `.claude-plugin/plugin.json` | `hooks/claude-hooks.json`（`type: command`） | 插件内 `agents/` | `zcode-expert-system:后端架构师`（限定名） |
| Qoder Desktop | 用户级目录 + 部署清单 | `~/.qoder/settings.json` → `UserPromptSubmit` | `~/.qoder/agents/` | `后端架构师`（中文裸名） |

## 🏗️ 架构设计

### 系统概述

ZCode Expert System v3.2.5 是适配 ZCode、Claude Code 与 Qoder Desktop 的专家路由系统。它承载来自 [dsh-agency-agents](https://github.com/MichengAI/dsh-agency-agents) 的 331 位专家完整人格提示词，并融合 **Superpowers 工程能力体系** 与 **OpenSpec 规格驱动开发体系**。插件采用**两轴正交路由**：

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
│  已注册为宿主子代理             │
│  由专家中文显示名派发           │
└─────────────────────────────────┘
```

**派发流程**：

1. **任务分类** → 归类为 32 个一级大类之一（`zcode_expert_system.classify_task_detailed`）
2. **总经理路由** → 对应的领域总经理（`manager-<分类>`）
3. **专家粗筛** → 从该大类专家中选 Top-5 候选（Embedding 可用时用向量，否则词元重叠打分）
4. **语义精判** → **主控（会话模型）必须亲自做**；Python 的选择只是词元计数，不是语义判断。`semantic_selection_required=true` 时，主控必须查看 `top_candidates[].score_detail` 按业务语义定夺，必要时用 `build_dispatch_for_expert("<专家名>", task)` 改判
5. **专家派发** → `Agent(subagent_type="<专家中文显示名>")`，派发 prompt 首段硬声明流程契约优先于专家人格；`confidence < 0.5` 且 `selection_basis: heuristic` 时**阻断实施者派发**，先向老板澄清领域
6. **上下文传递** → 各阶段结果通过返回值传递

> **语义精判契约**：本插件故意不额外配置 LLM/Embedding 服务，依赖会话中正在运行的模型。`scripts/llm_client.py` 的 `_call_llm` 与 `embedding_client.py` 的 `get_embedding` 恒返回 `None`，粗筛退化为本地词元重叠。当 `semantic_selection_required=true` 时，主控必须复核 `score_detail`，判断 Python 排序是否只是词面巧合（如「飞书集成开发工程师」仅因描述含「登录」二字而胜出），必要时改判。`build_dispatch_for_expert` 传入错误的专家名时抛 `ValueError`，并附上 difflib 近似的候选名，不会静默降级。

**置信度护栏**（在生成派发计划时生效）：

| 条件 | 行为 |
|---|---|
| `confidence ≥ 0.5` 且 margin 足够 | 保留派发，附加 `semantic_recheck` 动作；主控必须复核 `top_candidates[].score_detail`。**不再同时置 blocking** |
| `confidence < 0.5` **且** `selection_basis: heuristic` | **实施者/分析者派发被阻断**（`action: blocked_low_confidence` + `plan.blocking` + `clarify_options`）；须先向老板澄清领域 |
| `confidence_detail.margin < 0.15` | 按低置信度处理——top1/top2 差距过小，胜者只靠声明序/微小分差 |
| `confidence < 0.5`，但语义复核已完成 | 允许派发，但附加 `semantic_recheck` 动作，主控必须复核 `top_candidates[].score_detail` |
| `confidence = 0` | `domain.no_signal = true`——此时的 category 只是 `business-support` 兜底，不构成真实领域判断 |

> `confidence` 含义已改为**绝对证据 × top1-top2 margin**：单 2 字关键词最高 0.5，真并列最高 0.45，长复合词/多证据才可能接近 1.0。不要再看单个关键词就当成高置信。

> **词边界护栏**：`返回500` 不会命中 `返回5000行数据`（尾部数字段后面再接数字，视为更长数字串的一部分）；零宽字符（ZWSP / BOM / 软连字符）在匹配前即被清洗，无法借此绕过 Bug 判定。

### 规模轴信号词（本轮修复）

| 修复点 | 说明 |
|---|---|
| **写操作信号** | `WRITE_SIGNALS` 补入「变更 / 改变」：「数据模型变更」「接口变更」判为 `large`，不再误判只读 |
| **搭建 / 建设（N-NEW-1）** | `WRITE_SIGNALS` 补入「搭建 / 建设」：「搭建一个博客系统」「建设一个数据中台」不再误判只读（此前仅登记于 `FEATURE_CONTEXT` 与 `NEW_BUILD_VERBS` 两张语境/守卫表，主表缺席——与「变更」缺陷同族）；`NEW_BUILD_VERBS` 同步补「建设」并提升为模块级常量供表间一致性校验锚定 |
| **复合执行形态（N-NEW-2）** | `WRITE_SIGNALS` 补入「处理一下 / 处理下 / 应急响应 / 事件响应 / 处置一下 / 处置下」：「处理一下这个报错」「JWT令牌泄漏应急响应处理」等执行任务不再误判只读。裸「处理 / 处置」刻意不收——「怎么处理这个报错」（询问）会失守；新词均不进 `HARD_WRITE`，评审请求（「帮我看看这个搭建方案合理吗」）仍判只读 |
| **混合任务主诉** | 按诉求出现的位置定主诉：「修复...bug，顺便增加日志」判 **Bug**；「增加修复后的日志采集功能」判**非 Bug** |
| **表间一致性校验** | `tests/test_p4_consistency.py` 新增三表一致性测试：`NEW_BUILD_VERBS` / `FEATURE_CONTEXT`（名词豁免外）的实施动词必须在 `WRITE_SIGNALS` 登记（或显式豁免留档）；历次实证缺陷动词（变更/改变/搭建/建设）为种子锚——再缺主表必红 |
| **领域路由补词** | `frontend-client` 词表补「博客」：「搭建一个博客系统」不再因泛化词噪声决胜误路由 hr（conf=0.0268） |
| **解释意图（批次 1）** | 「说明/解释/讲解/对比/是什么/区别」优先判只读；纯现象 Bug 不再单独成案，「说明 Bug 与失败的区别」不再误判 Bug |
| **修复自证（批次 1）** | 只有「修复」动词、没有第二个故障信号时不再判 Bug：「说明修复流程」「修复 README 错别字」不再进根因流程；「修复登录接口的鉴权 bug」仍判 Bug |
| **元语言引号（批次 1）** | 引号内 ≤12 字且不含实施动词的短标签不参与信号：「说明 “Bug/失败” 的判定」判只读；「修复「登录页」白屏」仍判 Bug |
| **margin 置信度（批次 2）** | `confidence = 绝对证据 × top1-top2 margin`：单 2 字关键词最高 0.5，真并列最高 0.45；不再“最长关键词唯一命中即 1.0” |
| **低置信度硬门（批次 2）** | `confidence < 0.5` 或 `margin < 0.15`：不产出 analyst/implementer/reviewer 派发行，只给 `blocked_low_confidence` + `blocking` + `clarify_options` |
| **高置信度不再假 blocking（批次 2）** | 高置信度只要求 `semantic_recheck` 动作，不再同时置 `blocking`；消除“阻断文案 + 派发行并存”的矛盾 |
| **IDF 与字段去噪（批次 3）** | 专家 prompt 读取上限 3000→800 字；`专家/测试/评估/审计/操作` 在相应语境下不参与专家排序；`score_detail` 暴露 `name_idf/desc_idf/prompt_idf` 与被过滤词 |
| **复合词补口（批次 3）** | 补 `搜索相关性 / 相关性评估 / 评测集 / 专家路由 / 安装注册 / 插件安装 / CLI 工具 / 工作流修复` 等复合词；不收裸「搜索/插件/安装」避免劫持 |
| **类目画像（批次 3-4）** | 代码支持读取 `config/categories.json` 的 `description` 作为类目语义画像；**32 类已全部补齐**，不再只有 `frontend-client` |
| **关键词长度权重（批次 4）** | 2 字 1.0 / 3 字 1.5 / 4 字 2.0 / 5+ 字按 0.2 递增（上限 3.0）；「客户成功流程」能压过「客户成功」，「等保合规标书」能压过「等保」 |
| **路由评估集（批次 3-4）** | `tests/test_routing_eval.py`：**64 条正例（32 类 × 2）+ 5 条 hard negative + 9 条专家 top1**；门槛 top1 ≥0.95、hard-negative 正确/阻断 ≥0.8 |
| **派发证据门禁** | `workflow_check` 解析账本 `## Dispatches` 与计划 `## Review` 身份，新增 7 项检查：无 implementer 派发、孤儿 report、L0 无 reviewer、同名 reviewer、计划/账本身份不一致、删账本伪清理等均 FAIL；`tests/test_dispatch_evidence.py` 37 条专项测试 |

**残余风险留档（实测记录，均为可接受偏置）**：

- **误伤族**（readonly→light，符合「宁可偏重」偏置——误走一趟流程的代价低于漏判跳过门禁）：「采纳大家的建设性意见」「事件响应时间的P95统计怎么做」「这个搭建方案需要多少钱」「搭建环境教程」类名词短语。守护测试已锁定评审反例（「帮我看看这个搭建方案合理吗」「搭建方案是什么」仍 readonly）。
- **覆盖缺口**：「处理这个安全隐患」「处置这个安全事件」仍判只读——裸「处置 / 处理」误伤面大（名词语境「危废处置资质」「异常处理」），本轮只收「一下/下」复合形态；裸词修复待后续决策。
- **已知同构缺口**：`NEW_BUILD_VERBS` 中「做一个 / 做个 / 新增」字面不在 `WRITE_SIGNALS` 且无单字子串覆盖——实测「做一个登录页面」「新增日志功能」仍误判只读（与「搭建」缺陷完全同形态），已在一致性测试中显式豁免留档，修复待决策。

### 角色 × 专家矩阵（工作流角色）

工作流角色是**职责**，331 位专家是**领域能力**，二者正交组合：

| 角色 | 是否可派 | 核心约束 |
|---|---|---|
| **编排者（Orchestrator）** | ❌ 主控自任 | 唯一状态写者、亲跑验证、裁决记账 |
| **实施者（Implementer）** | ✅ 域专家 | 禁派子代理；不得超 brief 范围；TDD |
| **审查者（Reviewer）** | ✅ **异域专家** | 只读；不采信自评；必须给出 spec 符合性 + 代码质量双结论 |
| **调查者（Investigator）** | ✅ 域专家 | 只读；结论带 `file:line` |
| **分析者（Analyst）** | ✅ 域专家 | 只读分析；四段式「现象→原因→影响→建议」；领域判断不留主控；仅查看类工具，禁止增删改 |

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
| **P3** | 计划文档 `## Bug Investigation` / `## Baseline` / `## Review` / `## Rulings` / `## Integration Verification` | 根因、基线、审查、裁决、交付重测 | 随仓库 |
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
python "${CLAUDE_PLUGIN_ROOT:-${ZCODE_PLUGIN_ROOT:-$QODER_PLUGIN_ROOT}}/skills/zcode-expert-system/scripts/workflow_check.py" --change <change> --plan <plan.md> --scale medium
```

核对项：环境探测 / 规格产物 / 计划必备段 / 任务标题格式 / 占位符 / 双账本对齐 / 基线双写 / 账本身份 / 三元对齐 / 独立性标记 / Rulings 持久化 / 集成后重测 / 归档完成度。

退出码：`0` 无 FAIL，`1` 有 FAIL（不得进下一阶段）。

`--expect-archive` 支持归档后核验：active 的 `openspec/changes/<change>/`
已移走但 archive 副本存在时，S2 会切到
`openspec/changes/archive/YYYY-MM-DD-<change>/` 检查产物，不再永久
`S2.CHANGE_DIR` FAIL。

> **归档前必须校验 `tasks.md` 勾选**：存在未勾选任务时拒绝归档（`completedTasks == totalTasks`，只认 `x`/`X`）。Hook 每轮也会检测未完成任务并告警，不依赖主控自觉。

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

CLI 只暴露两个命令：

```bash
zcode-expert-system install
zcode-expert-system uninstall
```

### install

```bash
npm install -g zcode-expert-system
zcode-expert-system install
```

会弹出多选菜单：

```text
ZCode
Claude Code
Qoder
```

用 `Space` 选中一个或多个目标，`Enter` 确认。非交互终端默认 ZCode + Claude Code；
Qoder 需交互勾选，或脚本化使用 `--targets`：

```bash
zcode-expert-system install --targets zcode
zcode-expert-system install --targets claude-code
zcode-expert-system install --targets qoder
zcode-expert-system install --targets zcode,claude-code,qoder
```

`--dry-run` 只打印计划动作，不改动磁盘。

从源码仓库安装时，`npm install` 只安装依赖，**不会**在 `node_modules/.bin`
里生成 `zcode-expert-system` 可执行文件。请直接经 `node`（或 `npx .`）运行 CLI：

```bash
git clone https://github.com/wutian122/zcode-expert-system.git
cd zcode-expert-system
npm install                 # 只装依赖
node bin/cli.js install     # 等价于 npx . install
node bin/cli.js uninstall   # 等价于 npx . uninstall
```

> **破坏性变更：** CLI 已收敛为只有 `install` / `uninstall` 两个命令。
> 平台专用子命令（`cc-install`、`cc-uninstall`、`qoder-install`、
> `qoder-uninstall`、`qoder-status`、`version`、`help`）与
> `npm run cc:install` / `npm run qoder:install` 别名均已移除；
> 平台选择改在 `install` / `uninstall` 的菜单里完成，脚本化场景用
> `--targets` / `--zcode --claude-code --qoder`。

各平台部署内容：

| 宿主 | 安装内容 |
|---|---|
| ZCode | 插件缓存 + 技能（`~/.zcode/skills/zcode-expert-system`）+ 命令 + hooks + 363 个 Agent + 插件注册 + 图标 marketplace |
| Claude Code | 本地 marketplace `zcode-local` → `claude plugin install` + 363 个 Agent（插件根 `agents/`） |
| Qoder Desktop | 用户级 `~/.qoder/skills`、`~/.qoder/commands/wf`、`~/.qoder/agents`，并合并 `~/.qoder/settings.json` 的 `UserPromptSubmit` Hook |

三平台部署都带齐同一套运行时组件：`scripts/workflow_check.py`（机械门禁核对，
含 dispatch 派发证据门禁）、`config/categories.json`（32 类 description 画像）、
`config/experts.json`、`config/workflow.json`、`templates/`、`references/`、
`hooks/`、`SKILL.md` 与三个根级 Python 入口。Claude Code 额外带 `context/`、`bin/`；
Qoder 额外合并 `UserPromptSubmit` Hook。

安装器在复制后会**校验部署副本**，缺任一运行时组件即非零退出——残件不会报「完成」：

```text
✅ ZCode 技能部署校验通过：workflow_check / categories(32 类) / templates / references 均在位
```

> Claude Code 注册依赖 `claude` CLI：安装器会构建本地 marketplace，并执行
> `claude plugin marketplace add` / `claude plugin install`。只复制文件而不注册，
> `/plugin` 不会显示插件。未检测到 CLI 时仅复制到旧缓存并明确告警——那份副本
> **不会**被 Claude Code 加载。安装成功后执行 `/reload-plugins` 或重启 Claude Code。

`--dry-run` 会执行同一套源树预检（缺 `templates/`、`references/`、
`scripts/workflow_check.py` 或类目 description 时非零退出），但只打印计划动作，
不会声称「安装完成」。Claude Code 侧另有一道 fail-closed：插件已注册但
`settings.json.enabledPlugins` 无本条时非零退出，并提示先用 `/plugin` 启用
（或 `/reload-plugins` 后重试），而不是打印成功横幅。预检还会拒绝
`.claude-plugin/plugin.json` 的 `agents` 字段：Claude Code 要求该字段必须是
单个 `.md` 路径，目录声明会让整个插件加载失败；363 个专家靠 `agents/`
目录的约定式扫描注册。

安装后重启所选宿主（Agent 清单在会话启动时加载）。

### uninstall

```bash
zcode-expert-system uninstall
```

会弹出同样的多选菜单：

```text
ZCode
Claude Code
Qoder
```

已检测到的宿主默认预选。按 `Enter` 删除所选插件文件、命令、Agent 和
Hook/注册信息：

- **Claude Code**：先注销插件、移除 `zcode-local` 市场注册与目录，再删除本插件的
  两个缓存子目录（`cache/zcode-local/zcode-expert-system` 与旧版
  `cache/claude-plugins-official/zcode-expert-system`），不会触碰其他插件缓存。
  若 `claude` CLI 不可用或命令失败，回退为直接编辑 `installed_plugins.json`、
  `settings.json.enabledPlugins` 与 `known_marketplaces.json`（只删本插件条目）；
  注册仍有残留时非零退出，且不打印「卸载完成」。
- **Qoder**：只删本插件拥有的文件（部署清单；清单丢失时按
  `<!-- zcode-expert-system:qoder-adapter -->` ownership marker 精确回退）。
  用户同名命令/子代理一律保留，Hook 只删本插件那一条 entry。备份与运行时
  context 默认保留，`--purge` 才删除。
- **ZCode**：严格按清单删除（绝不按前缀扫），覆盖前先备份旧技能目录；
  `skills/zcode-expert-system.bak-*` 只有**不含用户文件**时才自动清理，
  含用户自建文件的备份保留并打印路径；`--purge` 才连同这些备份与
  `~/.zcode/expert-system/context/` 一起删除。

非交互终端沿用历史默认：Claude Code + ZCode。

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

**运行时上下文按宿主隔离**：

| 宿主 | 上下文目录 |
|---|---|
| ZCode | `~/.zcode/expert-system/context/` |
| Claude Code | `~/.claude/expert-system/context/` |
| Qoder | `$QODER_HOME/expert-system/context/` |

可用 `ZCODE_EXPERT_CONTEXT_DIR` 覆盖；测试套件每个用例都指向临时目录，
不会再写入真实用户上下文。

**专家名称可见性**：派发计划包含 `display_name` / `display_label`；主控必须先在
会话中显示 `正在调用专家：<专家名>`，并给 `Agent` / `Task` 传
`description = "专家：<专家名>"`。计划、派发单与只读审计锚点都携带同一专家名。

## 🚀 使用方法

### 调用专家体系

在任意受支持宿主会话（ZCode / Claude Code / Qoder Desktop）中直接下达专业任务——
`UserPromptSubmit` 钩子会自动注入路由规则，技能按领域关键词触发。

实际存在的入口：

| 入口 | 作用 |
|---|---|
| `Skill(zcode-expert-system)` | 以任务描述调用技能 |
| `/wf:triage <任务>` | 双轴分诊：规模 + 领域路由一次产出（只读/轻量/中任务/大任务/Bug；只读派 analyst，仅查看类工具） |
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

安装后三个宿主均可派发 **363 个子代理**：

| 宿主 | 总经理 | 专家 | 位置 | 派发方式 |
|---|---|---|---|---|
| ZCode | 32 | 331 | `~/.zcode/agents/` | `Agent(subagent_type="后端架构师")` |
| Claude Code | 32 | 331 | 插件内 `agents/` | `Agent(subagent_type="zcode-expert-system:后端架构师")` |
| Qoder Desktop | 32 | 331 | `~/.qoder/agents/` | `Agent(subagent_type="后端架构师")` |

> **专家名写错时的表现**：`build_dispatch_for_expert` 找不到精确匹配会抛 `ValueError`，
> 并在错误信息里给出 difflib 近似候选名，不会静默选一位"差不多"的专家。

> 注意：总经理用 **slug**（`manager-<分类>`）派发，因为各平台安装链写入部署文件的
> `name:` 就是 slug；专家用**中文显示名**派发。两者混淆会导致 `Agent` 调用找不到代理。
> Claude Code 额外使用插件限定名 `zcode-expert-system:<专家名>`。

> `subagent_type` 填**中文显示名**（专家 md 的 `name:` 字段）。
> 若名字不在会话清单中，回退为读取该专家提示词、代入其人格执行。

⚠️ **改动子代理文件后必须重启对应宿主** —— Agent 清单是会话启动时的快照，
中途新增或修改不会生效。

## 📁 目录结构

```
zcode-expert-system/
├── .zcode-plugin/plugin.json          # 插件清单
├── .claude-plugin/plugin.json         # Claude Code 插件清单
├── SKILL.md                            # 技能入口（三平台共用）
├── README.md / README_CN.md            # 英文 / 中文文档
├── zcode_expert_system.py              # 域轴（32 大类 → 331 专家）
├── zcode_dev_workflow.py               # 规模轴（分诊 → 阶段 → 派发计划）
├── skill_entry.py                      # 技能调用包装层
├── package.json                        # npm 包配置
├── src/
│   └── auth/                           # jwt-auth-system（openspec 在建；不随插件分发 — UNPACKED_COMPONENTS）
├── scripts/
│   ├── install.js                      # 统一部署 / 卸载（ZCode + Claude + Qoder 目标）
│   ├── install-claude-code.js          # Claude Code 部署（预检 + 备份 + 回滚）
│   ├── cc-uninstall.js                 # Claude Code 卸载
│   ├── install-qoder.js                # Qoder 用户级部署 / 状态 / 卸载
│   ├── workflow_check.py               # 门禁机械核对（+ --self-check）
│   ├── openspec_engine.py              # OpenSpec change/规格引擎
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
├── tests/                              # 回归测试（pytest，817 passed / 1 skipped）（801 基线 + 9 项三平台部署完整性守卫 + 7 项安装/卸载安全守卫）
├── hooks/
│   ├── hooks.json                      # 钩子配置（ZCode 标准 schema）
│   ├── claude-hooks.json               # 钩子配置（Claude Code 格式）
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

期望基线：**817 passed, 1 skipped** —— 801 条是 v3.2.5 运行时基线
（Claude 注册 + S1/P3 + 路由批次 1-4 + 派发门禁），另加 9 条三平台部署完整性
守卫（workflow_check/categories 校验、marketplace 与 Qoder 技能组件、卸载对称性），
再加 7 条安装/卸载安全守卫（`--zcode` 卸载保留含用户文件的备份、仅 `--purge`
才删、无 `claude` CLI 时清理幽灵注册、Claude dry-run 预检且不报「安装完成」、
`enabledPlugins` 缺失即 fail-closed）。

> 817 是**完整开发树**的验证基线。GitHub 运行时发布按你的口径只提交运行时文件，
> 不新增/更新 `tests/` 与 `docs/`；因此只取运行时文件的 clone 不会复现这个数字。
> 发布前已在完整开发树上本地跑过全量测试。

> 关于 `src/auth/`：JWT 认证模块（`jwt-auth-system` OpenSpec change）尚在建设中，由
> `tests/test_auth_login.py` 覆盖。其实现选择是刻意为之：
>
> - **口令哈希**：PBKDF2-HMAC-SHA256、100 000 轮、16 字节随机盐，存 base64(`salt||dk`)
>   （bcrypt 仅作为文档记录的备选，不是依赖）
> - **refresh token**：用 `secrets.token_urlsafe(32)` 生成（256 位熵），不再用
>   `sha256(user_id:time_ns)` 这类可预测派生；库中**只存 sha256 哈希**，不存令牌明文
> - **过期时间**：`expires_at` 以 **ISO 8601 字符串**存储，用 `datetime.fromisoformat`
>   解析（此前的 `float(ISO串)` 必然抛错）
> - **JWT 验签**：先解析 header，白名单校验 **`alg=HS256` 与 `typ=JWT`**，通过后再验签名

## 📄 许可证

本项目基于 [MIT 许可证](LICENSE) 开源。

## 🔗 引用来源与开源依赖

本项目在以下开源项目与能力体系的基础上进行了 ZCode / Claude Code / Qoder 平台适配与工程化改造：

| 来源 | 用途 | 项目地址 |
|---|---|---|
| **dsh-agency-agents** | 331 位专家完整人格提示词（专家库来源） | https://github.com/MichengAI/dsh-agency-agents |
| **Superpowers** | 工程能力体系（brainstorming、writing-plans、sdd、tdd、verification、code-review、finishing 等能力） | 待项目方补充 GitHub 地址 |
| **OpenSpec** | 规格驱动开发体系（change 提案、规格同步、归档工作流） | 待项目方补充 GitHub 地址 |

本项目在此基础上增加了三平台适配与工程化改造：三层路由架构（分类 → 总经理 → 专家）、两轴正交路由（规模轴 + 域轴）、九阶段受控工作流、机械门禁核对、七态状态机、证据分级与冲突裁决。

## 🙏 致谢

专家提示词来自 [dsh-agency-agents](https://github.com/MichengAI/dsh-agency-agents) 开源项目，并在此基础上做了 ZCode / Claude Code / Qoder 平台适配与工程化改造（三层路由架构、领域总经理任务分解、动态专家派发）。

## 📞 联系方式

如有问题或建议，请通过 GitHub Issues 提交。

---

**ZCode Expert System v3.2.5** - 让 AI 专家协作更智能 🚀
