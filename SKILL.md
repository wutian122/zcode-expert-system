---
name: zcode-expert-system
description: Use when a task spans design, development, security, marketing, testing, research, finance, legal, healthcare or any other professional domain and needs routing to a specialist, or when the task is a software engineering task that needs a disciplined workflow (requirements → spec → plan → TDD → review → delivery). 331 experts in 32 top-level categories with two-axis routing (scale → workflow stages, domain → expert), nine-stage dev workflow with gates and evidence. Also use when the user says 专家 / 会诊 / 多专家 / 专业分析 / 任务路由 / 任务分解 / 工作流 / 研发流程.
version: "3.2.6"
---

# ZCode Expert System v3.2.6

**运行平台**：ZCode / Claude Code / Qoder Desktop。宿主只影响安装目录与派发名格式，
两轴路由、九阶段门禁证据链与 `/wf:*` 命令协议完全一致。

**两轴正交路由**：

| 轴 | 回答 | 实现 |
|---|---|---|
| **规模轴** | 走不走流程、走多长 | `zcode_dev_workflow.py` → 只读/轻量/中/大/Bug 五类，决定九阶段裁剪 |
| **域轴** | 派哪一位专家 | `zcode_expert_system.py` → 32 类 → 331 专家 |

**先规模后域**：规模决定阶段裁剪，域决定 `subagent_type`。

---

## 一、入口判定（任何任务都先走这四步）

| # | 步骤 | 命令 / 动作 |
|---|---|---|
| 1 | **规模分诊** | `${CLAUDE_PLUGIN_ROOT:-${ZCODE_PLUGIN_ROOT:-$QODER_PLUGIN_ROOT}}/skills/zcode-expert-system/zcode_dev_workflow.py triage "<任务>" --files N` |
| 2 | **说出口** | 「老板，任务分类结果：只读/轻量/中任务/大任务/Bug」——不能不说 |
| 3 | **域路由**（**所有规模必做，readonly 亦不例外**） | `triage` 已双轴合一——规模与领域路由一次产出；亦可 `zcode_expert_system(task)` 取 `category` + `top_candidates` + `score_detail` |
| 4 | **语义精判（主控亲自做）** | 见下；`semantic_selection_required` 为 true 时**必须**自己定夺 |
| 5 | **按裁剪表执行** | 读 `references/stage-<S*>.md`，逐阶段过门禁 |

### 语义精判：主控不可省略的第 4 步

`zcode_expert_system()` 的 `selected_expert` **不是最终结论**。本插件不配外部
LLM/Embedding（刻意设计，依赖会话模型），所以 Python 的挑选只是词元计数：

```python
r = zcode_expert_system("实现用户登录接口")
r["semantic_selection_required"]  # True  → 语义精判还没做
r["selection_basis"]              # "heuristic" → 只是词面匹配
r["top_candidates"][0]["score_detail"]
# {'name_hits': 0, 'desc_hits': 1, 'matched_in_desc': ['登录'], ...}
#  ↑ 首选专家名称一个词都没中，只靠描述里恰好出现「登录」二字
```

**主控必须**：看 `score_detail` 判断是不是词面巧合 → 按业务语义定夺 →
需要改判时用 `build_dispatch_for_expert("<专家名>", task)` 生成派发单。

**这是模型的职责，不是 Python 的。** 只有模型能判断「登录取数接口」该给后端架构师
还是飞书集成专家——靠「描述里出现过哪两个字」永远判不准。

### 低置信度处置（第 4 步后必查）

`zcode_expert_system(task)` 返回 `confidence` / `confidence_detail` / `alternatives` / `routing_warning`：

`confidence` 不再是“词面强度”，而是**绝对证据 × top1-top2 margin**：单 2 字关键词最高 0.5，真并列最高 0.45，长复合词/多证据才可能接近 1.0。

| confidence | 含义 | 动作 |
|---|---|---|
| ≥ 0.5 | 证据足够 | 保留派发，但**必须**执行 `semantic_recheck`（复核 `score_detail`） |
| < 0.5 | 证据不足/并列/单弱词 | **阻断派发**，plan 含 `blocking` + `clarify_options`；先澄清领域 |
| `confidence_detail.margin < 0.15` | top1/top2 差距过小 | 按低置信度处理 |
| = 0.0 | 无信号，落默认 `business-support` | **必须澄清**，禁止拿 `business-support` 专家硬套 |

`selected_expert` 为 `None` 时**不得自行挑第一个候选**——那等于绕过相关性判断。按 `routing_warning` 向老板澄清后再派。

**高置信度只要求复核，不再同时置 blocking**：`blocking` 与派发行并存是旧契约的自相矛盾。低置信度必须 `blocking` 且不产出 analyst/implementer/reviewer 派发行。

**所有任务（含只读与机械任务）都必须完成两轴分诊，不得跳过域路由**（W10）。只读任务派 **analyst**（领域专家）只读分析，不得由主控凭通识自行分析；机械任务一旦需要领域解释或决策，必须升级为派专家。**复核/审查任何产出（含主控自己的产出）属于领域判断，必须派独立专家（实施者≠审查者），不得以「机械核对」名义自审。**

判据：`config/workflow.json` 是唯一声明源。阶段、门禁、产物、证据级只在那里声明一次，本文件与 `scripts/workflow_check.py` 都从它读取，不得各自手写。

---

## 二、九阶段与门禁

| 阶段 | 名称（= `workflow.json` 的 `name`） | 简称（`short`） | 主组件 | 门禁 | 证据级 | 停老板 |
|---|---|---|---|---|---|---|
| **S0** | 需求接收与任务分诊 | 需求分诊 | — | G0 | P4 | — |
| **S1** | 需求澄清与方案设计 | 设计 | zes-brainstorming（已内置） | G1 | — | ✅ |
| **S2** | OpenSpec 规格规划 | 规格 | openspec_engine.py（内置） | G2 | P2 | ✅ |
| **S3** | 实施计划制定 | 计划 | zes-writing-plans（已内置） | G3 | P3 | — |
| **S4** | 环境准备与基线测试 | 环境 | stage-S4-env-baseline.md（内置） | G4 | P3+P4 | 基线红时 |
| **S5** | 代码实施与多 Agent 协作 | 实施 | zes-sdd + zes-tdd（已内置） | G5 每任务 | P4→P2 | — |
| **S6** | 验证审查 | 验证审查 | zes-verification + zes-code-review（已内置） | G6+G7 | P3 | — |
| **S7** | 交付与集成 | 交付 | zes-finishing（已内置） | G8a | P3 | ✅ |
| **S8** | 规格同步与归档 | 归档 | openspec_engine.py（内置） | G8b | P2 | ✅ |

> 名称列与 `config/workflow.json` 的 `stages[].name` 逐字一致（消费方按名称 join
> 账本 `## Current Phase` 与报告引用时会用到）。简称列是 `stages[].short`，
> 供门禁标签派生（`workflow_check.gate_label()`）。
>
> 门禁编号修正：源规范 G0–G8 与九阶段非一一对应（S6 吃 G6+G7，S7/S8 共用 G8 且 S7 无出口门禁）。本体系拆为 **G8a（交付后重测）/ G8b（同步归档）**。

### 规模裁剪（`workflow.json` → `trim_matrix`）

| 规模 | 走哪些阶段 |
|---|---|
| 只读 | S0（双轴分诊）→ 派 analyst → 输出 → 结束 |
| 轻量 | S0 必（双轴分诊）→ S1 简 → S3 简 → S4 必 → S5 必（TDD 不可跳）→ S6 简 → S7 必 → S2/S8 条（当前等价于必，见 workflow-fusion-design.md 第三节） |
| 中/大任务 | 九阶段完整 |
| Bug | 先走 Bug 专项（根因→双确认→TDD），S1/S2/S3/S8 视影响范围 |

**规模只能升级不能降级。**

### Bug 专项方法（zes-systematic-debugging 核心，详见 `zes-systematic-debugging` 技能）

**铁律：无根因不修复；无失败测试不修码。**

- **Phase 1 根因调查**（动手前必做）：①仔细读报错与堆栈（行号/路径/错误码）；②稳定复现（不能复现就收集更多数据，不猜）；③查最近变更（git diff/新依赖/配置变更）；④多组件系统在各层边界记录进出数据，定位哪层断；⑤沿调用链回溯到坏值源头（root-cause-tracing），**在源头修不在症状处修**
- **Phase 2 模式分析**：找同仓相似的工作代码对照，逐条列差异（勿轻视任何差异），理清依赖与假设
- **Phase 3 假设与验证**：陈述单一假设「我认为 X 是根因因为 Y」→ 最小化测试（一次一个变量）→ 验证；失败则换**新假设**，不得在旧修复上叠加
- **Phase 4 实施**：先写失败测试（reproduce）→ 单一修复（禁顺手重构）→ 验证（测试过+其他测试不破+问题解决，verification-before-completion 才可声明成功）
- **3 连败即质疑架构**：3 次修复仍失败，停止继续修——「每次修复都在新地方暴露新问题」是架构信号，与老板讨论是否重构，而非第 4 次尝试
- **双确认门禁**（老板专项）：①方案等老板选 A/B/C，未选不改码；②选定后再确认执行（"好的/OK"不算确认，须"执行/开始/修"等明确动词）
- **红旗信号**（出现即回 Phase 1）：「先快速修了再说」「试试改 X 看行不行」「跳过测试手动验证」「我大概知道是哪」——猜测式修复是失败之母
- **P3 证据（强制）**：上述入口分诊、9 问根因、假设、方案、双确认、RED、red-green、全量回归必须同步到计划文档 `## Bug Investigation`，不能只留在会话或 P4 workspace

---

## 三、七态状态机（唯一）

`PENDING → IN_PROGRESS → REVIEW → NEEDS_FIX → DONE`，加 `BLOCKED`、`PARKED`。

**SDD 的四态（DONE / DONE_WITH_CONCERNS / NEEDS_CONTEXT / BLOCKED）是边标签，不是状态**——它们进入状态机后立即转化为状态转移。

| 关键转移 | 触发 |
|---|---|
| `IN_PROGRESS → REVIEW` | 实施报 DONE / DONE_WITH_CONCERNS，且变更集非空、report 含命令输出退出码 |
| `REVIEW → DONE` | 审查给 spec ✅ + 质量通过，且**主控亲跑全量测试见绿** |
| `NEEDS_FIX → PARKED` | 5 轮修复仍 open，主控裁决 |
| **`DONE → NEEDS_FIX`** | **归档前回归发现破坏**（源规范缺失的边，必须有） |

**唯一写者 = 主控。任何子代理不得写状态。唯一载体 = ledger 的 Tasks 表。**

不变量：一任务同时只有一状态；`DONE` 当且仅当 tasks.md 为 `- [x]`；非 DONE 一律 `- [ ]`（含 PARKED）。

---

## 四、角色 × 专家 二维派发

工作流四角色是**职责**，331 专家是**领域能力**，正交组合：

```python
Agent(
  subagent_type = "<专家中文名>",        # 域：从 zcode_expert_system 取
  prompt = "<references/roles/<role>.md 契约原文>\n---\n<task brief 路径>"
)
```

| 角色 | 可否派 | 核心约束 |
|---|---|---|
| Orchestrator | ❌ 主控自任 | 唯一状态写者、亲跑验证、裁决记账 |
| Implementer | ✅ 域专家 | **禁派子代理**；不得超 brief 范围；TDD |
| Reviewer | ✅ **异域**专家 | 只读；不采信自评；**必须给 spec + 质量双结论** |
| Investigator | ✅ 域专家 | 只读；结论带 `file:line` |
| Analyst | ✅ 域专家 | 只读分析；四段式「现象→原因→影响→建议」；领域判断不留主控 |

**流程契约优先于专家人格**——派发 prompt 首段必须硬声明这一点，否则架构类专家会自己重新设计架构。

**专家名称可见性**：每次派发前，主控先在会话中显示一行
`正在调用专家：<专家中文名>`；`Agent` / `Task` 的 `description` 使用
`专家：<专家中文名>`。三平台统一使用中文裸名/限定名的 `subagent_type`，
但可见标题必须显示专家名，不得只显示 Agent 或 general-purpose。

### Reviewer 独立性（三重保证）

331 专家里只有 1 位「代码审查员」，独立性不能靠"类型多"：

1. `type ≠` 不与 Implementer 同专家
2. `instance ≠` 独立派发、独立上下文
3. `input 隔离` 只给 brief / report / 变更集三件

必须落盘标记：`independence: L0`（独立）/ `L1`（主控自审降级，须声明）/ `L2`（无审查 → **禁止交付**）。

---

## 五、证据分级（防丢的关键）

| 级 | 位置 | 内容 | 生命周期 |
|---|---|---|---|
| **P1** | 文件快照哈希 或 git commit | 实际改了什么 | 交付后归档 |
| **P2** | `openspec/changes/<n>/tasks.md` + 计划文档 `## Rulings` | 完成度、ADR 决策 | 归档永久 |
| **P3** | 计划文档的 `## Bug Investigation` / `## Baseline` / `## Review` / `## Rulings` / `## Integration Verification` | 根因、基线、审查、裁决、交付重测 | 随仓库 |
| **P4** | `.superpowers/sdd/<plan>/` | ledger / brief / report / 快照 | **终审后删，删前必须导出 P3** |

> **铁律：P4 未导出，禁止删 workspace。** 否则基线、裁决、重测记录整体消失——这是源规范最危险的两处丢失。

---

## 六、无 Git Worktree 的并行模型（老板决策）

本体系**不使用 Git Worktree**。守恒关系必须讲清：

| 保留的并行 | 取消的并行 |
|---|---|
| ✅ 只读调查并行（多个无关失败分域取证） | ❌ **多 Agent 实施并行** |
| ✅ 审查并行（多位 Reviewer 同批任务，只读无冲突） | — |

**原因**：没有隔离工作区就不能有两个写者。实施**永远串行**——这是守恒，不是保守。

### git 降为可选增强层

| 探测 | 变更集来源 | 收尾 |
|---|---|---|
| 有 git | `review-package` 的 `BASE..HEAD` diff | finishing 三选一 |
| 无 git（默认） | **文件快照 sha256 差集 + 变更文件全文** | 改动清单验收 |

**快照机制**：派发前记录任务 Files 清单每个文件的 sha256 → 实施后重新计算 → 差集=新增/修改/删除。
**变更集由主控独立计算，不由实施者自述**——这是无 git 环境下仍可信的关键。

不擅自为老板的项目 `git init`。

---

## 七、冲突消解（关键 10 条，`workflow.json` → `conflict_rulings`）

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

---

## 八、机械核对（不靠自觉）

```bash
python "${CLAUDE_PLUGIN_ROOT:-${ZCODE_PLUGIN_ROOT:-$QODER_PLUGIN_ROOT}}/skills/zcode-expert-system/scripts/workflow_check.py" --change <change> --plan <plan.md> --scale medium
```

核对项：环境探测 / 规格产物 / 计划必备段 / 任务标题格式 / 占位符 / 双账本对齐 / 基线双写 / 账本身份 / 三元对齐 / 独立性标记 / Rulings 持久化 / 集成后重测 / 归档完成度。

退出码：`0` 无 FAIL，`1` 有 FAIL（不得进下一阶段）。

> **纯 Markdown 检查表一定会被跳过，所以必须机械可验。**

---

## 九、域路由（既有能力，保留）

### 32 个一级大类

| 大类 | 专家数 | 代表专家 |
|---|---|---|
| frontend-client | 8 | 桌面应用工程师、前端开发者、国际化工程师、移动应用开发者、移动发布工程师 |
| backend-architecture | 18 | API 平台工程师、后端架构师、CMS 开发者、钉钉集成开发工程师、Drupal 性能工程师 |
| data-database | 8 | AI 数据修复工程师、数据工程师、数据可视化工程师、数据库优化师、数据库可靠性工程师 |
| devops-operations | 7 | 自主优化架构师、DevOps 自动化师、FinOps 工程师、故障响应指挥官、IT 服务经理 |
| ai-llm | 9 | AI 工程师、邮件智能工程师、LLM 后训练工程师、多智能体系统架构师、Prompt 工程师 |
| embedded-iot | 6 | 嵌入式固件工程师、嵌入式 Linux 驱动工程师、FPGA/ASIC 数字设计工程师、物联网设备工程师、IoT 方案架构师 |
| network-engineering | 3 | 国内网络架构工程师、国内网络工程师、网络工程师 |
| engineering-quality | 10 | 代码审查员、代码库入职引导工程师、开发者工具工程师、Git 工作流大师、最小变更工程师 |
| security-compliance | 19 | 身份与访问管理工程师、隐私工程师、安全工程师、Solidity 智能合约工程师、威胁检测工程师（工程侧） |
| data-testing | 15 | ATS 简历校验架构师、PDF 引擎架构师、通用文档编译器架构师、文档生成器、模型 QA 专家 |
| design-creative | 14 | 品牌守护者、图像提示词工程师、包容性视觉专家、Persona 走查专家、UI 设计师 |
| marketing-growth | 45 | AEO 基础架构师、智能搜索优化师、AI 引文策略师、应用商店优化师、百度 SEO 专家 |
| paid-media | 7 | 付费媒体审计师、广告创意策略师、社交广告策略师、PPC 竞价策略师、程序化广告采买专家 |
| sales-customer | 10 | 客户拓展策略师、销售教练、赢单策略师、Discovery 教练、售前工程师 |
| business-strategy | 18 | 首席执行官（CEO）、首席营销官（CMO）、幕僚长（Chief of Staff）、首席运营官（COO）、首席产品官（CPO） |
| healthcare | 7 | 循证医学研究员、医疗创新战略顾问、医疗系统治理顾问、老年照护顾问、医疗客服专家 |
| supply-chain | 5 | 供应链采购策略师、服装工厂规划工程师、库存预测专家、物流路线优化师、供应商评估专家 |
| legal-compliance | 6 | 合同审查专家、制度文件撰写专家、数据隐私官、律所计费与工时专家、律所客户接案专家 |
| hr | 7 | 绩效管理专家、招聘专家（HR 全流程）、企业培训课程设计师、HR 入职管理专家、组织心理学家 |
| finance-tax | 14 | 簿记与财务总监、财务分析师、财务预测分析师、FP&A 分析师、金融风控分析师 |
| academic-research | 10 | 人类学家、地理学家、历史学家、叙事学家、心理学家 |
| government-public | 1 | 政务数字化售前顾问 |
| business-support | 6 | 鉴定评估师、酒店宾客服务专家、养殖档案核对员、个人成长导师、房地产经纪助手 |
| data-knowledge | 2 | 研究证据综合专家、ZK 管家 |
| game-dev | 21 | Blender 插件工程师、经济系统设计师、游戏音频工程师、游戏设计师、Godot 游戏脚本开发者 |
| spatial-computing | 6 | macOS Metal 空间工程师、终端集成专家、visionOS 空间工程师、XR 座舱交互专家、XR 沉浸式开发者 |
| gis | 13 | 三维场景开发者、GIS 分析师、BIM/GIS 专家、地图制图设计师、无人机实景测绘专家 |
| project-management | 9 | 实验追踪员、Jira工作流管家、会议纪要专家、项目牧羊人、工作室运营 |
| product-management | 6 | 行为助推引擎、开发者体验工程师、反馈分析师、产品经理（PM）、Sprint 排序师 |
| customer-support | 10 | 客户服务、客户成功经理、零售退货专家、数据分析师、高管摘要师 |
| language-translation | 2 | 语言翻译专家、技术翻译专家 |
| agent-governance | 9 | 身份信任架构师、智能体编排者、自动化治理架构师、数据整合师、身份图谱操作员 |

### 域路由执行流程

1. **粗筛**（Python）：从该大类专家中选出 Top 5 候选，并给出每个候选的 `score_detail`
2. **语义精判**（**主控亲自做**）：见下方「语义精判契约」
3. **派发**：`Agent(subagent_type="<专家中文显示名>")`

#### 🔴 语义精判契约（必读）

**本插件不额外配置 LLM/Embedding 服务**——这是刻意设计，不是缺陷：插件运行在宿主会话内，
会话里正在跑的模型就是可用模型，再接外部 LLM 既重复又要凭据要花钱。
所以 `scripts/llm_client.py` 的 `_call_llm` 与 `embedding_client.py` 的 `get_embedding`
恒返回 `None`，粗筛退化为本地词元重叠。

**由此产生一个必须由主控承担的责任**：

| 返回字段 | 含义 | 主控该做什么 |
|---|---|---|
| `semantic_selection_required: true` | 语义精判**尚未发生** | **必须自己复核**，不能直接采用 `selected_expert` |
| `selection_basis: heuristic` | Python 的选择只是词元计数 | 同上 |
| `selection_basis: semantic` | 模型真的判过（当前不会出现） | 可直接采用 |
| `top_candidates[].score_detail` | name/desc/prompt 各命中几个词元 | 用它判断 Python 的排序是否只是词面巧合 |

**判据**：看 `score_detail`。若首选专家的 `name_hits==0` 且只靠 `desc_hits` 命中日常词
（如「飞书集成开发工程师」因描述含「登录」二字而胜出），那就是**词面巧合**，主控必须按业务语义改判。

**改判方式**：

```python
# 主控按自己的语义判断直接生成派发单（覆盖 Python 的建议）
out = build_dispatch_for_expert("后端架构师", "实现用户登录接口")
# out["dispatch"]["subagent_type"] == "后端架构师"
```

`build_dispatch_for_expert` 在专家名不存在时抛 `ValueError`——不静默降级，
避免主控误以为派发成功。

**派发规则**：
- `subagent_type` 用**专家中文显示名**（专家 md 的 `name:` 字段），不是文件 id
- 优先派 1 位；需多专家协作时逐个派发，主控汇总
- 若某专家名不在会话子代理清单 → 回退为「读取该专家提示词后代入人格执行」
- **32 位总经理同样可派发**，用 **slug** `manager-<分类>`（如 `manager-backend-architecture`），
  用于本领域多专家协同的复杂任务。**总经理用 slug、专家用中文显示名**——
  各平台安装链写入总经理部署文件的 `name:` 是 slug，写中文名会找不到代理。

---

## 十、主入口

```python
from zcode_expert_system import zcode_expert_system
result = zcode_expert_system("设计一个支持高并发的后端 API 接口")
# → category / manager_id / selected_expert / manager_result / expert_result / context
```

```bash
python "${CLAUDE_PLUGIN_ROOT:-${ZCODE_PLUGIN_ROOT:-$QODER_PLUGIN_ROOT}}/skills/zcode-expert-system/zcode_dev_workflow.py" triage "<任务>" --files N   # 规模分诊
python "${CLAUDE_PLUGIN_ROOT:-${ZCODE_PLUGIN_ROOT:-$QODER_PLUGIN_ROOT}}/skills/zcode-expert-system/zcode_dev_workflow.py" stages medium              # 阶段序列
python "${CLAUDE_PLUGIN_ROOT:-${ZCODE_PLUGIN_ROOT:-$QODER_PLUGIN_ROOT}}/skills/zcode-expert-system/zcode_dev_workflow.py" plan "<任务>" --files N     # 派发计划（角色×专家）
python "${CLAUDE_PLUGIN_ROOT:-${ZCODE_PLUGIN_ROOT:-$QODER_PLUGIN_ROOT}}/skills/zcode-expert-system/zcode_dev_workflow.py" states                     # 状态机定义
```

---

## 十一、相关文件

| 文件 | 职责 |
|---|---|
| `config/workflow.json` | **唯一声明源**：阶段/门禁/状态机/证据级/裁剪矩阵 |
| `config/categories.json` | 32 大类 + 专家映射 |
| `config/experts.json` | 331 位专家元数据 |
| `agents/manager-*.md` | 32 个领域总经理 |
| `agents/expert-*.md` | 331 位专家提示词 |
| `zcode_expert_system.py` | 域轴路由 |
| `zcode_dev_workflow.py` | 规模轴分诊 + 状态机 + 派发计划 |
| `scripts/workflow_check.py` | 机械核对（无自觉依赖） |
| `references/roles/*.md` | 5 份角色契约（orchestrator / implementer / reviewer / investigator / analyst，拼进派发 prompt） |
| `references/stage-S*.md` | 9 份阶段规格（按需单读） |
| `docs/workflow-fusion-design.md` | 融合设计基线 |
| `scripts/llm_client.py` / `embedding_client.py` | LLM / Embedding 调用 |
| `context/context-manager.py` | 上下文管理 |
| `commands/wf/*.md` | 12 个 /wf:* 斜杠命令（triage/check/plan/… 的机械动作入口） |
| `templates/*.md` | 人工取用模板：plan-sections（计划 12 必备段）/ progress（SDD 账本·七态）/ task-report（任务报告）/ review-report（审查报告）/ bug-report（Bug 报告）/ minimal-contract（最小执行契约） |
| `hooks/hooks.json`（ZCode）/ `hooks/claude-hooks.json`（Claude）/ `~/.qoder/settings.json`（Qoder）+ `hooks/prepend-global-rules-reminder.mjs` | UserPromptSubmit 每轮注入触发规则 |
| `scripts/install.js` | 统一部署 / 卸载入口（ZCode / Claude Code / Qoder 目标；bin/cli.js 转调） |
| `scripts/install-qoder.js` | Qoder 用户级部署 / 状态 / 卸载（Skill / Commands / Agents / Hook） |
| `tests/*.py` | 回归防线（pytest 全量必须绿；改动后跑 `python -m pytest tests/ -q`） |
