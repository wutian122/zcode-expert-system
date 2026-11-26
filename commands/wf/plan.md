---
description: S3 实施计划制定 —— 生成可被 task-brief 抽取的计划文档
name: wf-plan
---

# /wf:plan

## 执行

产出 `docs/superpowers/plans/YYYY-MM-DD-<feature>.md`。

模板：`templates/plan-sections.md`（含 Baseline / Review / Rulings / Integration Verification / Review Focus / File Scope 段模板）

## 必备头部

```markdown
## Goal
## Architecture
## Tech Stack
## Spec                ← 指向 openspec/changes/<change>/ 并写明 change 名
## Review Focus        ← 审查者注意力透镜，终审须随附原文
## Global Constraints  ← 逐条原文值
## Dependencies        ← 任务依赖拓扑
## File Scope          ← 允许修改的文件白名单
```

## 任务格式（硬约束）

```markdown
### Task N: [组件名]

**Files**: 精确路径
**Interfaces**:
- Consumes: <签名>
- Produces: <签名>
**Steps**:
1. 写失败测试 <具体断言>
2. 跑它 —— 见 RED
3. 最小实现
4. 跑它 —— 见 GREEN
5. commit
```

标题必须严格 `### Task N:`——`task-brief` 脚本按正则 `^#+[ \t]+Task[ \t]+[0-9]+` 抽取。

一个 Task 覆盖多个 `tasks.md` 叶子时：`### Task 3: 登录接口与校验 (covers 2.1,2.2)`，后缀不影响正则。

## 任务粒度

一个任务应有：明确目标 / 明确输入输出 / 清晰文件范围 / 能独立测试 / 能独立审查 / 能明确判断完成。

**既不要拆成无意义微小任务，也不要把多个业务领域塞进一个巨型任务。**

## Self-Review 五项

- [ ] Spec 覆盖：每个需求有任务承接
- [ ] 占位符扫描：TBD / TODO / "适当的错误处理" / "同 Task N" 零命中
- [ ] 类型与签名跨任务一致
- [ ] Review Focus 各焦点有测试与任务承接
- [ ] 篇幅与规模相称

## 退出条件（G3）

- [ ] 必备段齐全
- [ ] `### Task N:` 数 与 tasks.md 叶子对齐（1 Task ≥ 1 叶子）
- [ ] 无占位符
- [ ] Self-Review 五项全过
- [ ] **执行模式已声明**（`sdd` | `apply-change`，二者互斥）

## 失败返回点

- 规格未覆盖 → 回 `/wf:spec` 补，再回来
- 执行模式未定 → **停，不得默认选**
- 计划与 spec 矛盾 → 以 spec 为准；或回 S2

核对：`${CLAUDE_PLUGIN_ROOT:-${ZCODE_PLUGIN_ROOT:-$QODER_PLUGIN_ROOT}}/skills/zcode-expert-system/scripts/workflow_check.py --change <change> --plan <plan.md> --scale <scale>`

下一阶段：`/wf:implement`
