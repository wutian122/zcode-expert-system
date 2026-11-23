# two-axis-routing 规格

## Purpose

定义 zcode-expert-system 插件的两轴强制串联契约：规模分诊（只读/轻量/中/大/Bug）与领域路由（32 类 → 331 专家）在 S0 阶段强制串联，任何规模（含只读）不得跳过域路由——只读任务必须派发 analyst（领域专家）并落盘 dispatch.json 审计锚点，域路由失败必须显式降级（degraded + blocking），workflow_check 以 S0.DOMAIN 六格判定表全规模账本执法。语义精判未完成时按置信度分级处置（低置信度阻断派发、高置信度保留派发并提醒复核，I-02/I-03），归档前须核对 tasks.md 实际勾选（I-05），hook 每轮告警未勾项（I-06）。规格真相源：change `enforce-domain-routing`（2026-11-18 归档），设计依据 docs/superpowers/plans/2026-11-17-enforce-domain-routing.md；I-02/I-03/I-05/I-06 增量来自 2026-11-21 十二缺陷审计与 P0/P1 修复轮。

## Requirements

（首次同步自 delta；后续增量见各归档 change 的 delta spec）

## ADDED Requirements

### Requirement: 规模分诊与领域路由强制串联

系统 MUST 在 S0 阶段将规模分诊与领域路由强制串联执行：`triage` 命令 MUST 同时产出规模结论与域路由结论（双轴合一），任何规模的构建派发计划 MUST 先完成域路由再分派角色，且域路由结论 MUST 在会话内说出口。

#### Scenario: 只读任务双轴输出
- WHEN 主控执行 `triage "分析一下这个模块的架构" --json`
- THEN 输出 JSON 同时含 scale=readonly 与非空 domain.category、domain.expert_name
- AND 文本输出首行保留「任务分类结果」锚点，其后追加领域路由两行

#### Scenario: 派发计划先域后派
- WHEN build_dispatch_plan 被调用
- THEN 执行顺序为：规模分诊 → 域路由 → 语义精判 blocking → readonly analyst 分支（如适用）→ Implementer/Reviewer
- AND readonly 任务在 semantic_selection_required=true 时 plan 必含 blocking（不得跳过语义精判直接派发）

### Requirement: 只读任务必须派 analyst（领域专家）

系统 MUST 为只读任务生成 analyst 角色派发，subagent_type MUST 为 experts.json 中真实存在的专家中文名；只读任务 MUST NOT 返回空 dispatches。

#### Scenario: 只读任务派发 analyst
- WHEN build_dispatch_plan 处理 readonly 任务且域路由成功
- THEN dispatches 含 role=analyst 条目且 subagent_type 为真实专家名（≠ general-purpose）
- AND prompt 前缀含 analyst 契约（只读、file:line 证据、现象→原因→影响→建议四段式）

#### Scenario: 只读任务落盘 dispatch.json
- WHEN readonly 任务生成 analyst 派发（域路由成功）
- THEN 系统写入 .superpowers/sdd/dispatch-<YYYYMMDD-HHMMSS>/dispatch.json
- AND 内容含 task/scale/category/expert_name/subagent_type/role/confidence/selection_basis/generated_at

#### Scenario: 域路由失败不落盘 dispatch.json
- WHEN readonly 任务域路由失败（异常或 conf=0）
- THEN 系统不写 dispatch.json
- AND plan.blocking 非空且 dispatches 为空

### Requirement: 域路由失败显式降级

域路由失败（异常或无专家）MUST NOT 静默降级：plan.domain.degraded MUST 为 true，plan.blocking MUST 非空，且涉及领域判断的结论 MUST NOT 由 general-purpose 产出。

#### Scenario: 路由异常显式降级
- WHEN zcode_expert_system 抛异常
- THEN plan.domain.degraded == true 且 plan.blocking 非空
- AND 派发行 note 如实陈述降级与「领域结论须重路由」

#### Scenario: 无信号任务两档文案
- WHEN 任务描述 conf=0（含闲聊输入如「你好」）
- THEN blocking 文案同时陈述「疑似闲聊（建议直接问候回应）」与「真无信号（需澄清领域）」两档
- AND 系统不做机械闲聊判定（两档归类由主控按语境判断）

### Requirement: S0.DOMAIN 全规模账本执法

workflow_check.py MUST 新增 S0.DOMAIN 检查项，按「规模×账本状态」六格判定表执法：非只读+有账本+可读且缺 Triage 域路由行 = FAIL；无账本 = SKIP(inapplicable:no_ledger)；账本不可读 = FAIL(malformed_ledger)；readonly+有账本缺行 = SKIP。检查 MUST NOT 依赖 Dispatches 派发行（S5 才产生）。

#### Scenario: 缺域路由行被判 FAIL
- WHEN 非只读任务的账本 ## Triage 缺领域/专家两行
- THEN workflow_check 报告含 id=S0.DOMAIN 的 FAIL
- AND 退出码非 0（不得进下一阶段）

#### Scenario: 无账本任务不误杀
- WHEN 任务尚无账本（S4 前常态）
- THEN S0.DOMAIN 判 SKIP 且理由码以 inapplicable: 开头
- AND 既有测试 test_p6_review_fixes / test_p7_a456_fixes 零回归

#### Scenario: 账本不可读判 FAIL
- WHEN 关联账本存在但不可读（损坏/权限）
- THEN S0.DOMAIN 判 FAIL 且理由码为 malformed_ledger
- AND 不静默跳过

#### Scenario: 账本 Scale 双语识别
- WHEN 关联账本的 Scale 段写中文形态（如「中任务」「只读」）或英文形态（medium/readonly）
- THEN 判定表按同一语义归类（中文「只读」= readonly）
- AND 中文账本不因语言形态被误判走 readonly SKIP 格

### Requirement: 配置声明与文档同批一致

config/workflow.json MUST 新增 domain_routing 声明块（mandatory=true），trim_matrix readonly/light 的 S0 MUST 为「必」，conflict_rulings MUST 含 W10，roles MUST 含 analyst；SKILL.md、stage-S0、workflow-tree、commands、templates、README MUST 与配置同批一致（「9 条」→10 条、「11 项」→13 项、删机械任务豁免文案、角色契约 5 份）。

#### Scenario: 声明源一致性
- WHEN 读 config/workflow.json
- THEN domain_routing.mandatory === true 且 trim_matrix.readonly.S0 === "必"
- AND SKILL.md 无「纯机械动作不必派专家」残留、hook 输出含「不得跳过域路由」

### Requirement: 三锚点向后兼容

改动 MUST 保留三个既有测试锚点：triage 文本输出首行「任务分类结果」、hook REMINDER 头行「【专家体系路由】」、REMINDER 非注释行不含 32 个领域名字面量。版本号 MUST bump（当前 3.2.2）且与 package.json 强一致的各处（plugin.json/workflow.json/SKILL.md/skill_entry.py）保持一致。

#### Scenario: 既有测试零回归
- WHEN 实施完成后运行 python -m pytest tests/ -q
- THEN 全量通过（含 test_cli_encoding、test_hooks、test_version_strings_agree）


### Requirement: P2-1 总经理提示词专家数一致性
系统 MUST 保证 agents/manager-*.md 中每个文件“从管辖的 N 位专家中选择”的 N 与 config/categories.json 的 expert_count 一致。新增一致性门禁测试 test_manager_prompt_expert_counts_match_categories，23 个文件的 46 处数字已修正。

### Requirement: 语义精判分级处置（I-02 / I-03）

`build_dispatch_plan` MUST 依据「`semantic_selection_required` × 置信度」对专家派发做**分级**处置，不得一律派发也不得一律阻断：低置信度且语义精判未完成时 MUST 阻断派发；高置信度但语义精判未完成时 MUST 保留派发并置复核提醒。分类置信度阈值 MUST 复用 `zcode_expert_system.LOW_CONFIDENCE_THRESHOLD`（当前 0.5），不得在本模块另立常量。

#### Scenario: 低置信度 + heuristic 阻断派发（I-02）
- WHEN 域路由返回 `semantic_selection_required=true` 且 `confidence < LOW_CONFIDENCE_THRESHOLD`（如 hr 专家命中 bigram「一个」）
- THEN plan 的 dispatches MUST NOT 含 role=implementer / reviewer 条目
- AND MUST 含 role=orchestrator、action=blocked_low_confidence 的阻断说明条目
- AND plan.blocking MUST 非空，文案指明「词元兜底专家与任务语义无关，须澄清领域或用 build_dispatch_for_expert 指定后重跑」

#### Scenario: 高置信度 + heuristic 保留派发并提醒复核（I-03）
- WHEN 域路由返回 `semantic_selection_required=true` 且 `confidence >= LOW_CONFIDENCE_THRESHOLD`（如 conf=1.0 但为词元巧合命中）
- THEN plan MUST 保留 implementer 与 reviewer 派发（分类可靠，不阻断）
- AND plan.dispatches MUST 含 role=orchestrator、action=semantic_recheck 条目，要求复核 `domain.top_candidates[].score_detail`
- AND 该提醒 MUST 指出 token/jwt/oauth 按声明序落 security-compliance，功能开发类任务应改判 backend-architecture

#### Scenario: 语义精判已完成时不受影响
- WHEN `selection_basis == "semantic"`（`semantic_selection_required=false`）
- THEN 不产生 semantic_recheck 条目，也不触发低置信度阻断（按域结论正常派发）

### Requirement: 归档前 tasks.md 勾选核对（I-05）

`openspec_engine.py archive-change` MUST 在七标志（tasksCompleted/…/docsUpdated）全为 true 之后，追加核对 `tasks.md` 的**实际勾选**状态：存在未勾选任务时 MUST 拒绝归档并 rc≠0。勾选口径 MUST 与 `workflow_check.count_checkboxes` 一致（仅 x/X 算完成，空框 `[]` 与异形标记均按未完成处理）；`tasks.md` 不存在时 MUST 沿用七标志判定（无账本可查）。

#### Scenario: 七标志全 true 但 tasks.md 有未勾项仍拒归档
- WHEN `.status.json` 七标志全为 true，且 tasks.md 存在未勾选任务
- THEN 归档命令返回非 0，stderr 含 `archive blocked: tasks.md has N unchecked task(s)`
- AND 不创建 `openspec/changes/archive/<date>-<name>` 目录

#### Scenario: tasks.md 全勾选放行
- WHEN 七标志全 true 且 tasks.md 所有叶子均已勾选
- THEN 归档继续执行（进入目录产物校验与归档）

#### Scenario: 无 tasks.md 时不校验勾选
- WHEN 变更目录不存在 tasks.md
- THEN 不因勾选核对失败，沿用七标志结果判定

### Requirement: 门禁自动可见（I-06）

UserPromptSubmit hook MUST 每轮读取活跃账本对应的 `openspec/changes/<slug>/tasks.md` 勾选统计，存在未勾项时在注入摘要中输出明确告警，使「任务未完成却要交付/归档」无需主控主动调用 `/wf:check` 即可见。实现 MUST fail-open：tasks.md 缺失或读失败时返回空统计，hook 输出退化为常规提示行，MUST NOT 抛异常或返回非 0。

#### Scenario: 活跃账本有未勾项则告警
- WHEN 注入的活跃账本 slug 对应 tasks.md 存在 N 项未勾选
- THEN 注入摘要末行为「⚠️ tasks.md 尚有 N 项未勾选（已完成 M）：未完成不得交付/归档…」
- AND hook 退出码仍为 0（只告警，不阻断输入）

#### Scenario: 全部勾选或无 tasks.md 时回退常规提示
- WHEN tasks.md 全部勾选，或 tasks.md 不存在/读失败
- THEN 注入摘要使用常规提示行「继续前先核证据与 tasks.md 勾选是否一致（不一致先修再派）」
- AND 不出现 ⚠️ 告警行，hook 不抛异常

### Requirement: R-1/R-2 hook 路由触发与复核专家
hook REMINDER 触发条件改为全称式“所有任务都必须先走两轴路由”，删除条件式“任务属 32 领域之一”；新增 R-2：“复核/审查任何产出（含主控自己的产出）属于领域判断，必须派独立专家（实施者≠审查者）”。SKILL.md:62 同步。

### Requirement: P2-4 git 探测 root 线程化
build_dispatch_plan 增加 --root 参数，detect_git 从 root 起探测而非 cwd，避免假阳性伪造 L0。默认 None 保持向后兼容。

### Requirement: P2-2/P2-5 状态机死字段清除
config/workflow.json states 删除 terminal 与 counts_as_complete 两个零消费字段；states_summary 不再透传；13 条 transitions 不动。

### Requirement: P2-3 install.js 单写对齐
vendored zes-* 技能安装与卸载均只作用于插件缓存 pluginRoot/skills，删除了卸载侧 zcodeDir/skills 死路径。

### Requirement: 版本 bump v3.2.2
package.json/.zcode-plugin/plugin.json/config/workflow.json/SKILL.md/skill_entry.py/config/experts.json/README.md/README_CN.md 全部 3.2.2。
