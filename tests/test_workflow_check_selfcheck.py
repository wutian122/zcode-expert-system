# -*- coding: utf-8 -*-
"""P1 · 验证器自检与架构不变量回归测试

**这个文件要抓的破坏**：`workflow_check.py` 是用来验证修复质量的仪器。
它自己坏了，任何「通过」都不可信——所以必须有机制在它漂移时当场暴露，
而不是等到某次门禁误判后才发现。

本文件检查三层：
  L1  配置 ↔ 代码一致性（--self-check）：id 集合、门禁覆盖、裁剪矩阵完整性、
      标签派生依赖的字段、L2 拦截语义依据
  L2  覆盖自检：每条检查项必须有稳定 id（供上游工具做「每项有反例」的机械核对）
  L3  架构不变量：INV-R1（无静默）、INV-R2（SKIP 必须有 inapplicable 理由码）

**为什么不放在 test_workflow_check_gates.py**：那个文件验业务语义（某缺陷修好没），
本文件验架构不变量（仪器本身还准不准）。混在一起会让每次跑业务测试都做一次
全量自检，成本与职责都不对。
"""

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts import workflow_check as wc  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_workflow_check_gates as G  # noqa: E402


@pytest.fixture
def proj():
    d = Path(tempfile.mkdtemp(prefix="wfc_self_")).resolve()
    yield d
    shutil.rmtree(str(d), ignore_errors=True)


# ---------------------------------------------------------------------------
# L1 —— 配置自检
# ---------------------------------------------------------------------------

def test_self_check_passes_on_shipped_config():
    """随包配置必须自检通过（这是 CI 的第一道闸）。

    防的破坏：改了 workflow.json 但没同步代码（或反之），
    门禁按旧规则继续跑且不报错——这正是本项目声称要防的「漂移」。
    """
    wf = wc.load_workflow()
    errors = wc.self_check(wf)
    assert errors == [], "配置漂移：%s" % errors


def test_self_check_cli_returns_zero():
    """CLI 层 --self-check 无漂移时 rc=0。"""
    assert wc.main(["--self-check"]) == 0


def test_self_check_detects_missing_checker():
    """注册表少一个阶段必须被自检抓出（模拟「代码没跟上配置」）。"""
    wf = wc.load_workflow()
    wf["stages"] = [s for s in wf["stages"] if s["id"] != "S5"]
    errors = wc.self_check(wf)
    assert any("检查器注册表" in e for e in errors), errors


def test_self_check_detects_unknown_gate():
    """stage 引用了未声明的门禁必须被抓出。"""
    wf = wc.load_workflow()
    wf["stages"][0]["gate"] = "G99"
    errors = wc.self_check(wf)
    assert any("G99" in e for e in errors), errors


def test_self_check_detects_invalid_trim_mark():
    """裁剪矩阵出现非法取值（如 `优`）必须被抓出。"""
    wf = wc.load_workflow()
    wf["trim_matrix"]["medium"]["S3"] = "优"
    errors = wc.self_check(wf)
    assert any("裁剪标记" in e for e in errors), errors


def test_self_check_detects_missing_short_field():
    """缺 short 字段会让门禁标签退化，必须被抓出。"""
    wf = wc.load_workflow()
    del wf["stages"][0]["short"]
    errors = wc.self_check(wf)
    assert any("short" in e for e in errors), errors


def test_self_check_detects_l2_semantics_lost():
    """L2 不再标注「禁止交付」时自检必须报错（S6 的拦截语义失去依据）。"""
    wf = wc.load_workflow()
    wf["reviewer_independence"]["levels"]["L2"] = "无审查"
    errors = wc.self_check(wf)
    assert any("L2" in e for e in errors), errors


def test_self_check_does_not_flag_legit_filename_placeholders():
    """回归守卫：`task-<N>-brief.md` 这类非 glob 产物的占位符是合法写法。

    初版自检把「文件名位不得有占位符」套到全部产物，实测误报 9 处——
    这些由 check_S5/check_S6 用正则匹配，不经过 expand_artifact。
    """
    wf = wc.load_workflow()
    assert not any("不可定界" in e for e in wc.self_check(wf))


# ---------------------------------------------------------------------------
# L2 —— 覆盖自检的基础：每条检查项要有稳定 id
# ---------------------------------------------------------------------------

def test_every_item_has_stable_id(proj):
    """所有检查项必须带 id：这是「每项有反例」机械核对的前提。

    没有 id 就只能按中文 check 名匹配，改一个措辞就断链——
    这正是本项目此前 123 条测试却漏掉 7 条假绿的原因之一。
    """
    G.build(proj)
    rep, _ = wc.run(change="demo", plan=G.PLAN_REL, scale="medium", root=str(proj))
    missing = [i["check"] for i in rep.items if not i.get("id")]
    assert not missing, "以下检查项缺 id：%s" % missing


def test_check_ids_are_unique_per_report(proj):
    """同一次报告内 id 不得重复（否则无法定位具体项）。"""
    G.build(proj)
    rep, _ = wc.run(change="demo", plan=G.PLAN_REL, scale="medium", root=str(proj))
    ids = [i["id"] for i in rep.items if i.get("id")]
    dup = sorted({x for x in ids if ids.count(x) > 1})
    assert not dup, "重复 id：%s" % dup


def test_all_eight_stages_emit_items(proj):
    """九个阶段在 medium 下都应有产出（供覆盖自检遍历）。"""
    G.build(proj)
    rep, _ = wc.run(change="demo", plan=G.PLAN_REL, scale="medium", root=str(proj))
    prefixes = {i["id"].split(".")[0] for i in rep.items if i.get("id")}
    expected = {"S0", "S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8"}
    assert expected <= prefixes, "缺阶段：%s" % (expected - prefixes)


# ---------------------------------------------------------------------------
# L3 —— 架构不变量
# ---------------------------------------------------------------------------

def test_skip_requires_inapplicable_reason(proj):
    """INV-R2：所有 SKIP 必须带 `inapplicable:` 理由码。

    这条不只是风格：enforce_reasons() 会把缺理由码的 SKIP 机械改判 FAIL。
    所以此处断言等价于「没有任何 SKIP 是靠省略理由蒙过去的」。
    """
    G.build(proj)
    rep, _ = wc.run(change=None, plan=G.PLAN_REL, scale="readonly", root=str(proj))
    bad = [i for i in rep.items
           if i["status"] == wc.SKIP
           and not (i.get("reason") or "").startswith("inapplicable:")]
    assert not bad, "缺合法理由的 SKIP：%s" % [(i["check"], i["reason"]) for i in bad]


def test_warn_requires_soft_reason(proj):
    """INV-R3：所有 WARN 必须带 `soft:` 理由码（WARN 只表达「此刻不必成立」）。"""
    G.build(proj)
    rep, _ = wc.run(change="demo", plan=G.PLAN_REL, scale="medium", root=str(proj))
    bad = [i for i in rep.items
           if i["status"] == wc.WARN
           and not (i.get("reason") or "").startswith("soft:")]
    assert not bad, "缺 soft 理由的 WARN：%s" % [(i["check"], i["reason"]) for i in bad]


def test_enforce_reasons_promotes_bare_skip_to_fail():
    """INV-R2 的机械保证：手工造一条无理由 SKIP，必须被改判 FAIL。"""
    rep = wc.Report()
    rep.add("x", "无理由的跳过", wc.SKIP, "我懒得查")
    rep.add("x", "有理由的跳过", wc.SKIP, "按声明不适用",
            reason="inapplicable:trim")
    rep.enforce_reasons()
    assert rep.items[0]["status"] == wc.FAIL
    assert rep.items[1]["status"] == wc.SKIP


def test_enforce_reasons_promotes_unverifiable_warn_to_fail():
    """查不了却报 WARN 的，必须改判 FAIL（WARN 不能当「查不了」的避风港）。"""
    rep = wc.Report()
    rep.add("x", "查不了但报 WARN", wc.WARN, "参数缺失")
    rep.enforce_reasons()
    assert rep.items[0]["status"] == wc.FAIL


def test_no_stage_silently_emits_zero_items(proj):
    """INV-R1：未被裁剪的阶段至少一条检查项。

    防的破坏：任何未来新增的提前 `return` 让某阶段整段消失——
    这正是 #1/#5 的共同根因形态，也是本次审计里最贵的两类假绿。
    """
    G.build(proj)
    rep, ctx = wc.run(change="demo", plan=G.PLAN_REL, scale="medium", root=str(proj))
    empty = [i["check"] for i in rep.items if i.get("id", "").endswith("STAGE_EMPTY")]
    assert not empty, "有空阶段：%s" % empty


def test_stage_exception_does_not_hide_other_stages(proj):
    """单阶段抛异常时，其他阶段仍要产出行（异常本身记 FAIL，不静默）。"""
    G.build(proj)
    # 用一个存在但类型错误的 plan 触发读失败路径
    rep, _ = wc.run(change="demo", plan=str(proj), scale="medium", root=str(proj))
    assert any(i["id"] == "S3.PLAN" and i["status"] == wc.FAIL for i in rep.items)
    assert any(i["id"] == "S7.INTEGRATION" for i in rep.items)


# ---------------------------------------------------------------------------
# 门禁标签派生
# ---------------------------------------------------------------------------

def test_gate_labels_derive_from_config(proj):
    """门禁标签必须与 workflow.json 派生值一致（消灭 39 处硬编码的漂移面）。"""
    wf = wc.load_workflow()
    allowed = {wc.gate_label(wf, s["id"]) for s in wf["stages"]}
    G.build(proj)
    rep, _ = wc.run(change="demo", plan=G.PLAN_REL, scale="medium", root=str(proj))
    stray = {i["gate"] for i in rep.items} - allowed
    assert not stray, "出现非派生标签：%s" % stray


def test_s6_label_includes_both_gates():
    """S6 的门禁标签应为 `G6+G7`（配置里就是复合门禁，旧标签只写了 G6）。"""
    wf = wc.load_workflow()
    assert wc.gate_label(wf, "S6").startswith("G6+G7")


# ---------------------------------------------------------------------------
# 解析辅助的单元级契约
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text,expect", [
    ("- [x] a", (1, 0, 0)),
    ("* [ ] b", (0, 1, 0)),
    ("+ [x] c", (1, 0, 0)),
    ("1. [ ] d", (0, 1, 0)),
    ("1) [x] e", (1, 0, 0)),
    ("  - [X] f", (1, 0, 0)),          # 嵌套子任务
    ("- [~] g", (0, 0, 1)),            # 异形标记 = 未完成
    ("- [] h", (0, 1, 0)),              # 空框（无内容）= 普通的未完成
    ("- [ x] i", (1, 0, 0)),            # 带空格的 x 仍是完成
    ("- [Some doc](./d.md)", (0, 0, 0)),  # 链接 bullet 不是任务
    ("- [A](http://e.com)", (0, 0, 0)),
    ("| - [x] t |", (0, 0, 0)),        # 表格行不是任务
])
def test_count_checkboxes_matches_openspec_semantics(text, expect):
    """勾选口径必须与 OpenSpec 真相源一致。

    `[~]` 算未完成这一点尤其重要：旧口径会把它从分母里去掉，
    于是「写 [~] 反而让完成度看起来更高」——实测的静默放大。
    """
    c = wc.count_checkboxes(text + "\n")
    assert (c["done"], c["todo"], c["other"]) == expect


def test_has_section_exact_match():
    """段名匹配必须精确：前缀不算。"""
    assert wc.has_section("## Review\nx\n", "Review")
    assert not wc.has_section("## Review Focus\nx\n", "Review")
    assert not wc.has_section("## Specification\nx\n", "Spec")
    assert wc.has_section("## Review（审查结论）\nx\n", "Review")
    assert wc.has_section("## Spec\nx\n", "Spec")


def test_has_section_ignores_fenced_examples():
    """围栏块里的示例段不得充当证据。"""
    text = "```markdown\n## Review\nindependence: L0\n```\n"
    assert not wc.has_section(text, "Review")


def test_expand_artifact_is_bounded(proj):
    """glob 产物展开不得越出声明前缀（旧实现会 walk 整个仓库根）。"""
    G.build(proj)
    found = wc.expand_artifact(str(proj),
                               "openspec/changes/<change>/specs/<capability>/spec.md",
                               "demo")
    assert found, "应找到 demo 下的 delta spec"
    for p in found:
        assert "openspec/changes/demo/specs" in p.replace("\\", "/")


def test_expand_artifact_rejects_filename_placeholder(proj):
    """文件名位占位符无法枚举，应返回空列表（由调用方报 malformed）。"""
    G.build(proj)
    assert wc.expand_artifact(str(proj), "openspec/changes/<change>/<weird>.md",
                              "demo") == []
