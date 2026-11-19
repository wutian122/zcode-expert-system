# S0 · 需求接收与任务分诊

**门禁**：G0 ｜ **证据级**：P4 ｜ **角色**：Orchestrator

## 输入

- 老板原始请求
- 项目 `AGENTS.md`
- 工作区事实：是否 git、`openspec_engine.py list --root <根>` 的 root、有无 `.codegraph`

## 动作

```bash
python "$ZCODE_PLUGIN_ROOT/skills/zcode-expert-system/zcode_dev_workflow.py" triage "<任务>" --files N
```

1. 探测环境（**只读，不产生副作用**）
2. 规模分诊：只读 / 轻量 / 中任务 / 大任务 / Bug（`triage` 已双轴合一——规模 + 领域路由一次产出）
3. **说出口**：「老板，任务分类结果：____」
4. 域路由确认：读 triage 输出的 `domain`（category / 专家名 / `score_detail`）；`semantic_selection_required=true` 时**主控亲自语义精判**
5. **说出口**：「领域路由：category=____，专家=____」
6. 按规模取裁剪表：`workflow.json` → `trim_matrix`
7. 写任务（轻量 / 中 / 大 / Bug）落账本 `## Triage` 段（13 项）

## 分诊 13 项（双轴分诊所有写任务必填）

任务名 / 类型 / 用户目标 / 涉及模块 / 预估影响范围 / 是否改数据库 / 是否改 API / 是否需多 Agent / 是否需老板确认 / 是否需隔离 / 验收标准 / **领域（category）** / **专家（name/basis）**

> 只读任务不产生账本（D4）：S0 双轴分诊后直接派 **analyst**（领域专家只读分析，四段式输出），
> S0.DOMAIN 对其判 SKIP（`workflow_check`）。

## 退出条件（G0）

- [ ] 分类已在会话内说出口
- [ ] 主要影响面已识别
- [ ] 无阻塞性歧义
- [ ] 环境已探测并按分支分流
- [ ] 域路由已完成并说出口（category + 专家名）

## 失败返回点

| 失败 | 返回 |
|---|---|
| 老板说"你决定" | 停，回问——**不得自定规模** |
| 歧义无法消解 | 停，问老板，**不得带歧义进 S1** |
| `root: null` 且非老板点名要 OpenSpec | 静默放弃 OpenSpec，按普通请求作答，**不提 setup** |
| `root: null` 且主管道已启动/老板点名 | 停，三选一：`init` / `--store <id>` / 不用 |
| `status` 报 `Declared in` 开头错误 | 停，展示 message + fix——**这不是未初始化** |
| 域路由 conf=0 / 无专家 | 停，两档并存陈述：疑似闲聊（直接问候回应，不走专家体系）或真无信号（问老板澄清领域，或 `build_dispatch_for_expert(专家名, 任务)` 指定）——**不做机械闲聊判定** |
| 域路由异常（`degraded=true`） | 显式降级三件套：`domain.degraded=true` + `plan.blocking` + note 如实——**不得静默按通识继续** |

## 关键约束

- **绝不副作用建根**：不自动 `init`、不手建 `openspec/`、不让命令顺手建
- 规模只能升级不能降级
- Bug 优先于规模判定（Bug 有专门根因流程，规模判定会让它走错路）
