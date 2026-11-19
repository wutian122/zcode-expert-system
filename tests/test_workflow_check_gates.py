# -*- coding: utf-8 -*-
"""P1 · 门禁判定语义回归测试（缺陷 #1 #2 #5 #6 #7 #8 + J/M/P + 2 处假红）

**这个文件要抓的破坏**：`scripts/workflow_check.py` 是整套「不靠自觉、机械可验」
承诺的唯一机器载体，而它在**七条路径上给出 rc=0 假绿**——本该 FAIL 的场景被判为通过。
假绿的危害远大于误报：误报会被人无视，假绿会让「通过」变成谎言。

每条用例的 docstring 都写明「修前实测」，即该用例在修复前必然失败的具体表现。
这些表现全部由主控在真实文件上复现过，不是推测。

**驱动真实行为**：直接用 `wc.run()` 在临时目录里跑真实检查流程，不 mock 判定逻辑。
唯一被替换的是「构造输入文件」这一步（写临时夹具），这属于测试夹具而非被测对象。

**分组**
  A. #1  change 名缺失的三态分流
  B. #2  independence 多标记取值
  C. #5  tasks.md 列表符与归档门禁静默
  D. #6  三元对齐的词尾边界与集合语义（含 2 处假红）
  E. #7  段名精确匹配（Review Focus ≠ Review）
  F. #8  trim_matrix 生效 / 规模校验 / 只读误标防护
  G. J/M/P 追加假绿
  H. H 组的杂项（env_probed / archive 子串 / 空检查项）
"""

import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts import workflow_check as wc  # noqa: E402


# ---------------------------------------------------------------------------
# 夹具
# ---------------------------------------------------------------------------

PLAN_FULL = """# Plan

## Goal
x
## Architecture
x
## Tech Stack
x
## Spec
x
## Review Focus
reviewer 只看 correctness
## Global Constraints
x
## Dependencies
x
## File Scope
x

## Baseline
- command: pytest -q
- exit: 0

## Review
independence: L0
reviewer: 代码审查员

## Rulings
Ruling: x — y — z

## Integration Verification
- command: pytest -q
- exit: 0

### Task 1: alpha

do a
"""

PLAN_REL = "docs/superpowers/plans/p.md"
LEDGER_REL = ".superpowers/sdd/p/progress.md"
LEDGER_HEAD = "# SDD ledger — plan: docs/superpowers/plans/p.md\n\n"


def _safe_write(root, rel, content):
    """在临时根内安全写文件：解析后必须仍在 root 之下。"""
    target = (root / rel).resolve()
    root_resolved = root.resolve()
    if root_resolved not in target.parents and target != root_resolved:
        raise ValueError("路径逃出临时根：%s" % rel)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target


def build(root, *, tasks="- [x] 1.1 alpha\n", ledger=None, plan=PLAN_FULL,
          delta_spec=True, workspace=True, archive_dir=False):
    """构造一个「证据齐备」的最小项目树，再按参数逐项注入缺陷。"""
    _safe_write(root, "openspec/changes/demo/proposal.md", "## Why\nx\n")
    _safe_write(root, "openspec/changes/demo/design.md", "## Design\nx\n")
    _safe_write(root, "openspec/changes/demo/tasks.md", tasks)
    _safe_write(root, "openspec/changes/demo/.openspec.yaml", "name: demo\n")
    if delta_spec:
        _safe_write(root, "openspec/changes/demo/specs/auth/spec.md", "## Requirement\nx\n")
    _safe_write(root, "openspec/specs/auth/spec.md", "## Purpose\nx\n")
    if plan is not None:
        _safe_write(root, PLAN_REL, plan)
    if workspace:
        _safe_write(root, LEDGER_REL,
                    (ledger if ledger is not None else LEDGER_HEAD +
                     "independence: L0\nTask 1: complete (abc123)\n"))
        _safe_write(root, ".superpowers/sdd/p/task-1-brief.md", "brief\n")
        _safe_write(root, ".superpowers/sdd/p/task-1-report.md", "report\n")
    if archive_dir:
        _safe_write(root, "openspec/changes/archive/2026-01-01-demo/proposal.md", "x\n")
    return root


@pytest.fixture
def proj():
    d = Path(tempfile.mkdtemp(prefix="wfc_gates_")).resolve()
    yield d
    shutil.rmtree(str(d), ignore_errors=True)


def runp(root, change="demo", plan=PLAN_REL, scale="medium"):
    return wc.run(change=change, plan=plan, scale=scale, root=str(root))


def find(rep, needle):
    """取 check 名含 needle 的条目（沿用现有测试的中文子串断言口径）。"""
    hits = [i for i in rep.items if needle in i["check"]]
    assert hits, "没有找到 check 含 %r 的条目；实际 checks=%s" % (
        needle, [i["check"] for i in rep.items])
    return hits[0]


def run_status(root, needle=None, **kw):
    rep, _ = runp(root, **kw)
    return find(rep, needle) if needle else rep


# ===========================================================================
# A. #1 —— change 名缺失的三态分流
# ===========================================================================

def test_unknown_change_name_is_fail_not_skip(proj):
    """变更名拼错必须 FAIL，不得 SKIP。

    修前实测：真实目录叫 `demo`，传 `--change dmeo` →
    `汇总：OK 3 / WARN 0 / FAIL 0 / SKIP 7`，`结论：无 FAIL 项`，**rc=0**。
    S2/S5/S8 三道门禁同时静默消失——一次拼写错误让门禁整体失效。

    根因：把「参数拼错」（应 FAIL）与「OpenSpec 未初始化」（应 SKIP）并进同一分支。
    """
    build(proj)
    rep, _ = runp(proj, change="dmeo")
    item = find(rep, "变更目录存在")
    assert item["status"] == wc.FAIL, (
        "变更名不存在必须 FAIL，实际 %s（detail=%s）" % (item["status"], item["detail"]))
    assert rep.has_fail()


def test_unknown_change_name_nonzero_exit(proj):
    """rc 必须非零——否则主控会把「无 FAIL 项」当放行证。"""
    build(proj)
    rc = wc.main(["--root", str(proj), "--change", "dmeo",
                  "--plan", PLAN_REL, "--scale", "medium"])
    assert rc == 1


def test_unknown_change_does_not_swallow_later_stages(proj):
    """S2 判定失败后，S8 的检查项仍必须产出（不得 `return` 吞掉后续阶段）。

    修前实测：`:144-147` 的 `return` 让 S5/S8 整段消失，连 PARKED 都不查。
    """
    build(proj)
    rep, _ = runp(proj, change="dmeo")
    assert any("归档" in i["check"] or "PARKED" in i["check"] for i in rep.items), (
        "S2 失败后 S8 的检查项消失了——门禁被 `return` 整段吞掉")


def test_no_openspec_dir_still_skips(proj):
    """合法场景守卫：未初始化 OpenSpec 时，若没传 --change 应 SKIP 而非 FAIL。

    防的破坏：把「未初始化」也判 FAIL，导致非 OpenSpec 项目无法用它核对
    （本项目自身就是这种状态：实测 `openspec=无`）。
    """
    build(proj)
    shutil.rmtree(str(proj / "openspec"), ignore_errors=True)
    rep, _ = wc.run(change=None, plan=PLAN_REL, scale="light", root=str(proj))
    items = [i for i in rep.items if "变更目录" in i["check"]]
    assert items, "S2 应产出一条检查项"
    assert items[0]["status"] in (wc.SKIP, wc.OK), (
        "未初始化 OpenSpec 且未传 --change 时不该 FAIL，实际 %s" % items[0]["status"])


def test_archived_change_reports_archived_not_missing(proj):
    """已归档的变更应给出「已归档」提示，而不是笼统的「不存在」。

    这是可操作性要求：两者都 FAIL，但用户看到的信息决定他下一步做什么。
    """
    build(proj, archive_dir=True)
    shutil.rmtree(str(proj / "openspec/changes/demo"), ignore_errors=True)
    item = run_status(proj, "变更目录存在", change="demo")
    assert item["status"] == wc.FAIL
    assert "归档" in item["detail"], (
        "已归档场景应提示「已归档」，实际 detail=%s" % item["detail"])


def test_change_name_path_traversal_rejected(proj):
    """`--change ../../docs` 必须 FAIL，不得逃出 openspec/changes。

    修前实测：`os.path.join(root,"openspec","changes","../../docs")` 解析到
    `<root>/docs`，即 `--change` 可以指向任意目录并对其做「规格检查」。
    """
    build(proj)
    item = run_status(proj, "变更目录存在", change="../../docs")
    assert item["status"] == wc.FAIL


# ===========================================================================
# B. #2 —— independence 多标记取值
# ===========================================================================

def test_independence_worst_marker_wins(proj):
    """账本先写「L0 设想」再写「最终 L2」时必须判 L2。

    修前实测：`re.search` 只取首个匹配 → `[ OK ] 级别 L0`。
    而 L2 是 workflow.json `reviewer_independence.levels.L2` 定义的
    「禁止交付」——全流程唯一硬性交付禁止项，却被一句历史讨论洗白。
    """
    build(proj, ledger=LEDGER_HEAD + "independence: L0 设想\n"
                                    "最终 independence: L2（无审查）\n"
                                    "Task 1: complete (abc123)\n")
    item = run_status(proj, "独立性")
    assert item["status"] == wc.FAIL, (
        "末位是 L2 应判 FAIL，实际 %s（detail=%s）" % (item["status"], item["detail"]))
    assert "L2" in item["detail"]


def test_independence_across_plan_and_ledger_worst_wins(proj):
    """计划写 L0、账本写 L2：两份载体取最坏值（不能只看先出现的那份）。"""
    build(proj, ledger=LEDGER_HEAD + "independence: L2\nTask 1: complete (abc123)\n")
    item = run_status(proj, "独立性")
    assert item["status"] == wc.FAIL


def test_independence_l2_alone_still_fails(proj):
    """回归守卫：只写 L2 时本来就能判 FAIL，修复不得破坏这条既有能力。"""
    build(proj, ledger=LEDGER_HEAD + "independence: L2\nTask 1: complete (abc123)\n")
    assert run_status(proj, "独立性")["status"] == wc.FAIL


def test_independence_l0_alone_passes(proj):
    """回归守卫：只写 L0 时必须 OK（不得改成「有多个标记就 FAIL」的过度收紧）。"""
    build(proj)
    assert run_status(proj, "独立性")["status"] == wc.OK


def test_independence_marker_in_code_fence_ignored(proj):
    """围栏代码块里的示例 `independence: L0` 不得充当证据。

    防的破坏：账本/计划里贴了一段模板示例（```...independence: L0...```），
    被当成真实标记，从而把真实的 L2 判成 L0。
    """
    build(proj, ledger=LEDGER_HEAD + "```\nindependence: L0   # 示例\n```\n"
                                    "independence: L2\nTask 1: complete (abc123)\n")
    assert run_status(proj, "独立性")["status"] == wc.FAIL


# ===========================================================================
# C. #5 —— tasks.md 列表符与归档门禁静默
# ===========================================================================

def test_star_bullet_tasks_are_counted(proj):
    """`* [ ]` 必须被计入勾选统计。

    修前实测：`count_checkboxes` 只认 `^\\s*-\\s*\\[`，星号列表 →
    `total==0` → `[SKIP] tasks.md 无勾选项`。OpenSpec 自己的解析器接受
    `-`/`*`/`+`/`1.`/`1)`（见 node_modules/@fission-ai/openspec/dist/utils/task-progress.js）。
    """
    build(proj, tasks="* [ ] alpha\n* [x] beta\n")
    item = run_status(proj, "completedTasks")
    assert item["status"] == wc.FAIL, (
        "星号列表的未完成任务未被计入（应 FAIL 1/2 完成）；实际 %s" % item["status"])
    assert "未完成 1" in item["detail"], (
        "应识别出 1 项未完成；detail=%s" % item["detail"])


def test_plus_and_ordered_bullets_are_counted(proj):
    """`+ [ ]` 与 `1. [ ]` 同样必须计入（OpenSpec 口径：任意 CommonMark 列表符）。"""
    build(proj, tasks="+ [ ] a\n1. [ ] b\n")
    item = run_status(proj, "completedTasks")
    assert item["status"] == wc.FAIL
    assert "未完成 2" in item["detail"], (
        "两种列表符都应计入；detail=%s" % item["detail"])


def test_no_checkbox_at_all_is_fail_not_skip(proj):
    """tasks.md 存在但一个勾选框都没有 → 必须 FAIL（malformed），不得 SKIP。

    修前实测：`total==0` → SKIP 且 `return`，连带跳过 PARKED/specs/archive 三项，
    等于放行一个格式非法的变更。
    """
    build(proj, tasks="这是一份没有勾选框的任务清单\n")
    item = run_status(proj, "completedTasks")
    assert item["status"] == wc.FAIL, (
        "无勾选框应判 malformed FAIL，实际 %s" % item["status"])
    assert "解析不到任何勾选框" in item["detail"]


def test_no_checkbox_does_not_skip_parked_check(proj):
    """无勾选框时，PARKED / 主 spec / 归档三项仍必须产出检查项。"""
    build(proj, tasks="无勾选\n",
          ledger=LEDGER_HEAD + "independence: L0\nTask 2: parked (reason)\n")
    rep, _ = runp(proj)
    checks = " ".join(i["check"] for i in rep.items)
    assert "PARKED" in checks, "PARKED 检查被吞掉了；checks=%s" % checks


def test_completed_star_bullet_passes_archive(proj):
    """`* [x]` 全部完成时归档门禁应通过（不得因为换了列表符就一律 FAIL）。"""
    build(proj, tasks="* [x] 1.1 alpha\n")
    item = run_status(proj, "completedTasks")
    assert item["status"] == wc.OK, "全部完成却判 %s：%s" % (item["status"], item["detail"])


# ===========================================================================
# D. #6 —— 三元对齐：词尾边界 + 集合语义（含 2 处假红）
# ===========================================================================

def test_complete_pending_is_not_complete(proj):
    """`Task 2: complete_pending` 不得计入完成。

    修前实测：`Task\\s+\\d+.*:\\s*complete` 无词尾锚点 → 勾选 2 / ledger complete 2 → OK。
    """
    build(proj, tasks="- [x] 1.1 a\n- [x] 2.1 b\n",
          ledger=LEDGER_HEAD + "independence: L0\n"
                              "Task 1: complete (abc)\nTask 2: complete_pending\n")
    item = run_status(proj, "三元对齐")
    assert item["status"] == wc.FAIL, (
        "complete_pending 被计为完成；detail=%s" % item["detail"])


def test_completed_word_is_still_accepted(proj):
    """`Task 1: completed` 是合法变体，不得因加词尾锚点而误杀。

    防的破坏：把 `\\b` 写成 `$` 或过严的 lookahead，导致既合规写法也被判失败。
    """
    build(proj, ledger=LEDGER_HEAD + "independence: L0\nTask 1: completed (abc)\n")
    assert run_status(proj, "三元对齐")["status"] == wc.OK


def test_multi_line_complete_not_counted(proj):
    """跨行的 `Task 1:` ⏎ `complete` 不得计入（`\\s*` 跨行正是缺陷成因）。"""
    build(proj, ledger=LEDGER_HEAD + "independence: L0\nTask 1:\ncomplete\n")
    assert run_status(proj, "三元对齐")["status"] == wc.FAIL


def test_one_task_covers_multiple_leaves_is_ok(proj):
    """假红修复：一个 `### Task 1 (covers 1.1,1.2,1.3)` 覆盖 3 个叶子应判 OK。

    修前实测：`勾选 3 / ledger complete 1` → FAIL。
    而 references/stage-S3-plan.md:46 明文允许 `1 Task ≥ 1 叶子`（covers 语法）。
    即：按文档做对的写法被门禁判死——这是「制度逼人编证据」的典型来源。
    """
    build(proj, tasks="- [x] 1.1 a\n- [x] 1.2 b\n- [x] 1.3 c\n",
          ledger=LEDGER_HEAD + "independence: L0\nTask 1: complete (abc)\n")
    item = run_status(proj, "三元对齐")
    assert item["status"] == wc.OK, (
        "一 Task 覆盖多叶子被误判；detail=%s" % item["detail"])


def test_two_completes_on_one_line_counted_separately(proj):
    """假红修复：同一行写两个 `Task N: complete` 必须计为 2。

    修前实测：`.*` 贪婪 → `勾选 2 / ledger complete 1` → FAIL。
    """
    build(proj, tasks="- [x] 1.1 a\n- [x] 2.1 b\n",
          ledger=LEDGER_HEAD + "independence: L0\n"
                              "Task 1: complete (a) | Task 2: complete (b)\n")
    item = run_status(proj, "三元对齐")
    assert item["status"] == wc.OK, (
        "一行两个 complete 被合并；detail=%s" % item["detail"])


def test_leaf_without_number_falls_back_to_count(proj):
    """叶子无编号时退化到计数比较，且不得误报。

    防的破坏：集合判据在「tasks.md 无编号」时算出空集，把一切判成 FAIL。
    """
    build(proj, tasks="- [x] alpha\n- [x] beta\n",
          ledger=LEDGER_HEAD + "independence: L0\n"
                              "Task 1: complete (a)\nTask 2: complete (b)\n")
    assert run_status(proj, "三元对齐")["status"] == wc.OK


# ===========================================================================
# E. #7 —— 段名精确匹配
# ===========================================================================

def test_review_focus_does_not_satisfy_review_section(proj):
    """`## Review Focus` 不得冒充 `## Review`（审查结论）。

    修前实测：计划里只有 `## Review Focus: reviewer 只看 correctness`
    → `[ OK ] 审查结论已持久化`。即用 S3 的「计划必备段」冒充了 S6 的「审查结论证据」。
    """
    plan = PLAN_FULL.replace("## Review\nindependence: L0\nreviewer: 代码审查员\n", "")
    build(proj, plan=plan)
    item = run_status(proj, "审查结论")
    assert item["status"] != wc.OK, (
        "Review Focus 冒充了 Review 段；status=%s" % item["status"])


def test_spec_section_not_satisfied_by_specification(proj):
    """`## Specification` 不得满足必备段 `Spec`（前缀匹配无边界）。

    修前实测：`^#+\\s*Spec` 会命中 `## Specification of things` → `[OK] 必备段：Spec`。
    后果：某段只需以必备段名**开头**即可冒充，8 个必备段检查形同虚设。
    """
    plan = PLAN_FULL.replace("## Spec\nx\n", "## Specification of things\nx\n")
    build(proj, plan=plan)
    item = run_status(proj, "必备段：Spec")
    assert item["status"] == wc.FAIL, (
        "`## Specification` 冒充了 `## Spec`；status=%s" % item["status"])


def test_architecture_notes_not_satisfy_architecture(proj):
    """`## Architecture Notes` 不得满足必备段 `Architecture`（同族缺陷）。"""
    plan = PLAN_FULL.replace("## Architecture\nx\n", "## Architecture Notes\nx\n")
    build(proj, plan=plan)
    assert run_status(proj, "必备段：Architecture")["status"] == wc.FAIL


def test_exact_section_still_passes(proj):
    """回归守卫：精确段名写法必须仍然通过（不得收紧成永远 FAIL）。"""
    build(proj)
    for sec in ("Goal", "Architecture", "Tech Stack", "Spec",
                "Review Focus", "Global Constraints", "Dependencies", "File Scope"):
        assert run_status(proj, "必备段：%s" % sec)["status"] == wc.OK, sec


def test_section_with_inline_comment_still_passes(proj):
    """`## Review（审查结论）` 这类带括注的写法应视为同一个段（可操作性）。"""
    plan = PLAN_FULL.replace("## Review\n", "## Review（审查结论）\n")
    build(proj, plan=plan)
    assert run_status(proj, "审查结论")["status"] == wc.OK


# ===========================================================================
# F. #8 —— trim_matrix 生效 / 规模校验 / 只读误标防护
# ===========================================================================

def test_readonly_scale_has_zero_fail(proj):
    """只读规模：装配齐全的只读任务应 0 FAIL。

    修前实测：`--scale readonly` → 11 项 FAIL（含 `## Baseline`、`### Task N:`
    、independence 等），rc=1。而 trim_matrix 对 readonly 声明 S1–S8 全 `-`，
    两轴工具对同一任务给出互相矛盾的结论，用户只能「无视 rc」或「编造证据」。

    **本用例不传 --plan**（P6 A-2 修复后）：只读任务按 trim_matrix 不产生
    plan，所以「只读 + 给了 plan」是自相矛盾的声明，现在会 FAIL
    （`malformed:readonly_mismatch`）。要测「只读任务正常通过」，
    夹具就必须是不带 plan 的只读形态。
    """
    build(proj, workspace=False, tasks="- [x] 1\n")
    rep, _ = wc.run(change=None, plan=None, scale="readonly", root=str(proj))
    assert rep.count(wc.FAIL) == 0, (
        "readonly 不该有 FAIL；实际 FAIL=%d：%s"
        % (rep.count(wc.FAIL),
           [(i["check"], i["detail"][:60]) for i in rep.items if i["status"] == wc.FAIL]))


def test_readonly_with_plan_is_contradiction(proj):
    """只读 + 给了 --plan 是自相矛盾 → 必须 FAIL（P6 A-2 的正面表达）。

    这条是上一条的反面：上一条测「干净只读能过」，这条测「自相矛盾必须卡」。
    """
    build(proj, workspace=False, tasks="- [x] 1\n")
    _safe_write(proj, "docs/superpowers/plans/ro.md", "# 只读分析\n\n## Goal\n看代码\n")
    rep, _ = wc.run(change=None, plan="docs/superpowers/plans/ro.md",
                    scale="readonly", root=str(proj))
    assert any(i["id"] == "S0.SCALE_MISMATCH" and i["status"] == wc.FAIL
               for i in rep.items), (
        "只读 + --plan 未被判为矛盾声明；FAIL=%s"
        % [(i["id"], i["reason"]) for i in rep.items if i["status"] == wc.FAIL])


def test_readonly_skips_are_labelled_with_reason(proj):
    """被裁剪的阶段必须产出 SKIP 且写明理由，不能凭空消失（可审计）。"""
    build(proj, workspace=False)
    _safe_write(proj, "docs/superpowers/plans/ro.md", "# 只读\n\n## Goal\nx\n")
    rep, _ = wc.run(change=None, plan="docs/superpowers/plans/ro.md",
                    scale="readonly", root=str(proj))
    skips = [i for i in rep.items if i["status"] == wc.SKIP]
    assert skips, "READONLY 下应有被裁剪阶段的 SKIP 记录"
    for i in skips:
        assert i["detail"], "SKIP 必须写理由：%s" % i["check"]


@pytest.mark.parametrize("bad", ["nonsense", "Medium", " medium", "LIGHT"])
def test_invalid_scale_is_fail(proj, bad):
    """非法/大小写不规范/带空格的规模值必须 FAIL。

    修前实测：`--scale nonsense` → `[ OK ] 规模已分类 —— scale=nonsense`。
    未知规模无法查 trim_matrix，只能按最严执行或直接报错——绝不能判 OK。
    """
    build(proj)
    rep, _ = wc.run(change="demo", plan=PLAN_REL, scale=bad, root=str(proj))
    item = find(rep, "规模")
    assert item["status"] == wc.FAIL, (
        "scale=%r 被接受为 OK（detail=%s）" % (bad, item["detail"]))


def test_invalid_scale_exit_code_is_param_error(proj):
    """CLI 层非法规模应返回 2（参数错误），与「内容不合格」的 1 区分开。"""
    build(proj)
    rc = wc.main(["--root", str(proj), "--change", "demo",
                  "--plan", PLAN_REL, "--scale", "nonsense"])
    assert rc == 2, "非法 --scale 应 rc=2，实际 %d" % rc


def test_light_scale_does_not_demand_all_eight_sections(proj):
    """轻量规模不得要求全部 8 个必备段（「简」只减项、不减严重度）。

    修前实测：`--scale light` 下只含 Goal 与 Task 标题的计划仍被判 7 个必备段 FAIL。
    """
    build(proj, plan="# P\n\n## Goal\nx\n\n### Task 1: a\n",
          ledger=LEDGER_HEAD + "independence: L0\nTask 1: complete (abc)\n")
    rep, _ = wc.run(change="demo", plan=PLAN_REL, scale="light", root=str(proj))
    section_fails = [i for i in rep.items
                     if "必备段" in i["check"] and i["status"] == wc.FAIL]
    assert not section_fails, (
        "light 仍要求全部必备段：%s" % [i["check"] for i in section_fails])


def test_light_scale_still_requires_task_title(proj):
    """「简」不得形同虚设：缺 `### Task N:` 必须 FAIL（task-brief 脚本依赖它）。"""
    build(proj, plan="# P\n\n## Goal\nx\n", 
          ledger=LEDGER_HEAD + "independence: L0\n")
    rep, _ = wc.run(change="demo", plan=PLAN_REL, scale="light", root=str(proj))
    item = find(rep, "任务标题")
    assert item["status"] == wc.FAIL


def test_readonly_with_change_or_plan_warns(proj):
    """只读误标防护：声明 readonly 却给了 --change/--plan 必须告警。

    防的破坏：trim_matrix 生效后，任何人只要写 `--scale readonly` 就能让
    任意真实变更拿到 rc=0——从「误报淹没」退化成「一键放行」，性质更坏。
    """
    build(proj)
    rep, _ = wc.run(change="demo", plan=PLAN_REL, scale="readonly", root=str(proj))
    assert any(i["status"] in (wc.WARN, wc.FAIL) for i in rep.items), (
        "readonly 同时给了 change 与 plan 却无任何告警")
    detail = " ".join(i["detail"] for i in rep.items)
    assert "只读" in detail or "readonly" in detail.lower(), (
        "告警需写明规模可能标注错误；detail=%s" % detail)


def test_scale_conflicts_with_ledger_fails(proj):
    """账本记录的规模与 --scale 冲突必须 FAIL（runtime 自报 vs 账本留痕交叉校验）。

    这是真正的闭环：只靠调用方自报 `--scale` 无法防住「标注 readonly 逃避门禁」。
    """
    build(proj, ledger=LEDGER_HEAD + "## Scale\nmedium\n"
                                    "independence: L0\nTask 1: complete (abc)\n")
    rep, _ = wc.run(change="demo", plan=PLAN_REL, scale="readonly", root=str(proj))
    assert rep.has_fail(), "账本写 medium 却传 readonly，应报冲突 FAIL"


# ===========================================================================
# G. J / M / P —— 追加假绿
# ===========================================================================

def test_missing_plan_at_medium_is_fail(proj):
    """medium 规模下不给 --plan 必须 FAIL。

    修前实测：`--change demo --scale medium`（无 --plan）→
    `OK 10 / WARN 1 / FAIL 0 / SKIP 5`，rc=0。S3/S4/S7 三项证据全部跳过。
    """
    build(proj)
    rep, _ = wc.run(change="demo", plan=None, scale="medium", root=str(proj))
    item = find(rep, "计划文档")
    assert item["status"] == wc.FAIL, (
        "medium 下缺 --plan 被判 %s（SKIP 即假绿）" % item["status"])


def test_missing_change_at_medium_is_fail(proj):
    """medium 规模下不给 --change 必须 FAIL（S2 规格产物无从核对）。"""
    build(proj)
    rep, _ = wc.run(change=None, plan=PLAN_REL, scale="medium", root=str(proj))
    items = [i for i in rep.items if "变更目录" in i["check"]]
    assert items and items[0]["status"] == wc.FAIL, (
        "medium 下缺 --change 未判 FAIL：%s" % (items and items[0]["status"]))


def test_missing_workspace_at_medium_not_silent(proj):
    """medium、变更未完成、无 workspace → 必须 FAIL 或具名 WARN，不得静默 rc=0。

    修前实测：`--change demo --plan ...`（无 workspace）→
    `OK 27 / WARN 1 / FAIL 0 / SKIP 2`，rc=0。S5 整段 SKIP，
    而 workflow.json 把逐任务产物标为 `required: true`。
    """
    build(proj, workspace=False, tasks="- [ ] 1.1 alpha\n")
    rep, _ = runp(proj)
    item = find(rep, "任务产物")
    assert item["status"] in (wc.FAIL, wc.WARN), (
        "无 workspace 却被判 %s" % item["status"])
    assert item["status"] != wc.SKIP or item["detail"].count("inapplicable") > 0, (
        "无 workspace 的 SKIP 必须写明 inapplicable 理由，不能静默：%s" % item["detail"])


def test_missing_root_fails(proj):
    """`--root` 指向不存在的目录必须 FAIL。

    修前实测：`[ OK ] 环境已探测（git / openspec root） —— git=无, openspec=无`，
    rc=0。根因是 `"env_probed": True` 写死——环境探测从未真正发生。
    """
    missing = str(proj / "does-not-exist")
    rep, ctx = wc.run(change=None, plan=None, scale="medium", root=missing)
    item = find(rep, "环境已探测")
    assert item["status"] == wc.FAIL, (
        "不存在的 root 被判 OK（env_probed 写死）")


def test_existing_root_env_probe_is_ok(proj):
    """回归守卫：真实存在的 root 环境探测仍应为 OK。"""
    build(proj)
    assert run_status(proj, "环境已探测")["status"] == wc.OK


# ===========================================================================
# H. 杂项
# ===========================================================================

def test_archive_substring_match_rejected(proj):
    """`archive/2026-01-01-demo-v2/` 不得满足变更 `demo`（子串匹配缺陷）。

    修前实测：`ctx["change"] in e` → `my-change` 命中 `my-change-v2`。
    """
    build(proj, tasks="- [x] 1.1 a\n")
    _safe_write(proj, "openspec/changes/archive/2026-01-01-demo-v2/proposal.md", "x\n")
    item = run_status(proj, "归档目录")
    assert item["status"] != wc.OK, (
        "子串匹配误命中：%s" % item["detail"])


def test_archive_dir_absent_produces_an_item(proj):
    """archive/ 不存在时必须产出一条检查项（修前：一个都不产生）。

    修前实测：`if os.path.isdir(arch)` 为假 → 完全不 `rep.add`，
    归档状态在报告里彻底隐形。
    """
    build(proj, tasks="- [x] 1.1 a\n")
    rep, _ = runp(proj)
    assert any("归档" in i["check"] for i in rep.items), (
        "archive 目录缺失时没有任何检查项")


def test_no_stage_silently_emits_zero_items(proj):
    """INV-R1 无静默：每个未被裁剪的阶段至少产出一条检查项。

    防的破坏：任何未来新增的提前 `return` 让某阶段整段消失——
    这正是 #1/#5 的共同根因形态。
    """
    build(proj)
    rep, ctx = runp(proj)
    gates = {i["gate"] for i in rep.items}
    assert len(gates) >= 8, "只产出了 %d 个阶段的检查项：%s" % (len(gates), sorted(gates))


def test_report_items_carry_identity(proj):
    """每条检查项应带稳定 id 与理由码，便于覆盖自检与机器消费。"""
    build(proj)
    rep, _ = runp(proj)
    assert all("id" in i for i in rep.items), "检查项缺 id 字段"


# ---------------------------------------------------------------------------
# I. S0.DOMAIN 关联性（enforce-domain-routing #11）
#
# 六格主判定（no_ledger / missing / ok / readonly_skip / malformed，含中文
# Scale「中任务」「只读」双形态夹具）已由 tests/test_domain_routing_mandatory.py
# 的 A7 组锁定；本组补 #11 账本关联性维度——遗留账本不得被扫入执法。
# ---------------------------------------------------------------------------

LEGACY_LEDGER = ("# SDD ledger — plan: docs/superpowers/plans/old.md\n\n"
                 "Task 1: complete (abc123)\n")


def test_s0_domain_legacy_ledger_not_scanned_when_plan_given(proj):
    """#11：--plan 给定时只查 plan 关联账本，不扫全仓遗留账本。

    本仓存在遗留账本（openspec-impl / vendor-skills，均无 Triage 域路由行）。
    若判定表做 discover_ledger 全仓兜底，合法运行会因遗留账本缺行被无限期
    FAIL——执法对象必须是 S0 即产生的**本计划**账本。
    """
    _safe_write(proj, PLAN_REL, PLAN_FULL)
    # 遗留账本：在 plan 关联 workspace（.superpowers/sdd/p/）之外，缺域路由行
    _safe_write(proj, ".superpowers/sdd/legacy-impl/progress.md", LEGACY_LEDGER)
    rep, _ctx = runp(proj)
    bad = [i for i in rep.items if i.get("reason") == "s0_domain_missing"]
    assert not bad, (
        "plan 关联账本缺失时不得扫全仓拿遗留账本执法（#11）；FAIL=%s"
        % [(i["id"], i["detail"]) for i in bad])
    skips = [i for i in rep.items if i.get("reason") == "inapplicable:no_ledger"]
    assert skips, (
        "plan 关联账本缺失应显式 SKIP（inapplicable:no_ledger），不得静默不产出；"
        "实际 S0.DOMAIN 相关 items=%s"
        % [(i["id"], i["status"], i["reason"]) for i in rep.items if i["id"] == "S0.DOMAIN"])
    assert skips[0]["status"] == wc.SKIP


def test_s0_domain_ok_cell_unaffected_by_legacy_ledger(proj):
    """#11 正向：plan 关联账本行齐 → OK 格成立，遗留账本不产生任何干扰。"""
    _safe_write(proj, PLAN_REL, PLAN_FULL)
    _safe_write(proj, ".superpowers/sdd/legacy-impl/progress.md", LEGACY_LEDGER)
    _safe_write(proj, LEDGER_REL,
                LEDGER_HEAD + "## Triage\n\n| 项 | 值 |\n|---|---|\n"
                "| 任务名 | x |\n"
                "| 领域（category） | backend-architecture |\n"
                "| 专家（name/basis） | 软件架构师（semantic） |\n")
    rep, _ctx = runp(proj)
    bad = [i for i in rep.items if i.get("reason") == "s0_domain_missing"]
    assert not bad, "行齐的 plan 关联账本不得判 s0_domain_missing（假红）"
    oks = [i for i in rep.items if i.get("id") == "S0.DOMAIN" and i["status"] == wc.OK]
    assert oks, (
        "行齐的 plan 关联账本必须产出 S0.DOMAIN OK 项；实际 S0.DOMAIN items=%s"
        % [(i["status"], i["reason"]) for i in rep.items if i["id"] == "S0.DOMAIN"])


def test_s8_parked_status_json_false_但账本有PARKED须FAIL(proj):
    """P1-4：.status.json parked=false，但账本有 PARKED 时，S8.PARKED 必须 FAIL。

    旧实现 .status.json 存在即以其 parked 字段为准，不查账本兜底——
    账本中真实存在的 PARKED 任务会被漏判，违反 W8「PARKED 默认禁归档」。
    修复前本用例因 S8.PARKED 报 OK 而 RED。
    """
    build(proj)
    # .status.json 声明 parked=false
    _safe_write(proj, "openspec/changes/demo/.status.json",
                json.dumps({"parked": False, "PARKED": False}, ensure_ascii=False))
    # 但账本中存在 PARKED 任务
    _safe_write(proj, LEDGER_REL,
                LEDGER_HEAD + "independence: L0\n"
                "Task 1: complete (abc123)\n"
                "Task 2: PARKED (def456) — 裁决\n")

    rep, _ctx = runp(proj)
    s8_parked = [i for i in rep.items if i.get("id") == "S8.PARKED"]
    assert s8_parked, "S8.PARKED 检查项必须产出"
    assert s8_parked[0]["status"] == wc.FAIL, (
        "P1-4：账本有 PARKED 但 .status.json parked=false 时 S8.PARKED 须 FAIL，"
        "不得被 .status.json 单点口径漏判\n"
        f"实际：{s8_parked[0]['status']} detail={s8_parked[0].get('detail','')}"
    )
