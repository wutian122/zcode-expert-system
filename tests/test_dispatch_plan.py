# -*- coding: utf-8 -*-
"""派发计划层回归测试

对应 2026-11-16 审计发现 #10：
  `_pick_reviewer` 三个分支全部返回 "L0"，`independence` 恒为 L0（含
  implementer_type=None 的降级情形），主控照抄进账本后
  `workflow_check.py` 的 L2 拦截永不触发，审查独立性降级形同无标记。

运行：
    python -m pytest tests/test_dispatch_plan.py -v
"""

import glob
import io
import json
import os
import shutil
import sys
import time

import pytest

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PROJECT_ROOT)

import zcode_dev_workflow as wf  # noqa: E402


def _expert_names():
    """config/experts.json 的真实专家名集合。

    每次断言都读文件实核，不硬编码专家名——专家清单变更时测试自动跟随。
    """
    path = os.path.join(_PROJECT_ROOT, "config", "experts.json")
    with io.open(path, "r", encoding="utf-8") as f:
        return set(e["name"] for e in json.load(f)["experts"])


def _valid_subagent_types():
    """子代理派发名的合法集合（中文裸名 + Claude Code 限定名）。

    ZCode 环境：中文裸名（如「后端架构师」）
    Claude Code 环境：插件名:中文名（如「zcode-expert-system:后端架构师」）
    """
    names = _expert_names()
    return names | {f"zcode-expert-system:{n}" for n in names}


def _retry_remove(path, attempts=20, is_dir=False):
    """带核验的重试删除（T4 CONCERNS 遗留加固，复制自 test_domain_routing_mandatory.py）。

    为什么复制而不是跨测试文件 import：测试模块必须可独立运行，跨模块
    引用会耦合 pytest 收集顺序并破坏单文件执行——本仓已有 _safe_write
    在两个 workflow_check 测试文件中各自成文的先例，沿用同款做法。
    为什么必须重试：Windows 上刚写完的文件可能被 AV/索引器短暂锁定，
    rmtree/os.remove 会偶发失败——差集式清理漏网一次即永久残留
    （Task 4 实测根因，预算 ~2s：20×100ms）。
    """
    for _ in range(attempts):
        if is_dir:
            shutil.rmtree(path, ignore_errors=True)
        else:
            try:
                os.remove(path)
            except OSError:
                pass
        if not os.path.exists(path):
            return
        time.sleep(0.1)


def plan_for(task, **kw):
    r = wf.classify_scale(task, kw.get("files"))
    return wf.build_dispatch_plan(task, scale=r, files=kw.get("files"))


# ---------------------------------------------------------------------------
# I-02/I-03：低置信度误选专家必须阻断派发；高置信度 heuristic 标注依据
# ---------------------------------------------------------------------------


def test_low_confidence_heuristic_blocks_implementer_dispatch():
    """I-02：分类置信度低于阈值时，不得按词元兜底选出的专家直接派发。

    「实现一个支付回调的幂等性」词元退化后落 hr（conf 远低于 0.5），
    选中的「招聘专家」与任务语义无关。语义精判未完成 + 低置信度
    → 分类本身不可靠，必须阻断 implementer 派发，仅留 semantic_recheck
    动作与 blocking，让主控澄清领域。
    """
    task = "实现一个支付回调的幂等性"
    plan = plan_for(task)
    # 确认这是低置信度 + heuristic 的场景（前提自检，避免用例随词表变化空转）
    domain = plan.get("domain", {})
    assert domain.get("confidence", 1.0) < 0.5, \
        f"用例前提失效：该任务置信度应低于 0.5，实际 {domain.get('confidence')}"
    assert domain.get("selection_basis") == "heuristic", \
        f"用例前提失效：selection_basis 应为 heuristic，实际 {domain.get('selection_basis')}"
    # 修复后：不得有 implementer 派发
    impl_roles = [d for d in plan["dispatches"] if d["role"] == "implementer"]
    assert not impl_roles, "低置信度 + heuristic 不得派发 implementer（分类不可靠）"
    # 应保留 semantic_recheck 动作 + blocking
    actions = [d.get("action") for d in plan["dispatches"]]
    assert "semantic_recheck" in actions, "应保留 semantic_recheck 动作"
    assert plan.get("blocking"), "低置信度误派必须设 blocking"


def test_high_confidence_heuristic_keeps_recheck_but_dispatches():
    """I-03：分类置信度高但 selection_basis=heuristic 时，保留派发但标注依据。

    分类可靠（conf≥0.5），只是专家挑选是词元计数。此时保留 implementer
    派发（分类正确），但 semantic_recheck 动作与 blocking 必须存在，
    提醒主控复核 top_candidates 的 score_detail。
    """
    # 选一个高置信度、heuristic 的典型任务：域路由确定但专家词元计数
    task = "修复用户登录接口的鉴权 bug"
    plan = plan_for(task)
    domain = plan.get("domain", {})
    assert domain.get("confidence", 0.0) >= 0.5, \
        f"用例前提失效：该任务置信度应 ≥0.5，实际 {domain.get('confidence')}"
    impl_roles = [d for d in plan["dispatches"] if d["role"] == "implementer"]
    assert impl_roles, "高置信度分类下应保留 implementer 派发"
    actions = [d.get("action") for d in plan["dispatches"]]
    assert "semantic_recheck" in actions, "heuristic 选择必须保留 semantic_recheck 提醒"


# ---------------------------------------------------------------------------
# #10 独立性必须由实际情况推导
# ---------------------------------------------------------------------------

def test_independence_derived_from_actual_pairing():
    """独立性级别必须反映真实配对，不能恒为 L0。

    场景：实施者与审查者由 `_pick_reviewer` 决定，只要两者不是同一专家，
    且审查者是独立派发，才是 L0。
    """
    plan = plan_for("实现用户登录接口", files=6)
    rv = [d for d in plan["dispatches"] if d["role"] == "reviewer"][0]
    assert "independence" in rv, "reviewer 派发缺 independence 字段"
    assert rv["independence"] in ("L0", "L1", "L2"), (
        "独立性级别非法：%s" % rv["independence"]
    )


def test_reviewer_type_differs_from_implementer():
    """审查者类型不得与实施者相同（I1 硬约束）。

    注意：只读任务不产生派发（正确行为），所以此处只用实施类任务。
    """
    for task in ("实现用户登录接口", "训练一个 LoRA 微调模型", "写一个 Dockerfile 多阶段构建"):
        plan = plan_for(task, files=6)
        impl = [d for d in plan["dispatches"] if d["role"] == "implementer"]
        rv = [d for d in plan["dispatches"] if d["role"] == "reviewer"]
        assert impl, "「%s」应产生实施者派发" % task
        assert rv, "「%s」应产生审查者派发" % task
        assert rv[0]["subagent_type"] != impl[0]["subagent_type"], (
            "「%s」实施者与审查者都是 %s，违反 I1" % (task, impl[0]["subagent_type"])
        )


def test_no_implementer_means_lower_independence():
    """域路由不可用（实施者降级 general-purpose）时，独立性不得标 L0。

    理由：没有领域实施者时，「独立审查」的语义已经弱化，必须显式标记，
    让主控在账本里留下痕迹，而不是照抄 L0 掩盖问题。
    """
    assert hasattr(wf, "_pick_reviewer"), "缺少 _pick_reviewer"
    _rv, level, _reason = wf._pick_reviewer(None)
    assert level != "L0", "实施者缺失时独立性不得为 L0，实际 %s" % level


def test_independence_returns_reason():
    """独立性必须带理由，便于主控在账本里记录。"""
    out = wf._pick_reviewer("后端架构师")
    assert len(out) == 3, "_pick_reviewer 应返回 (reviewer, level, reason)"
    _rv, level, reason = out
    assert reason, "独立性缺理由说明"
    assert level in ("L0", "L1", "L2")


# ---------------------------------------------------------------------------
# 派发计划结构契约
# ---------------------------------------------------------------------------

def test_plan_has_serial_implementation():
    """无 Worktree ⇒ 实施必须串行（W1 守恒）。"""
    plan = plan_for("实现用户登录接口", files=6)
    assert plan["parallel"]["implementation"] == "serial"
    assert "Worktree" in plan["parallel"]["reason"] or "worktree" in plan["parallel"]["reason"]


def test_readonly_plan_dispatches_analyst():
    """只读任务必须完成域路由并派发 analyst（W10 双轴强制，D3）。

    旧断言「只读任务不分派、派发恒空」随 enforce-domain-routing 变更反转：
    readonly 也必须先走域轴路由，并按领域结论派发 role=analyst。
    subagent_type 必须是 config/experts.json 里的真实专家名（读文件实核，
    不硬编码——A2 裁决口径）。
    """
    sdd_root = os.path.join(_PROJECT_ROOT, ".superpowers", "sdd")
    before = set(glob.glob(os.path.join(sdd_root, "dispatch-*")))
    try:
        # M-1（修复轮 1）：plan_for 移入 try——生成派发计划（含 dispatch.json
        # 落盘）期间任何异常都走 finally 的 glob 差集兜底清理，不残留 dispatch-*
        plan = plan_for("分析一下这个模块的架构")
        analysts = [d for d in plan["dispatches"] if d.get("role") == "analyst"]
        assert analysts, (
            "只读任务应派发 role=analyst（旧契约「只读不分派」已按 W10 反转；"
            "实际 dispatches roles=%s）" % [d.get("role") for d in plan["dispatches"]]
        )
        sub = analysts[0].get("subagent_type")
        assert sub in _valid_subagent_types(), (
            "analyst.subagent_type=%r 不是 config/experts.json 中的真实专家名" % sub
        )
    finally:
        # Task 2 落地后 readonly analyst 派发会落盘 dispatch.json（裁决 2）：
        # 按 glob 差集自清，测试不残留 dispatch-*（sdd_root 在 try 前定义一次；
        # T4 CONCERNS 加固：改用 _retry_remove 堵 Windows 首扫锁竞态）
        for d in set(glob.glob(os.path.join(sdd_root, "dispatch-*"))) - before:
            _retry_remove(d, is_dir=True)


def test_role_contract_prefix_has_priority_clause():
    """角色契约前缀必须含「流程契约优先」声明（W6）。"""
    for role in ("implementer", "reviewer", "investigator"):
        prefix = wf._role_contract_prefix(role)
        assert "流程契约优先" in prefix, "%s 契约缺优先级声明" % role


def test_implementer_prefix_forbids_subagent():
    """实施者契约必须禁止派子代理。"""
    prefix = wf._role_contract_prefix("implementer")
    # ③ 审查移交顺手修：原断言两个操作数相同（"禁止派子代理" in prefix or
    # "禁止派子代理" in prefix），属笔误——改为容忍两种等价措辞
    assert "禁止派子代理" in prefix or "不得派子代理" in prefix


def test_reviewer_prefix_has_do_not_trust():
    """审查者契约必须声明不采信自评。"""
    prefix = wf._role_contract_prefix("reviewer")
    assert "不采信" in prefix or "待验证主张" in prefix
