# 计划文档必备段模板

> 用法：复制到 `docs/superpowers/plans/YYYY-MM-DD-<feature>.md` 并填充。
> 缺任一必备段，`workflow_check.py` 会报 FAIL。
>
> **本模板覆盖两组段，缺一不可**：
> - **G3 必备段（8）**：Goal / Architecture / Tech Stack / Spec /
>   Review Focus / Global Constraints / Dependencies / File Scope
> - **证据段（4）**：Baseline（S4）/ Review + Rulings（S6）/ Integration Verification（S7）
>
> （缺陷 #13：本节此前只有后半组 6 段，缺 G3 的 6 段，照模板写必被判 6 个 FAIL。）

---

## Goal

> 一句话说明这件事要达成什么。**可验收**，不是「优化一下体验」这类无法判定的话。

```markdown
## Goal

把登录接口的 P95 延迟从 800ms 降到 200ms 以内，且不改变现有 API 契约。
```

---

## Architecture

> 方案骨架：改了哪几层、数据怎么流、为什么是这个结构。
> 只写「决定了什么」，不写「怎么一步步做」（那是 Task 的部分）。

```markdown
## Architecture

- 鉴权从「每次请求查库」改为「Redis 缓存 + 失效广播」
- 缓存键：`auth:{user_id}:{token_version}`
- 失效路径：改密/登出时 bump `token_version`，旧键自然过期
- 不引入新服务，复用现有 Redis 实例
```

---

## Tech Stack

> 本任务实际用到的技术，含版本约束。**不写整个项目的技术栈**，只写这次涉及的。

```markdown
## Tech Stack

- Python 3.13（`functools.lru_cache` 用于纯函数缓存）
- Redis 6.2+（`SET PX` 原子过期）
- pytest 8（`tmp_path` 夹具）
```

---

## Spec

> 指向规格真相源：OpenSpec 变更路径与关键段落。
> 中/大任务必须有 change 名；轻量任务可写「无 OpenSpec 变更」并说明理由。

```markdown
## Spec

- `openspec/changes/login-latency/design.md` 的「缓存失效策略」段
- `openspec/changes/login-latency/specs/auth/spec.md` 的「REQ-AUTH-3」
- 轻量任务写法：`无 OpenSpec 变更（单文件改动，验收标准见 Goal）`
```

---

## Global Constraints

> 逐条写死**具体值**，不写「性能要好」这类形容词。
> 这些约束会被 reviewer 当作硬标准核对。

```markdown
## Global Constraints

- 不得修改 `config/workflow.json` 的 `scale.ratchet` 语义
- 测试必须在 30s 内跑完（当前 3.5s，留余量）
- 不新增第三方依赖（保持零依赖）
- 现有 123 条测试不得变红
```

---

## Dependencies

> 这件事依赖什么、被什么依赖。含**外部依赖的前置条件**与**内部任务顺序**。

```markdown
## Dependencies

- 前置：Redis 实例可达（`redis-cli ping` → PONG）
- 前置：`functools` 无需安装（标准库）
- 被依赖：`docs/superpowers/plans/2026-01-02-login-audit.md` 的 Task 3 需要本任务的缓存键格式
- 无外部服务依赖
```

---

## Baseline

> **必须落在计划文档，不能只写 ledger。** ledger 会在终审后被删，基线证据随之消失。

| 项 | 值 |
|---|---|
| 命令 | `<测试命令>` |
| 退出码 | `<0 / 非0>` |
| 通过/失败 | `<142 passed, 3 failed>` |
| 基线失败清单 | `<文件::测试名 — 失败摘要>` |

> 基线红的三条纪律：①不阻断开工但必须记清单 ②此后每个红项比对清单内/外 ③交付报告列出全部既存红项

---

## Review

```markdown
## Review
- independence: L0        # L0 独立子代理 / L1 主控自审降级 / L2 无审查（禁止交付）
- reviewer: 代码审查员
- implementer: 后端架构师
- spec: ✅ SPEC-OK
- quality: APPROVED
- round: 1
```

---

## Rulings

> **必须落在计划文档。** workspace 删除后，这是唯一能回答"老板不知道的那些决定"的地方。

```markdown
## Rulings

Ruling: 采用 Redis 而非本地缓存 — 多实例需共享状态 — 若部署为单实例则多一层运维成本
Ruling: 任务 3 拆为两个 commit — 迁移脚本需独立回滚 — 若回滚粒度不符则需手工拆
Ruling: 跳过 Task 5 的集成测试 — 该接口无外部依赖 — 若后续接入则漏检
```

格式固定三段，缺一段即不合格：`Ruling: <决断> — <理由> — <错了的代价>`

交付时必须全量汇报给老板（"Rulings I made"）。

---

## Integration Verification

> **集成后重测，不得沿用集成前结果。** 未写入此段不得进 S8。

| 项 | 值 |
|---|---|
| 命令 | `<测试命令>` |
| 退出码 | `<0>` |
| 通过/失败 | `<142 passed, 0 failed>` |
| 目标树 | `<合并后分支 / 当前树>` |

---

## Review Focus

> 审查者的注意力透镜。终审时必须随附本段原文给审查者。

```markdown
## Review Focus
- 并发安全：<具体关注点>
- 错误处理路径：<具体关注点>
- 与既有 <模块> 的接口兼容：<具体关注点>
- <属性标签触发的专项>：<具体关注点>
```

---

## File Scope

```markdown
## File Scope
允许修改：
- src/auth/login.py
- src/auth/models.py
- tests/test_login.py

禁止修改（共享文件，归主控独占）：
- package.json
- src/routes/__init__.py
- migrations/
```
