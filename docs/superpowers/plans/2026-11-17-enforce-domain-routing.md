# enforce-domain-routing 实施计划

## Goal

两轴强制串联：任何规模（含只读/轻量）必须完成领域路由并派遣领域专家（硬性门禁）。消灭三断点——readonly 零派发、轻量机械任务可绕过、路由失败静默降级。变更 `enforce-domain-routing`，OpenSpec 规格已获批（G2，含 10 处亲审修订）。

## Architecture

- **域轴**（zcode_expert_system.py）：路由算法零改动；仅加 2 个可选参数（`role_prefix`、`persist`），向后兼容。
- **规模轴**（zcode_dev_workflow.py）：build_dispatch_plan 内钉死语句顺序（D6）——规模分诊 → 域路由 → 语义精判 blocking（复用现 661-676）→ readonly analyst 分支（插在现 :678 Implementer 段之前）→ Implementer/Reviewer → return plan。
- **机械执法**（workflow_check.py）：S0.DOMAIN 检查项，六格判定表（A 案），只查 S0 即产生的 Triage 域路由行，Scale 中英双语识别，账本关联性限定 --change/--plan 关联。
- **声明源**（workflow.json）：domain_routing 块 mandatory=true，六处配置同步。
- **提示层**（hook + 文档）：REMINDER 重写（三锚点保留），全库口径同批。
- **审计锚点**（dispatch.json）：readonly 域路由成功时落盘 `.superpowers/sdd/dispatch-<ts>/`，P4 生命周期，审计定位不进执法。

## Tech Stack

纯 Python 标准库（零新依赖）+ pytest + Node（hook，零新依赖）+ Bash（SDD 脚本不动）。

## Spec

OpenSpec change：`enforce-domain-routing`（openspec/changes/enforce-domain-routing/）。
- proposal.md：三断点现状 + 五项裁决记录
- design.md：唯一设计真相（D1-D6、六格判定表、dispatch.json、诚实条款、实施顺序、变异测试）
- specs/two-axis-routing/spec.md：6 Requirement / 13 Scenario
- tasks.md：10 任务（本计划一一承接，Task N covers 对应条目）

## Review Focus

1. **D6 语句顺序**（C1）：readonly 分支必须在语义精判 blocking 之后——A9 顺序验收锁定，审查者须专查 build_dispatch_plan 内 try/except 与 readonly 分支的相对位置；
2. **六格判定表**（C2）：workflow_check 新增项不得依赖 Dispatches 派发行（C3）；Scale 中文值识别（#10）；账本关联不扫全仓（#11）；
3. **三锚点**（C5）：triage「任务分类结果」首行、hook「【专家体系路由】」头行、REMINDER 非注释行无 32 领域名——审查者须实跑 test_cli_encoding/test_hooks；
4. **向后兼容**：496 既有测试零回归；zcode_expert_system 新参数默认值不变行为；
5. **降级诚实性**（I1）：degraded 双发射点一致，no-expert 路径 note 不再说谎。

## Global Constraints

- TDD 铁律：每任务先 RED 后 GREEN（实施者禁跳）；
- W6：派发 prompt 首段硬声明流程契约优先于专家人格；
- W1：实施永远串行，不并行；
- 零新依赖（标准库 only）；
- 三锚点禁破坏（违反任一挂 3-5 既有测试）；
- `build_dispatch_plan` 对 zcode_expert_system 的函数内 import **不得上提**（I5，上提即破坏 A3 monkeypatch 打点与降级语义）；
- 实施者禁改 tasks.md 勾选、禁派子代理、禁超 brief 范围。

## Dependencies

```
Task 1 (测试骨架 RED) → Task 2 (代码层+dispatch.json) → Task 3 (可选参数)
                                    ├→ Task 4 (S0.DOMAIN)
                                    ├→ Task 5 (workflow.json)
                                    ├→ Task 6 (hook)
                                    ├→ Task 7 (analyst.md)
                                    └→ Task 8 (文档同批) → Task 9 (版本 bump) → Task 10 (回归+变异)
```

实际执行串行按序 1→10。

## File Scope

允许修改：
- zcode_dev_workflow.py、zcode_expert_system.py
- config/workflow.json
- hooks/prepend-global-rules-reminder.mjs
- scripts/workflow_check.py
- SKILL.md、references/stage-S0-triage.md、references/workflow-tree.md、references/roles/（新增 analyst.md）、docs/workflow-fusion-design.md
- commands/wf/{triage,dispatch,check}.md
- templates/progress.md
- README.md、README_CN.md
- package.json、.zcode-plugin/plugin.json、skill_entry.py
- tests/（反转 1 个 + 新增 1 个 + 夹具补行）

禁止修改：config/{experts,categories}.json、agents/*、scripts/{openspec_engine,install,llm_client,embedding_client}.py、scripts/sdd/*、vendor/*、templates/{bug-report,minimal-contract,plan-sections,review-report,task-report}.md、openspec/ 已有制品、hooks/hooks.json。

## Execution Mode

**sdd**（默认模式）：有子代理、10 任务可独立拆分；ledger + 原子回写 tasks.md。与 apply-change 直行互斥（W3），本 change 全程 SDD。

---

### Task 1: 反转旧测试 + 新增双轴测试骨架（RED）

**Files**: tests/test_dispatch_plan.py、tests/test_domain_routing_mandatory.py（新建）
**Interfaces**:
- Consumes: build_dispatch_plan(task, files=None)（现签名）
- Produces: A1-A9 断言全部就位且新行为断言先红
**Steps**:
1. 写失败测试：test_readonly_plan_dispatches_analyst（反转 test_readonly_plan_has_no_dispatch，断言 dispatches 含 role=analyst 且 subagent_type ∈ experts.json 真实名）
2. 写失败测试 A1（五规模 domain 非空，语料：readonly=「分析一下这个模块的架构」/ light=「给登录接口加缓存」--files 1 / medium=「设计一个支持高并发的后端 API 接口」/ large=「重构认证体系」/ bug=「登录报错了排查」）
3. 写失败测试 A3（monkeypatch 源模块 zcode_expert_system 抛异常 → degraded=true + blocking 非空）
4. 写失败测试 A9（monkeypatch 返回 semantic_selection_required=True → readonly plan 必含 blocking，锁 D6 顺序）
5. 写失败测试 A2 含 dispatch.json 存在性 + 字段齐备断言
6. 跑 pytest —— 见 RED（新断言红、旧反转断言红）
7. commit

### Task 2: zcode_dev_workflow.py 代码层五改动 + dispatch.json 落盘（GREEN 之一）

**Files**: zcode_dev_workflow.py（:622-627、:657-692、:824-838、:874-895、readonly 分支新增）
**Interfaces**:
- Consumes: zcode_expert_system(task)（函数内 import，禁上提）
- Produces: plan JSON 新增 domain.degraded / blocking / dispatches[].role=analyst；triage --json 加 domain 键（文本保首行锚点）；落盘 .superpowers/sdd/dispatch-<ts>/dispatch.json
**Steps**:
1. 写实现：删 readonly early return；按 D6 顺序插 readonly analyst 分支（域路由成功 → 派 analyst + 写 dispatch.json；conf=0 → blocking 两档文案、不写 dispatch.json）
2. 降级统一：except 与 no-expert 两发射点都置 degraded=true，note 如实
3. triage 双轴合一：--json 加 domain 键；文本在首行后追加领域路由两行
4. _role_contract_prefix 加 analyst 分支（只读/证据/四段式/领域判断职责）
5. 跑 pytest —— A1/A2/A3/A4/A9 见 GREEN
6. commit

### Task 3: zcode_expert_system.py 可选参数

**Files**: zcode_expert_system.py（build_dispatch_for_expert、zcode_expert_system 签名）
**Interfaces**:
- Consumes: 现有签名（task_description, task_id=None）/（expert_name, task_description, context_summary=""）
- Produces: 新增 role_prefix=""（改判路径拼角色契约）、persist=True（False 时跳过 result-*.json 落盘）
**Steps**:
1. 写失败测试：改判路径派发单 dispatch.prompt 含 role_prefix 内容；persist=False 不产生新 result-*.json
2. 跑 —— 见 RED
3. 最小实现两个可选参数（默认值保旧行为）
4. 跑 —— 见 GREEN；全量 pytest 零回归
5. commit

### Task 4: workflow_check.py S0.DOMAIN 六格判定表（A 案）

**Files**: scripts/workflow_check.py（check_S0 内）、tests/test_workflow_check_gates.py（扩展）、tests 夹具账本补行、tests/test_p2_triage_dispatch.py（顺手微修，R2 裁决）
**Interfaces**:
- Consumes: ctx["ledger"]/ctx["scale"]（现有解析）
- Produces: 检查项 id=S0.DOMAIN；理由码 inapplicable:no_ledger / inapplicable:readonly_no_ledger_expected / s0_domain_missing / malformed_ledger
**Steps**:
1. 写失败测试：六格各一用例（含中文 Scale「中任务」「只读」双形态 + malformed + 关联性[不扫全仓]）
2. 跑 —— 见 RED
3. 实现：判定表 + 双语识别 + 账本关联沿用现有 plan/ledger 归属机制；夹具账本同批补「领域/专家」两行
4. 顺手微修（Task 2 审查 CONCERNS 裁决，R2）：test_p2_triage_dispatch.py:303 加 try/finally 清理（防每次全量跑泄漏 1 个 dispatch-* 目录）；删除 .superpowers/sdd/ 下现存 dispatch-* 残留目录
4b. 补 T3 审查 Important-1 反向对照测试：非只读语料（如「给登录接口加缓存」）经 build_dispatch_plan 后必须真实落盘 result-*.json（守卫 :718 被误改 persist=False 时测试变红，约 10 行）
5. 跑 —— 见 GREEN；test_p6/test_p7 零回归；--self-check rc=0；全量后 dispatch-* 残留=0
6. commit

### Task 5: config/workflow.json 六处

**Files**: config/workflow.json
**Interfaces**:
- Consumes: 既有 schema（stages/gates/trim_matrix/minimum_gates/conflict_rulings/roles）
- Produces: domain_routing 块（mandatory:true/readonly_role:analyst/dispatch_artifact/evidence/degrade_policy）；S0 exit_criteria+G0.check 同步；trim readonly/light S0=必；minimum_gates 追加；W10；roles.analyst
**Steps**:
1. 写失败测试 A6（mandatory===true、trim readonly S0==="必"、roles 含 analyst、W10 存在）
2. 跑 —— 见 RED
3. 六处编辑（JSON 语法保持，$comment 风格一致）
4. 跑 —— 见 GREEN；--self-check rc=0
5. commit

### Task 6: hook REMINDER 重写

**Files**: hooks/prepend-global-rules-reminder.mjs、tests/test_hooks.py（扩展）
**Interfaces**:
- Consumes: REMINDER 常量（现 69-82 行）
- Produces: 新 REMINDER——①triage 双轴合一（对齐 AGENTS.md Step1→Step2）；②保留「【专家体系路由】」头行；③删机械豁免改 analyst 派发；「不得跳过域路由」字样；非注释行零领域名
**Steps**:
1. 写失败测试 A5（输出含「不得跳过域路由」、不含「不强制派专家」；test_domain_names_not_hardcoded_in_source 仍绿）
2. 跑 —— 见 RED
3. 重写 REMINDER（锚点保留、口径更新）
4. 跑 —— 见 GREEN；test_hooks 全绿
5. commit

### Task 7: analyst.md 角色契约

**Files**: references/roles/analyst.md（新建）
**Interfaces**:
- Consumes: 四份既有契约结构（orchestrator/implementer/reviewer/investigator）
- Produces: 身份/输入三件/必须做/严格禁止/输出格式（四段式逐字「现象→原因→影响→建议」+ 可选未解疑点）
**Steps**:
1. 对照 workflow-tree.md:15 B0 行四段结构起草
2. grep 验证四段措辞逐字一致
3. 文档审查（结构 + 与 _role_contract_prefix("analyst") 前缀语义一致）
4. commit

### Task 8: 文档同批

**Files**: SKILL.md、references/stage-S0-triage.md、references/workflow-tree.md、docs/workflow-fusion-design.md、commands/wf/{triage,dispatch,check}.md、templates/progress.md、README.md、README_CN.md
**Interfaces**:
- Consumes: 定稿后的配置（Task 5）与 hook（Task 6）口径
- Produces: 全库术语统一（双轴分诊/显式降级三件套/W10/analyst）；「11 项」→13、「9 条」→10、「4 份角色契约」→5、「S0 简」→必（readonly/light 行）、删「不强制派专家」、README 三处旧描述清理、progress.md Triage +2 行
**Steps**:
1. 逐文件编辑（8 文件 + 联动 grep 清单见 design §7）
2. 全库 grep 五个旧口径词零残留
3. 引擎 validate --specs 无回归
4. commit

### Task 9: 版本号 bump 3.2.0

**Files**: SKILL.md（frontmatter+标题）、skill_entry.py:111、package.json、config/workflow.json、.zcode-plugin/plugin.json
**Interfaces**:
- Consumes: test_version_strings_agree 断言集
- Produces: 六处版本一致 3.2.0
**Steps**:
1. 跑 test_version_strings_agree —— 见 RED（若其断言 3.1.0）
2. 六处统一改为 3.2.0
3. 跑 —— 见 GREEN
4. commit

### Task 10: 全量回归 + 变异测试 M1-M3

**Files**: 无新改动（验证任务）
**Interfaces**:
- Consumes: 全部前序产物
- Produces: 全绿证据 + 三次变异红证据（还原后）+ CLI 冒烟证据
**Steps**:
1. python -m pytest tests/ -q 全量 —— 必须全绿
2. 变异 M1：临时删 degraded 标记 → A3 红 → 还原
3. 变异 M2：临时恢复 :622-627 early return → A2+A9 红 → 还原
4. 变异 M3：临时删 triage 首行/hook 锚点 → A4/A5 红 → 还原
5. CLI 冒烟：triage --json 双轴输出；plan readonly 含 analyst + dispatch.json 存在
6. commit（如有还原修正）

## Baseline

- command: `python -m pytest tests/ -q`
- exit: 0
- passed: 496, failed: 0, skipped: 1（2026-11-17 实测）
- 失败清单：无（基线全绿）
- 环境：**无 git**（`git rev-parse` exit=128）→ 快照证据路径（sha256 差集），审查独立性 **L1**（W7 降级，交付时显式声明）
- ledger：`.superpowers/sdd/2026-11-17-enforce-domain-routing/progress.md`（首行身份已核）

## Self-Review 五项

- [x] Spec 覆盖：10 Task covers R1-R6 全部 13 Scenario（A8/A9 锁 D6 与豁免口径）
- [x] 占位符扫描：零 TBD/TODO
- [x] 类型与签名跨任务一致：role_prefix/persist 默认值、S0.DOMAIN 理由码、dispatch.json 字段集三处引用一致
- [x] Review Focus 各焦点有测试与任务承接：D6→A9/Task1-2、判定表→A7/Task4、锚点→A4/A5/Task2/6、兼容→Task3/10、诚实→A3/Task2
- [x] 计划篇幅与任务规模相称：10 Task 对应 10 tasks.md 条目，一 Task ≥ 1 叶子

## Rulings

Ruling: A5/A8 测试骨架缺席 — A5 hook 测试归 Task 6、A8 文档级一致性归 Task 8 验收（计划文档 Task 6/8 明载）— 若混入 Task 1 会使 RED 骨架与实现耦合错位

Ruling: 审查者 Minor 1/2（plan_for 移入 try、A9 夹具真实专家名）移交 Task 2 brief 顺手项；Minor 3（conftest 合并）移交 Task 10 收尾 — 均在同一测试文件或收尾范围内，不构成 Task 1 阻塞

Ruling: T2 修复轮 I-1 选 setdefault 方案（审查建议 a）— 与实施者声明语义对齐、零行为回归风险 — 选更正报告方案会让「blocking 不丢信息」的核心安全属性失去代码保证

Ruling: T2 CONCERNS（test_p2:303 泄漏）折进 Task 4 顺手微修 — 主控禁亲手改码（S5 铁律），tests/test_p2 在 File Scope 允许清单内，双账本已同步登记

Ruling: T3 审查 Important-1（接线单向守卫缺口）折进 Task 4 补反向对照测试 — 当前实现正确不阻塞，但「非只读误传 persist=False」无测试守卫，约 10 行补齐

Ruling: triage persist=True 既有行为维持 — 向后兼容设计（200 自剪枝兜底），triage 是主控显式调用非 readonly 分析路径

Ruling: T4 审查 Minor-1（report 计数 4→5）与 Minor-2（英文账本形态 A7 层无专门用例，函数级双语由既有 p6 覆盖）不阻塞，随报告勘误与 T10 收尾带过

Ruling: T4 CONCERNS（test_dispatch_plan.py 反转测试裸 rmtree 加固）折进 T10 收尾 — 一行加固，范围外文件统一在收尾任务处理

Ruling: T5 审查 3 Minor — 报告坐标失准（实体正确）随 T8 勘误；「域路由已完成」vs「领域路由已执行」措辞归一随 T8 术语同批；brief 步骤 1 时序出入（A6 预置于 T4 批次）备忘不改

Ruling: T6 审查 Minor-1 可选收紧（A5 L409 analyst 单 token → 整短语）不执行 — 审查者自评误红风险低且现断言已锁 design 意图，改动收益不抵测试维护成本

Ruling: T7 审查 I1（报告行数 74→62 勘误）主控认领 — 亲验背书时复述实施者数字未独立数行，账本以此为准（62 行）；交付物本体零缺陷不阻塞

Ruling: T5 审查 Minor-1（task-5-report 坐标失准）同类元数据勘误，同批记录 — 两处均为审计痕迹修正，非交付物缺陷

Ruling: T8 审查 Minor-1（13 项行序两文件既有漂移）折进 T9 顺手归一 — Task 8 未动既有行序属存量不一致

Ruling: T8 审查 Minor-2（after-8 快照未落盘）主控补记 — 快照纪律执行瑕疵，审查者已独立补齐差集（10 全变），结果状态不受影响

Ruling: T9 修复轮 Files 扩展 scripts/install.js 三处（:3/:242/:249）— 审查发现 deploy 链路会把 plugin.json description 回写为 v3.1 侵蚀 bump 成果；纯字符串修复

Ruling: T9 实施者勘误主控同源前提成立（部署脚本 :242 与 plugin.json 同源而非 package.json）— 采纳其处置；主控 brief 六处口径未覆盖 scripts/ 属制定遗漏，认领

Ruling: 主控「grep 命中仅在 .superpowers/」口径陈述不全认领 — docs/ 另有 12 处带日期历史快照非残留；后续零残留声明必须列举完整口径含排除理由（审查者指出同类病灶复发）


## Integration Verification

- command: python -m pytest tests/ -q
- exit: 0
- passed: 520, failed: 0, skipped: 1
- tree: E:\zcode-expert-system（本地交付，源仓即交付树，无 git 无合并动作）
- 附加：workflow_check --self-check rc=0（无漂移）；openspec validate --change valid:true；CLI 冒烟 triage 双轴 True + 域轴 backend-architecture conf=1.0
- 重测时间: 2026-11-18（集成后重跑，未沿用集成前结果）
- 交付方式: 老板选定「本地交付」（选项 1）
