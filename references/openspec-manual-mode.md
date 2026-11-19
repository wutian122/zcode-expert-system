# OpenSpec 手工模式（CLI 不可用时）

当 `scripts/openspec_engine.py` 不可用（未部署、无 Python、仓库损坏）或老板明确要求手工操作时使用本文件。
本文件只声明**手工等价路径**，不改变 `config/workflow.json` 的唯一声明地位——阶段、门禁、产物路径仍以其为准。

## 一、何时使用

| 触发条件 | 动作 |
|---|---|
| `python scripts/openspec_engine.py list --root <根>` 报错/无输出 | 进入手工模式 |
| 宿主环境无 Python | 进入手工模式 |
| 老板明确说「手工走 OpenSpec」 | 进入手工模式 |

**不适用**：老板已用 CLI 正常驱动变更时——此时仍以 CLI 输出为真相，不要切手工模式。

## 二、手工等价路径（逐产物）

OpenSpec 变更目录位于 `openspec/changes/<change>/`，四件产物 + 元数据：

### 1. `openspec/changes/<change>/.openspec.yaml`（手工等价 `new-change`）

新建 change 目录后手工写入（LF 行尾）：

```yaml
schema: spec-driven
name: <change>
created: <YYYY-MM-DD>
status: pending
requires: <逗号分隔的 requires 列表；无则留空>
applyRequires: <逗号分隔的 applyRequires 列表；无则留空>
```

### 2. `proposal.md`（手工等价 `instructions proposal`）

手写：为什么做、现状问题、目标、影响范围、不包含什么。模板见 `templates/minimal-contract.md` 的 proposal 段。

### 3. `design.md`（手工等价 `instructions design`）

**唯一设计真相**：架构、模块职责、数据结构、API、核心流程、安全兼容、风险。模板同上。

### 4. `specs/<capability>/spec.md`（手工等价 `instructions specs`）

每个能力一个子目录，写 `spec.md`：

```markdown
## Requirement: <能力名>

### Scenario: <场景名>
- WHEN <条件>
- THEN <预期>
- AND <附带预期>
```

### 5. `tasks.md`（手工等价 `instructions tasks`）

- 每个任务一条 `- [ ] N.M 描述`（列表符支持 `-` `*` `+` 与 `1.`/`1)`）
- 每条任务必须可勾选、可验收
- **勾选口径：只有 `- [x]` / `- [X]` 算完成**（与 `openspec list --json` 一致），其他异形标记一律未完成

### 6. 状态自检（手工等价 `status`）

状态只判**文件存在性**：

- `proposal.md` / `design.md` / `tasks.md` 存在 → done
- `specs/` 下存在任一 `<cap>/spec.md` → done

### 7. 手工归档（等价 `archive-change`）

七条件逐条为真，缺一不可归档：
- [ ] 所有必须完成的任务已完成（tasks.md 全 `- [x]`）
- [ ] 规格与实现一致
- [ ] 测试验证通过
- [ ] 代码审查通过
- [ ] 无未解决阻断问题（`.status.json` 无 `parked: true`）
- [ ] 交付状态符合要求
- [ ] 必要文档已更新

归档动作：`openspec/changes/<change>/` → `openspec/changes/archive/YYYY-MM-DD-<change>/`（日期不叠）。

## 三、手工模式下的机械核验

手工模式无法跑 `workflow_check.py`（它依赖 `--change` 目录结构），但可以用以下等价手段自检：

| 检查项 | 手工等价命令 |
|---|---|
| 完成度只认 x/X | `grep -c '^- \[x\]\|^\* \[x\]\|^+ \[x\]' openspec/changes/<change>/tasks.md` |
| 未完成项 | `grep -c '^- \[ \]\|^\* \[ \]\|^+ \[ \]' openspec/changes/<change>/tasks.md` |
| 归档目录日期不叠 | `ls openspec/changes/archive/ | grep <change>` 应无同日重复 |
| PARKED 残留 | `grep -i 'parked' openspec/changes/<change>/tasks.md openspec/changes/<change>/.status.json` 应无命中 |

## 四、回退到 CLI

手工模式产出的目录与 CLI 产出的目录**结构完全一致**，修复环境后可直接恢复 CLI：

1. 修好 Python / 重新部署 `scripts/openspec_engine.py`
2. `python scripts/openspec_engine.py status --change <change>` 应能正确读取手工产物
3. 若产物缺漏，按 status 返回的 `products` 补齐后再继续