# -*- coding: utf-8 -*-
"""G5/G6 dispatch 证据门禁（ledger `## Dispatches` + 计划 `## Review` 身份）

抓的破坏：账本 `## Dispatches` 段与计划 `## Review` 的 implementer/reviewer
字段早就写在模板里，但 `workflow_check.py` 从未解析它们——于是
「主控在自己会话里实施、又自己审查」只要在账本写一句 `independence: L0`
就能拿完成态通过，证据链上没有任何一处机械拦截。

本文件锁定 7 项检查：
  S5.DISPATCH_IMPLEMENTER / S5.DISPATCH_ORPHAN_REPORT / S5.IMPLEMENTER_IS_EXPERT
  S6.REVIEWER_DISPATCH / S6.REVIEWER_DIFFERENT_EXPERT /
  S6.L0_REQUIRES_DISPATCH / S6.REVIEW_IDENTITIES

运行：
    python -m pytest tests/test_dispatch_evidence.py -q
"""

import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts import workflow_check as wc  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parent.parent

PLAN_REL = "docs/p.md"
WORKSPACE = ".superpowers/sdd/p"

IMPL_AGENT = "软件架构师"          # backend-architecture
REV_AGENT = "代码审查员"           # engineering-quality


def dispatch_line(task, role, agent, category, *, brief=None, report=None,
                  changeset="-", base="abc123", instance="1"):
    """按 templates/progress.md 的固定格式拼一条派发行。"""
    if brief is None:
        brief = "%s/task-%s-brief.md" % (WORKSPACE, task)
    if report is None:
        report = ("%s/review-1.md" % WORKSPACE if role == "reviewer"
                  else "%s/task-%s-report.md" % (WORKSPACE, task))
    return ('dispatch %s role=%s agent="%s" category=%s instance=%s '
            'base=%s brief=%s report=%s changeset=%s'
            % (task, role, agent, category, instance, base, brief, report,
               changeset))


IMPL_LINE = dispatch_line("1", "implementer", IMPL_AGENT, "backend-architecture")
REV_LINE = dispatch_line("1", "reviewer", REV_AGENT, "engineering-quality")


def plan_text(*, independence="L0", implementer=IMPL_AGENT, reviewer=REV_AGENT,
              rulings="Ruling: 采用 A 方案 — 理由 — 错了的代价"):
    lines = [
        "## Goal", "x",
        "## Architecture", "x",
        "## Tech Stack", "x",
        "## Spec", "x",
        "## Review Focus", "x",
        "## Global Constraints", "x",
        "## Dependencies", "x",
        "## File Scope", "x",
        "", "## Baseline", "- command: pytest -q", "- exit: 0",
        "", "## Review", "independence: %s" % independence,
    ]
    if implementer is not None:
        lines.append("implementer: %s" % implementer)
    if reviewer is not None:
        lines.append("reviewer: %s" % reviewer)
    lines += ["spec: ✅", "quality: APPROVED",
              "", "## Rulings", rulings,
              "", "## Integration Verification", "- command: pytest -q", "- exit: 0",
              "", "### Task 1: alpha", "", "do a", ""]
    return "\n".join(lines)


def ledger_text(dispatches, *, scale="中任务", completed=True):
    parts = ["# SDD ledger — plan: %s" % PLAN_REL, "",
             "## Scale", scale, "",
             "## Triage", "", "| 项 | 值 |", "|---|---|",
             "| 任务名 | 夹具 |",
             "| 领域（category） | backend-architecture |",
             "| 专家（name/basis） | 软件架构师（semantic） |", "",
             "## Dispatches", ""]
    parts += list(dispatches)
    parts.append("")
    if completed:
        parts.append("Task 1: complete (abc123)")
    return "\n".join(parts) + "\n"


def _write(root, rel, content):
    target = (root / rel).resolve()
    root_resolved = root.resolve()
    if root_resolved not in target.parents and target != root_resolved:
        raise ValueError("路径逃出临时根：%s" % rel)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target


def build(root, **kw):
    """证据齐备的最小项目；按参数逐项注入缺陷。"""
    dispatches = kw.pop("dispatches", [IMPL_LINE, REV_LINE])
    plan = kw.pop("plan", None)
    ledger = kw.pop("ledger", None)
    tasks = kw.pop("tasks", "- [x] 1.1 alpha\n")
    report_tasks = kw.pop("report_tasks", ("1",))
    scale = kw.pop("scale", "中任务")
    completed = kw.pop("completed", True)

    _write(root, "openspec/changes/demo/proposal.md", "## Why\nx\n")
    _write(root, "openspec/changes/demo/design.md", "## Design\nx\n")
    _write(root, "openspec/changes/demo/tasks.md", tasks)
    _write(root, "openspec/changes/demo/.openspec.yaml", "name: demo\n")
    _write(root, "openspec/changes/demo/specs/auth/spec.md", "## Requirement\nx\n")
    _write(root, "openspec/specs/auth/spec.md", "## Purpose\nx\n")
    _write(root, PLAN_REL, plan if plan is not None else plan_text())
    _write(root, WORKSPACE + "/progress.md",
           ledger if ledger is not None
           else ledger_text(dispatches, scale=scale, completed=completed))
    for tid in ("1",):
        _write(root, "%s/task-%s-brief.md" % (WORKSPACE, tid), "brief\n")
    for tid in report_tasks:
        _write(root, "%s/task-%s-report.md" % (WORKSPACE, tid), "report\n")
    _write(root, "%s/review-1.md" % WORKSPACE,
           "## Review\nspec: ✅\nquality: APPROVED\nindependence: L0\n")
    return root


@pytest.fixture
def proj():
    d = Path(tempfile.mkdtemp(prefix="wfc_dispatch_")).resolve()
    yield d
    shutil.rmtree(str(d), ignore_errors=True)


def run_medium(root, **kw):
    return wc.run(change="demo", plan=PLAN_REL, scale=kw.pop("scale", "medium"),
                  root=str(root))


def item(rep, id_):
    for i in rep.items:
        if i.get("id") == id_:
            return i
    raise AssertionError("找不到 id=%r；实际 ids=%s"
                         % (id_, sorted(x.get("id") or "" for x in rep.items)))


# ---------------------------------------------------------------------------
# 解析器：模板注释与围栏示例不是证据
# ---------------------------------------------------------------------------

def test_parser_ignores_template_html_comment_examples():
    """`templates/progress.md` 里的示例派发行在注释/围栏内，不得被当成证据。

    防的破坏：照抄模板的空账本直接满足「已派发」——那是假绿。
    """
    tpl = (PROJECT_ROOT / "templates" / "progress.md").read_text(encoding="utf-8")
    assert wc._parse_dispatches(tpl) == []


def test_parser_ignores_fenced_and_commented_lines():
    """围栏块与 HTML 注释里的派发行一律不算证据；注释外的真实行照常解析。"""
    text = ("# SDD ledger — plan: x\n\n## Dispatches\n\n"
            "<!-- %s -->\n"
            "```text\n%s\n```\n" % (IMPL_LINE, REV_LINE))
    assert wc._parse_dispatches(text) == []

    text2 = ("## Dispatches\n\n%s\n<!-- %s -->\n" % (IMPL_LINE, REV_LINE))
    rows = wc._parse_dispatches(text2)
    assert len(rows) == 1, rows
    assert rows[0]["task"] == "1" and rows[0]["role"] == "implementer"
    assert rows[0]["agent"] == IMPL_AGENT
    assert rows[0]["category"] == "backend-architecture"
    assert rows[0]["malformed"] is False


# ---------------------------------------------------------------------------
# S5：实施者派发
# ---------------------------------------------------------------------------

def test_completed_task_without_implementer_dispatch_fails(proj):
    """完成任务只有 reviewer 派发行 → S5.DISPATCH_IMPLEMENTER FAIL。

    这是「主控自己实施」的机械证据缺口：没人派过实施者，却有完成行。
    """
    build(proj, dispatches=[REV_LINE])
    rep, _ = run_medium(proj)
    it = item(rep, "S5.DISPATCH_IMPLEMENTER")
    assert it["status"] == wc.FAIL, (it["status"], it["detail"])
    assert (it["reason"] or "").startswith("missing:"), it["reason"]


def test_orphan_report_without_dispatch_fails(proj):
    """有 `task-2-report.md` 但无该任务的 implementer 派发行 → 孤儿 report FAIL。"""
    build(proj, dispatches=[IMPL_LINE], report_tasks=("1", "2"))
    rep, _ = run_medium(proj)
    it = item(rep, "S5.DISPATCH_ORPHAN_REPORT")
    assert it["status"] == wc.FAIL, (it["status"], it["detail"])
    assert "task-2-report.md" in it["detail"]


def test_dispatch_report_pointing_to_other_task_fails(proj):
    """派发行 report 指向别的 task → FAIL（同一份 report 不会被两个任务共用）。"""
    bad = dispatch_line("1", "implementer", IMPL_AGENT, "backend-architecture",
                        report="%s/task-2-report.md" % WORKSPACE)
    build(proj, dispatches=[bad, REV_LINE])
    rep, _ = run_medium(proj)
    it = item(rep, "S5.DISPATCH_ORPHAN_REPORT")
    assert it["status"] == wc.FAIL, (it["status"], it["detail"])
    assert "task-2-report.md" in it["detail"]


def test_agent_not_in_registry_fails(proj):
    """agent 不在 config/experts.json → S5.IMPLEMENTER_IS_EXPERT FAIL。"""
    bad = dispatch_line("1", "implementer", "幽灵专家", "backend-architecture")
    build(proj, dispatches=[bad, REV_LINE])
    rep, _ = run_medium(proj)
    it = item(rep, "S5.IMPLEMENTER_IS_EXPERT")
    assert it["status"] == wc.FAIL, (it["status"], it["detail"])
    assert "幽灵专家" in it["detail"]


def test_agent_category_mismatch_fails(proj):
    """category 与注册表不一致 → S5.IMPLEMENTER_IS_EXPERT FAIL。"""
    bad = dispatch_line("1", "implementer", IMPL_AGENT, "frontend-client")
    build(proj, dispatches=[bad, REV_LINE])
    rep, _ = run_medium(proj)
    it = item(rep, "S5.IMPLEMENTER_IS_EXPERT")
    assert it["status"] == wc.FAIL, (it["status"], it["detail"])
    assert "frontend-client" in it["detail"]


def test_general_purpose_implementer_fails_at_medium(proj):
    """`general-purpose` 不是注册表专家：medium 判 FAIL，light 才给 soft WARN。"""
    gen = dispatch_line("1", "implementer", "general-purpose",
                        "backend-architecture")
    build(proj, dispatches=[gen, REV_LINE])
    rep, _ = run_medium(proj)
    assert item(rep, "S5.IMPLEMENTER_IS_EXPERT")["status"] == wc.FAIL


# ---------------------------------------------------------------------------
# S6：审查者派发与独立性
# ---------------------------------------------------------------------------

def test_l0_without_reviewer_dispatch_fails(proj):
    """`independence: L0` 但没有任何 reviewer 派发行 → L0 声明不成立，FAIL。"""
    build(proj, dispatches=[IMPL_LINE])
    rep, _ = run_medium(proj)
    it = item(rep, "S6.L0_REQUIRES_DISPATCH")
    assert it["status"] == wc.FAIL, (it["status"], it["detail"])
    assert item(rep, "S6.REVIEWER_DISPATCH")["status"] == wc.FAIL


def test_l0_with_orchestrator_as_reviewer_fails(proj):
    """L0 而 reviewer 是主控自称 → 「自己审查标 L0」必须 FAIL。"""
    self_rev = dispatch_line("1", "reviewer", "主控", "backend-architecture")
    build(proj, dispatches=[IMPL_LINE, self_rev])
    rep, _ = run_medium(proj)
    it = item(rep, "S6.L0_REQUIRES_DISPATCH")
    assert it["status"] == wc.FAIL, (it["status"], it["detail"])
    assert (it["reason"] or "").startswith("forbidden:"), it["reason"]


def test_reviewer_same_as_implementer_fails(proj):
    """reviewer 与 implementer 同名 → 不是异域审查，FAIL。"""
    same = dispatch_line("1", "reviewer", IMPL_AGENT, "backend-architecture")
    build(proj, dispatches=[IMPL_LINE, same])
    rep, _ = run_medium(proj)
    it = item(rep, "S6.REVIEWER_DIFFERENT_EXPERT")
    assert it["status"] == wc.FAIL, (it["status"], it["detail"])
    assert (it["reason"] or "").startswith("forbidden:"), it["reason"]


def test_reviewer_same_domain_different_expert_warns(proj):
    """同域不同人（同为 backend-architecture）→ 允许但 WARN soft:same_domain_review。"""
    same_domain = dispatch_line("1", "reviewer", "后端架构师",
                                "backend-architecture")
    build(proj, dispatches=[IMPL_LINE, same_domain])
    rep, _ = run_medium(proj)
    it = item(rep, "S6.REVIEWER_DIFFERENT_EXPERT")
    assert it["status"] == wc.WARN, (it["status"], it["detail"])
    assert (it["reason"] or "").startswith("soft:"), it["reason"]


def test_registered_expert_same_name_changed_category_fails(proj):
    """注册表专家当 reviewer 且与 implementer 同名：改 category 不能洗白（C1）。

    反证（修前）：implementer=软件架构师/backend-architecture，
    reviewer=软件架构师/engineering-quality → WARN + rc=0。
    注册表专家名→域是 1:1，自述 category 改了也不改事实：同名＝同一席专家。
    """
    rev = dispatch_line("1", "reviewer", IMPL_AGENT, "engineering-quality")
    build(proj, dispatches=[IMPL_LINE, rev],
          plan=plan_text(reviewer=IMPL_AGENT))
    rep, _ = run_medium(proj)
    it = item(rep, "S6.REVIEWER_DIFFERENT_EXPERT")
    assert it["status"] == wc.FAIL, (it["status"], it["detail"])
    assert it["reason"] == "forbidden:reviewer_same_as_implementer", it["reason"]


def test_general_purpose_same_agent_changed_category_fails(proj):
    """非注册表 agent 同名改 category：无法证明不同，必须 FAIL。"""
    impl = dispatch_line("1", "implementer", "general-purpose",
                         "backend-architecture")
    rev = dispatch_line("1", "reviewer", "general-purpose", "frontend-client")
    build(proj, dispatches=[impl, rev])
    rep, _ = run_medium(proj)
    it = item(rep, "S6.REVIEWER_DIFFERENT_EXPERT")
    assert it["status"] == wc.FAIL, (it["status"], it["detail"])
    assert it["reason"] in ("forbidden:reviewer_same_as_implementer",
                            "missing:reviewer_expert"), it["reason"]


def test_general_purpose_reviewer_medium_fails(proj):
    """medium 下 reviewer=general-purpose 不得豁免。"""
    rev = dispatch_line("1", "reviewer", "general-purpose", "engineering-quality")
    build(proj, dispatches=[IMPL_LINE, rev])
    rep, _ = run_medium(proj)
    it = item(rep, "S6.REVIEWER_DIFFERENT_EXPERT")
    assert it["status"] == wc.FAIL, (it["status"], it["detail"])
    assert it["reason"] == "missing:reviewer_expert", it["reason"]


def test_general_purpose_reviewer_light_warns(proj):
    """light 下 reviewer=general-purpose 才允许降级为 WARN。"""
    rev = dispatch_line("1", "reviewer", "general-purpose", "engineering-quality")
    build(proj, dispatches=[IMPL_LINE, rev])
    rep, _ = run_medium(proj, scale="light")
    it = item(rep, "S6.REVIEWER_DIFFERENT_EXPERT")
    assert it["status"] == wc.WARN, (it["status"], it["detail"])
    assert it["reason"] == "soft:reviewer_general_purpose", it["reason"]


def test_l0_general_purpose_reviewer_fails(proj):
    """L0 的 reviewer 不能是 general-purpose。"""
    rev = dispatch_line("1", "reviewer", "general-purpose", "engineering-quality")
    build(proj, dispatches=[IMPL_LINE, rev])
    rep, _ = run_medium(proj)
    it = item(rep, "S6.L0_REQUIRES_DISPATCH")
    assert it["status"] == wc.FAIL, (it["status"], it["detail"])
    assert it["reason"] == "missing:reviewer_expert", it["reason"]


def test_reviewer_category_mismatch_fails(proj):
    """reviewer 行的 category 必须与注册表一致（I4）。"""
    rev = dispatch_line("1", "reviewer", REV_AGENT, "frontend-client")
    build(proj, dispatches=[IMPL_LINE, rev])
    rep, _ = run_medium(proj)
    it = item(rep, "S6.REVIEWER_DIFFERENT_EXPERT")
    assert it["status"] == wc.FAIL, (it["status"], it["detail"])
    assert it["reason"] == "malformed:reviewer_category_mismatch", it["reason"]
    assert "frontend-client" in it["detail"]


def test_unregistered_reviewer_fails(proj):
    """reviewer 行的 agent 必须是注册表内真实专家（I4）。"""
    rev = dispatch_line("1", "reviewer", "幽灵审查员", "engineering-quality")
    build(proj, dispatches=[IMPL_LINE, rev])
    rep, _ = run_medium(proj)
    it = item(rep, "S6.REVIEWER_DIFFERENT_EXPERT")
    assert it["status"] == wc.FAIL, (it["status"], it["detail"])
    assert it["reason"] == "missing:reviewer_expert", it["reason"]
    assert "幽灵审查员" in it["detail"]


def test_l1_without_ruling_line_fails(proj):
    """`independence: L1`（主控自审降级）必须有一条 `Ruling:` 留痕，缺则 FAIL。"""
    build(proj, dispatches=[IMPL_LINE],
          plan=plan_text(independence="L1", rulings="x"))
    rep, _ = run_medium(proj)
    it = item(rep, "S6.RULINGS")
    assert it["status"] == wc.FAIL, (it["status"], it["detail"])


def test_l1_self_review_without_reviewer_dispatch_skips(proj):
    """`independence: L1`（主控自审 + Ruling）不要求 reviewer 派发行（I1）。

    L1 声明的是「主控自审」，本来就没有独立子代理可派；
    逼它伪造一条 reviewer 行才是错的门禁。
    """
    build(proj, dispatches=[IMPL_LINE], plan=plan_text(independence="L1"))
    rep, _ = run_medium(proj)
    it = item(rep, "S6.REVIEWER_DISPATCH")
    assert it["status"] == wc.SKIP, (it["status"], it["detail"])
    assert it["reason"] == "inapplicable:not_l0", it["reason"]
    # 身份对照也不得变相强制它：账本零 reviewer 行时不做 reviewer 侧比对（I2 不反转 I1）
    assert item(rep, "S6.REVIEW_IDENTITIES")["status"] == wc.OK


def test_review_identities_missing_fails_at_medium(proj):
    """medium 下计划 `## Review` 缺 implementer/reviewer 身份行 → FAIL。"""
    build(proj, plan=plan_text(implementer=None, reviewer=None))
    rep, _ = run_medium(proj)
    it = item(rep, "S6.REVIEW_IDENTITIES")
    assert it["status"] == wc.FAIL, (it["status"], it["detail"])


def test_review_identities_warn_at_light(proj):
    """light 下身份行缺失降为 WARN soft（不阻断轻量任务）。"""
    build(proj, plan=plan_text(implementer=None, reviewer=None), scale="轻量")
    rep, _ = run_medium(proj, scale="light")
    it = item(rep, "S6.REVIEW_IDENTITIES")
    assert it["status"] == wc.WARN, (it["status"], it["detail"])
    assert (it["reason"] or "").startswith("soft:"), it["reason"]


def test_plan_identity_contradicting_ledger_fails(proj):
    """计划 `## Review` 身份必须与账本派发行对得上（I2）。

    计划写 implementer=代码审查员 / reviewer=软件架构师，账本写反 → FAIL。
    只查「计划有没有写」等于不查：写反了照样绿。
    """
    build(proj, plan=plan_text(implementer=REV_AGENT, reviewer=IMPL_AGENT))
    rep, _ = run_medium(proj)
    it = item(rep, "S6.REVIEW_IDENTITIES")
    assert it["status"] == wc.FAIL, (it["status"], it["detail"])
    assert it["reason"] == "malformed:identity_mismatch", it["reason"]
    assert REV_AGENT in it["detail"] and IMPL_AGENT in it["detail"], it["detail"]


# ---------------------------------------------------------------------------
# 适用范围：无完成任务 / readonly / light
# ---------------------------------------------------------------------------

def test_workspace_with_deleted_ledger_fails(proj):
    """只删账本、保留 workspace → 派发门禁 FAIL（I3）。

    修前：`rm .superpowers/sdd/p/progress.md` 后 7 项派发检查全 SKIP 即绿。
    """
    build(proj)
    (proj / WORKSPACE / "progress.md").unlink()
    rep, _ = run_medium(proj)
    for cid in ("S5.DISPATCH_IMPLEMENTER", "S6.REVIEWER_DISPATCH"):
        it = item(rep, cid)
        assert it["status"] == wc.FAIL, (cid, it["status"], it["detail"])
        assert it["reason"] == "missing:ledger", (cid, it["reason"])


def test_review_identities_checked_when_ledger_missing(proj):
    """账本缺席不得吞掉计划侧身份检查（M1）：身份行只依赖计划文档。"""
    build(proj)
    shutil.rmtree(str(proj / ".superpowers"))
    rep, _ = run_medium(proj)
    assert item(rep, "S6.REVIEWER_DISPATCH")["status"] == wc.SKIP
    it = item(rep, "S6.REVIEW_IDENTITIES")
    assert it["status"] == wc.OK, (it["status"], it["detail"])


def test_dispatch_keyword_and_role_case_insensitive(proj):
    """`Dispatch` / `ROLE=` / `Implementer` 大小写笔误不得变成「没派发」（M3）。"""
    impl = dispatch_line("1", "implementer", IMPL_AGENT,
                         "backend-architecture").replace(
                             "dispatch 1 role=implementer",
                             "Dispatch 1 ROLE=Implementer")
    rev = dispatch_line("1", "reviewer", REV_AGENT,
                        "engineering-quality").replace(
                            "dispatch 1 role=reviewer", "Dispatch 1 Role=Reviewer")
    build(proj, dispatches=[impl, rev])
    rep, _ = run_medium(proj)
    assert item(rep, "S5.DISPATCH_IMPLEMENTER")["status"] == wc.OK
    assert item(rep, "S6.REVIEWER_DISPATCH")["status"] == wc.OK


def test_experts_registry_unreadable_is_malformed(proj, monkeypatch):
    """注册表读不出 → malformed:experts_unreadable，不误报「不是注册表专家」（M4）。"""
    build(proj)
    monkeypatch.setattr(wc, "BASE_DIR", str(proj / "no-such-base"))
    monkeypatch.setattr(wc, "_EXPERTS_CACHE", {})
    rep, _ = run_medium(proj)
    it = item(rep, "S5.IMPLEMENTER_IS_EXPERT")
    assert it["status"] == wc.FAIL, (it["status"], it["detail"])
    assert it["reason"] == "malformed:experts_unreadable", it["reason"]
    assert item(rep, "S6.REVIEWER_DIFFERENT_EXPERT")["reason"] == \
        "malformed:experts_unreadable"

def test_no_completed_task_skips_dispatch_checks(proj):
    """完成集为空（没有任何 Task N: complete）→ 派发门禁 SKIP，不得误红。"""
    build(proj, dispatches=[], completed=False, tasks="- [ ] 1.1 alpha\n")
    rep, _ = run_medium(proj)
    for cid in ("S5.DISPATCH_IMPLEMENTER", "S5.DISPATCH_ORPHAN_REPORT",
                "S5.IMPLEMENTER_IS_EXPERT"):
        it = item(rep, cid)
        assert it["status"] == wc.SKIP, (cid, it["status"], it["detail"])
        assert (it["reason"] or "").startswith("inapplicable:"), it["reason"]


def test_no_ledger_skips_dispatch_checks(proj):
    """无账本（交付后清理）→ 派发门禁 SKIP inapplicable，不得误红。"""
    build(proj)
    shutil.rmtree(str(proj / ".superpowers"))
    (proj / "openspec/changes/demo/tasks.md").write_text(
        "- [x] 1.1 alpha\n", encoding="utf-8")
    rep, _ = run_medium(proj)
    for cid in ("S5.DISPATCH_IMPLEMENTER", "S6.REVIEWER_DISPATCH"):
        it = item(rep, cid)
        assert it["status"] == wc.SKIP, (cid, it["status"], it["detail"])
        assert (it["reason"] or "").startswith("inapplicable:"), it["reason"]


def test_readonly_trims_dispatch_checks(proj):
    """readonly → S5/S6 整体裁剪，派发门禁不得产出 FAIL。"""
    build(proj, scale="只读")
    rep, _ = wc.run(change=None, plan=None, scale="readonly", root=str(proj))
    ids = [i.get("id") or "" for i in rep.items]
    dispatch_ids = [i for i in ids
                    if i.startswith(("S5.DISPATCH", "S5.IMPLEMENTER_IS_EXPERT",
                                     "S6.REVIEWER", "S6.L0_", "S6.REVIEW_IDENTITIES"))]
    assert not dispatch_ids, "readonly 下派发门禁仍产出检查项：%s" % dispatch_ids
    assert "S5.TRIM" in ids and "S6.TRIM" in ids


def test_light_still_fails_when_implementer_dispatch_missing(proj):
    """light 下 implementer 派发行缺失仍 FAIL（轻量不减完成态证据）。"""
    build(proj, dispatches=[REV_LINE], scale="轻量")
    rep, _ = run_medium(proj, scale="light")
    it = item(rep, "S5.DISPATCH_IMPLEMENTER")
    assert it["status"] == wc.FAIL, (it["status"], it["detail"])


def test_light_general_purpose_implementer_is_soft_warn(proj):
    """light 下 `general-purpose` 实施者降为 soft WARN（矩阵允许的唯一降级）。"""
    gen = dispatch_line("1", "implementer", "general-purpose",
                        "backend-architecture")
    build(proj, dispatches=[gen, REV_LINE], scale="轻量")
    rep, _ = run_medium(proj, scale="light")
    it = item(rep, "S5.IMPLEMENTER_IS_EXPERT")
    assert it["status"] == wc.WARN, (it["status"], it["detail"])
    assert (it["reason"] or "").startswith("soft:"), it["reason"]


def test_happy_path_has_no_dispatch_fail(proj):
    """证据齐备（合法派发行 + 身份行）时 7 项检查不得有任何 FAIL。"""
    build(proj)
    rep, _ = run_medium(proj)
    ids = ("S5.DISPATCH_IMPLEMENTER", "S5.DISPATCH_ORPHAN_REPORT",
           "S5.IMPLEMENTER_IS_EXPERT", "S6.REVIEWER_DISPATCH",
           "S6.REVIEWER_DIFFERENT_EXPERT", "S6.L0_REQUIRES_DISPATCH",
           "S6.REVIEW_IDENTITIES")
    bad = [(i.get("id"), i["status"], i.get("detail"))
           for i in rep.items if i.get("id") in ids and i["status"] == wc.FAIL]
    assert not bad, bad


def _template_shaped_plan(*, independence="L0", rulings=None):
    """按 templates/plan-sections.md 的「外层 ## Review + 围栏内同名片」写法。"""
    base = plan_text(independence=independence,
                     rulings=rulings if rulings is not None else
                     "Ruling: 采用 A 方案 — 理由 — 错了的代价")
    start = base.index("## Review")
    end = base.index("## Rulings")
    inner = base[start:end].replace("## Review", "", 1).strip()
    fenced = "## Review\n```markdown\n## Review\n%s\n```\n\n" % inner
    return base[:start] + fenced + base[end:]


def test_template_shaped_review_identities_ok(proj):
    """模板形态（外层 Review + 围栏内同名标题）不得被截断成缺身份。"""
    build(proj, plan=_template_shaped_plan())
    rep, _ = run_medium(proj)
    it = item(rep, "S6.REVIEW_IDENTITIES")
    assert it["status"] == wc.OK, (it["status"], it["detail"])


def test_template_shaped_l1_ruling_ok(proj):
    """模板形态的 L1 + 围栏内 Ruling 不得假红。"""
    base = plan_text(independence="L1", rulings="")
    base = base.replace("## Rulings\n\n", "## Rulings\n\n```markdown\n"
                        "Ruling: 采用 A 方案 — 理由 — 错了的代价\n```\n\n")
    build(proj, dispatches=[IMPL_LINE], plan=base)
    rep, _ = run_medium(proj)
    it = item(rep, "S6.RULINGS")
    assert it["status"] == wc.OK, (it["status"], it["detail"])


def test_section_body_ignores_fenced_inner_headings():
    """section_body(keep_fences=True) 找段尾时不得被围栏内标题截断。"""
    text = ("## Review\n```markdown\n## Review\nimplementer: 软件架构师\n"
            "reviewer: 代码审查员\n```\n\n## Rulings\nRuling: x\n")
    body = wc.section_body(text, "Review", keep_fences=True)
    assert body is not None
    assert "implementer: 软件架构师" in body
    assert "## Rulings" not in body
