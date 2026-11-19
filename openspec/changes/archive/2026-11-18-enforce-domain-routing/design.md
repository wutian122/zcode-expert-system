# Design：两轴强制串联（唯一设计真相）

> 本文是本变更的唯一设计真相。设计稿 v2（Temp/workflow-optimization-plan.md）+ 老板三项裁决已固化于此。
> 四域复核（代码层/配置与状态机/文档契约/测试边界）的 19 条发现已全部吸收。

## 1. 已批准裁决（2026-11-17 老板）

1. **S0.DOMAIN 执法范围 = A 案（全规模账本执法）**：有账本的非只读任务，ledger `## Triage` 缺域路由行即 FAIL。连带义务：`stage-S0-triage.md` 的「分诊 11 项中/大必填」改为「双轴分诊所有写任务必填」；在途账本迁移条款（见 §8）。
2. **dispatch.json = 做**：readonly 任务落盘派发单作为文件级审计锚点（设计见 §6）。
3. **版本 bump 3.2.0**：六处联动（SKILL.md frontmatter + 标题、skill_entry.py:111、package.json:3、config/workflow.json:3、.zcode-plugin/plugin.json:8、tests/test_version_strings_agree 回归）。

## 2. 设计决策（D1-D6）

| # | 决策 | 理由 |
|---|---|---|
| D1 | 域路由放 S0 内，不新增阶段 | 新增阶段牵动九阶段产物/门禁/裁剪矩阵，改动面 ×4 收益为零 |
| D2 | `triage` 命令双轴合一输出 | 工具层强制：主控拿规模结论必须同时接受域路由 |
| D3 | readonly 派发新增 **analyst** 角色 | 只读+领域判断+「现象→原因→影响→建议」四段式；不复用 investigator（根因三段式对分析任务错配） |
| D4 | readonly 保留无账本形态，S0.DOMAIN 对其判 SKIP | 为只读强制建账本违背轻量原则；文件级锚点由 dispatch.json 承担（裁决 2） |
| D5 | 路由失败显式降级三件套 | 保留可用性但堵住静默：degraded=true + plan.blocking + 派发行 note |
| D6 | **语句顺序契约**（C1 修复）：build_dispatch_plan 内钉死「规模分诊 → 域路由 → 语义精判 blocking（复用现 661-676）→ readonly analyst 分支（插在现 :678 Implementer 段之前）→ Implementer/Reviewer（非只读）→ return plan」 | v1 示意把 readonly 分支画在 blocking 之前——照做会跳过 semantic_recheck、按词元巧合派 analyst（正是要消灭的失效模式）；A9 顺序验收锁定 |

## 3. S0.DOMAIN 判定表（C2 修复：六格闭合，A 案）

| 规模 | 账本状态 | Triage 域路由行 | 判定 | 理由码 |
|---|---|---|---|---|
| 任何 | 无账本 | — | **SKIP** | `inapplicable:no_ledger` |
| 任何 | 账本不可读 | — | **FAIL** | `malformed_ledger` |
| readonly | 有账本 | 缺 | **SKIP** | `inapplicable:readonly_no_ledger_expected`（readonly 按裁剪不产生账本） |
| 非只读 | 有账本+可读 | **有** | **OK** | — |
| 非只读 | 有账本+可读 | **缺** | **FAIL** | `s0_domain_missing`（A 案执法核心格） |

- 只查 **S0 即产生**的 Triage 域路由行，**不查 Dispatches 派发行**（C3 修复：派发行 S5 才产生，查它会误杀 S4~S5 初段合法中间态）。
- 对既有测试影响：test_p6:228（readonly+completed change 夹具）、test_p7:143（无账本）两格均为 SKIP/无账本，**零影响**（实机已验证：14 测试全绿 + 夹具账本确无 Triage 行）。
- **Scale 双语识别（#10，实机验证补充）**：账本 Scale 段实际写中文（实测「中任务」「只读」），判定表实现 MUST 兼容中英双形态（只读/轻量/中任务/大任务/Bug + readonly/light/medium/large/bug），否则「非只读+有账本」格会把中文账本误判 readonly 走 SKIP——执法静默失效。
- **账本关联性（#11，实机验证补充）**：只查与当前 `--change`/`--plan` **关联**的账本，**不扫全仓 workspace**——本仓存在两本已归档 change 的遗留账本（openspec-impl、vendor-skills，实核均无 Triage 段），扫全仓会让遗留账本无限期 FAIL。账本与检查的关联判定沿用 workflow_check 现有 plan/ledger 归属机制（首行 plan 路径）。

## 4. 代码层设计

### 4.1 zcode_dev_workflow.py（5 处改动）

1. **删 readonly early return**（现 622-627），readonly 分支按 D6 顺序插入：
   - 域路由正常 + 专家已选 → 派发 `role=analyst`、`prompt_prefix=_role_contract_prefix("analyst")`，并**写 dispatch.json**（§6）；
   - 域路由 conf=0 / 无专家 → `plan.blocking` 两档文案（I6）：「疑似闲聊（建议直接问候回应）」vs「真无信号（向老板澄清领域或 build_dispatch_for_expert 指定）」。**不做机械闲聊判定**（#2 实机验证：你好/谢谢/不用专家体系三者 conf=0 且无任何可区分特征，新增词表违反零依赖裁决）——文案同时陈述两档，归类交主控按语境判断；
2. **降级统一**（I1）：except 路径与 no-expert 路径**都置** `domain.degraded=true`，note 如实陈述（不再说"降级通用代理"谎话——领域结论禁 general-purpose 产出，机械执行可承接）；
3. **triage 子命令双轴合一**：`--json` 加 `domain` 键；文本输出在「任务分类结果」首行**之后**追加领域路由两行（三锚点 ①：首行锚点不动）；
4. **`_role_contract_prefix` 加 analyst 分支**：只读禁改文件、结论带 file:line/URL 证据、四段式输出、领域判断不得留待主控；
5. **`classify_scale` / 状态机 / trim 判定逻辑零改动**。

### 4.2 zcode_expert_system.py（2 处可选参数，向后兼容）

- `build_dispatch_for_expert(expert_name, task, context_summary="", role_prefix="")`（I3：改判路径不丢角色契约）；
- `zcode_expert_system(task, task_id=None, persist=True)`（I2：readonly 场景传 `persist=False`，不写 result-*.json；默认 True 保持既有行为）。
- **禁令**：`build_dispatch_plan` 对 `zcode_expert_system` 是函数内 import（I5），实施**不得上提到模块顶层**——上提即改变降级语义、破坏 A3 monkeypatch 打点。

## 5. 配置层设计（config/workflow.json 六处）

1. 新增顶层 `domain_routing` 声明块：`mandatory:true`、`order:"scale-then-domain"`、`readonly_role:"analyst"`、`dispatch_artifact:".superpowers/sdd/dispatch-<ts>/dispatch.json"`、`evidence`、`degrade_policy`；
2. S0 `exit_criteria` 追加「域路由已完成并说出口（category + 专家名）」；**G0.check 文案同步**（I10，防三段漂移）；
3. `trim_matrix` readonly/light 的 S0「简」→「必」（机械安全：LIGHT_KEEP 不含 S0）；
4. `minimum_gates` 五规模追加域路由门禁项（bug 9 项不变——investigator 派发本就含域路由）；
5. `conflict_rulings` 追加 **W10**（两轴强制串行；豁免仅两级——闲聊/问候、老板明示且记 Ruling）；
6. `roles` 增加 `analyst`（dispatchable:true、read_only:true、cannot 三条）。

## 6. dispatch.json 设计（裁决 2：做）

- **位置**：`.superpowers/sdd/dispatch-<YYYYMMDD-HHMMSS>/dispatch.json`（时间戳目录，并发任务不互覆）；
- **内容**：`{task, scale, category, expert_name, expert_id, subagent_type, role:"analyst", confidence, selection_basis, generated_at}`；
- **写入时机**：build_dispatch_plan 生成 readonly analyst 派发时（域路由成功才写；conf=0 不写，记入 blocking）；
- **核验方式（诚实边界，#9 老板已确认维持审计定位）**：workflow_check **不**执法它（S0.DOMAIN 仍按 §3 判定表走账本锚；workflow_check 参数面实核无 dispatch 入口，加执法需扩 CLI，收益不成比例）；它的价值 = 文件级审计痕迹，老板可随时查看最近 dispatch-* 复核派发行为；正确性由 A2/A4 测试契约锁定（plan 生成 ⇒ dispatch.json 存在且字段齐备）。
- **生命周期（#3 修订）**：dispatch-* 目录归入 **P4 过程证据**生命周期——终审 clean 后随 workspace 清理规则一并删除，不无限累积（实核 .superpowers/sdd/ 已有 4 目录零清理，此条为必须项）。

## 7. hook 与文档设计

- **hook REMINDER 重写**（三锚点 ②③）：保留「【专家体系路由】」头行锚点；**不得出现 32 个领域名字面量**（test_hooks.py:353 实核判据：只豁免 `*`/`//`/`/*` 开头行，REMINDER 非注释行碰领域名即挂）；① 条改「先跑 triage（双轴合一）→ 复核 score_detail 语义精判」，修「先域后规模」顺序矛盾——**修复后与全局 AGENTS.md Step 1（规模分类）→ Step 2（路由）顺序对齐**（#7，AGENTS.md:117-120 实核，防插件 hook 与老板全局规则矛盾复发）；③ 条删「不强制派专家」，改「所有任务（含只读与机械任务）都必须完成两轴分诊；只读任务派 analyst」；
- **文档同批**（术语统一「双轴分诊 / 显式降级三件套 / W10 / analyst」）：SKILL.md（入口表、删 62 行豁免段、裁剪表 readonly 行、角色表 +1、相关文件表）、stage-S0-triage.md（动作+13 项+退出条件+失败返回点+必填范围改「所有写任务」）、workflow-tree.md（B0 分支 + **第 5 节三方核验表、第 6 节断点识别树**补 readonly/analyst 行——I7）、fusion-design（「九条裁决」→10 条）、commands/wf/{triage,dispatch,check}.md、templates/progress.md（Triage 表 +2 行）、README.md:194 / README_CN.md:192,315 旧描述清理、「4 份角色契约」→5 份、triage.md「轻量 6 道」随 minimum_gates 同步、全库「11 项」→13 项 grep（I8）。

## 8. 在途账本迁移条款（A 案连带义务）

S0.DOMAIN 生效后，存量 light/medium 账本若缺 Triage 域路由行：首次跑 `workflow_check` 会 FAIL。处理：**不自动改账本**——账本由主控补记两行（领域 category / 专家 name+basis，按当时实际派发事实补记）并记一条 Ruling（`Ruling: 补记 S0 域路由行 — A 案生效首跑 — 不补则该账本永 FAIL`）。测试夹具账本由本变更同批补两行。

## 9. analyst.md 角色契约（C6：必改，单点阻塞）

结构对照四份既有契约：身份 / 输入（只三件：任务陈述+允许取证手段+领域人格）/ 必须做 6 条 / 严格禁止 5 条 / 输出格式。**输出格式四段式逐字采用「现象→原因→影响→建议」**（与 references/workflow-tree.md:15 B0 行逐字一致），「未解疑点」可选附加段。

## 10. 诚实条款

- readonly 域路由的**运行时**文件级锚点 = dispatch.json（裁决 2 落地）；workflow_check 的执法锚点仍 = 账本 Triage 行（A 案），readonly 格判 SKIP 不造假绿；
- analyst 产物不落 task-N-report.md（无实施），ledger Dispatches 段无机械解析——如实声明，不伪造解析能力；
- triage 双轴耗时实测 +22ms（本地 51→73ms），hook 71ms 不变，5 并发无共享状态。

## 11. 实施顺序（四步，每步有完成判据）

| 步 | 内容 | 完成判据 |
|---|---|---|
| ① 代码层 | 4.1 全部 + 反转 test_dispatch_plan.py:93-97 | A2/A9 绿 |
| ② S0.DOMAIN | workflow_check 判定表 + 夹具账本补行 | A7 绿 + test_p6/test_p7 零回归 |
| ③ triage/hook 文案 | 三锚点过闸 | A4/A5 绿 |
| ④ 文档+配置同批 | §5 + §7 + analyst.md + 版本六处 | A1/A6/A8 绿 + 全库 grep 零残留 |

> **验收索引**：A1 五规模含非空 domain · A2 readonly 派 analyst + dispatch.json 存在 · A3 路由失败 degraded+blocking · A4 triage CLI 双轴输出（保「任务分类结果」首行）· A5 hook 锚点与旧豁免文案反断言 · A6 workflow.json domain_routing.mandatory + trim readonly S0=必 · A7 S0.DOMAIN 判定表（夹具驱动）· **A8 豁免口径文档级一致性（hook/AGENTS.md/SKILL.md 三处豁免口径同批：闲聊/问候、老板明示记 Ruling）** · A9 readonly 顺序验收（semantic_selection_required=True 时 plan 必含 blocking）。

## 12. 变异测试（验收的本体论证明）

| # | 变异 | 预期 |
|---|---|---|
| M1 | 删 degraded 标记 | A3 必红 |
| M2 | 恢复 :622-627 early return | A2 必红、A9 亦红 |
| M3 | 删「任务分类结果」首行或 hook「【专家体系路由】」锚点 | A4/A5 必红 |
| M4（可选） | 判定表 readonly+有账本格改 FAIL | test_p6 必红（证明格 a 被锁定） |
