# Tasks：两轴强制串联

> 实施顺序四步（见 design.md §11），每任务 TDD：先失败测试后实现。covers 映射 spec 需求。
> 依赖：1 → 2 → 3 →（4,5,6,7,8,9 可依 1-3 完成后并行推进，实施仍串行按序做）→ 10 收尾。

- [x] 1. 反转旧测试 + 新增双轴测试骨架（RED）——test_dispatch_plan.py:93-97 `test_readonly_plan_has_no_dispatch` 反转为 `test_readonly_plan_dispatches_analyst`；新建 tests/test_domain_routing_mandatory.py（A1-A9 断言先写先红）(covers R1/R2/R3)
  - 依赖：无（首任务）
  - 验收：新测试全红（A2/A9 因旧代码红）；`python -m pytest tests/test_dispatch_plan.py tests/test_domain_routing_mandatory.py -q` 退出码非 0
- [x] 2. zcode_dev_workflow.py 代码层五改动 + dispatch.json 落盘（GREEN 之一）——删 readonly early return；analyst 分支按 D6 顺序插入（:678 Implementer 段之前）；degraded 双发射点统一（I1）；triage 双轴合一（保「任务分类结果」首行）；_role_contract_prefix 加 analyst 分支；**readonly 域路由成功时写 .superpowers/sdd/dispatch-<ts>/dispatch.json（#1 修订：落盘逻辑在 build_dispatch_plan，归本任务）**；失败时不写（spec R2 新 Scenario）(covers R1/R2/R3)
  - 依赖：Task 1（RED 就绪）
  - 验收：A1/A2/A3/A4/A9 转绿；blocking 两档文案并存不做机械判定（I6/#2）
- [x] 3. zcode_expert_system.py 可选参数——build_dispatch_for_expert 加 role_prefix（I3）；zcode_expert_system 加 persist（I2，readonly 传 False）(covers R1/R2)
  - 依赖：Task 2
  - 验收：默认参数下既有行为不变（496 基线零回归）；改判路径派发单含 analyst 契约前缀
- [x] 4. workflow_check.py S0.DOMAIN 六格判定表（A 案）——check_S0 新增检查项；删 Dispatches 子项；**Scale 中英双语识别（#10）**；**账本关联性：只查 --change/--plan 关联账本，不扫全仓（#11）**；夹具账本同批补 Triage 域路由两行；**顺手微修 test_p2:303 清理泄漏 + 删 dispatch-* 残留（R2 裁决）**；**补 T3-I1 反向对照测试（非只读必落盘 result-*.json）** (covers R4)
  - 依赖：Task 2
  - 验收：A7 绿（含 malformed_ledger 格）；test_p6:228 / test_p7:143 零回归；--self-check rc=0；全量跑后 dispatch-* 残留=0
- [x] 5. config/workflow.json 六处——domain_routing 块、S0 exit_criteria + G0.check 同步、trim_matrix S0 简→必、minimum_gates 追加、W10、roles.analyst (covers R5)
  - 依赖：Task 2
  - 验收：A6 绿；--self-check rc=0
- [x] 6. hook REMINDER 重写——保留「【专家体系路由】」锚点与 32 领域名避讳（只豁免注释行）；① 条修顺序矛盾（对齐 AGENTS.md Step1→Step2）；③ 条删机械豁免改 analyst 派发 (covers R5/R6)
  - 依赖：Task 2
  - 验收：A5 绿（含「不得跳过域路由」、不含旧豁免文案）；test_hooks.py 全绿
- [x] 7. analyst.md 角色契约——四段式逐字「现象→原因→影响→建议」；结构对照四份既有契约 (covers R2)
  - 依赖：Task 2（契约前缀定稿后写）
  - 验收：与 workflow-tree.md:15 B0 行逐字一致（grep 验证）；文档审查通过
- [x] 8. 文档同批——SKILL.md（入口表/删 62 行豁免/裁剪表/角色表/相关文件表）、stage-S0（动作+13 项+退出+失败返回+必填范围改所有写任务）、workflow-tree（B0+第 5/6 节）、fusion-design（9→10 条）、commands/wf/{triage,dispatch,check}.md、templates/progress.md（Triage +2 行）、README×2 旧描述清理、「4 份角色契约」→5 份、「轻量 6 道」同步 (covers R5)
  - 依赖：Tasks 4-6（口径以配置与 hook 定稿为准）
  - 验收：全库 grep「11 项」「S0 简」「9 条」「不强制派专家」「4 份角色契约」零残留（I8/I11/I12/I14）
- [x] 9. 版本号 bump 3.2.0——SKILL.md frontmatter+标题、skill_entry.py:111、package.json、workflow.json:3、plugin.json:8 六处一致 (covers R6)
  - 依赖：Task 8
  - 验收：test_version_strings_agree 绿；六处 grep 一致
- [x] 10. 全量回归 + 变异测试 M1-M3——python -m pytest tests/ -q 全绿；**变异测试（自 spec R6 移入本任务验收，#8）：删 degraded → A3 红；恢复 early return → A2+A9 红；删锚点 → A4+A5 红；每次变异后还原** (covers R6)
  - 依赖：Tasks 1-9 全部完成
  - 验收：全绿 + 三次变异按预期红后还原；CLI 冒烟：triage --json 双轴输出、plan readonly 含 analyst + dispatch.json 存在
