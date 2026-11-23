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


def _valid_subagent_types():
    """子代理派发名的合法集合（中文裸名 + Claude Code 限定名）。

    ZCode 环境：中文裸名（如「后端架构师」）
    Claude Code 环境：插件名:中文名（如「zcode-expert-system:后端架构师」）
    """
    import json
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "experts.json")
    with open(path, "r", encoding="utf-8") as f:
        names = set(e["name"] for e in json.load(f)["experts"])
    return names | {f"zcode-expert-system:{n}" for n in names}


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
    assert out["dispatch"]["subagent_type"] in _valid_subagent_types(), (
        "subagent_type=%r 不是合法派发名" % out["dispatch"]["subagent_type"]
    )
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


def test_qualified_subagent_type_by_platform():
    """平台探测：Claude Code 环境输出限定名，ZCode 环境保持中文裸名。

    - CLAUDE_PLUGIN_ROOT 存在（Claude Code）→ zcode-expert-system:<中文名>
    - CLAUDE_PLUGIN_ROOT 不存在（ZCode / CI）→ 中文裸名
    """
    import os as _os
    _orig = _os.environ.get("CLAUDE_PLUGIN_ROOT")

    try:
        # Claude Code 环境：设置 CLAUDE_PLUGIN_ROOT
        _os.environ["CLAUDE_PLUGIN_ROOT"] = "/tmp/fake-plugin-root"
        out = zes.build_dispatch_for_expert("后端架构师", "测试任务")
        assert out["dispatch"]["subagent_type"] == "zcode-expert-system:后端架构师", (
            "Claude Code 环境下 subagent_type 应为 zcode-expert-system:后端架构师，"
            "实际 %r" % out["dispatch"]["subagent_type"]
        )

        # ZCode 环境：清除 CLAUDE_PLUGIN_ROOT
        _os.environ.pop("CLAUDE_PLUGIN_ROOT", None)
        out = zes.build_dispatch_for_expert("后端架构师", "测试任务")
        assert out["dispatch"]["subagent_type"] == "后端架构师", (
            "ZCode 环境下 subagent_type 应为后端架构师，"
            "实际 %r" % out["dispatch"]["subagent_type"]
        )
    finally:
        # 恢复原始环境变量
        if _orig is not None:
            _os.environ["CLAUDE_PLUGIN_ROOT"] = _orig
        else:
            _os.environ.pop("CLAUDE_PLUGIN_ROOT", None)


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


# ---------------------------------------------------------------------------
# 2. 领域词缺口：「博客」类内容平台词（2026-11-22）
# ---------------------------------------------------------------------------

BLOG_FRONTEND = [
    ("搭建一个博客系统", {"frontend-client"}),
    ("写一个博客系统", {"frontend-client"}),
    ("做一个个人博客", {"frontend-client"}),
]


@pytest.mark.parametrize("text,expected", BLOG_FRONTEND,
                         ids=[t for t, _ in BLOG_FRONTEND])
def test_blog_system_routes_to_frontend_client(text, expected):
    """博客类任务必须路由到 frontend-client，不得被泛化词噪声决胜。

    修复前：「搭建一个博客系统」→ hr（conf=0.0268）——「博客」不在任何
    词表，hr/ai-llm 仅因泛化词「一个」（STOP_TOKEN，来自「招一个」的
    二元组）并列 0.0357×0.75 折半胜出。典型「矮子里将军」：唯一命中的
    词元是零区分度的泛化词，却仍产出「伪领域」结论。

    conf 护栏同断言：修复后必须 ≥0.5（LOW_CONFIDENCE_THRESHOLD），
    不再依赖微弱噪声得分。
    """
    cat, conf, _alts = zes.classify_task_detailed(text)
    assert cat in expected, "「%s」应路由到 %s，实际 %s（conf=%s）" % (
        text, sorted(expected), cat, conf)
    assert conf >= zes.LOW_CONFIDENCE_THRESHOLD, (
        "「%s」conf=%s < 0.5——泛化词噪声决胜仍在（应为词表精确命中）" % (text, conf))


def test_blog_word_substring_collision_is_bounded():
    """「博客」入 frontend-client 词表后的子串碰撞不得越过显式领域词。

    「博客」会子串命中「博客园」（站点名，如「爬取博客园文章」是爬虫
    任务）——接受轻度偏航（frontend-client 优于 0 信号兜底），但必须
    守住两条底线：
      1. 不得落入与站点爬取明显无关的领域（hr / healthcare / finance）；
      2. 显式后端/数据词共存时，等长并列由声明序裁决，行为须稳定可预期。
    """
    unrelated = ["爬取博客园热门文章", "博客园怎么爬取"]
    for text in unrelated:
        cat, _conf, _alts = zes.classify_task_detailed(text)
        assert cat not in ("hr", "healthcare", "finance"), (
            "「%s」被误路由到 %s（子串碰撞越界）" % (text, cat))
