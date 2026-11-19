# Proposal：两轴强制串联 —— 所有规模必须派遣领域专家

## Why

v3.1.0 的域路由（派哪位专家）在三个断点上失效，导致「专家派发」沦为自觉行为而非门禁：

1. **只读任务硬跳过域路由**：`zcode_dev_workflow.py:622-627` 对 readonly 直接 `return plan`，`dispatches:[]`，不派任何专家——实测 `plan "分析一下这个模块的架构"` 返回空派发。
2. **轻量/机械任务可绕过**：hook 提示（`hooks/prepend-global-rules-reminder.mjs` ③ 条）与 `SKILL.md:62` 明文写「纯机械任务不强制派专家」，在提示层发放豁免许可证。
3. **路由失败静默降级**：`zcode_dev_workflow.py:657-692` 路由异常时静默换 `general-purpose`，无门禁拦截、无降级标记。

2026-11-17 老板明示硬性要求：**不管只读/轻量/中/大/Bug，都必须根据任务派遣对应领域专家，这是硬性门禁，不可跳过**。

## What Changes

- 两轴（规模分诊 × 领域路由）在 S0 内强制串联，`triage` 命令双轴合一输出；
- 只读任务新增 **analyst 角色**派发（subagent_type = 领域专家中文名），消灭 readonly 零派发；
- 域路由失败**显式降级三件套**（degraded=true + plan.blocking + 派发行 note），领域结论禁止由 general-purpose 产出；
- `workflow_check.py` 新增 **S0.DOMAIN 检查项**，按老板裁决 A 案**全规模账本执法**；
- 只读任务落盘 **dispatch.json**（老板裁决：做）作为文件级审计锚点；
- 版本 bump **3.2.0**（老板裁决：bump，六处联动）。

## 影响范围

代码 2（zcode_dev_workflow.py、zcode_expert_system.py 加可选参数）、配置 1（workflow.json 六处）、hook 1、文档 9（SKILL.md、stage-S0、workflow-tree、fusion-design、README×2、角色契约+1、命令 3）、模板 1、核对器 1（workflow_check.py）、测试 3+1 新增、版本号 6 处。

## 不包含什么

- `classify_scale` 规模判定逻辑（规模轴本身无缺陷）；
- `zcode_expert_system.py` 路由算法（词元粗筛 + 主控语义精判架构不变）；
- 九阶段结构 S1-S8、七态状态机、OpenSpec 产物格式；
- 331 专家人格内容与 categories.json 映射。

## 老板裁决记录（2026-11-17）

| # | 裁决项 | 结果 |
|---|---|---|
| 1 | S0.DOMAIN 执法范围 | **A：全规模账本执法**（light 以上有账本任务缺 Triage 域路由行即 FAIL） |
| 2 | readonly dispatch.json 落盘 | **做**（复核确认：**审计锚点定位**——测试契约锁正确性、老板可查，不进 workflow_check 执法） |
| 3 | 版本号 | **3.2.0** |
| 4 | 推进方式 | **完整九阶段** |
| 5 | 产物亲审修订 | **10 处修订全部落盘**（#1-#8 + #10 Scale 双语识别 + #11 账本关联性），实机验证 8 项声明全证实 |
