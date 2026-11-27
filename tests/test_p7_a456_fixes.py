# -*- coding: utf-8 -*-
"""P7 · 复核审查建议级项修复（A-4 / A-5 / A-6）

这三条的共同点：**不构成假绿，但正常使用会被误判**——
它们会持续侵蚀团队对门禁工具的信任，最终导致「无视 rc」，
那才是门禁真正的死因。

### A-4 交付后 workspace 已清理这个**正常终态**被判 FAIL

`AGENTS.md` 铁律 11 要求「完工清场」，即终审后删除 `.superpowers/sdd/<plan>/`。
但 `check_S4` 把「找不到账本」一律判 `missing:ledger` FAIL，
于是**按规范做完交付的项目，回查门禁时必然 rc=1**。
更糟的是它给的出路是「未使用 SDD 模式时请用 --scale light」——教人用降级绕门禁。

同一次运行里 S8 对「无账本」给的是 WARN（`soft:no_ledger`），
S4 给的是 FAIL —— 两个阶段对同一事实态度相反。

正确做法照 `check_S5` 已有的范式：按 tasks.md 是否还有未完成项三态分流。

### A-5 一个无编号叶子就让**全项目**退化到计数比较

`_tasks_done_ids` 原逻辑：只要有**一个**勾选叶子没写数字编号
（`n_no_id >= 1`），整体切到计数比较。而计数比较把「勾选叶子数」与
「任务号个数」当同一单位，于是文档明文允许的 `1 Task ≥ N 叶子`
（`references/stage-S3-plan.md:46` 的 covers 语法）必然假红。

实测原子行为：
    `_tasks_done_ids("- [x] 1.1 a\\n- [x] 1.2 b\\n- [x] 无编号 c\\n")`
    → `({'1'}, 3, 1)`，n_no_id=1 → basis=count → 3 != 1 → FAIL
同两份文件若第三行写成 `1.3 c` → id-set 比较 `{'1'}=={'1'}` → OK。
**同一事实，结论相反，只差一个编号。**

### A-6 用表格写 independence 会被整行剥掉

`strip_quoted_markers` 为防「文档里引用的示例被当成真实标记」，
整行丢弃以 `|` 开头的表格行。但表格恰恰是本项目模板的主推排版
（`templates/plan-sections.md` 的 Baseline / Integration Verification、
`templates/progress.md` 的 Triage 全是表格）。

后果：用表格填 `independence: L0` 被判「缺标记」FAIL（假红），
而填 `L2` 也判「缺标记」——**错误方向对不同取值不一致**。
"""

import os
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts import workflow_check as wc  # noqa: E402

REVIEW_HEAD = ("## Review\nindependence: L0\nimplementer: 软件架构师\n"
               "reviewer: 代码审查员\n")

PLAN = """### Task 1: a
## Baseline
x
## Review
independence: L0
implementer: 软件架构师
reviewer: 代码审查员
spec: \u2705
## Rulings
x
## Integration Verification
x
## Goal
x
## Architecture
x
## Tech Stack
x
## Spec
x
## Review Focus
x
## Global Constraints
x
## Dependencies
x
## File Scope
x
"""


@pytest.fixture
def proj(tmp_path):
    """证据齐备的最小项目（含 workspace）。"""
    (tmp_path / "openspec/changes/demo/specs/auth").mkdir(parents=True)
    (tmp_path / "openspec/specs/auth").mkdir(parents=True)
    (tmp_path / "docs").mkdir()
    (tmp_path / ".superpowers/sdd/p").mkdir(parents=True)
    (tmp_path / "openspec/changes/demo/proposal.md").write_text(
        "x\n", encoding="utf-8", newline="")
    (tmp_path / "openspec/changes/demo/design.md").write_text(
        "x\n", encoding="utf-8", newline="")
    (tmp_path / "openspec/changes/demo/tasks.md").write_text(
        "- [x] 1.1 a\n", encoding="utf-8", newline="")
    (tmp_path / "openspec/changes/demo/specs/auth/spec.md").write_text(
        "x\n", encoding="utf-8", newline="")
    (tmp_path / "openspec/changes/demo/.openspec.yaml").write_text(
        "n: d\n", encoding="utf-8", newline="")
    (tmp_path / "openspec/specs/auth/spec.md").write_text(
        "## Purpose\n认证主规格\n", encoding="utf-8", newline="")
    (tmp_path / "docs/p.md").write_text(PLAN, encoding="utf-8", newline="")
    (tmp_path / ".superpowers/sdd/p/progress.md").write_text(
        "# SDD ledger — plan: docs/p.md\n\n"
        # G5/G6 派发证据（dispatch 门禁）：完成态必须有 implementer/reviewer 派发行
        "## Dispatches\n\n"
        "dispatch 1 role=implementer agent=\"软件架构师\" "
        "category=backend-architecture instance=1 base=abc "
        "brief=.superpowers/sdd/p/task-1-brief.md "
        "report=.superpowers/sdd/p/task-1-report.md changeset=-\n"
        "dispatch 1 role=reviewer agent=\"代码审查员\" "
        "category=engineering-quality instance=1 base=abc "
        "brief=.superpowers/sdd/p/task-1-brief.md "
        "report=.superpowers/sdd/p/review-1.md changeset=-\n\n"
        "independence: L0\n"
        "Task 1: complete (abc)\n", encoding="utf-8", newline="")
    (tmp_path / ".superpowers/sdd/p/task-1-brief.md").write_text(
        "b\n", encoding="utf-8", newline="")
    (tmp_path / ".superpowers/sdd/p/task-1-report.md").write_text(
        "r\n", encoding="utf-8", newline="")
    return tmp_path


def _item(rep, id_):
    for i in rep.items:
        if i.get("id") == id_:
            return i
    raise AssertionError("找不到 id=%r；实际 ids=%s"
                         % (id_, [i.get("id") for i in rep.items]))


# ===========================================================================
# A-4 —— 交付后 workspace 已清理是正常终态，不得判 FAIL
# ===========================================================================

def test_cleaned_workspace_is_not_fail(proj):
    """交付完成 + workspace 已按铁律 11 清理 → 不得 FAIL。

    这是**正常终态**：`AGENTS.md` 铁律 11 要求完工清场，
    终审后删除 `.superpowers/sdd/<plan>/`。修前实测这种状态必然 rc=1：
        [FAIL] 账本存在 —— missing:ledger
        [WARN] 无 PARKED 残留 —— soft:no_ledger
    同一次运行里 S8 认为「无账本 = 可核验性不足（WARN）」，
    S4 认为「无账本 = FAIL」——两个阶段对同一事实态度相反。
    """
    import shutil
    shutil.rmtree(str(proj / ".superpowers"))

    rep, _ = wc.run(change="demo", plan="docs/p.md", scale="medium", root=str(proj))
    item = _item(rep, "S4.LEDGER")
    assert item["status"] != wc.FAIL, (
        "交付后正常清理被判 FAIL：%s（%s）" % (item["status"], item["detail"]))
    assert rep.count(wc.FAIL) == 0, (
        "清理后仍有 FAIL：%s"
        % [(i["id"], i["reason"]) for i in rep.items if i["status"] == wc.FAIL])


def test_unfinished_tasks_without_ledger_is_still_fail(proj):
    """反例：任务未完成却没有账本 → 仍必须 FAIL（证据缺失，不是正常清理）。

    防的破坏：为了放行「已清理」而让无账本一律 WARN ——
    那会把「实施做了一半、账本丢了」这种真问题也放过。
    """
    (proj / "openspec/changes/demo/tasks.md").write_text(
        "- [ ] 1.1 未完成\n", encoding="utf-8", newline="")
    import shutil
    shutil.rmtree(str(proj / ".superpowers"))

    rep, _ = wc.run(change="demo", plan="docs/p.md", scale="medium", root=str(proj))
    item = _item(rep, "S4.LEDGER")
    assert item["status"] == wc.FAIL, (
        "未完成任务 + 无账本被判 %s（应 FAIL）" % item["status"])


def test_ledger_missing_but_tasks_unreadable_is_fail(proj):
    """反例：tasks.md 读不到时无法判断是否完成 → 按 FAIL（不猜）。"""
    (proj / "openspec/changes/demo/tasks.md").unlink()
    import shutil
    shutil.rmtree(str(proj / ".superpowers"))

    rep, _ = wc.run(change="demo", plan="docs/p.md", scale="medium", root=str(proj))
    assert _item(rep, "S4.LEDGER")["status"] == wc.FAIL


def test_s4_and_s8_agree_on_missing_ledger(proj):
    """S4 与 S8 对「无账本」的态度必须一致（都 WARN 或都 FAIL）。

    修前实测：S4=FAIL、S8=WARN —— 同一事实两个结论，
    消费者无法判断该信哪个。
    """
    import shutil
    shutil.rmtree(str(proj / ".superpowers"))

    rep, _ = wc.run(change="demo", plan="docs/p.md", scale="medium", root=str(proj))
    s4 = _item(rep, "S4.LEDGER")
    s8 = _item(rep, "S8.PARKED")
    assert s4["status"] == s8["status"] or (
        s4["status"] != wc.FAIL and s8["status"] != wc.FAIL), (
        "S4=%s 与 S8=%s 对无账本结论相反" % (s4["status"], s8["status"]))


def test_existing_ledger_still_checked(proj):
    """回归守卫：账本存在时仍要检查首行身份（不得因放宽缺失判定而跳过）。"""
    (proj / ".superpowers/sdd/p/progress.md").write_text(
        "没有身份行\n", encoding="utf-8", newline="")
    rep, _ = wc.run(change="demo", plan="docs/p.md", scale="medium", root=str(proj))
    assert _item(rep, "S4.LEDGER_ID")["status"] == wc.FAIL


# ===========================================================================
# A-5 —— 混合编号不得让全项目退化到计数比较
# ===========================================================================

def test_mixed_numbered_unnumbered_leaves_stay_ok(proj):
    """一个 Task 覆盖多个叶子 + 其中一个叶子没编号 → 仍应 OK。

    修前实测：
        tasks.md = `- [x] 1.1 a` / `- [x] 1.2 b` / `- [x] 无编号 c`
        `_tasks_done_ids` → ({'1'}, 3, 1) → n_no_id=1 → 切到计数比较
        3（勾选叶子数）!= 1（ledger 任务号数）→ FAIL
    而 `references/stage-S3-plan.md:46` 明文允许 `1 Task ≥ N 叶子`。
    **同一事实，只因一个叶子漏写编号就全红。**
    """
    (proj / "openspec/changes/demo/tasks.md").write_text(
        "- [x] 1.1 a\n- [x] 1.2 b\n- [x] 无编号 c\n",
        encoding="utf-8", newline="")
    rep, _ = wc.run(change="demo", plan="docs/p.md", scale="medium", root=str(proj))
    item = _item(rep, "S5.TRIAD")
    assert item["status"] == wc.OK, (
        "混合编号被误判：%s（%s）" % (item["status"], item["detail"]))


def test_all_leaves_unnumbered_falls_back_to_count(proj):
    """反例：**全部**叶子都无编号时，才退化到计数比较。

    这是 A-5 修复后的正确退化条件（原来是「有一个就退化」）。
    """
    (proj / "openspec/changes/demo/tasks.md").write_text(
        "- [x] alpha\n- [x] beta\n",
        encoding="utf-8", newline="")
    (proj / ".superpowers/sdd/p/progress.md").write_text(
        "# SDD ledger — plan: docs/p.md\n\nindependence: L0\n"
        "Task 1: complete (a)\nTask 2: complete (b)\n",
        encoding="utf-8", newline="")
    rep, _ = wc.run(change="demo", plan="docs/p.md", scale="medium", root=str(proj))
    assert _item(rep, "S5.TRIAD")["status"] == wc.OK


def test_unnumbered_leaf_emits_its_own_warn(proj):
    """无编号叶子应单独出一条 WARN，而不是静默改变全项目判据。

    这是「把不可判定项显式化」的做法：不影响主判据，但留下可操作提示。
    """
    (proj / "openspec/changes/demo/tasks.md").write_text(
        "- [x] 1.1 a\n- [x] 无编号 c\n",
        encoding="utf-8", newline="")
    rep, _ = wc.run(change="demo", plan="docs/p.md", scale="medium", root=str(proj))
    warns = [i for i in rep.items
             if i["status"] == wc.WARN and "编号" in (i["detail"] or "")]
    assert warns, ("无编号叶子未产出任何提示；items=%s"
                   % [(i["id"], i["status"]) for i in rep.items])


def test_real_mismatch_still_fails_with_mixed_numbering(proj):
    """反例（关键）：混合编号下**真的不一致**仍必须 FAIL。

    防的破坏：为了让混合编号通过而把判据放宽成「总能过」。
    tasks.md 勾了 1 和 2，账本只记 1 → 集合 {1,2} vs {1} → 必须 FAIL。
    """
    (proj / "openspec/changes/demo/tasks.md").write_text(
        "- [x] 1.1 a\n- [x] 2.1 b\n- [x] 无编号 c\n",
        encoding="utf-8", newline="")
    rep, _ = wc.run(change="demo", plan="docs/p.md", scale="medium", root=str(proj))
    assert _item(rep, "S5.TRIAD")["status"] == wc.FAIL


# ===========================================================================
# A-6 —— 表格里写 independence 不得被整行剥掉
# ===========================================================================

def test_independence_in_table_is_recognized(proj):
    """用表格写 `independence: L0` 必须被识别（不得判「缺标记」）。

    修前实测：`strip_quoted_markers` 整行丢弃以 `|` 开头的行 →
        `| independence | L0 |` 被剥光 → `[FAIL] missing:independence`

    **账本里也必须不带标记**，否则账本那处会兜底，测不出表格路径
    （初版就是这样：用例「通过」了，但通过的原因是账本兜底，
     而不是表格被识别 —— 假通过）。
    """
    (proj / ".superpowers/sdd/p/progress.md").write_text(
        "# SDD ledger — plan: docs/p.md\n\nTask 1: complete (abc)\n",
        encoding="utf-8", newline="")
    (proj / "docs/p.md").write_text(
        PLAN.replace(REVIEW_HEAD,
                     "## Review\n| 项 | 值 |\n|---|---|\n| independence | L0 |\n"),
        encoding="utf-8", newline="")
    rep, _ = wc.run(change="demo", plan="docs/p.md", scale="medium", root=str(proj))
    item = _item(rep, "S6.INDEPENDENCE")
    assert item["status"] == wc.OK, (
        "表格里的 independence 未被识别：%s（%s）" % (item["status"], item["detail"]))


def test_independence_l2_in_table_still_fails(proj):
    """反例（关键）：表格里写 `L2` 仍必须 FAIL。

    L2 是唯一硬性交付禁止项，不能因为「表格写法」就放过。
    账本同样不带标记，确保测的是表格路径。
    """
    (proj / ".superpowers/sdd/p/progress.md").write_text(
        "# SDD ledger — plan: docs/p.md\n\nTask 1: complete (abc)\n",
        encoding="utf-8", newline="")
    (proj / "docs/p.md").write_text(
        PLAN.replace(REVIEW_HEAD,
                     "## Review\n| 项 | 值 |\n|---|---|\n| independence | L2 |\n"),
        encoding="utf-8", newline="")
    rep, _ = wc.run(change="demo", plan="docs/p.md", scale="medium", root=str(proj))
    item = _item(rep, "S6.INDEPENDENCE")
    assert item["status"] == wc.FAIL, (
        "表格里的 L2 被放过了：%s（%s）" % (item["status"], item["detail"]))


def test_quoted_marker_in_code_span_still_ignored(proj):
    """回归守卫：行内代码里的引用**仍须忽略**（A-6 修复不能破它）。

    这是 A-6 的原始目的：计划文档里写「修前：`independence: L2`」这类
    历史引用时，不能被当成真实标记——否则记录了修复过程的文档反而被判 L2。
    """
    (proj / "docs/p.md").write_text(
        PLAN.replace(REVIEW_HEAD,
                     "## Review\n修前实测：`independence: L2` 曾被误判。\n"
                     "independence: L0\n"),
        encoding="utf-8", newline="")
    rep, _ = wc.run(change="demo", plan="docs/p.md", scale="medium", root=str(proj))
    item = _item(rep, "S6.INDEPENDENCE")
    assert item["status"] == wc.OK, (
        "行内代码引用被当成了真实标记：%s（%s）" % (item["status"], item["detail"]))


def test_table_without_independence_key_not_matched(proj):
    """反例：表格里有 `L0` 但没有 `independence` 键 → 不算标记。

    防的破坏：为了识别表格而放宽成「表格里出现 L0 就算」——
    那会让任何提到「L0」的级别对照表都被当成结论。

    账本同样不带标记（否则账本兜底，测不出表格路径）。
    """
    (proj / ".superpowers/sdd/p/progress.md").write_text(
        "# SDD ledger — plan: docs/p.md\n\nTask 1: complete (abc)\n",
        encoding="utf-8", newline="")
    (proj / "docs/p.md").write_text(
        PLAN.replace(REVIEW_HEAD,
                     "## Review\n| 级别 | 含义 |\n|---|---|\n| L0 | 独立审查 |\n"),
        encoding="utf-8", newline="")
    rep, _ = wc.run(change="demo", plan="docs/p.md", scale="medium", root=str(proj))
    item = _item(rep, "S6.INDEPENDENCE")
    assert item["status"] == wc.FAIL, (
        "无 independence 键的对照表被当成了标记：%s" % item["status"])
