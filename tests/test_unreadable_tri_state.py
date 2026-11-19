# -*- coding: utf-8 -*-
"""P8 批次二 Task 6：不可读证据的三态文案修正（S4/S7 计划、S5/S6 账本）。

抓的破坏：`read(ctx["plan"]) if ctx["plan"] else None` 把「提供了但读不出」
混同成「没提供」——报错文案教用户去补传 --plan，而真正的问题是文件编码/权限
（对照 check_S3 已有的 malformed:plan_unreadable 分流先例）。S5/S6 在账本
不可读时证据面静默蒸发（S5 三元对齐整体不出项、S6 独立性核验被归为
「不该查」的 SKIP）——「查不了」被印成「查过且干净」的同族形态。

方向双向：不可读 → FAIL malformed:*；未提供 → 仍 unverifiable:plan_required；
真没证据 → 仍 SKIP inapplicable:no_evidence。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts import workflow_check as wc  # noqa: E402
# 跨文件复用夹具：tests/ 无 __init__.py，Python 3 隐式命名空间包 + 模块顶部
# sys.path 注入使其可行（先例 test_p8_precision.py:46-48）。proj 是夹具函数，
# 重暴露到本模块命名空间后 pytest 按本模块收集。
from tests.test_p8_precision import item  # noqa: E402
from tests.test_p8_precision import proj as _proj  # noqa: E402

proj = _proj


def test_unreadable_plan_s4_is_malformed_not_plan_required(proj):
    """计划提供了但读不出 → malformed:plan_unreadable，不得混同「未提供」。"""
    (proj / "docs" / "p.md").write_bytes(b"\xff\xfe invalid")
    rep, _ = wc.run(change="demo", plan="docs/p.md", scale="medium", root=str(proj))
    it = item(rep, "S4.BASELINE")
    assert it["status"] == wc.FAIL and it["reason"] == "malformed:plan_unreadable", (
        "计划不可读应判 malformed:plan_unreadable（修前被混同成"
        " unverifiable:plan_required，文案误导用户补传 --plan）：%s / %s"
        % (it["status"], it["reason"]))


def test_unreadable_plan_s7_is_malformed(proj):
    """S7 同构：不可读 → malformed，不混同。"""
    (proj / "docs" / "p.md").write_bytes(b"\xff\xfe invalid")
    rep, _ = wc.run(change="demo", plan="docs/p.md", scale="medium", root=str(proj))
    it = item(rep, "S7.INTEGRATION")
    assert it["status"] == wc.FAIL and it["reason"] == "malformed:plan_unreadable", (
        "S7 计划不可读被混同：%s / %s" % (it["status"], it["reason"]))


def test_missing_plan_still_unverifiable(proj):
    """双向反例：真没提供计划 → 仍是 unverifiable:plan_required（语义不丢）。"""
    rep, _ = wc.run(change="demo", plan=None, scale="medium", root=str(proj))
    assert item(rep, "S4.BASELINE")["reason"] == "unverifiable:plan_required"
    assert item(rep, "S7.INTEGRATION")["reason"] == "unverifiable:plan_required"


def test_unreadable_ledger_s5_emits_fail_not_silent(proj):
    """账本存在但读不出 → S5 三元对齐必须出 FAIL 项，不得静默蒸发。"""
    (proj / ".superpowers/sdd/p/progress.md").write_bytes(b"\xff\xfe invalid")
    rep, _ = wc.run(change="demo", plan="docs/p.md", scale="medium", root=str(proj))
    triads = [i for i in rep.items if i.get("id") == "S5.TRIAD"]
    assert any(i["status"] == wc.FAIL
               and i["reason"] == "malformed:ledger_unreadable" for i in triads), (
        "账本不可读时 S5 三元对齐静默蒸发（修前该区间零检查项）：%s" % triads)


def test_unreadable_evidence_s6_not_inapplicable(proj):
    """账本存在但读不出 → S6 独立性核验必须 FAIL，不得归为「不该查」。"""
    (proj / ".superpowers/sdd/p/progress.md").write_bytes(b"\xff\xfe invalid")
    rep, _ = wc.run(change="demo", plan=None, scale="medium", root=str(proj))
    it = item(rep, "S6.INDEPENDENCE")
    assert it["status"] == wc.FAIL and it["reason"] == "malformed:ledger_unreadable", (
        "账本不可读时独立性核验被 SKIP（L2 禁止交付项的核验面失效）：%s / %s"
        % (it["status"], it["reason"]))
    # P9 复审收口：INDEPENDENCE 的 FAIL 早退路径不得吞掉 REVIEW_REPORT 检查项。
    # 本场景 plan=None → workspace 无从定位，合法 SKIP no_workspace；
    # 断言锁「检查项在场」（修前被早退整个吞掉，item() 会 raise）。
    rr = item(rep, "S6.REVIEW_REPORT")
    assert rr["status"] == wc.SKIP and (rr["reason"] or "").startswith("inapplicable:"), (
        "早退路径下 REVIEW_REPORT 应在场且合法 SKIP：%s / %s"
        % (rr["status"], rr["reason"]))


def test_unreadable_plan_s6_not_inapplicable(tmp_path):
    """计划提供但读不出 + 无账本 → S6 不得 SKIP inapplicable（复审 🟡 收口）。

    计划 Task 6 第 3 条：SKIP 仅限「证据确实不存在（无账本且无计划）」。
    plan 在 ctx 里但读不出时，独立性核验是「查不了」→ FAIL，
    不是「不该查」——inapplicable 会把「查不了」印成「不该查」。
    """
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "p.md").write_bytes(b"\xff\xfe invalid")
    rep, _ = wc.run(change=None, plan="docs/p.md", scale="medium", root=str(tmp_path))
    it = item(rep, "S6.INDEPENDENCE")
    assert it["status"] == wc.FAIL, (
        "计划读不出时 S6 被判 %s/%s —— 证据声明了却查不出，不得 SKIP"
        % (it["status"], it["reason"]))


def test_no_evidence_s6_still_inapplicable(tmp_path):
    """双向反例：真没证据（无账本无计划）→ 仍 SKIP inapplicable:no_evidence。"""
    rep, _ = wc.run(change=None, plan=None, scale="medium", root=str(tmp_path))
    it = item(rep, "S6.INDEPENDENCE")
    assert it["status"] == wc.SKIP and (it["reason"] or "").startswith("inapplicable:"), (
        "真没证据被误改判：%s / %s" % (it["status"], it["reason"]))
