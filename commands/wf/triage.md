---
description: S0 需求分诊 —— 判定任务规模并给出阶段裁剪表
name: wf-triage
---

# /wf:triage

对给定任务做规模分诊，输出分类结论与阶段裁剪。

## 执行

```bash
python "$ZCODE_PLUGIN_ROOT/skills/zcode-expert-system/zcode_dev_workflow.py" triage "<任务描述>" --files <预估文件数>
```

随后 `${ZCODE_PLUGIN_ROOT}/skills/zcode-expert-system/zcode_dev_workflow.py stages <scale>` 取阶段序列。

## 必须输出（说出口，不能不说）

```
老板，任务分类结果：<只读 | 轻量 | 中任务 | 大任务 | Bug>
依据：<脚本给出的 reasons>
领域路由：category=<32 类之一>（conf=<0~1>）
领域专家：<专家名>（basis=<semantic | heuristic | none>）
阶段裁剪：<S0=必, S1=必, ...>
最少门禁：<轻量 7 道 / Bug 9 道>
```

## 判据

- **双轴合一**：`triage` 一次产出规模 + 领域路由——所有任务（含只读与机械任务）都必须完成，不得跳过域路由（W10）
- **只读**：无写动作 → 派 analyst（领域专家只读分析，四段式输出），不进实施流程
- **轻量**：≤3 文件 → 简化流程，但 TDD 与验证不可跳
- **中/大任务**：九阶段完整
- **Bug**：优先于规模，走根因流程

## 铁律

- 规模**只能升级不能降级**
- 老板说"你决定" → 停，回问——**不得自定规模**
- 歧义未消解 → 停，不得带歧义进 S1

## 环境探测（本命令内含）

- `git rev-parse --is-inside-work-tree` → 决定 diff 还是快照证据路径
- `python "$ZCODE_PLUGIN_ROOT/skills/zcode-expert-system/scripts/openspec_engine.py" list` → 读 `root`；`null` 属正常返回，**不重试、不自动 init**
  - 我自选 OpenSpec 且 root=null → 静默放弃，不提 setup
  - 老板点名/主管道已启动 → 停，三选一：`init` / `--store <id>` / 不用

下一阶段：`/wf:design`（轻量任务可直接进 `/wf:implement`）
