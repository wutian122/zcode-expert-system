# ZCode 专家体系 · 2026-11-16 晚审计发现修复计划

> 生成日期：2026-11-16
> 依据：2026-11-16 晚主控审计简报（P8 收尾 / 工具精度 / 发布链 / context 死特性 / hook 注入面），
> 全部 file:line 锚点已由规划阶段逐一 Read/Grep 抽验。**本文件只做规划，未修改任何代码。**
> 格式先例：`docs/superpowers/plans/2026-11-16-defect-remediation.md`（无 git 环境批次格式）。
> 文中行号为 2026-11-16 实测值；实施时若遇 ±5 行漂移，以锚点描述的代码特征为准定位。

---

## Goal

把 2026-11-16 晚审计发现的五类问题收口到可验收状态：

1. **假绿面**：`workflow_check.py` 的「不可读 ≠ 空 ≠ 缺失」三态混同（6 处 `read(...) or ""` +
   4 处 `if ctx[...] else None` 混同），以及「测试假通过」式的守卫弱断言。
2. **死特性面**：context 持久化「宣称已修实测未修」的接线断裂；
   `config/workflow.json` 声明 `required:true` 却无人消费的 `review-<N>.md`。
3. **发布链面**：npm 包名迁移（`zcode-expert-system`）、tarball 白名单混入开发残留、
   install.js 把用户 `tests/` 当插件产物、agents 覆盖不备份、第三方供应链推广段。
4. **注入面**：hook 把账本字段（`\S+` 裸捕获）未消毒注入每轮上下文。
5. **精度面**：BUG_SIGNALS ASCII 裸子串误判、`workflow_check.py` 缺输出编码地基。

**验收口径**：`python -m pytest tests/ -q` 全绿（基线 5 failed / 405 passed / 2 skipped →
既有 5 条 RED 全部转绿 + 各批新增用例全绿）；每处行为修复有 RED→GREEN 证据；
发布类动作只做到「发布前准备」，不执行发布。

---

## Review Focus（审查子代理 / 主控自审的注意力透镜）

本次审计的三个风险族，每族给出「审查时必问的问题」：

| 风险族 | 历史教训 | 审查必问 |
|---|---|---|
| **假绿**（测试假通过 / 三态混同） | ① 17/17 双向误判（P6）；② A-6 三条用例「通过」但走的是兜底路径；③ `review` in id 被 `S6.REVIEW` 子串假满足；④ A-15 教训：放宽判定造新假绿 | 断言是否**双向**（该判的判了 + 不该判的没判）？夹具是否堵死所有兜底路径？修复是否把「查不了」印成「查过且干净」？ |
| **死特性**（宣称已修实测未修） | context_summary 注释写「已修」但恒空串（P1 #12）；`required:true` 产物全文不读 | 每个修复是否**从调用方真跑一遍**（全新进程 / 全新实例）？声明（workflow.json / SKILL.md / README）与行为是否一致？ |
| **发布链**（改名的连锁面） | tarball 混入 `scripts/__pycache__/*.pyc` 与 `docs/superpowers/plans` 开发残留 | 包名/URL/cd 目录四处是否同步？files 白名单收窄后 tarball 清单是否干净？供应链推广段（agenticbtc）是否零残留？ |

---

## Global Constraints（老板既定裁决，2026-11-16，勿再问）

1. **不 `git init`**；每批动手前 `cp -r` 整树快照到 /tmp（排除 `.mimosa`/`__pycache__`/.pytest_cache）
   作唯一回滚手段（Task 0 固化命令）。
2. **批次严格串行**（无 worktree 隔离）；审查独立性固定 **L1（主控自审）**，交付中显式声明；
   验收 = pytest 全绿 + 夹具前后对照。
3. **TDD 不可跳**：每处行为修复先见 RED；断言必须双向（该判的判了 + 不该判的没判）。
4. **Mimosa 拦截规避**：Bash 命令含 `install.js` 等脚本路径会被误拦——核对/编辑该文件一律用
   Read/Edit 工具；验证脚本行为用 `python - <<'PY'` 内联 import。
5. **npm 改名已拍板**：包名 `zcode-expert-system-plugin` → `zcode-expert-system`；
   README 安装命令与 cd 目录用新名后恰好自洽；repository URL 同步改。
   **发布动作本身仍须老板明示授权**——本计划只做发布前准备（Task 12 标注）。
6. **context 接线复活已拍板**：理由 = SKILL.md 已对外宣称 + 落盘/加载基础设施已有八成 +
   不接线 =「宣称已修实测未修」复发；接线成本中等可测。
7. **A-9 / A-14 / A-15 裁决沿用**（`tests/test_p8_precision.py:7-34` 裁决记录）：
   A-9 修有 rc 后果的 + AST lint 防复发；A-14 最小范围（review 检查补齐 + **先实现
   「workspace 已删 → inapplicable」防跨阶段假红**）；A-15 不实现 `条` 触发引擎、
   把「条 当前等价于必」写进设计文档。

---

## Architecture

### 分批结构（5 批 + 每批前置快照）

分批原则：① 先清既有账（5 条 RED 已在 test_p8_precision.py 挂账）；② 同一文件的根因簇
一次改完（批次一、二都在 `scripts/workflow_check.py` 上，紧邻执行避免跨批回改同文件）；
③ 批次四（context）独立性强、保持简报原顺序；④ 收尾批（hook + 全量验证）必须最后。

| 批次 | 主题 | 任务 | 主要文件 |
|---|---|---|---|
| **一** | P8 收尾（A-9 / A-14 / 文档义务） | Task 1-3 | `scripts/workflow_check.py`、`tests/test_p8_precision.py`、3 份文档 |
| **二** | 核对工具精度族 | Task 4-6 | `scripts/workflow_check.py`、`zcode_dev_workflow.py` |
| **三** | 发布链（改名决策落地） | Task 7-12 | `package.json`、`scripts/install.js`、agents、README×2、SKILL.md |
| **四** | context 接线复活 | Task 13-14 | `context/context-manager.py`、`zcode_expert_system.py` |
| **五** | hook 加固 + 全量收尾 | Task 15-16 | `hooks/prepend-global-rules-reminder.mjs`、全仓 |

**每批节奏**：Task 0 快照 → 逐任务 TDD（RED → 最小实现 → GREEN）→ 批末
`python -m pytest tests/ -q` 全绿 → 主控 L1 自审核对清单（对照本计划 Files 清单逐文件核）。

### 批次间无依赖声明

批次三、四互不依赖，可按老板指令调换；批次一、二因共享 `workflow_check.py` 必须
一→二顺序；批次五依赖全部前序批次的测试集。

---

## Tech Stack

- Python 3.13 + pytest（现有 17 个测试文件、412 条用例：405 passed / 5 failed / 2 skipped）
- Node.js v24（hooks / install.js / bin/cli.js）
- npm（仅本地 `npm pack --dry-run`；registry 查询与发布动作见 Task 12 的授权标注）
- 无 git（快照即回滚，见 Global Constraints #1）

---

## Spec

### 三态判定原则（批次一/二的行为规格，沿用旧计划已定稿的 Q1/Q2/Q3）

```
Q1 这一项「应当被检查」吗？   否 → SKIP，理由码 inapplicable:<why>
Q2 输入合法、可解析、可定位吗？ 否 → FAIL，理由码 malformed:* / missing:* / unverifiable:*
Q3 这个事实「此刻应当已经成立」吗？ 是 → 缺失即 FAIL；否 → WARN（soft:*）
```

- 「文件**不存在**」（未提供）与「文件**存在但读不出**」（无效 UTF-8 / 权限）是两个
  不同的 Q2 失败态：前者按声明定级（unverifiable:plan_required 类），
  后者一律 `malformed:*`。
- 「内存/缓存里没有」≠「事实不存在」（批次四：磁盘 `result-*.json` 是第二证据源）。

### 各批次规格来源

| 批次 | 规格 = |
|---|---|
| 一 Task 1 | `tests/test_p8_precision.py:327-427` 五条既有 RED（裁决已冻结验收） |
| 一 Task 2 | `config/workflow.json:266-268`（S6 `review-<N>.md` `required:true`）+ A-14 裁决 |
| 二 | `zcode_expert_system.py:427-455`（`_keyword_hits` 整词纪律）、`zcode_expert_system.py:33-53`（编码地基）、`scripts/workflow_check.py:671-681`（S3 三态分流先例） |
| 三 | 老板决策 #5 + tarball 实测混入清单（`scripts/__pycache__/*.pyc`、`docs/superpowers/plans/`） |
| 四 | `zcode_expert_system.py:819-838`（`_load_context_summary` 契约：取历史摘要注入派发单） |
| 五 | hook 头注释「任何异常都 fail-open（rc=0），绝不阻断用户输入」 |

---

## Tasks

### Task 0: 每批前置快照基线（本计划全部批次共用的前置作业）

**Files**：无代码改动；快照落在 /tmp。

**每批动手前执行**（批次号代入 `<B>` = 1..5）：

```bash
SNAP="/tmp/tree.bak-audit-B<B>"; rm -rf "$SNAP"
cp -r /e/zcode-expert-system "$SNAP"
rm -rf "$SNAP/.mimosa" "$SNAP/__pycache__" "$SNAP/.pytest_cache" \
       "$SNAP/tests/__pycache__" "$SNAP/scripts/__pycache__" "$SNAP/context/__pycache__"
ls "$SNAP/zcode_expert_system.py" "$SNAP/scripts/workflow_check.py"   # 快照成功才可开工
```

**回滚方式**：`rm -rf /e/zcode-expert-system && cp -r "$SNAP" /e/zcode-expert-system`
（先删后拷；快照本身保留到最后一批验收后再清，见 Task 16）。

**Expected**：`ls` 两行都有输出；快照路径记入该批交付报告。

---

### Task 1: workflow_check.py 六处 read-or-empty 三态化（A-9 收口）

**Files**：`scripts/workflow_check.py:453`、`:786`、`:1045`、`:1505`、`:1321`、`:1325`；
测试规格（已存在，不改测试）：`tests/test_p8_precision.py:327-427` 五条 RED。

**既有 RED（修前必须看到 5 failed，主控 2026-11-16 实测）**：

```
tests/test_p8_precision.py::test_unreadable_ledger_blocks_readonly_escape      # :1505 后门
tests/test_p8_precision.py::test_missing_scale_section_blocks_readonly_escape  # :1507-1514 静默
tests/test_p8_precision.py::test_unreadable_ledger_is_not_ok_for_parked        # :1045 假绿
tests/test_p8_precision.py::test_empty_ledger_is_not_ok_for_parked             # :1045 空账本
tests/test_p8_precision.py::test_no_read_or_empty_coalescing_in_source         # AST lint 六处
```

**逐处修法**（`read()` 定义在 `scripts/workflow_check.py:133-152`，返回 None 表示
「不可读」——三态分流全部围绕它）：

1. **:453（check_S1 · S1.DESIGN_LEAK）**——无 rc 后果，因 AST lint 必须重构：
   ```python
   head = read(os.path.join(specs_dir, f))
   if head is None or "非权威" not in head[:200]:
       bad.append(f if head is not None else f + "（不可读）")
   ```
   WARN `soft:design_not_marked` 方向不变；不可读文件并入 bad 并显式标注。

2. **:786（check_S4 · S4.LEDGER_ID 身份行）**——有判定后果（不可读被印成「空账本」）。
   此分支账本文件必已存在（外层已判存在性），`None` = 存在但读不出：
   ```python
   ltext = read(ledger)
   if ltext is None:
       rep.add(label, "账本首行为身份行（INV4）", FAIL,
               "[malformed:ledger_unreadable] 账本存在但读不出（无效 UTF-8 / 权限），"
               "身份行无从核验", id="S4.LEDGER_ID", reason="malformed:ledger_unreadable")
       return
   first = ltext.splitlines()[0] if ltext else ""
   ```
   空串分支保持现行 FAIL `malformed:ledger_identity`（文案「空账本」），语义不变。

3. **:1045（check_S8 · S8.PARKED）**——真假绿主犯（不可读 → `parked==0` → OK「无残留」）：
   ```python
   ltext = read(ctx["ledger"])
   if ltext is None:
       rep.add(label, "无 PARKED 残留（W8）", FAIL,
               "[malformed:ledger_unreadable] 账本存在但读不出，「无残留」无法证明",
               id="S8.PARKED", reason="malformed:ledger_unreadable")
   elif ltext == "":
       rep.add(label, "无 PARKED 残留（W8）", WARN,
               "[soft:ledger_empty] 账本存在但为空（无身份行），证明力不完整",
               id="S8.PARKED", reason="soft:ledger_empty")
   else:
       # 现行 parked 正则判定不动
   ```
   对齐三条既有测试：`test_unreadable_ledger_is_not_ok_for_parked`（!=OK → FAIL 满足）、
   `test_empty_ledger_is_not_ok_for_parked`（!=OK → WARN 满足）、
   `test_readable_ledger_without_parked_still_ok`（==OK 不回退）。

4. **:1505（`_apply_ledger_scale_conflict` · S0.SCALE_CONFLICT）**——readonly 后门：
   ```python
   ltext = read(ctx["ledger"])
   if ltext is None:
       rep.add(gate_label(wf, "S0"), "规模与账本一致", FAIL,
               "[malformed:ledger_unreadable] 账本存在但读不出——"
               "readonly 下账本是唯一检查对象，不得静默放行",
               id="S0.SCALE_CONFLICT", reason="malformed:ledger_unreadable")
       return
   recorded = parse_scale_section(ltext)
   if recorded is None:
       if not section_body(ltext, "Scale"):
           rep.add(gate_label(wf, "S0"), "规模与账本一致", FAIL,
                   "[missing:scale_section] 账本缺 `## Scale` 段——S0 产出缺失"
                   "（readonly 下账本唯一，缺段即整次核对空转）",
                   id="S0.SCALE_CONFLICT", reason="missing:scale_section")
       else:
           # 现行 WARN soft:scale_unparsable（有段但歧义 = 「查了但查不出结论」，
           # 维持 WARN 是 A-9 裁决范围，不扩大）
           ...
       return
   ```
   缺段 FAIL **仅限 readonly**（S1-S8 全裁剪、账本是唯一检查对象的场景）——
   其他规模下账本缺段维持静默，否则 `proj` 夹具（无 `## Scale` 段的常规账本）驱动的
   十余条既有用例会被误伤，等于把「账本格式历史包袱」变成大面积假红。
   readonly 判据：`scale == "readonly"`（或按 `trim_matrix` 全 `-` 判定；
   `_apply_ledger_scale_conflict` 的可得入参二选一，实施时定并记入 Rulings）。
   依据：`test_missing_scale_section_blocks_readonly_escape` docstring 明确该用例
   只锁 readonly 逃生路（`tests/test_p8_precision.py:348-360`，主控已核）。

5. **:1321 / :1325（snapshot 辅助信息段）**——无 rc 后果，显式三态文案：
   ```python
   ltext = read(ctx["ledger"])
   lines.append("  ledger complete 行：%s" % (
       ",".join(sorted(_ledger_completed_ids(ltext))) if ltext is not None else "读不出"))
   ptext = read(ctx["plan"])
   secs = re.findall(r"^#{1,6}[ \t]+(.+?)[ \t]*$", ptext, re.M) if ptext is not None else []
   lines.append("  计划段名：%s" % (", ".join(secs[:14]) or ("读不出" if ptext is None else "无")))
   ```

**验证命令**：
```bash
python -m pytest tests/test_p8_precision.py -q          # 18 条全绿（5 RED 转绿，13 既有不回退）
python -m pytest tests/ -q                              # 批末全绿
```

**Expected**：`test_no_read_or_empty_coalescing_in_source` 的 AST 扫描
（`tests/test_p8_precision.py:397-427`，限被调名 `read`/`read_required`）零命中；
readonly + 无效 UTF-8 账本 → `rep.has_fail()` 为真（修前 rc=0）。

**不做**：不改 `read()` 本身的编码策略（`utf-8-sig`）；不动 `parse_scale_section`；
不把「有段但歧义」升级为 FAIL（A-9 裁决范围外）。

---

### Task 2: S6 补 review-<N>.md 必需产物检查 + 守卫测试真断言（A-14 收口）

**Files**：`scripts/workflow_check.py`（`check_S6`，:885-976 区间内新增检查项；
`:1278` 注释同步修正）；`tests/test_p8_precision.py:187-204`（守卫测试弱断言改真）、
`:207-215`（反例已存在，复用不改）。

**现状（已实锤）**：`config/workflow.json:266-268` 声明
`.superpowers/sdd/<plan>/review-<N>.md` `required:true`，但 `check_S6` 全文只读
ledger/plan 文本，从不列 workspace 目录；`scripts/workflow_check.py:1278` 注释却写
「`review-<N>.md` 由 check_S5/check_S6 用正则匹配」——声明与实现脱节。
守卫测试 `test_review_report_missing_is_not_silent` 用
`"review" in (i.get("id") or "").lower()` 判覆盖，被既有 `S6.REVIEW`
（审查结论已持久化）子串假满足——**测试假通过**。

**修法**：

1. `check_S6` 末尾（`:976` 之后）新增检查项，**先实现 inapplicable 分支**（A-14 既有
   裁决：workspace 已删 → SKIP，防交付后跨阶段核对假红）：
   ```python
   # review-<N>.md：config/workflow.json S6 artifacts 声明 required:true（:266-268），
   # 旧实现从不读 → 声明无人消费。硬约束（A-14 裁决）：workspace 已删必须
   # inapplicable——交付后跨阶段核对不能因 workspace 清理而假红。
   workspace = ctx.get("workspace") or ""
   if not workspace or not os.path.isdir(workspace):
       rep.add(label, "审查报告 review-<N>.md", SKIP,
               "[inapplicable:no_workspace] workspace 不存在或已删，审查报告无从核对",
               id="S6.REVIEW_REPORT", reason="inapplicable:no_workspace")
   else:
       reviews = sorted(f for f in os.listdir(workspace)
                        if re.match(r"^review-\d+\.md$", f))
       if reviews:
           rep.add(label, "审查报告 review-<N>.md", OK, ", ".join(reviews[:3]),
                   id="S6.REVIEW_REPORT")
       else:
           rep.add(label, "审查报告 review-<N>.md", FAIL,
                   "[missing:review_report] workspace 存在但零个 review-<N>.md"
                   "（config/workflow.json S6 声明 required:true）",
                   id="S6.REVIEW_REPORT", reason="missing:review_report")
   ```
   workspace 键来自 `run()` 构建的 ctx（`--json` 输出已含 `workspace` 字段，
   `scripts/workflow_check.py:1598-1610` 区间）。
2. `:1278` 注释改为指向新检查：「`review-<N>.md` 的存在性由 check_S6 的
   S6.REVIEW_REPORT 项核对；check_S5/check_S6 读的是账本与计划文本」。
3. 守卫测试改真断言（`tests/test_p8_precision.py:187-204`）：
   ```python
   it = item(rep, "S6.REVIEW_REPORT")
   assert it["status"] == wc.FAIL, (
       "workspace 存在但无任何 review 文件时 S6.REVIEW_REPORT 必须 FAIL，"
       "实际 %s / %s" % (it["status"], it["detail"]))
   ```
   改造后先跑一次：修前 `item()` 因 id 不存在 raise → **RED**；补检查后 → **GREEN**。
   （原弱断言删除——`S6.REVIEW` 子串假满足正是它要防的事。）

**新增双向用例**（追加到 `tests/test_p8_precision.py` A-14 分节之后）：

- `test_review_report_skipped_when_workspace_deleted`：`shutil.rmtree(proj/.superpowers)`
  后跑 `wc.run(change="demo", plan="docs/p.md", scale="medium", root=str(proj))`，
  断言 `S6.REVIEW_REPORT` 状态 == `wc.SKIP` 且 reason 以 `inapplicable:` 开头
  （防跨阶段假红——本用例在实现第 1 步时就该绿，若红说明 inapplicable 分支缺失）。
- `test_review_report_present_is_ok`（既有 :207-215）作为不误报反例继续生效。

**验证命令**：
```bash
python -m pytest tests/test_p8_precision.py -q
python - <<'PY'
import sys; sys.path.insert(0, ".")
from tests.test_p8_precision import proj, item   # 夹具复用性冒烟（无断言，仅 import 检查）
print("fixture-ok")
PY
```

**Expected**：`proj` 夹具（`.superpowers/sdd/p/` 存在、无 review 文件）→ FAIL；
写入 `review-1.md` → OK；workspace 删除 → SKIP inapplicable。

---

### Task 3: P8 文档义务三件（裁决落纸）

**Files**：`docs/workflow-fusion-design.md`（第三节 `## 三、裁剪矩阵的语义（必 / 简 / 条 / -）`，
:58 起）；`docs/superpowers/plans/2026-11-16-defect-remediation.md:1033-1037`；
`SKILL.md:93`。均为文档改动，无 TDD，验证用 grep 断言。

1. **fusion-design 补「条 当前等价于必」**：第三节末尾追加小节，内容固定为
   （依据 `tests/test_p8_precision.py:15-34` 裁决记录）：
   - `条` 在当前实现中等价于 `必`（`LIGHT_KEEP` / `check_*` 按必执行）；
   - 不实现 `apply_when` 触发引擎的理由：`条` 的触发判据只能是「调用方给没给
     `--plan`」，等于「不传参数 ⇒ 门禁不查」，与 readonly 后门同构；
     主控实证：light + 全完成 + 无 plan 恰好 3 条 FAIL 全来自 `plan_required`，
     实现 `条` 让它们 SKIP 后 rc=0，构成新假绿；
   - `LIGHT_KEEP["S3"]` 把 `plan_exists` 列为机器承重项，佐证 `trim_matrix.light.S3 = "条"`
     是写错的标记而非未实现的功能；
   - 三方口径统一后：`workflow.json`（条）、`SKILL.md`（见下）、本文档（条=必）一致。
2. **旧计划 P8 结论段更正**（`2026-11-16-defect-remediation.md:1033-1037`）：
   「仍未处理」三项与现状不符，改写为：
   - A-15：已按裁决**改配置收口**（light `S2/S8=条` 保留，声明与行为已一致，
     「条=必」写入 `docs/workflow-fusion-design.md` 第三节）；
   - A-14：已完成 2/3（S8 跟随配置路径、snapshot 降级非必需），残项
     review-<N>.md 检查由《2026-11-16-audit-findings-remediation.md》Task 2 收口；
   - A-9：六处 `read(...) or ""` 由同文件 Task 1 收口（既有 5 条 RED 为验收）。
   段尾追加一行指向新计划文档路径。
3. **SKILL.md:93 轻量行改口径**（与 `config/workflow.json` `trim_matrix.light` 实测值
   对齐：S0简/S1简/S2条/S3简/S4必/S5必/S6简/S7必/S8条）：
   ```
   | 轻量 | S0 简 → S1 简 → S3 简 → S4 必 → S5 必（TDD 不可跳）→ S6 简 → S7 必 → S2/S8 条（当前等价于必，见 workflow-fusion-design.md 第三节） |
   ```
   删除「其余视情况」（与 S4/S7=必 矛盾，正是「声明源与行为不一」的复发形态）。

**验证命令**：
```bash
grep -n "当前等价于必" docs/workflow-fusion-design.md
grep -n "audit-findings-remediation" docs/superpowers/plans/2026-11-16-defect-remediation.md
grep -n "其余视情况" SKILL.md    # 期望零命中
grep -n "S4 必" SKILL.md | head -3
```

**Expected**：三条 grep 分别命中新内容 / 零命中旧口径。

**批次一批末门禁**：`python -m pytest tests/ -q` 全绿（此时 5 failed 已清，
新增/改造用例全绿）+ L1 自审（对照 Task 1-3 Files 清单逐文件核对）。

---

### Task 4: workflow_check.py 补输出编码地基

**Files**：`scripts/workflow_check.py`（新增 `_force_utf8_stdout()`，置于模块头部
工具函数区；`main()`（:1526）首行调用）；`tests/test_cli_encoding.py`（新增用例）。

**现状（已实锤）**：四个入口中唯一没做 UTF-8 重配的（`grep reconfigure scripts/workflow_check.py`
零命中；对照 `zcode_expert_system.py:33-53` 的完整写法——stdout+stderr 双流、
`getattr` 探测、`except (AttributeError, ValueError, OSError)` 吞掉）。

**修法**：照 `zcode_expert_system.py:33-53` 原样移植 `_force_utf8_stdout()`（含 docstring
注明来源与缺陷 #3 背景），在 `def main(argv=None):`（:1526）函数体第一行调用。
只挂在 `main()`，不挂 `run()`（库调用方不应被改变 stdio 行为）。

**新增测试**（`tests/test_cli_encoding.py`，复用既有 `run_cli()` :38-65）：

- `test_workflow_check_exit_zero_under_cp936_with_emoji_change`：
  ```python
  def test_workflow_check_exit_zero_under_cp936_with_emoji_change(tmp_path):
      proc = run_cli(["scripts/workflow_check.py", "--change", "修复⚙️",
                      "--scale", "readonly", "--json", "--root", str(tmp_path)])
      assert proc.returncode == 0, as_text(proc.stderr)
  ```
  （`run_cli(args)` 把 args 原样拼到 `python` 之后——`tests/test_cli_encoding.py:58-59`
  实测，故脚本路径必须是单个元素 `"scripts/workflow_check.py"`。）
  `--change` 名含 emoji（⚙️）会透出到 `变更：%s` 打印（:1584 实测）——
  CP936 编不了该码位 → 修前 UnicodeEncodeError rc=1（**RED**）；修后 rc=0。
  `--root` 指向空 tmp_path（无 openspec/ 也不崩——环境探测已有降级路径）。
- `test_workflow_check_json_stdout_decode_utf8`：同命令断言 stdout 用 utf-8 解码后
  `json.loads` 成功（复用 `as_text()` :68-70）。

**验证命令**：
```bash
python -m pytest tests/test_cli_encoding.py -q
PYTHONIOENCODING=cp936 python scripts/workflow_check.py --change "修复⚙️" --scale readonly --json --root . >/dev/null; echo $?   # 0
```

**Expected**：修前 RED 两条（rc=1 / JSON 解码失败），修后全绿；既有 4 条参数化用例不回退。

---

### Task 5: BUG_SIGNALS ASCII 词整词匹配

**Files**：`zcode_dev_workflow.py:242`（匹配点）、`:89-96`（表定义旁新增 `_word_hit` 辅助
或复用式实现）；测试新建 `tests/test_bug_signals_word_boundary.py`。

**现状（已实锤）**：`bug_hits = [s for s in BUG_SIGNALS if s in text]`（:242）裸子串。
BUG_SIGNALS（:89-96）中的 ASCII 词 `bug` / `regression` / `crash` / `error` / `broken` /
`fix` / `5xx` 会误中 `debug`（de**bug**）、`fixture`（**fix**ture）、`errors`、
`1500xx` 类数字串等。中文词（`缺陷`、`报错` 等）子串匹配本就正确，不动。

**修法**：新增 `_word_hit(signal, text)`，判定纪律对齐 `zcode_expert_system.py:427-455`
的 `_keyword_hits`：

- 纯 ASCII 词：整词匹配——命中位的前一字符与后一字符不得是 `[a-z0-9_]`
  （允许 `-` `.` `+` `#` 作边界，如 `regression-test` 中 `regression` 仍算独立词）；
- 含中文的词：子串包含（中文无空格词边界）；
- `:242` 改为 `bug_hits = [s for s in BUG_SIGNALS if _word_hit(s, text)]`。

**同根因簇一次改完**：实施时 `grep -nE '"[a-z0-9]' zcode_dev_workflow.py` 核对
`BUG_CONTEXT` / `STRONG_BUG` / `PHENOMENON_WORDS` / `FEATURE_CONTEXT` 四张表（:98 起）
是否也含 ASCII 成员并走 :243-246 的裸子串匹配——**若存在同类 ASCII 词，一并改走
`_word_hit`**（同一文件同一根因不留半成品），并在测试中覆盖之。

**新增测试**（双向，参照 `tests/test_p2_triage_dispatch.py` 的既有分诊调用方式）：

- `test_ascii_signal_whole_word_no_false_positive`：
  「给 debug 日志开关加配置」「补 fixture 测试数据」「重命名 errors 模块」——
  修前 `bug` 命中 de**bug**、`fix` 命中 **fix**ture、`error` 命中 **error**s，
  走两道门槛判 Bug（**RED**）；修后不得判 Bug。
- `test_ascii_signal_no_miss_on_real_failure`（双向反例）：
  「登录接口报错 error 500，直接 crash」「修复 regression」——修前修后都必须判 Bug
  （整词化不得把真故障洗白）。
- `test_chinese_signals_still_substring`：「页面白屏了」「数据库死锁」仍判 Bug
  （中文路径不回退）。

**验证命令**：
```bash
python -m pytest tests/test_bug_signals_word_boundary.py tests/test_p2_triage_dispatch.py tests/test_scale_triage.py -q
```

**Expected**：新文件 RED→GREEN；分诊与规模既有用例（17/17 误判修复成果）零回退。

---

### Task 6: workflow_check.py 不可读三态文案修正（S4/S7 计划、S5/S6 账本）

**Files**：`scripts/workflow_check.py:739-743`（check_S4）、`:981-985`（check_S7）、
`:845-846`（check_S5 三元对齐守卫）、`:897-904`（check_S6 INDEPENDENCE 守卫）；
测试新建 `tests/test_unreadable_tri_state.py`。

**现状（已实锤）**：

- :739-743 与 :981-985：`text = read(ctx["plan"]) if ctx["plan"] else None` 后
  `if text is None` 统一报 `[unverifiable:plan_required] 必须提供 --plan`——
  **提供了但读不出**也被说成「没提供」。`check_S3:671-681` 已有三态分流先例
  （先判 `not ctx["plan"]` → unverifiable；再判 `text is None` → malformed:plan_unreadable）。
- :845-846（S5）：`ttext`/`ltext` 任一为 None 时 `if ttext is not None and ltext is not None`
  直接跳过——**证据面静默收缩**，无任何检查项。
- :897-904（S6）：`ltext`/`ptext` 都为 None → SKIP `inapplicable:no_evidence`——
  账本**存在但读不出**被归为「不该查」。

**修法**（方向：把「没查成」显式化为 FAIL，不改动任何既有 OK/FAIL 判定路径）：

1. check_S4 / check_S7 对齐 S3 先例：
   ```python
   text = read(ctx["plan"]) if ctx["plan"] else None
   if not ctx["plan"]:
       rep.add(label, "<原检查名>", FAIL,
               "[unverifiable:plan_required] 该规模下 S4/S7 不被裁剪，必须提供 --plan",
               id="S4.BASELINE" / "S7.INTEGRATION", reason="unverifiable:plan_required")
       return
   if text is None:
       rep.add(label, "<原检查名>", FAIL,
               "[malformed:plan_unreadable] 无法读取 %s" % ctx["plan"],
               id="S4.BASELINE" / "S7.INTEGRATION", reason="malformed:plan_unreadable")
       return
   ```
2. check_S5 :846 守卫改三态：`ttext is None`（tasks.md 存在但读不出）或 `ltext is None`
   （账本存在但读不出）时 emit FAIL `[malformed:tasks_unreadable]` /
   `[malformed:ledger_unreadable]`（id 复用 `S5.TRIAD`，reason 区分），仅两者皆可读才进
   现行三元对齐判定。
3. check_S6 :900 守卫改三态：`ctx["ledger"]` 非空但 `ltext is None` → FAIL
   `[malformed:ledger_unreadable]`（id `S6.INDEPENDENCE`）；仅当证据**确实不存在**
   （无账本且无计划）才保留 SKIP `inapplicable:no_evidence`。

**新增测试**（`tests/test_unreadable_tri_state.py`，复用 `test_p8_precision.py` 的
`proj` 夹具：tests/ 目录无 `__init__.py`，但 Python 3 隐式命名空间包 + 模块顶部
`sys.path.insert(0, str(PROJECT_ROOT))`（先例：`tests/test_p8_precision.py:46-48`）
使 `from tests.test_p8_precision import item` 与
`from tests.test_p8_precision import proj as _proj`（随后 `proj = _proj` 重暴露，
pytest 按本模块命名空间收集该 fixture 对象）可行；实施第一步先跑一次 import 冒烟，
若命名空间导入在当前 pytest 配置下失败，再退回在本文件内复制精简版夹具并记入
Rulings）：

- `test_unreadable_plan_s4_is_malformed_not_plan_required`：plan 文件写
  `b"\xff\xfe invalid"` → `item(rep, "S4.BASELINE")["reason"] == "malformed:plan_unreadable"`
  （修前为 `unverifiable:plan_required`，**RED**）。
- `test_unreadable_plan_s7_is_malformed`：同构，id `S7.INTEGRATION`。
- `test_missing_plan_still_unverifiable`（双向反例）：不传 plan → reason 仍是
  `unverifiable:plan_required`（不因分流改造而丢失「未提供」语义）。
- `test_unreadable_ledger_s5_emits_fail_not_silent`：账本写无效字节 →
  `rep.items` 中存在 status==FAIL 且 reason==`malformed:ledger_unreadable` 的项
  （修前该区间零检查项，**RED**）。
- `test_unreadable_evidence_s6_not_inapplicable`：账本读不出 + 无 plan →
  `item(rep, "S6.INDEPENDENCE")` 不得为 SKIP
  （修前 SKIP inapplicable，**RED**）。
- `test_no_evidence_s6_still_inapplicable`（双向反例）：无账本无计划 → 仍 SKIP
  `inapplicable:no_evidence`。

**验证命令**：
```bash
python -m pytest tests/test_unreadable_tri_state.py tests/test_p8_precision.py tests/test_workflow_check.py tests/test_workflow_check_gates.py -q
```

**Expected**：新用例 RED→GREEN；Task 1 已绿的 22 条与 workflow_check 全家不回退。

**批次二批末门禁**：`python -m pytest tests/ -q` 全绿 + L1 自审。

---

### Task 7: package.json 改名与 files 白名单收窄

**Files**：`package.json:2`（name）、`:5`（main）、`:25-28`（repository）、`:29-48`（files）；
测试扩展 `tests/test_p4_consistency.py`。

**修法**（老板决策 #5 落地，四处同步）：

```json
"name": "zcode-expert-system",
"main": "bin/cli.js",
"repository": { "type": "git", "url": "git+https://github.com/wutian122/zcode-expert-system.git" },
"files": [
  ".zcode-plugin/",
  "scripts/install.js", "scripts/workflow_check.py",
  "scripts/llm_client.py", "scripts/embedding_client.py",
  "config/", "agents/", "references/", "templates/", "commands/",
  "docs/workflow-fusion-design.md",
  "context/context-manager.py",
  "SKILL.md", "zcode_expert_system.py", "zcode_dev_workflow.py", "skill_entry.py",
  "README.md", "README_CN.md", "LICENSE", "bin/", "hooks/"
]
```

- `"scripts/"` → 逐文件列举（scripts/ 实有 4 个文件：install.js / workflow_check.py /
  llm_client.py / embedding_client.py，已 `ls` 实测）：阻断 `scripts/__pycache__/*.pyc`
  随 tarball 分发（实测混入）。
- `"docs/"` → `"docs/workflow-fusion-design.md"`：阻断 `docs/superpowers/plans/`
  开发残留随包分发（实测混入）。
- `"main"`：`zcode_expert_system.py` 是 Python 文件，npm 的 main 指向它无意义；
  改 `bin/cli.js`（Node 模块，存在性已实测）。

**新增测试**（`tests/test_p4_consistency.py`，声明源一致性域）：

- `test_package_name_is_expert_system`：`json.load(package.json)["name"] == "zcode-expert-system"`
  （修前 == plugin 名，**RED**）。
- `test_files_whitelist_has_no_directory_wildcard_for_scripts_and_docs`：files 数组中
  不存在 `"scripts/"` 与 `"docs/"` 两个整目录项；`"docs/workflow-fusion-design.md"` 在列；
  scripts 四文件在列（**RED**）。
- `test_main_points_to_cli`：`["main"] == "bin/cli.js"` 且 `Path("bin/cli.js").is_file()`
  （**RED**）。

**验证命令**：
```bash
python -m pytest tests/test_p4_consistency.py -q
npm pack --dry-run 2>&1 | grep -E "__pycache__|\.pyc|superpowers"   # 期望零命中
npm pack --dry-run 2>&1 | grep -E "install\.js|workflow-fusion-design"  # 期望命中
```

**Expected**：tarball 清单无 `__pycache__`/`.pyc`/`docs/superpowers/`；
`npm pack --dry-run` 是纯本地打包预览，不上传、不查 registry。

---

### Task 8: install.js PLUGIN_OUTPUTS 去 tests + agents 覆盖前备份

**Files**：`scripts/install.js:346-351`（PLUGIN_OUTPUTS）、`:527-558`（agents 写入循环）；
测试扩展 `tests/test_p5_install_safety.py`。
**核对/编辑一律用 Read/Edit 工具**（Mimosa 对含 install.js 路径的 Bash 命令误拦，
Global Constraints #4）。

**修法**：

1. `PLUGIN_OUTPUTS`（:346-351）移除 `'tests'`：该集合语义是「本插件产出的顶层条目」，
   用于 `backupDir()`（:353-366）的 `hasUserFiles` 判定——把 `tests` 算进去会让
   **用户自建的 tests/ 被当插件产物**，备份目录被判定「无用户文件」后自动删除。
2. agents 写入（:530-558 两个分支 `fs.writeFileSync` 前）加覆盖前备份，对齐技能目录
   `backupDir()` 的 rename 策略：
   - 写入前若目标已存在：`fs.renameSync(dest, dest + ".bak-" + Date.now())`；
   - 同一次安装内同一文件只备一次（写入循环天然满足）；
   - 备份文件不进卸载清单（卸载逻辑按 manifest 清单删，`.bak-*` 不在
     `deployedAgentNames` 中，天然满足——实施时确认 `uninstall` 路径无前缀清扫即可，
     `test_uninstall_without_manifest_does_not_prefix_sweep`（:354）已在守护）。

**新增测试**（`tests/test_p5_install_safety.py`，复用 `sandbox`/`make_source`/
`run_installer` 夹具 :68-149）：

- `test_user_tests_dir_blocks_backup_autodelete`：
  预装一次 → 在部署目标（`~/.zcode/` 技能/插件目录树）手工创建 `tests/用户文件.txt`
  → 再跑一次安装 → 断言含该用户文件的备份目录**仍存在**且文件完好。
  （修前：`tests` 在 PLUGIN_OUTPUTS → `hasUserFiles=False` → 备份被自动清理，**RED**。）
- `test_modified_agent_file_backed_up_before_overwrite`：
  预装一次 → 改写一个已部署 agent 文件内容为「用户定制标记」→ 再安装 →
  (a) 部署位置该文件内容恢复为源内容；(b) 存在 `.bak-*` 文件且其内容含
  「用户定制标记」（修前直接覆盖丢失，**RED**）。
- `test_agent_content_updated_when_unmodified`（双向反例）：未改动过的 agent，
  重装后内容 == 源内容（备份逻辑不得妨碍正常更新）。

**验证命令**：
```bash
python -m pytest tests/test_p5_install_safety.py -q
```

**Expected**：新三条 RED→GREEN；既有 12 条（:166-400）零回退。

---

### Task 9: 支付代理删除 AgenticBTC 供应链推广段

**Files**：`agents/expert-accounts-payable-agent.md`（:56-77 配置推广段；:79-90
AgenticBTC 通道表；:92 起「核心工作流」中的 `agenticbtc.*` 代码示例）。

**现状（已实锤）**：该段推广 `npm install agenticbtc-mcp` / `npx -y agenticbtc-mcp` /
到 agenticbtc.io 取 API key——随部署注入人格 prompt 的第三方供应链通道（主控亲核属实）。
且范围不止 :56-77：`## 可用支付通道`（:79 起）与 `## 核心工作流` 的
`agenticbtc.checkPaymentByReference` 等示例持续引用该包。

**修法**：

- 删除 `## 配置说明（AgenticBTC MCP）` 整节（:56-77）；
- 删除 `## 可用支付通道` 整节（:79-90）；
- `## 核心工作流` 中所有 `agenticbtc.*` 调用改写为中性支付描述（保留业务语义：
  幂等查重、供应商白名单校验、失败上报），示例改为语言无关的步骤描述或
  标注「通过企业已批准的支付网关执行」；
- **保留**该文件其余部分（`### 异常处理` :50-54 等既有安全行为段不动）。

**硬约束**：改后全文不得出现 `npm install` 第三方包指引、`npx -y` 外部包执行、
外部域名取 key 指引。

**新增测试**（`tests/test_p4_consistency.py`，声明源一致性域）：

- `test_agents_have_no_third_party_supply_chain_promo`：
  遍历 `PROJECT_ROOT / "agents"` 全部 `.md`，断言全文不含 `agenticbtc`
  （不区分大小写）；对 `expert-accounts-payable-agent.md` 额外断言不含
  `npm install` 与 `npx -y`（修前命中，**RED**）。

**验证命令**：
```bash
python -m pytest tests/test_p4_consistency.py -q
grep -rni "agenticbtc" agents/ README.md README_CN.md SKILL.md   # 期望零命中
```

**Expected**：agents 全目录与三份门面文档零残留。

---

### Task 10: README 双语安装链与目录树修正

**Files**：`README.md:121`、`:139-142`、`:145-148`（Option 3）、`:280-306`（目录树）、
`:312`；`README_CN.md:120`、`:138-141`、`:145-147`（方式三）、`:260-298`（目录树）、
`:307`。

**修法**（改名自愈链，老板决策 #5）：

1. 安装命令：`npm install -g zcode-expert-system-plugin` → `npm install -g zcode-expert-system`
   （双语 :121 / :120）。
2. 源码安装段（双语 :139-142 / :138-141）与开发指南段（:312 / :307）：
   clone URL 改 `zcode-expert-system.git`——改完后 `cd zcode-expert-system`
   与 clone 产生的目录名**恰好自洽**（现状 cd 行是错的：clone 下来的目录叫
   `zcode-expert-system-plugin`）。
3. Option 3 / 方式三（:145-148 / :145-147）：保留标题但标注未上架——
   在段落首行加 `（尚未上架，当前请用方式一 npm 安装）`（双语对应）。
   不整段删除：保留占位便于上架后恢复。
4. 目录树（README.md :280-306、README_CN.md :260-298）：
   - 补 `tests/` 行（`├── tests/  # 回归测试（pytest）`）；
   - docs/ 行双语均已只列 `workflow-fusion-design.md`（实测确认，无需改）；
   - README.md 目录树核对 `commands/` 行存在（README_CN.md:280 已有；
     若 README.md 缺则补 `├── commands/  # wf/*.md 12 个斜杠命令`）。
5. 安装段（Option 2 之后）补一行说明（双语）：
   > 注：`.zcode-plugin/plugin.json` 的 `skills` 字段仅对部署后布局生效；
   > 仓库直装（源码方式）请将技能目录指向仓库根。

**验证命令**：
```bash
grep -n "zcode-expert-system-plugin" README.md README_CN.md   # 期望零命中
grep -n "npm install -g zcode-expert-system$" README.md README_CN.md
grep -n "tests/" README.md README_CN.md | head -4
```

**Expected**：旧包名零命中；新安装命令双语各命中；目录树含 tests/ 行。
无 pytest 用例（文档改动以 grep 为验收）。

---

### Task 11: SKILL.md 第十一节文件表补全

**Files**：`SKILL.md:322-339`（`## 十一、相关文件` 表）。

**修法**：表格追加四行（职责列措辞如下）：

```
| `commands/wf/*.md` | 12 个 /wf:* 斜杠命令（triage/check/plan/… 的机械动作入口） |
| `templates/*.md` | 计划段模板 / SDD 账本模板 / 任务·审查·Bug 报告模板 |
| `hooks/hooks.json` + `hooks/prepend-global-rules-reminder.mjs` | UserPromptSubmit 每轮注入触发规则 |
| `scripts/install.js` | 部署 / 卸载入口（bin/cli.js install/uninstall 转调） |
```

（commands/wf 下 12 个命令文件、templates/ 与 hooks/ 两目录存在性均已 `ls` 实测。）

**验证命令**：
```bash
ls commands/wf/ | wc -l        # 12
grep -n "commands/wf" SKILL.md  # 期望命中第十一节新行
```

**Expected**：表覆盖安装链四要素；`grep -rn "十一" SKILL.md` 章节内四行齐。
无 pytest 用例（文档改动）。

**批次三批末门禁**：`python -m pytest tests/ -q` 全绿（Task 7/8/9 新用例含内）+
L1 自审 + 本批所有 grep 断言复核。

---

### Task 12: 发布前验证（**发布时执行，须老板授权**）

**Files**：无代码改动。本任务整体标注：**发布时执行，须老板明示授权后运行**；
计划阶段不执行、不代跑。

1. `npm view zcode-expert-system`——确认包名未被占用（预期 404 / E404 即可用；
   若返回元数据说明已被占，停下来报告老板，改名决策需重议）。
2. `npm publish --dry-run`——核对 tarball 内容清单：
   - 必含：`.zcode-plugin/`、四份 scripts 文件、`docs/workflow-fusion-design.md`、
     `context/context-manager.py`、SKILL.md、三个 py 入口、bin/、hooks/；
   - 必不含：`__pycache__`/`*.pyc`、`docs/superpowers/`、`tests/`、任何 `.bak-*`。
3. 真实 `npm publish` 不在本计划范围（老板明示授权后另行执行）。

**验证命令**（发布时）：
```bash
npm view zcode-expert-system ; echo "exit=$?"
npm publish --dry-run 2>&1 | tail -40
```

---

### Task 13: context-manager.py 读盘回填接线 + 两处精度项

**Files**：`context/context-manager.py:219-226`（`get_context_summary`）、`:228-230`
（`load_result`）、`:93-102`（`_get_result_file_path` 时间戳）、`:196-214`
（`_llm_summarize` 的 sys.path.insert）；测试新建 `tests/test_context_wiring.py`。

**现状（已实锤）**：

- `get_context_summary`（:219-226）只读内存 `context_store`——每次调用
  `zcode_expert_system.py:832-834` 用 `spec_from_file_location + exec_module`
  生成**全新模块与全新 ExpertContext 实例**，内存 store 必空 → 恒返回 ""。
- `load_result`（:228-230）定义了却**从未被任何代码调用**（grep 全仓零调用点）。
- 磁盘上其实有证据：`save_context`（:113-134）每轮都落盘
  `result-<task>-<expert>-<ts>.json` 到 `_default_store_dir()`（:16-23，
  `~/.zcode/expert-system/context`），容量由 `MAX_RESULT_FILES = 200`（:13）滚动。

**修法**：

1. `get_context_summary` 内存 miss 时扫盘回填：
   ```python
   def get_context_summary(self, task_id):
       context = self.get_context(task_id)
       if not context:
           context = self._load_task_from_disk(task_id)
           if not context:
               return ""
       steps = context.get("steps", [])
       summaries = ["[" + step['expert'] + "] " + step['summary'] for step in steps]
       return "\n".join(summaries)

   def _load_task_from_disk(self, task_id):
       """内存 miss 时扫 result-<task>-*.json 回填 store（跨进程接线的另一半）。

       文件名中的 task 段经 _sanitize_component 清洗（:26-42），按同一函数
       清洗 task_id 后精确前缀匹配，杜绝路径穿越与误匹配。
       """
       safe_task = _sanitize_component(task_id)
       prefix = "result-" + safe_task + "-"
       hits = []
       try:
           with os.scandir(self.context_dir) as it:
               for entry in it:
                   name = entry.name
                   if not (name.startswith(prefix) and name.endswith(".json")):
                       continue
                   try:
                       hits.append((entry.stat(follow_symlinks=False).st_mtime, entry.path))
                   except OSError:
                       continue
       except OSError:
           return {}
       hits.sort()                      # 旧 → 新，与 save_context 的 append 顺序一致
       steps = []
       for _mtime, path in hits[-MAX_RESULT_FILES:]:
           try:
               result = self.load_result(path)
           except (OSError, ValueError):
               continue                 # 坏文件跳过，不让单文件毁掉整个摘要
           expert = _sanitize_component(
               (result.get("selected_expert") or {}).get("id", "none")
               if isinstance(result.get("selected_expert"), dict) else "none")
           steps.append({
               "expert": expert,
               "summary": self._generate_summary(result),
               "result_file": path,
               "timestamp": datetime.fromtimestamp(_mtime).isoformat(),
           })
       if not steps:
           return {}
       self.context_store[task_id] = {"task_id": task_id, "steps": steps, "shared_data": {}}
       return self.context_store[task_id]
   ```
   `_generate_summary`（:141-145）对整份 result JSON 截断 200 字符，回填直接复用。
   `selected_expert` 结构以 `zcode_expert_system.py:796-812` 的 save_context 输入为准
   （dict 含 id 键）；非 dict 时回退 "none"。
2. **精度项①：结果文件名秒级时间戳可碰撞**（:99）：
   `timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")` →
   `datetime.now().strftime("%Y%m%d-%H%M%S%f")`（微秒精度，文件名变长无副作用）；
   同 task+expert 同一秒连续两次 save 不再互相覆盖。
3. **精度项②：sys.path 每调用重复 insert**（:199）：
   把 `scripts` 目录路径的插入挪到模块顶部一次性执行：
   ```python
   _SCRIPTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
   if _SCRIPTS_DIR not in sys.path:
       sys.path.insert(0, _SCRIPTS_DIR)
   ```
   `_llm_summarize`（:196-214）内的 insert 行删除。带 `not in sys.path` 守卫，
   因为本模块是 exec_module 重复加载的（模块顶部代码每次 exec 都会执行）。

**新增测试**（`tests/test_context_wiring.py`；**测试必须覆盖「全新实例 / 全新进程」
读盘路径**——exec_module 不进 sys.modules，进程内复用是假象）：

- `test_summary_survives_process_restart`：subprocess 两段式——
  脚本 A：`ExpertContext(context_dir=tmp)` + `save_context("t1", "exp-x", <最小 result dict>)`
  落盘；脚本 B（**新进程**）：同 tmp 目录新建实例，`get_context_summary("t1")`
  非空且含 `[exp-x]`。修前 B 返回 ""（**RED**）。
  最小 result dict 形态参照 `zcode_expert_system.py:793-812` 的 build_context 产物
  （至少含 `selected_expert: {"id": "exp-x"}` 键）。
- `test_summary_empty_without_any_evidence`（双向反例）：新实例 + 空目录 → 返回 ""，
  不得编造摘要。
- `test_bad_result_file_skipped_not_fatal`（双向反例）：目录里混入一个写坏字节的
  `result-<t>-x-<ts>.json` → 摘要仍由好文件生成（坏文件跳过）。
- `test_result_filename_collision_safe`：同 task_id + expert_id 连续两次
  `save_context` → 存在两个不同 result 文件，且第一次写入的内容未被覆盖
  （修前秒级时间戳同名覆盖，**RED**）。
- `test_scripts_dir_inserted_once`：同一实例连续调 `_llm_summarize("x")` 两次
  （LLM 不可用时走 :211-214 降级截断，不触网）→ `sys.path.count(_SCRIPTS_DIR) == 1`
  （修前 ==2，**RED**）；测试 finally 还原 sys.path。

**验证命令**：
```bash
python -m pytest tests/test_context_wiring.py -q
```

**Expected**：五条 RED→GREEN。注意 subprocess 内 env 不污染真实
`~/.zcode`——`context_dir` 显式传 tmp_path（构造参数 :55-59 支持）。

---

### Task 14: zcode_expert_system.py 接线验证 + 死代码兜底处置

**Files**：`zcode_expert_system.py:904-917`（context_summary 装配点与死兜底）、
`:819-838`（`_load_context_summary`，本身不动）；测试扩展 `tests/test_context_wiring.py`。

**现状（已实锤）**：`:911-912` 的兜底
`if not context_summary: context_summary = manager_result.get("context_summary", "") or ""`
——`dispatch_manager` 从不写 `context_summary` 键（:906-909 注释自己也承认），
兜底恒返回 ""，属死代码。Task 13 接线后 `_load_context_summary` 变为真路径，
兜底若保留会让读者误以为存在第二数据源。

**修法**：

```python
# 派发专家执行
#
# context_summary 唯一来源是上下文存储（_load_context_summary → 磁盘
# result-*.json 回填，见 context-manager.py get_context_summary）。
# dispatch_manager 从不写 context_summary 键——旧实现这里的
# manager_result.get(...) 兜底恒空串，属死代码，随接线复活一并删除。
context_summary = _load_context_summary(task_id)
expert_result = dispatch_expert(
    selected_expert=selected_expert,
    task_description=task_description,
    context_summary=context_summary,
)
```

**新增测试**（`tests/test_context_wiring.py`，subprocess 集成）：

- `test_full_chain_second_call_has_context`：subprocess 跑
  `python zcode_expert_system.py "<任务>" --task-id t-wire` 两次（**同一隔离 HOME**：
  env 覆盖 `USERPROFILE`/`HOME` 指向 tmp_path，使 `_default_store_dir()` 落在
  `tmp/.zcode/expert-system/context`——`os.path.expanduser` 读这两个变量，实测路径）。
  断言第二次运行的 stdout JSON 中派发单含非空前序上下文
  （断言点：`expert_result` 内 prompt 含 `【前序上下文】`，字段位置以
  `dispatch_expert` 返回结构 `zcode_expert_system.py:736-783` 为准——
  :758-759 证明 prompt 拼接该头，:779 证明返回 dict 携带 `context_summary` 键，
  实施时以两者其一为准写死断言，不得改成模糊的「字段里找找」）。
  修前：Task 13 未接或本兜底未删时第二次仍 ""（**RED**）。
- `test_one_shot_without_task_id_has_empty_context`（双向反例）：不传 task_id →
  输出 JSON 中 `context_summary == ""` 且 prompt **不含** `【前序上下文】` 头
  （:758-759 的 `if context_summary:` 分支保证，防空段注入）。

**验证命令**：
```bash
python -m pytest tests/test_context_wiring.py -q
grep -n "manager_result.get(\"context_summary\"" zcode_expert_system.py   # 期望零命中
```

**Expected**：集成两条 RED→GREEN；死键 grep 零命中。
**注意**：本任务依赖 Task 13 先行（同一批次内串行）。

**批次四批末门禁**：`python -m pytest tests/ -q` 全绿 + L1 自审。

---

### Task 15: hook 账本字段白名单消毒

**Files**：`hooks/prepend-global-rules-reminder.mjs:153-155`（`\S+` 裸捕获）、
`:169-172`（`pick`）；测试扩展 `tests/test_hooks.py`。

**现状（已实锤）**：phase/status/scale 从账本 `progress.md` 头 60 行
（:149 `slice(0, 60)`）以 `(\S+)` 捕获后**未消毒**即拼进
`additionalContext`（:159-166）注入每轮用户上下文。账本是自由文本文件，
恶意或意外内容（控制字符、超长值、模板语法）会原样进入每轮 prompt。

**修法**（fail-open 原则：消毒只丢字段，hook 永不 rc≠0）：

```js
// 白名单消毒：账本是自由文本，捕获值在注入前必须过闸。
// 允许：字母/数字/下划线/短横线/点/加号 + 中文（值可为中文，如「S5实施」——
// 注意捕获用 `(\S+)`，值天然不含空格，白名单亦不含空格，两处口径一致）。
// 剔除控制字符；超长（>40）或含白名单外字符 → 整个字段丢弃（fail-open）。
function sanitizeField(value) {
  if (!value) return '';
  const cleaned = value.replace(/[\u0000-\u001f\u007f]/g, '');
  if (!cleaned || cleaned.length > 40) return '';
  return /^[A-Za-z0-9_\-.+\u4e00-\u9fff]+$/.test(cleaned) ? cleaned : '';
}
```

调用点（:153-155 之后）：

```js
const phase = sanitizeField(pick(head, /^#+\s*Current Phase\s*\n+\s*(\S+)/m));
const status = sanitizeField(pick(head, /^#+\s*Overall Status\s*\n+\s*(\S+)/m));
const scale = sanitizeField(pick(head, /^#+\s*Scale\s*\n+\s*(\S+)/m));
```

被丢弃的字段整行不注入（:162-164 的三元判定天然处理空串）。

**新增测试**（`tests/test_hooks.py`，复用 `write_ledger`/`workspace` 夹具 :205-219）：

- `test_field_with_control_chars_dropped`：账本 `## Current Phase` 值内嵌
  `\u0000` 或裸换行 → `additionalContext`（:71-73 助手）不含该值（**RED**）。
- `test_field_overlong_dropped`：>40 字符的 phase 值 → 不注入（**RED**）。
- `test_field_with_injection_syntax_dropped`：值含 `<script>` / `${...}` /
  反引号 → 不注入（**RED**）。
- `test_chinese_field_values_pass_through`（双向反例）：`Current Phase\nS5实施`、
  `Scale\n中任务` → 正常注入（捕获 `\S+` 不含空格，夹具值写无空格形式；白名单含中文；
  既有 `test_single_line_summary_has_expected_fields`（:292）的合法夹具值继续通过）。

**验证命令**：
```bash
python -m pytest tests/test_hooks.py -q
node -e "const m=require('fs').readFileSync('hooks/prepend-global-rules-reminder.mjs','utf8'); console.log(/sanitizeField/.test(m) ? 'sanitizer-present' : 'MISSING')"
```

**Expected**：四条 RED→GREEN；test_hooks.py 既有全部用例（:94-401）零回退。

---

### Task 16: 全量收尾（pytest 全绿 + L1 自审 + 清场）

**Files**：无代码改动（除 Task 3 已完成的旧计划确认项复核）。

1. **全量绿测**：`python -m pytest tests/ -q` ——
   基线 405 passed / 5 failed / 2 skipped → 预期终态 **410 passed + 新增用例全绿 +
   2 skipped**（新增用例数以各任务 Test 段实际条数为准：Task 2 约 2 条、Task 4 约 2 条、
   Task 5 约 3 条、Task 6 约 6 条、Task 7 约 3 条、Task 8 约 3 条、Task 9 约 1 条、
   Task 13 约 5 条、Task 14 约 2 条、Task 15 约 4 条；skipped 的 2 条确认仍是
   环境性 skip 而非新增 skip）。
2. **文档一致性复核**：Task 3 的三条 grep 复跑一次；SKILL.md / README / fusion-design
   与 `config/workflow.json` 口径一致。
3. **L1 自审声明**：对照本计划 Tasks 0-16 的 Files 清单逐文件核对实际改动，
   交付报告显式写明：「审查独立性 L1（无 git，快照证据 + 主控自审）」+
   每个任务一段「改动文件 × 验证命令 × 实测输出摘要」。
4. **Rulings I made**：实施中每项裁决（范围收窄、行号漂移改判、测试夹具取舍）
   按序汇总给老板。
5. **清场清单**（铁律 11：交付物与验证证据不清理）：
   - 删：实施期间的临时脚本 / 内联验证文件（若产生）；
   - **保留**：`/tmp/tree.bak-audit-B1..B5` 五份快照——交付确认前是唯一回滚手段，
     老板验收通过后另行征询是否清理；
   - **保留**：全部测试文件与文档改动（交付物本体）。
6. **完成声明前置**：按全局规则第十二章 A/B/C 三段自检表逐项过（B 段 TDD/red-green
   证据、C 段无 OpenSpec 变更故标「不适用（本次走本地快照流程，未开 OpenSpec 变更）」）。

**验证命令**：
```bash
python -m pytest tests/ -q
# 占位符扫描：只扫本次实施新增/改动的文件（既有文件的遗留 TODO 属历史，
# 记录并区分，不算本次违规）
grep -rnE "TBD|待定|加适当的|同 Task [0-9]" \
  scripts/workflow_check.py zcode_expert_system.py zcode_dev_workflow.py \
  context/context-manager.py hooks/prepend-global-rules-reminder.mjs \
  tests/test_context_wiring.py tests/test_unreadable_tri_state.py \
  tests/test_bug_signals_word_boundary.py \
  && echo "FOUND-PLACEHOLDER" || echo "clean"
```

---

## 附录一：审计发现 → 任务承接对照表

| 审计发现 | 承接任务 |
|---|---|
| A-9 六处 `read(...) or ""`（453/786/1045/1321/1325/1505） | Task 1 |
| A-14 残项：review-<N>.md required 无人消费 + :1278 注释失实 | Task 2 |
| 守卫测试 `"review" in id` 子串假满足（test_p8_precision.py:187-204） | Task 2 |
| 「workspace 已删 → inapplicable」防跨阶段假红（既有裁决） | Task 2 |
| 「条 当前等价于必」写进设计文档（test_p8_precision.py:33-34 承诺） | Task 3 |
| 旧计划 :1033-1037 P8 结论与现状不符 | Task 3 |
| SKILL.md:93「其余视情况」与 light（S4/S7=必）矛盾 | Task 3 |
| workflow_check.py 缺 `_force_utf8_stdout()` | Task 4 |
| BUG_SIGNALS ASCII 裸子串误中 debug/fixture | Task 5 |
| :739-743/:981-985 计划不可读混同未提供；:845/:897 账本不可读静默收缩 | Task 6 |
| package.json 改名 / URL / main / files 白名单（pyc、docs/superpowers 混入） | Task 7 |
| install.js PLUGIN_OUTPUTS 含 tests；agents 覆盖不备份 | Task 8 |
| expert-accounts-payable-agent.md AgenticBTC 供应链段 | Task 9 |
| README 双语安装命令 / cd 错行 / 方式三未上架 / 目录树 tests/ / 技能目录说明 | Task 10 |
| SKILL.md 第十一节缺 commands/templates/hooks/install.js | Task 11 |
| npm view 占用核查 + publish dry-run（须授权） | Task 12 |
| get_context_summary 只读内存 / load_result 零调用 / exec_module 恒新实例 | Task 13 |
| :99 时间戳碰撞；:199 sys.path 重复 insert | Task 13 |
| :911-912 死代码兜底 | Task 14 |
| hook :153-155 `\S+` 未消毒注入 | Task 15 |
| 全量绿测 + 旧计划确认 + L1 自审 + 清场 | Task 16 |

## 附录二：批次门禁汇总

| 批次 | 批末必须全绿的测试节点 | 额外验收 |
|---|---|---|
| 一 | `tests/` 全量 | A-9 五条 RED 转绿记录；三条文档 grep |
| 二 | `tests/` 全量 | CP936 手工命令 rc=0；分诊既有用例零回退 |
| 三 | `tests/` 全量 | `npm pack --dry-run` 清单干净；双语 grep 零旧名 |
| 四 | `tests/` 全量 | 全新进程读盘集成两条；死键 grep 零命中 |
| 五 | `tests/` 全量（终态） | L1 自审清单 + Rulings 汇总 + 清场清单 |
