# v3.2.1 P2 修复 规格（delta）

## ADDED Requirements

### Requirement: P2-1 总经理提示词专家数一致性
系统 MUST 保证 agents/manager-*.md 中每个文件“从管辖的 N 位专家中选择”的 N 与 config/categories.json 的 expert_count 一致。新增一致性门禁测试 test_manager_prompt_expert_counts_match_categories，23 个文件的 46 处数字已修正。

### Requirement: R-1/R-2 hook 路由触发与复核专家
hook REMINDER 触发条件改为全称式“所有任务都必须先走两轴路由”，删除条件式“任务属 32 领域之一”；新增 R-2：“复核/审查任何产出（含主控自己的产出）属于领域判断，必须派独立专家（实施者≠审查者）”。SKILL.md:62 同步。

### Requirement: P2-4 git 探测 root 线程化
build_dispatch_plan 增加 --root 参数，detect_git 从 root 起探测而非 cwd，避免假阳性伪造 L0。默认 None 保持向后兼容。

### Requirement: P2-2/P2-5 状态机死字段清除
config/workflow.json states 删除 terminal 与 counts_as_complete 两个零消费字段；states_summary 不再透传；13 条 transitions 不动。

### Requirement: P2-3 install.js 单写对齐
vendored zes-* 技能安装与卸载均只作用于插件缓存 pluginRoot/skills，删除了卸载侧 zcodeDir/skills 死路径。

### Requirement: 版本 bump v3.2.1
package.json/.zcode-plugin/plugin.json/config/workflow.json/SKILL.md/skill_entry.py/config/experts.json/README.md/README_CN.md 全部 3.2.1。
