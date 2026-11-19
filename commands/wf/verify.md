---
description: S6 验证审查 —— 五层验证 + 终审 + 独立性标记
name: wf-verify
---

# /wf:verify

## 五层验证（按任务属性取用）

| 层 | 内容 |
|---|---|
| 一 质量 | 编译 / Lint / 类型 / 静态分析 / 依赖安全 / 格式 |
| 二 单元 | 核心逻辑 / 工具 / 数据处理 / 参数校验 / 异常 / 边界 |
| 三 集成 | 模块调用 / 数据库 / API / 第三方 / 事务一致性 |
| 四 系统 | 完整流程 / 异常流程 / 权限 / 数据状态 / 并发 / 边界输入 / 兼容性 |
| 五 专项 | 按属性标签触发 |

### 专项四域

| 标签 | 追加 |
|---|---|
| 前端 UI | 加载 / 交互 / 表单 / 网络 / 控制台 / 多分辨率（内置浏览器，主代理亲为） |
| 后端 | 返回结构 / 参数校验 / 权限 / 异常 / 日志 / 事务 |
| 数据库 | 迁移 / 字段 / 索引 / 约束 / 一致性 / **回滚验证** |
| 安全 | 认证 / 授权 / 输入过滤 / SQL 注入 / XSS / 敏感信息 / 文件上传 |

## 终审

```bash
bash "${ZCODE_PLUGIN_ROOT}/skills/zcode-expert-system/scripts/sdd/review-package" <plan> <MERGE_BASE> <HEAD>     # 有 git
```

用 `references/roles/reviewer.md` 模板（双结论：spec 符合性 + 代码质量），最强档专家。审查报告写 `review-<N>.md`，对照 `templates/review-report.md` 输出。

**只做一轮修复 wave + 一次 scoped 重审。** 残余裁决汇报老板，不做第二轮。

## verification 门函数（5 步，不可省）

1. 识别证明命令
2. 完整运行（不是抽样）
3. 读输出与退出码
4. 核对输出是否支持声明
5. 才开口

**禁止**：没跑说通过 / 只看汇报认为完成 / 只跑部分说全部 / 拿历史结果当本次证据。

## 审查独立性（必须落盘）

| 级别 | 可交付 |
|---|---|
| L0 独立子代理 | ✅ |
| L1 主控自审降级（须声明） | ✅ |
| L2 无审查 | ❌ **禁止交付** |

写入计划文档 `## Review`：

```markdown
## Review
- independence: L0
- reviewer: 代码审查员
- spec: ✅ SPEC-OK
- quality: APPROVED
```

## Rulings 持久化（防丢）

账本里的 `Ruling:` 行会随 workspace 删除而消失。**必须导出到计划文档 `## Rulings`。**

```markdown
## Rulings
Ruling: <决断> — <理由> — <错了的代价>
```

## 退出条件（G6 + G7）

- [ ] 五层验证按属性全过
- [ ] 门函数 5 步已在本会话执行
- [ ] 独立性已标记 L0/L1/L2
- [ ] **Rulings 已写入 `## Rulings`**
- [ ] 审查结论已写入 `## Review`
- [ ] Critical/Important 已修或已裁决

## 失败返回点

| 失败 | 返回 |
|---|---|
| Critical/Important | 回 `/wf:implement`，**仅一轮** wave |
| wave 后仍 open | 残余裁决 → 汇报老板 |
| 验证红 | 回 S5，不得带红进 S7 |

核对：`${ZCODE_PLUGIN_ROOT}/skills/zcode-expert-system/scripts/workflow_check.py --change <n> --plan <plan.md>`

下一阶段：`/wf:deliver`
