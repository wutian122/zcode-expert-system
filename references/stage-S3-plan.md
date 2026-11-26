# S3 · 实施计划制定

**门禁**：G3 ｜ **证据级**：P3 ｜ **角色**：Orchestrator + 架构类专家

## 输入

- S2 的 `design.md` + `tasks.md`
- 十项计划要素

## 动作

产出 `docs/superpowers/plans/YYYY-MM-DD-<feature>.md`

> **Bug 任务额外要求**：计划必须有 `## Bug Investigation` 段，记录入口分诊、
> 9 问根因、假设三段、分级方案、副作用自查、双确认、RED、red-green 四段
> 复验与全量回归。该段是 P3 证据，不能只留在会话或 P4 workspace。

### 必备头部

```markdown
# <feature> 实施计划

## Goal
## Architecture
## Tech Stack
## Spec            ← 指向 openspec/changes/<change>/ 并写明 change 名
## Review Focus    ← 审查者注意力透镜；终审须随附原文
## Global Constraints  ← 逐条原文值
## Dependencies    ← 任务依赖拓扑
## File Scope      ← 允许修改的文件
```

### 任务格式硬约束

```markdown
### Task N: [组件名]

**Files**: 精确路径清单
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

标题必须严格 `### Task N:`（`task-brief` 脚本按此正则抽取）。若一个 Task 覆盖多个 `tasks.md` 叶子，标 `(covers 2.1,2.2)`——后缀不影响正则。

### 任务依赖拓扑

```
数据库设计 → 后端数据层 → 后端业务接口 → 前端页面 → 前后端联调 → 系统测试
```

有依赖按序执行；无依赖才可考虑并行（但**本体系实施永远串行**，见 W1）。

## 退出条件（G3）

- [ ] 必备段齐全
- [ ] **Bug 规模：`## Bug Investigation` 段齐全，且含入口/根因/假设/方案/双确认/RED/red-green/全量回归**
- [ ] `grep -c "^### Task " <plan>` 与 tasks.md 叶子数对齐（1 Task ≥ 1 叶子）
- [ ] 无占位符：TBD / TODO / "适当的错误处理" / "同 Task N"
- [ ] Self-Review 五项全过
- [ ] **执行模式已声明**（`sdd` | `apply-change`）

### Self-Review 五项

- [ ] Spec 覆盖：每个需求有任务承接
- [ ] 占位符扫描：零命中
- [ ] 类型与签名跨任务一致
- [ ] Review Focus 各焦点有测试与任务承接
- [ ] 计划篇幅与任务规模相称（不过粗不过碎）

## 失败返回点

| 失败 | 返回 |
|---|---|
| 自审发现规格未覆盖 | 回 S2 补 spec，再回 S3 |
| 执行模式未定 | 停——**不得默认选** |
| 计划与 spec 矛盾 | 以 spec 为准改计划；或回 S2 修订 |

## 任务粒度原则

一个任务应当：有明确目标 / 有明确输入输出 / 有清晰文件范围 / 能独立测试 / 能独立审查 / 能明确判断完成。

既不要拆成无意义的微小任务，也不要把多个业务领域塞进一个巨型任务。
