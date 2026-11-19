# -*- coding: utf-8 -*-
"""专家选型：语义精判契约与口语缩略词回归测试

背景（2026-11-16 老板指正）：
  `llm_client._call_llm` 恒返回 None 是**刻意设计**——插件依赖宿主会话
  正在使用的模型，不额外配置 LLM 服务。这不是缺陷。

  真正的缺陷是：SKILL.md 承诺「LLM 精判：从 Top 5 中选出最匹配的专家」，
  但 Python 拿不到模型时**并未把选择权交出去**，而是用「描述里出现过哪两个
  字」的词元计数冒充语义判断。实测「实现用户登录接口」选中
  「飞书集成开发工程师」仅因其描述含「登录」二字，而「后端架构师」
  描述写的是「API 开发」——词不同，不命中。

本文件断言两件事：
  1. Python 必须**显式标记**语义精判仍未完成，由主控接手（不许静默冒充）
  2. 口语缩略词（招一个/招人）必须能被词表命中（老板选择补词表修复）

运行：
    python -m pytest tests/test_semantic_selection.py -v
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import zcode_expert_system as zes  # noqa: E402


# ---------------------------------------------------------------------------
# 1. 语义精判契约：Python 不得静默冒充语义判断
# ---------------------------------------------------------------------------

def test_result_declares_semantic_selection_required():
    """主入口必须显式声明「语义精判待主控完成」。

    Python 无模型可用时，任何自动选择都只是词元计数，不是语义判断。
    必须把这个事实暴露出来，否则主控会直接采信错误结果。
    """
    r = zes.zcode_expert_system("实现用户登录接口")
    assert "semantic_selection_required" in r, (
        "返回结构缺 semantic_selection_required —— 主控无从知道要不要自己精判"
    )
    assert r["semantic_selection_required"] is True, (
        "无 LLM 可用时应标记为 True，实际 %r" % r.get("semantic_selection_required")
    )


def test_candidates_carry_score_breakdown():
    """候选必须带评分明细，主控才能判断 Python 的选择是否可信。"""
    r = zes.zcode_expert_system("实现用户登录接口")
    cands = r["top_candidates"]
    assert cands, "应有候选"
    for e in cands:
        assert "score" in e, "候选缺 score：%s" % e.get("name")
    # 至少第一个候选要有可解释的明细
    first = cands[0]
    assert "score_detail" in first, "首选候选缺 score_detail（name/desc/prompt 各命中多少）"
    detail = first["score_detail"]
    for key in ("name_hits", "desc_hits", "prompt_hits"):
        assert key in detail, "score_detail 缺 %s" % key


def test_suggestion_is_marked_as_heuristic():
    """若给出建议专家，必须标记它是启发式的，不是语义判定。"""
    r = zes.zcode_expert_system("实现用户登录接口")
    assert "selection_basis" in r, "缺 selection_basis"
    # 无 LLM 时只能是 heuristic；有 LLM 才可为 semantic
    assert r["selection_basis"] in ("heuristic", "semantic"), (
        "selection_basis 取值非法：%r" % r.get("selection_basis")
    )
    assert r["selection_basis"] == "heuristic", (
        "LLM 不可用时必须是 heuristic，实际 %r" % r.get("selection_basis")
    )


def test_routing_warning_tells_controller_to_decide():
    """语义精判待完成时，routing_warning 要明确告诉主控「你来定」。"""
    r = zes.zcode_expert_system("实现用户登录接口")
    w = r.get("routing_warning") or ""
    assert ("语义" in w) or ("主控" in w) or ("精判" in w), (
        "warning 未提示主控接手语义精判：%r" % w
    )


def test_manual_override_supported():
    """主控要能覆盖 Python 的默认选择（语义判断权在主控）。"""
    assert hasattr(zes, "build_dispatch_for_expert"), (
        "缺 build_dispatch_for_expert —— 主控需要按自己选的专家生成派发单"
    )
    # 直接指定一个专家名
    out = zes.build_dispatch_for_expert("后端架构师", "实现用户登录接口")
    assert out["dispatch"]["subagent_type"] == "后端架构师"
    assert out["status"] == "pending_dispatch"


def test_build_dispatch_for_expert_专家名不存在抛ValueError():
    """P2-4：build_dispatch_for_expert 传不存在专家名时抛 ValueError。

    静默降级会让主控误以为派发成功，故抛异常（zcode_expert_system.py:704-705）。
    旧测试只用真实专家名，未覆盖不存在名。本用例锁定该行为。
    """
    with pytest.raises(ValueError, match="未找到专家") as exc:
        zes.build_dispatch_for_expert("不存在的专家名XYZ", "实现用户登录接口")
    assert "不存在的专家名XYZ" in str(exc.value), (
        "ValueError 消息应包含所传的专家名，实际：%s" % str(exc.value)
    )


# ---------------------------------------------------------------------------
# 2. 口语缩略词表（老板选择补词表修复）
# ---------------------------------------------------------------------------

COLLOQUIAL = [
    # (输入, 期望分类集合) —— 口语招聘表达必须归 hr
    ("招一个前端工程师", {"hr"}),
    ("招个后端开发", {"hr"}),
    ("招人", {"hr"}),
    ("招聘一个测试工程师", {"hr"}),
    ("要招一个算法工程师", {"hr"}),
]


@pytest.mark.parametrize("text,expected", COLLOQUIAL,
                         ids=[t for t, _ in COLLOQUIAL])
def test_colloquial_recruiting_routes_to_hr(text, expected):
    """口语招聘表达必须能命中 hr。

    修复前：「招一个前端工程师」→ frontend-client（conf=1.0，自信地错），
    因为 hr 词表只有「招聘」，而口语说「招一个」「招人」。
    """
    cat, _conf, _alts = zes.classify_task_detailed(text)
    assert cat in expected, "「%s」应路由到 %s，实际 %s" % (text, sorted(expected), cat)


def test_single_char_zhao_does_not_overreach():
    """补「招」类词不得让无关表达误落 hr。

    「招标」「招呼」「招牌」等含「招」字但与招聘无关。
    """
    not_hr = ["招标文件怎么写", "招牌设计", "打招呼的英文怎么说"]
    for text in not_hr:
        cat, _conf, _alts = zes.classify_task_detailed(text)
        assert cat != "hr", "「%s」被误判为 hr" % text


def test_existing_hr_cases_still_work():
    """补词不得破坏既有 hr 归属。"""
    for text in ("招聘一个后端工程师", "员工绩效怎么考核", "培训计划怎么排"):
        cat, _conf, _alts = zes.classify_task_detailed(text)
        assert cat == "hr", "「%s」应仍为 hr，实际 %s" % (text, cat)
