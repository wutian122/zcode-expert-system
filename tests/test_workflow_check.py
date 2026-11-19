# -*- coding: utf-8 -*-
"""工作流门禁核对层回归测试

对应 2026-11-16 审计发现 #4：
  `workflow_check.py` 对 `required: true` 的 glob 产物（specs/<capability>/spec.md）
  缺失只报 WARN，导致「delta spec 整份不存在」的空壳变更也能拿 rc=0
  「无 FAIL 项」通过 G2 规格门禁。

本文件此前完全缺失——门禁层零测试，该缺陷永远不会被发现。

运行：
    python -m pytest tests/test_workflow_check.py -v
"""

import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts import workflow_check as wc  # noqa: E402


PLAN_OK = """# Plan

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


def _safe_write(root: Path, rel: str, content: str) -> Path:
    """在临时根内安全写文件：解析后必须仍在 root 之下。"""
    target = (root / rel).resolve()
    root_resolved = root.resolve()
    if root_resolved not in target.parents and target != root_resolved:
        raise ValueError("路径逃出临时根：%s" % rel)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target


def build_project(root: Path, with_delta_spec=True, done=True):
    """构造最小可核对项目树（全部写入限制在 root 内）。"""
    _safe_write(root, "openspec/changes/demo/proposal.md", "## Why\nx\n")
    _safe_write(root, "openspec/changes/demo/design.md", "## Design\nx\n")
    _safe_write(root, "openspec/changes/demo/tasks.md",
                "- [x] 1.1 alpha\n" if done else "- [ ] 1.1 alpha\n")
    _safe_write(root, "openspec/changes/demo/.openspec.yaml", "name: demo\n")

    if with_delta_spec:
        _safe_write(root, "openspec/changes/demo/specs/auth/spec.md", "## Requirement\nx\n")

    _safe_write(root, "openspec/specs/auth/spec.md", "## Purpose\nx\n")
    _safe_write(root, PLAN_REL, PLAN_OK)

    _safe_write(root, ".superpowers/sdd/p/progress.md",
                "# SDD ledger — plan: docs/superpowers/plans/p.md\n\n"
                # S0.DOMAIN 夹具补行（enforce-domain-routing 同批）：
                # 本夹具用于非只读（medium）场景，S0.DOMAIN 判定表要求
                # Triage 段含域路由两行，缺行即 FAIL（s0_domain_missing）
                "## Triage\n\n| 项 | 值 |\n|---|---|\n"
                "| 任务名 | 夹具 |\n"
                "| 领域（category） | backend-architecture |\n"
                "| 专家（name/basis） | 软件架构师（semantic） |\n\n"
                "Task 1: complete (abc123)\n")
    _safe_write(root, ".superpowers/sdd/p/task-1-brief.md", "brief\n")
    _safe_write(root, ".superpowers/sdd/p/task-1-report.md", "report\n")
    # review-<N>.md 是 S6 声明 required:true 的产物（A-14 裁决后 S6.REVIEW_REPORT
    # 会真核对它）——「完整项目」夹具必须含它，否则按规范做对的项目会被误判。
    _safe_write(root, ".superpowers/sdd/p/review-1.md",
                "## Review\nspec: ✅\nquality: APPROVED\nindependence: L0\n")


@pytest.fixture
def proj():
    d = Path(tempfile.mkdtemp(prefix="wfc_")).resolve()
    yield d
    shutil.rmtree(str(d), ignore_errors=True)


def run_check(root: Path):
    return wc.run(change="demo", plan=PLAN_REL, scale="medium", root=str(root))


# ---------------------------------------------------------------------------
# #4 核心：required 的 glob 产物缺失必须 FAIL
# ---------------------------------------------------------------------------

def test_missing_delta_spec_is_fail(proj):
    """required 的 glob 产物（delta spec）缺失必须报 FAIL，不能只 WARN。

    修复前：空壳变更（proposal/design/tasks/.openspec.yaml 全在、specs 为空）
    拿到 rc=0「无 FAIL 项」，G2 规格门禁形同虚设。
    """
    build_project(proj, with_delta_spec=False)
    rep, _ctx = run_check(proj)
    fails = [i for i in rep.items if i["status"] == wc.FAIL]
    assert fails, "delta spec 缺失却无 FAIL 项"
    assert any("spec.md" in i["check"] for i in fails), (
        "FAIL 项未指向 delta spec：%s" % [i["check"] for i in fails]
    )
    assert rep.has_fail() is True


def test_missing_delta_spec_exit_code_nonzero(proj):
    """有 FAIL 时 main 必须返回非零退出码。"""
    build_project(proj, with_delta_spec=False)
    rc = wc.main(["--root", str(proj), "--change", "demo",
                  "--plan", PLAN_REL, "--scale", "medium"])
    assert rc == 1, "delta spec 缺失时退出码应为 1，实际 %d" % rc


def test_complete_project_has_no_fail(proj):
    """证据齐备时不得有 FAIL（防止假阳性）。"""
    build_project(proj, with_delta_spec=True)
    rep, _ctx = run_check(proj)
    fails = [i for i in rep.items if i["status"] == wc.FAIL]
    assert not fails, "完整项目出现 FAIL：%s" % [(i["check"], i["detail"]) for i in fails]


# ---------------------------------------------------------------------------
# 三元对齐
# ---------------------------------------------------------------------------

def test_checkbox_ledger_mismatch_is_fail(proj):
    """tasks.md 勾选数与 ledger complete 数不符必须 FAIL。"""
    build_project(proj)
    _safe_write(proj, "openspec/changes/demo/tasks.md", "- [ ] 1.1 alpha\n")
    rep, _ctx = run_check(proj)
    fails = [i for i in rep.items if i["status"] == wc.FAIL]
    assert any("三元对齐" in i["check"] for i in fails), (
        "三元不一致未报 FAIL：%s" % [i["check"] for i in fails]
    )


# ---------------------------------------------------------------------------
# 基线双写 / 集成后重测 / 独立性
# ---------------------------------------------------------------------------

def test_missing_baseline_in_plan_is_fail(proj):
    build_project(proj)
    p = (proj / PLAN_REL).resolve()
    p.write_text(p.read_text(encoding="utf-8").replace("## Baseline", "## NoBaseline"),
                 encoding="utf-8")
    rep, _ctx = run_check(proj)
    assert any(i["status"] == wc.FAIL and "基线" in i["check"] for i in rep.items)


def test_missing_integration_verification_is_fail(proj):
    build_project(proj)
    p = (proj / PLAN_REL).resolve()
    p.write_text(
        p.read_text(encoding="utf-8").replace(
            "## Integration Verification", "## NoIV"),
        encoding="utf-8")
    rep, _ctx = run_check(proj)
    assert any(i["status"] == wc.FAIL and "集成后重测" in i["check"] for i in rep.items)


def test_l2_independence_is_fail(proj):
    """L2（无审查）必须 FAIL。"""
    build_project(proj)
    p = (proj / PLAN_REL).resolve()
    p.write_text(p.read_text(encoding="utf-8").replace(
        "independence: L0", "independence: L2"), encoding="utf-8")
    rep, _ctx = run_check(proj)
    assert any(i["status"] == wc.FAIL and "独立性" in i["check"] for i in rep.items)


def test_parked_blocks_archive(proj):
    """存在 PARKED 必须 FAIL（W8：默认禁归档）。"""
    build_project(proj)
    ws = (proj / ".superpowers/sdd/p/progress.md").resolve()
    ws.write_text(ws.read_text(encoding="utf-8") + "Task 2: parked (reason)\n",
                  encoding="utf-8")
    rep, _ctx = run_check(proj)
    assert any(i["status"] == wc.FAIL and "PARKED" in i["check"] for i in rep.items)


# ---------------------------------------------------------------------------
# 边界
# ---------------------------------------------------------------------------

def test_missing_scale_is_fail(proj):
    """未提供 --scale 且无法推断时应 FAIL，不是静默通过。"""
    build_project(proj)
    rep, _ctx = wc.run(change="demo", plan=PLAN_REL, scale=None, root=str(proj))
    assert any(i["status"] == wc.FAIL and "规模" in i["check"] for i in rep.items)


def test_warns_do_not_block(proj):
    """WARN 不得单独把 has_fail 变真（区分严重度）。"""
    build_project(proj)
    rep, _ctx = run_check(proj)
    if rep.count(wc.WARN) > 0:
        assert rep.has_fail() or rep.count(wc.FAIL) == 0
