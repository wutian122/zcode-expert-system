# 工作流组件内化实施计划（方案 A：注册为独立技能）

> **Spec**: 本计划自承载（项目无 openspec root，按插件 S2 双分支规则走简化路径）
> 日期：2026-11-17 ｜ 规模：中任务 ｜ 执行模式：SDD（老板批准）
> 设计依据：2026-11-17 软件架构师内化设计报告（老板选定方案 A + P0-P2）

## Goal

把工作流硬依赖的 3 个 bash 脚本内化进插件，把 9 个方法论文本以**独立插件技能**形态收编，消除对 Superpowers 插件的运行时依赖；同时修掉 `workflow.json` 的 5 个假技能名与 `workflow_check.py` 的组件校验缺口。完成后外部依赖矩阵：**Superpowers 插件 = 非必需；openspec 技能 = 非必需；OpenSpec CLI = 完整模式增强（保留硬依赖，P3 才做手工降级）；/opsx = 不使用**。

## Architecture

```
新增 vendor/skills/<zes-技能名>/      ← 9 个技能源码（仅源码树，install.js 部署到插件 skills/ 兄弟目录）
新增 scripts/sdd/{sdd-workspace,task-brief,review-package}   ← 三脚本内化（no-git 修复）
改 scripts/install.js                  ← 多技能兄弟部署 + 部署清单 + 卸载 + preflight
改 config/workflow.json                ← 5 个冒号名→连字符 + component_registry
改 scripts/workflow_check.py           ← self_check 第 8 条（registry 路径存在性）
改 references/stage-S4/S5/S6*.md + commands/wf/{env,verify}.md  ← 内部路径
改 SKILL.md + README*.md               ← 组件表与依赖矩阵
```

## Tech Stack

Node.js（install.js，零依赖）· Python 3 标准库（workflow_check.py 与测试）· Bash 3.2+（三脚本，Git Bash 兼容）· pytest

## Spec

### 功能需求

1. **R1 三脚本内化**：`scripts/sdd/` 下三个脚本可被 `bash <path>` 调用；无 git 仓库时 `sdd-workspace` 回落到当前目录建工作区（当前必挂）；`review-package` 无 git 时以 exit 4 + 明确提示结束（走快照差集）；`task-brief` 按 `### Task N:` 抽取。
2. **R2 技能注册**：9 个技能以 `zes-` 前缀命名（目录名与 frontmatter `name` 一致），部署后以 `<plugin>:zes-<name>` 暴露；每份 SKILL.md 顶部含「插件规则优先」声明块，明确三点覆盖：S1 不落盘（R3/W2）、不用 worktree（W1）、无 model 参数（W9）。
3. **R3 部署**：`install.js` 把 `vendor/skills/*` 逐个复制为插件缓存 `skills/*` 兄弟目录；写 `deployed-skills.json` 清单；uninstall 按清单删除；`preflight()` 校验 vendored 资产齐备后才动磁盘；不对 vendored SKILL.md 跑 `normalizeSkillMd`（保留 license 字段）。
4. **R4 登记表**：`workflow.json` 新增 `component_registry`，每个 `stages[].components` 字符串都有登记（internal 路径 + external 可选等价物 + required 布尔）；5 个 `openspec:*` 冒号名改为真实技能连字符名。
5. **R5 机械校验**：`workflow_check.py --self-check` 增加第 8 条：每个 registry 的 `internal` 路径存在；`required: true` 的缺失即 rc=2。
6. **R6 文档一致**：stage-S4/S5/S6 与 commands/wf/{env,verify} 中 `<superpowers>/...` 路径与 `requesting-code-review/code-reviewer.md` 全部改为插件内路径；README 写明依赖矩阵。

### 非目标（本轮不做）

- P3：OpenSpec 手工降级模式（无 CLI 时 S2/S8 仍报错停止）
- 不做 `/opsx` 命令搬运
- 不改 `~/.zcode/AGENTS.md`

## Review Focus

- **技能前缀与命名一致性**：目录名 / frontmatter name / registry 登记名三方一致，否则部署后 Skill 调用名对不上
- **install.js 的删除安全**：卸载只删自己清单里的技能，绝不按前缀扫（P5 安全契约）
- **no-git 回归**：三个脚本在无 git 临时目录的行为必须逐条实测
- **许可合规**：vendor LICENSE + PROVENANCE + frontmatter license 三处齐全
- **不破坏现有 451 测试**：install.js 改动必须保持 P5 安全契约用例全绿

## Global Constraints

- 三脚本保持 Bash 3.2 兼容（macOS 老 bash + Git Bash），统一 `bash <path>` 调用，不依赖执行位
- vendored SKILL.md 不得臆造内容：文本来自 superpowers 7.0.1 原件，只允许在顶部**追加**覆盖声明块，不改写正文
- 技能命名格式：`zes-<kebab-name>`；禁止裸名（避免与外部 superpowers 触发竞争）
- 所有新文件 LF 行尾（脚本必须 LF）
- 现有测试一个不许红；新行为必须有新测试

---

### Task 1: 三脚本内化与 no-git 修复

**Files**:
- 新增 `scripts/sdd/sdd-workspace`（改造：`git rev-parse` 失败回落 `pwd -P`；git 存在才写 `.superpowers/sdd/.gitignore`）
- 新增 `scripts/sdd/task-brief`（原样 + 顶部注释标注来源版本）
- 新增 `scripts/sdd/review-package`（新增 git 探测：非 git 仓库时 stderr 提示走快照差集 + exit 4）
- 新增 `tests/test_sdd_scripts.py`

**Interfaces**:
- Consumes: 计划文件路径（含 `### Task N:` 标题）、git 可选
- Produces: `sdd-workspace <plan>` → 打印工作区绝对路径（no-git 时基于 cwd）；`task-brief <plan> <N>` → 打印任务原文并写 brief；`review-package <plan> <BASE> <HEAD>` → 写 diff 文件（无 git 时 exit 4）

**Steps**:
1. 写失败测试 `tests/test_sdd_scripts.py`：① 无 git 临时目录跑 `sdd-workspace` 返回含 `.superpowers/sdd/` 的路径且 rc=0；② `task-brief` 能抽出 `### Task 2:` 段落；③ 无 git 跑 `review-package` rc=4 且 stderr 含「快照」
2. 跑测试 —— 见 RED（脚本不存在）
3. 从 superpowers 7.0.1 复制三脚本到 `scripts/sdd/`，按上述改造（sdd-workspace 根回落 + review-package git 探测）
4. 跑测试 —— 见 GREEN
5. `git add` + commit（若仓库有 git；本仓库无 git 则记为文件快照）

### Task 2: vendor 技能收编（9 个 + 前缀 + 覆盖声明 + 许可）

**Files**:
- 新增 `vendor/skills/zes-brainstorming/SKILL.md` + `builder-check-prompt.md`
- 新增 `vendor/skills/zes-writing-plans/SKILL.md`
- 新增 `vendor/skills/zes-sdd/SKILL.md` + `references/{batching,cannot-verify,final-review,fix-loop,handling-reports,preflight,resuming}.md`
- 新增 `vendor/skills/zes-tdd/SKILL.md` + `writing-good-tests.md`
- 新增 `vendor/skills/zes-verification/SKILL.md`
- 新增 `vendor/skills/zes-code-review/SKILL.md`
- 新增 `vendor/skills/zes-receiving-review/SKILL.md`
- 新增 `vendor/skills/zes-finishing/SKILL.md`
- 新增 `vendor/skills/zes-systematic-debugging/SKILL.md` + `{root-cause-tracing,defense-in-depth,condition-based-waiting}.md` + `find-polluter.sh`
- 新增 `vendor/skills/LICENSE`（superpowers MIT 全文）
- 新增 `vendor/skills/PROVENANCE.md`（上游仓库/版本 7.0.1/日期/改名映射表/覆盖点清单）
- 新增 `tests/test_vendor_skills.py`

**Interfaces**:
- Consumes: superpowers 7.0.1 缓存目录原件
- Produces: 每个 `vendor/skills/zes-*/SKILL.md` frontmatter 含 `name: zes-<x>`、`description`、`license: MIT`；正文首段为覆盖声明块

**Steps**:
1. 写失败测试 `tests/test_vendor_skills.py`：① 9 个目录都存在且含 SKILL.md；② 每个 frontmatter `name` 以 `zes-` 前缀且与目录名一致；③ 每个 SKILL.md 含「插件规则优先」声明块；④ LICENSE 与 PROVENANCE 存在；⑤ 禁止出现 `using-git-worktrees`/`executing-plans` 目录（不内化清单不得误入）
2. 跑测试 —— 见 RED
3. 复制 9 技能原件，重命名目录与 frontmatter name（加 zes- 前缀），在正文前追加覆盖声明块（模板见下），写 LICENSE 与 PROVENANCE
4. 跑测试 —— 见 GREEN

覆盖声明块模板：
```markdown
> **插件规则优先（zcode-expert-system）**
> 本文件是 Superpowers 7.0.1 `<原名>` 的只读参考，其指令与插件规则冲突时以下者为准：
> - **不落盘**：S1 设计只在对话内展示与批准，禁止写入 `docs/superpowers/specs/`（插件 R3/W2）
> - **不用 worktree**：实施永远串行，无隔离工作区（插件 W1）
> - **无 model 参数**：Agent 派发不接受 model，升档=换更专专家（插件 W9）
> - 其余细节以 `references/stage-S*.md` 与 `references/roles/*.md` 为准
```

### Task 3: install.js 多技能部署

**Files**:
- 修改 `scripts/install.js`（多技能兄弟复制 + `deployed-skills.json` + 卸载清单 + preflight + normalize 跳过）
- 修改 `package.json`（`files` 加 `"vendor/"`、`"scripts/sdd/"`）
- 新增测试 `tests/test_install_multiskill.py`（或并入现有 install 测试文件）

**Interfaces**:
- Consumes: `vendor/skills/*/`、`scripts/sdd/*`
- Produces: 插件缓存 `skills/zes-*` 兄弟目录 + `skills/deployed-skills.json`（记录本次部署的技能名清单）

**Steps**:
1. 写失败测试：dry-run 输出包含 9 个 `zes-*` 技能部署计划；`deployed-skills.json` 机制存在（读源码断言）；卸载逻辑按清单删（源码断言 + 临时目录模拟）
2. 跑测试 —— 见 RED
3. 改 install.js：在现有单技能复制之后，遍历 `vendor/skills/*` 复制到 `pluginRoot/skills/<name>/`；写清单；uninstall 读清单删除（清单缺失时不动，保持 P5 契约）；preflight 增加 vendored 资产校验
4. 跑测试 —— 见 GREEN（含原有 install 安全用例）

### Task 4: workflow.json 登记表与机械校验

**Files**:
- 修改 `config/workflow.json`（5 处冒号名→连字符；新增 `component_registry`）
- 修改 `scripts/workflow_check.py`（`self_check()` 增加第 8 条）
- 新增测试 `tests/test_component_registry.py`

**Interfaces**:
- Consumes: `stages[].components` 字符串集合
- Produces: `component_registry` 覆盖全部组件；self_check 对 registry 路径与 required 资产做存在性校验

**Steps**:
1. 写失败测试：① registry 覆盖所有 stages components（无遗漏）；② 每个 `internal` 路径存在；③ 每个 `scripts` 键指向 `scripts/sdd/` 真实文件；④ `openspec:` 冒号名零出现
2. 跑测试 —— 见 RED
3. 改 workflow.json（改名 + registry）+ workflow_check.py（第 8 条）
4. 跑测试 —— 见 GREEN；跑 `python scripts/workflow_check.py --self-check` 见 rc=0
5. `workflow_check.py` 改动后跑全量 `pytest tests/ -q`

### Task 5: 文档路径一致化

**Files**:
- 修改 `references/stage-S4-env-baseline.md`（`<superpowers>/...` → `${ZCODE_PLUGIN_ROOT}/skills/zcode-expert-system/scripts/sdd/...`）
- 修改 `references/stage-S5-implement.md`（task-brief / review-package 内部路径）
- 修改 `references/stage-S6-verify-review.md`（review-package 内部路径；`code-reviewer.md` → `templates/review-report.md` + `references/roles/reviewer.md`）
- 修改 `commands/wf/env.md`、`commands/wf/verify.md`
- 修改 `SKILL.md`（阶段表主组件列与 registry 同步；相关文件表加 `vendor/skills/`、`scripts/sdd/`；依赖矩阵小节）
- 修改 `README.md` / `README_CN.md`（依赖矩阵：Python/Node/Git Bash 必需；Superpowers 与 openspec 技能非必需；OpenSpec CLI 完整模式必需）
- 新增测试 `tests/test_doc_paths.py`

**Steps**:
1. 写失败测试：插件文档中 `<superpowers>` 与 `requesting-code-review/code-reviewer.md` 零命中；`scripts/sdd/` 路径在 stage-S4/S5/S6 与 commands/wf/env,verify 中各至少 1 处
2. 跑测试 —— 见 RED
3. 逐文件改写路径与说明
4. 跑测试 —— 见 GREEN

### Task 6: 端到端验收

**Files**: 无新增（只跑验证与修复）

**Steps**:
1. `python -m pytest tests/ -q` 全量 —— 必须全绿（基线 451 passed + 新增用例）
2. `python scripts/workflow_check.py --self-check` —— rc=0
3. `node scripts/install.js --dry-run` —— 输出含 9 个 zes-* 技能与 scripts/sdd 资产，零写入
4. `npm pack --dry-run` —— 确认 `vendor/` 与 `scripts/sdd/` 在包内
5. `bash scripts/sdd/sdd-workspace <plans/本计划>` 在无 git 目录实测（临时目录）—— rc=0 且路径含 `.superpowers/sdd/`
6. 输出验收报告（命令 + 退出码 + 结论）

## 任务依赖

```
Task1(脚本) ──┐
Task2(技能) ──┼→ Task3(部署) → Task4(登记表) → Task5(文档) → Task6(验收)
              ┘
```

Task1 与 Task2 无相互依赖，可交换顺序；Task3 依赖 1+2；4/5 依赖 3；6 收尾。