# 审查报告模板

> 文件名 `review-<N>.md` 的 **N 是审查轮次，不是任务号**；一次审查覆盖多个任务时仍写 `review-1.md`。
> `review-<range>.diff` 是变更集文件，不用于审查报告命名。
>
> 独立性：`L0` = 独立审查可交付；`L1` = 自审降级可交付须声明；`L2` = 无审查，禁止交付。

```
VERDICT: APPROVED | NEEDS_FIX | BLOCKED
SPEC: ✅ SPEC-OK | ❌ SPEC-FAIL
QUALITY: APPROVED | NEEDS_FIX | BLOCKED
TASK: <N>
REVIEWER: <专家名>
INDEPENDENCE: L0 | L1 | L2
```

## 规格对照

| # | brief 要求 | 实现位置 | 判定 |
|---|---|---|---|
| 1 | | `file:line` | ✅ / ❌ |

## 发现

### Critical（必须立即修）
- `file:line` — <问题> — <为什么严重>

### Important（前进前修）
- `file:line` — <问题>

### Minor（记录，不进修复循环）
- `file:line` — <问题>

## 超范围检查

> 专家人格最容易犯的错：做得比 brief 要求的更彻底。

- [ ] 无超出 `File Scope` 的改动
- [ ] 无 brief 未要求的新功能
- 超范围项：<无 / 列出>

## 无法从变更集判断的项

> 这些由主控裁决，不由你猜。

- <项> → 需要看 <什么> 才能判断

## 测试真实性

- [ ] 测试驱动真实行为（非仅断言无异常）
- [ ] 测试名描述它要抓的破坏
- [ ] 未见"写了测试文件代替跑测试"

## 回归风险

<是否可能破坏既有功能；依据>
