# PROVENANCE — vendor 技能出处、许可与覆盖声明

本目录收录的 9 个技能文本均来自 **Superpowers 7.0.1**，按 MIT 许可再分发，
仅作只读参考与方法论依据。实际执行以本插件 `SKILL.md`、`references/stage-S*.md`
与 `references/roles/*.md` 为准；两者冲突时以插件规则为准。

## 上游

| 项 | 值 |
|---|---|
| 项目 | Superpowers `7.0.1` |
| 仓库 | https://github.com/obra/superpowers |
| 作者 / 版权 | Copyright (c) 2025 Jesse Vincent |
| 许可 | MIT（全文见同目录 [`LICENSE`](LICENSE)） |
| 内化来源 | ZCode 插件缓存 `claude-plugins-official/superpowers/7.0.1/`（只读） |
| 内化日期 | 2026-11-17 |

## 改名映射

每份 SKILL.md 的 frontmatter `name` 与所在目录同名，均为 `zes-` 前缀；
除 `name` 与新增的 `license: MIT` 外，frontmatter 其余字段原样保留。

| 上游技能（原名） | 本插件技能名（zes- 前缀） | 收录文件 |
|---|---|---|
| `brainstorming` | `zes-brainstorming` | SKILL.md、builder-check-prompt.md |
| `writing-plans` | `zes-writing-plans` | SKILL.md |
| `subagent-driven-development` | `zes-sdd` | SKILL.md、references/ 下 7 个 md |
| `test-driven-development` | `zes-tdd` | SKILL.md、writing-good-tests.md |
| `verification-before-completion` | `zes-verification` | SKILL.md |
| `requesting-code-review` | `zes-code-review` | SKILL.md |
| `receiving-code-review` | `zes-receiving-review` | SKILL.md |
| `finishing-a-development-branch` | `zes-finishing` | SKILL.md |
| `systematic-debugging` | `zes-systematic-debugging` | SKILL.md、root-cause-tracing.md、defense-in-depth.md、condition-based-waiting.md、find-polluter.sh |

## 覆盖点清单

每份 SKILL.md 顶部（frontmatter 之后、正文首个标题之前）均插入
「插件规则优先（zcode-expert-system）」声明块。上游指令与本插件规则冲突时，
以以下覆盖点为准：

1. **不落盘**：S1 设计只在对话内展示与批准，禁止写入 `docs/superpowers/specs/`（插件 R3/W2）。
2. **不用 worktree**：实施永远串行，无隔离工作区（插件 W1）。
3. **无 model 参数**：Agent 派发不接受 model，升档=换更专专家（插件 W9）。
4. **派发模板不收录**：`implementer-prompt.md` / `task-reviewer-prompt.md` /
   `re-review-prompt.md` 三个模板以插件 `references/roles/*.md` 为准
   （上游模板要求 model 参数与 commit，与本插件 W9 / 无 git 基线冲突）。
5. **`code-reviewer.md` 不收录**：改用插件 `templates/review-report.md` +
   `references/roles/reviewer.md` 的双结论（spec + 质量）。

## 排除清单与理由

按精确清单执行，不收上游其余文件。上游正文中对被排除文件的交叉引用按原样
保留（「只读参考」定位），实际执行一律以本插件产物为准。

| 源技能 | 排除文件 | 理由 |
|---|---|---|
| brainstorming | `scripts/*` | visual-companion 服务器（62KB），R8 默认不启用 |
| brainstorming | `visual-companion.md` | 同上（visual-companion 默认不启用） |
| subagent-driven-development | `scripts/*` | 已内化到本插件 `scripts/sdd/`，避免重复 |
| subagent-driven-development | `implementer-prompt.md`、`task-reviewer-prompt.md`、`re-review-prompt.md` | 要求 model 参数与 commit，与本插件 W9 / 无 git 冲突，已被 `references/roles/*.md` 取代 |
| requesting-code-review | `code-reviewer.md` | 上游只有 git diff + 单结论；本插件用 `templates/review-report.md` + `references/roles/reviewer.md` 双结论 |
| systematic-debugging | `condition-based-waiting-example.ts`、`CREATION-LOG.md`、`test-academic.md`、`test-pressure-1.md`、`test-pressure-2.md`、`test-pressure-3.md` | 上游开发期测试产物，非工作流运行所需 |
| writing-plans、test-driven-development、verification-before-completion、receiving-code-review、finishing-a-development-branch | 无 | 全量收录（仅 SKILL.md 及其被引用的依赖文件） |
| （根） | 除 `LICENSE` 外无 | `LICENSE` 原样复制 |

未内化的上游技能（`using-superpowers`、`using-git-worktrees`、`executing-plans`、
`dispatching-parallel-agents`、`writing-skills`、`diagnosing-superpowers`）不设目录，
由本插件自有规则与技能承担对应职责。

## 同步方法

上游升级时：

1. 按「改名映射」表重新复制对应文件（依赖文件原样复制，`LICENSE` 一并更新）；
2. 每份 SKILL.md 重新执行 frontmatter 改造（`name` 改为 `zes-` 名、保留其余字段、
   加 `license: MIT`），并重新插入声明块；
3. 重新核对「排除清单」，确认排除项未被误收、不内化技能未建目录；
4. 更新本文件顶部的上游版本、内化日期与改名映射表；
5. 运行 `python -m pytest tests/test_vendor_skills.py -q` 验证。