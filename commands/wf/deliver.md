---
description: S7 交付 —— 老板选交付方式 + 集成后重测 + workspace 导出
name: wf-deliver
---

# /wf:deliver

## 前置

- 绿树（S6 通过）
- 老板已看到 `Rulings I made`
- 无 Critical/Important 未处置

## 1. 交付方式（停老板，三选一）

| 选项 | 说明 |
|---|---|
| 1. 合并 | 合到基分支 |
| 2. 推并建 PR | `gh` 建 PR |
| 3. 保留分支 | 暂不合并 |

> **丢弃不出现在菜单。** 仅老板明说丢弃 + 输入 `discard` 才执行，且禁用 `--force`。
> 无 git → 标"不适用（无分支收尾条件）"，改为**改动清单验收**。

## 2. 集成后重测（G8a 核心）

**在目标树上重跑全量测试，不得沿用集成前结果。**

写入计划文档：

```markdown
## Integration Verification
- command: pytest -q
- exit: 0
- passed: 142, failed: 0
- tree: <合并后分支 / 当前树>
```

**未写入此段，不得进 S8。**

## 3. workspace 导出（删前必做）

`.superpowers/sdd/<plan>/` 在终审 clean 后才可删。**删前必须导出到 P3**：

- 全部 `Ruling:` 行 → 计划 `## Rulings`
- 基线 → 计划 `## Baseline`（S4 已双写）
- 审查结论与独立性 → 计划 `## Review`
- 集成后重测 → 计划 `## Integration Verification`

**未导出禁止删。** 否则老板永远看不到"我做了哪些裁决"。

## 4. 清理

只清理 `.worktrees/`、`worktrees/` 或老板声明偏好目录下**自建的**。
删除被拒 → 列未提交文件，请老板三选一（提交/移出/删除）。

## 退出条件（G8a）

- [ ] 集成后全量测试已重跑并见绿
- [ ] 交付方式由老板选定
- [ ] 命令与退出码已写入 `## Integration Verification`
- [ ] `--force` 未使用
- [ ] workspace 已导出后才删（或保留）

## 失败返回点

| 失败 | 返回 |
|---|---|
| 集成后红 | **停**，原地保留 → 回 `/wf:verify` 定位 |
| 基分支判断错 | 集成前必须确认；错则回滚（代价高） |

## 交付时必须汇报

**"Rulings I made"** —— 账本中每一条裁决按序全量列出。这是老板知情权的底线。

下一阶段：`/wf:archive`
