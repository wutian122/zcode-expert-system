---
description: 工作流完整性核对 —— 机械检查阶段产物与证据是否齐备
name: wf-check
---

# /wf:check

按唯一声明源 `config/workflow.json` 核对当前阶段证据。**不靠自觉，机械可验。**

## 执行

```bash
python "$ZCODE_PLUGIN_ROOT/skills/zcode-expert-system/scripts/workflow_check.py" --change <change> --plan <plan.md> --scale <scale>
```

`--json` 取结构化输出供脚本消费。

## 核对项（9 个门禁 / 30+ 检查点）

| 门禁 | 核对内容 |
|---|---|
| G0 | 环境探测 / 规模已分类 / 变更名格式 / 规模与账本一致 / **S0.DOMAIN**（账本 Triage 域路由两行：无账本 SKIP、不可读 FAIL `malformed_ledger`、readonly SKIP、非只读缺行 FAIL `s0_domain_missing`） |
| G1 | 设计未违规落盘（R3） |
| G2 | 变更目录存在 / proposal / design / tasks / delta specs / .openspec.yaml |
| G3 | 计划必备段（按 scale 裁剪）/ `### Task N:` 格式 / 无占位符 / 双账本对齐 |
| G4 | **基线主副本在计划文档** / 账本存在 / 账本首行身份（INV4） |
| G5 | brief + report 存在 / **三元对齐**（任务号集合相等，退化时比计数） |
| G6 | **审查独立性标记 L0/L1/L2**（取最坏值）/ Rulings 持久化 / Review 段含结论载体 |
| G8a | **集成后重测已记录** |
| G8b | 完成度（只认 x/X）/ 无 PARKED 残留 / 主 spec 逐能力同步 / 归档目录 |

> **G7 不在本表**：G7（验证门禁）判定的是「所需验证是否全部通过且为本会话证据」，
> 这需要读命令输出与退出码，纯文件系统核对无法断定。G7 由主控按
> `superpowers:verification-before-completion` 的门函数 5 步人工执行并落 `## Review` 段，
> 本脚本只能核对「`## Review` 段里有没有结论载体」——**不能替代 G7 本身**。
>
> （缺陷 #24 族：本节标题此前写「13 类」，表格只有 9 行，脚本实际 30+ 个检查点，
> 三个数字互不相同。现改为「9 个门禁 / 30+ 检查点」并显式说明 G7 的归属。）

## 退出码

- `0` — 无 FAIL，可进下一阶段（WARN 需人工确认）
- `1` — 有 FAIL，**不得进下一阶段**
- `2` — 参数/环境错误

## 为什么必须机械核对

**纯 Markdown 检查表一定会被跳过。** 本脚本专门抓七类最容易静默丢失的环节：

1. 基线只写 ledger → 删 workspace 后消失
2. Reviewer 独立性降级后不留痕
3. 集成后重测沿用旧结果
4. delta spec 从 design.md 推断而非 `existingOutputPaths`
5. 为清目录提前归档
6. Ruling 随 workspace 删除
7. tasks.md 勾选与 ledger 不符

## 常见 FAIL 与修法

| FAIL | 修法 |
|---|---|
| `s0_domain_missing` | 在账本 `## Triage` 段补「领域（category）」与「专家（name/basis）」两行（S0 即产生，按当时实际路由事实补记并记 Ruling） |
| 基线主副本缺失 | 把 S4 基线记录写入计划 `## Baseline` |
| 三元对齐不符 | 核对 git/快照实际变更，修正 ledger 与 tasks.md，记 Ruling |
| 独立性标记缺失 | 补 `independence: L0/L1`；L2 禁止交付 |
| Rulings 未持久化 | 从 ledger 导出全部 `Ruling:` 行到计划 `## Rulings` |
| 集成后重测未记录 | 在目标树重跑全量测试并写入 `## Integration Verification` |
| PARKED 残留 | 迁出到新 change，或终审裁决后勾选 |
