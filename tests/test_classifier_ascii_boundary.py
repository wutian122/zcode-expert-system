# -*- coding: utf-8 -*-
"""分类器 ASCII 词边界、关键词归属、排序信息保真回归测试

对应 2026-11-16 审计发现的 4 条缺陷：
  #1 ASCII 关键词裸子串匹配 → `ai` 命中 `email`/`detail`/`main`
  #6 关键词 `路由` 双归属 → 网络问题全落 frontend-client
  #7 min(1.0) 截顶抹掉排序信息 → raw 更高的专家反而落选
  #2 selected_expert=None 时无 routing_warning → 静默失效

运行：
    python -m pytest tests/test_classifier_ascii_boundary.py -v
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import zcode_expert_system as zes  # noqa: E402


# ---------------------------------------------------------------------------
# #1 ASCII 词边界
# ---------------------------------------------------------------------------

ASCII_FALSE_POSITIVE = [
    # (输入, 不应命中的分类, 说明)
    ("给 email 模板加变量", "ai-llm", "ai 命中 email"),
    ("detail 页样式调整", "ai-llm", "ai 命中 detail"),
    ("重构 main 分支合并逻辑", "ai-llm", "ai 命中 main"),
    ("用 gdb 调试程序", "data-database", "db 命中 gdb"),
    ("explain 一下这段逻辑", "ai-llm", "ai 命中 explain"),
]


@pytest.mark.parametrize("text,forbidden,why", ASCII_FALSE_POSITIVE,
                         ids=[t for t, _, _ in ASCII_FALSE_POSITIVE])
def test_ascii_keyword_needs_word_boundary(text, forbidden, why):
    """ASCII 关键词必须整词匹配，不能命中别的单词的子串。"""
    cat, _conf, _alts = zes.classify_task_detailed(text)
    assert cat != forbidden, "「%s」被 %s 劫持（%s）" % (text, forbidden, why)


ASCII_TRUE_POSITIVE = [
    # 整词出现时必须仍然命中
    ("这个 api 需要限流", "backend-architecture"),
    ("写个 sql 查询", "data-database"),
    ("用 redis 做缓存", "backend-architecture"),
    # 复合 ASCII 词：加边界后 `docker` 不再命中 `dockerfile` 的前缀，
    # 必须显式声明 composite 词，否则会落兜底分类
    ("写一个 Dockerfile 多阶段构建", "devops-operations"),
    ("用 docker 部署", "devops-operations"),
]


@pytest.mark.parametrize("text,expected", ASCII_TRUE_POSITIVE,
                         ids=[t for t, _ in ASCII_TRUE_POSITIVE])
def test_ascii_keyword_still_matches_whole_word(text, expected):
    """加词边界后，整词出现的 ASCII 关键词必须仍然命中。"""
    cat, _conf, _alts = zes.classify_task_detailed(text)
    assert cat == expected, "「%s」应路由到 %s，实际 %s" % (text, expected, cat)


def test_ai_keyword_matches_but_allows_domain_ambiguity():
    """整词 `ai` 必须能命中 ai-llm。

    「用 ai 做一个智能客服」同时命中「智能客服」(customer-support) 与
    「ai」(ai-llm)，是真实领域歧义——两者都可接受，但绝不能落到无关分类
    （修复前 `ai` 因无词边界被 email/detail/main 劫持）。
    """
    cat, _conf, _alts = zes.classify_task_detailed("用 ai 做一个智能客服")
    assert cat in ("ai-llm", "customer-support"), (
        "「用 ai 做一个智能客服」应路由到 ai-llm 或 customer-support，实际 %s" % cat
    )


# ---------------------------------------------------------------------------
# #6 关键词归属：网络路由不应落前端
# ---------------------------------------------------------------------------

NETWORK_ROUTING = [
    "路由器怎么配置",
    "配置交换机路由",
    "网络路由优化",
]


@pytest.mark.parametrize("text", NETWORK_ROUTING)
def test_network_routing_not_frontend(text):
    """「路由」在网络语境下不应被前端抢走。

    修复前：「路由」同时声明在 frontend-client 与 network-engineering，
    声明序让 frontend 恒胜，三条网络问题全部落前两天。
    """
    cat, _conf, _alts = zes.classify_task_detailed(text)
    assert cat == "network-engineering", (
        "「%s」应路由到 network-engineering，实际 %s" % (text, cat)
    )


FRONTEND_ROUTING = [
    "前端路由配置",
    "vue router 配置",
]


@pytest.mark.parametrize("text", FRONTEND_ROUTING)
def test_frontend_routing_not_network(text):
    """前端语境的路由仍应归前端。"""
    cat, _conf, _alts = zes.classify_task_detailed(text)
    assert cat in ("frontend-client",), (
        "「%s」应路由到 frontend-client，实际 %s" % (text, cat)
    )


# ---------------------------------------------------------------------------
# #7 排序信息保真：对外值域 0~1，内部排序用原始分
# ---------------------------------------------------------------------------

def test_score_clamp_preserves_ordering():
    """raw 分更高的专家必须排在前面，不能被 min(1.0) 抹成并列。

    修复前：技术翻译专家 raw=1.667、语言翻译专家 raw=1.333，
    双双击顶 1.0 → 稳定排序按候选声明序取胜 → 选了分低的。
    """
    r = zes.zcode_expert_system("翻译")
    assert r["selected_expert"] is not None, "「翻译」不该零专家"
    assert r["selected_expert"]["name"] == "技术翻译专家", (
        "raw 分更高的「技术翻译专家」应胜出，实际 %s" % r["selected_expert"]["name"]
    )


def test_keyword_score_still_within_range():
    """对外暴露的分数仍受 0~1 契约约束。"""
    task = "登录接口"
    tokens = zes._tokenize(task)
    expert = {"name": "登录接口", "description": "登录接口", "file": ""}
    score = zes._keyword_score(tokens, expert)
    assert 0.0 <= score <= 1.0, "对外分数越界：%.3f" % score


def test_raw_score_exposed_for_ordering():
    """内部排序用的原始分必须可被拿到（无截顶）。"""
    assert hasattr(zes, "_keyword_score_raw"), (
        "缺少 _keyword_score_raw —— 排序必须用未截顶的原始分"
    )
    task = "翻译"
    tokens = zes._tokenize(task)
    expert = {"name": "技术翻译专家", "description": "技术翻译", "file": ""}
    raw = zes._keyword_score_raw(tokens, expert)
    assert raw > 1.0, "构造的用例应产生 >1.0 的原始分，实际 %.3f" % raw


# ---------------------------------------------------------------------------
# #2 selected_expert 为 None 必须有 warning（不论 confidence）
# ---------------------------------------------------------------------------

NONE_EXPERT_CASES = ["编译报错", "报错", "写个季度汇报"]


@pytest.mark.parametrize("text", NONE_EXPERT_CASES)
def test_none_expert_always_warns(text):
    """拿不到专家时必须给 warning，否则调用方看到 conf=1.0 会直接派发 None。

    修复前：「编译报错」返回 conf=1.0 + selected_expert=None + warning=None，
    调用方无任何依据，属静默失效。
    """
    r = zes.zcode_expert_system(text)
    if r["selected_expert"] is None:
        assert r["routing_warning"], (
            "「%s」selected_expert=None 却无 routing_warning（conf=%s）"
            % (text, r.get("confidence"))
        )


def test_warning_mentions_missing_expert():
    """warning 文案应说明是「无可用专家」，不只是「置信度低」。"""
    r = zes.zcode_expert_system("编译报错")
    if r["selected_expert"] is None:
        w = r["routing_warning"] or ""
        assert ("专家" in w) or ("候选" in w), (
            "warning 未说明专家缺失：%r" % w
        )


def test_confidence_and_alternatives_consistent():
    """置信度与备选语义自洽（伪并列防回归）。"""
    for text in ("把数据库慢查询优化一下", "训练一个大模型做rag", "实现用户登录接口"):
        _cat, conf, alts = zes.classify_task_detailed(text)
        assert not (conf < 1.0 and not alts), (
            "「%s」conf=%.3f 但 alts=[] —— 伪并列" % (text, conf)
        )
