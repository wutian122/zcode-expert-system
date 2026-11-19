# -*- coding: utf-8 -*-
"""分类器词表覆盖与置信度自洽回归测试

背景：既有 15 条测试（tests/test_classifier_tiebreak.py）全绿，但对
**词表内容缺口**完全盲——它们断言的是"给定当前词表，决胜规则是否自洽"，
不是"输入 X 应路由到 Y"。2026-11-16 实测 16 条真实用例中 5 条错路由，
15 条测试一条都没抓到。

本文件补两类断言：
  1. 语义断言：输入 → 具体期望分类（不再是"32 类之一"）
  2. 自洽断言：conf 与 alternatives 不得互相矛盾（伪并列 Bug）

运行：
    python -m pytest tests/test_classifier_coverage.py -v

red-green 复验：临时抽掉 KEYWORD_MAP 里某个关键补词，本文件必须复红；
恢复后必须复绿。未走完此循环不得声称测试有效。
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import zcode_expert_system as zes  # noqa: E402


# ---------------------------------------------------------------------------
# 黄金集：输入 → 可接受分类集合
#
# 断言规则：
#   - 断言具体分类，不是"属于 32 类之一"
#   - 允许多选，但必须是人工标注的领域内可接受集
#   - DEFAULT_CATEGORY（business-support）除输入本身无关任务外，永不可接受
# ---------------------------------------------------------------------------

GOLD_ENGINEERING = [
    ("实现用户登录接口", {"backend-architecture"}),
    ("开发登录功能", {"frontend-client", "backend-architecture"}),
    ("做一个登录页面", {"frontend-client"}),
    ("给页面加个登录表单", {"frontend-client"}),
    ("帮我看下这段日志为什么报错", {"devops-operations"}),
    ("线上服务崩溃了帮我排查", {"devops-operations"}),
    ("分析一下这个模块的架构", {"backend-architecture", "engineering-quality"}),
    ("设计一个支持高并发的后端API", {"backend-architecture"}),
    ("给登录加个验证码", {"backend-architecture", "frontend-client"}),
    ("页面加载很慢", {"frontend-client", "data-testing"}),
    ("实现一个用户注册流程", {"backend-architecture", "frontend-client"}),
]

GOLD_BOUNDARY = [
    # 补词不得抢走既有的正确归属：长复合词应压过新补的短词
    ("公司组织架构调整方案", {"business-strategy"}),
    ("安全架构设计评审", {"security-compliance"}),
    ("游戏关卡设计", {"game-dev"}),
    ("产品设计评审", {"product-management"}),
    ("客户服务投诉处理", {"customer-support"}),
    ("帮我看看这份合同有什么风险", {"legal-compliance"}),
    ("做一份财务报表", {"finance-tax"}),
    # 人文社科学术域（academic-research 覆盖历史/人类学/社会学/心理学，
    # 不含计算机科学理论——本项目无 CS 理论分类，勿用此类输入断言）
    ("写一篇文献综述，需要考据史料", {"academic-research"}),
    ("做一个社会学问卷调查", {"academic-research", "data-testing"}),
]

GOLD = GOLD_ENGINEERING + GOLD_BOUNDARY


# ---------------------------------------------------------------------------
# 1. 语义断言：输入 → 具体分类
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text,expected", GOLD, ids=[t for t, _ in GOLD])
def test_routes_to_expected_category(text, expected):
    """词表覆盖缺陷的正面断言。

    既有测试从不断言具体分类，因此词表缺「登录」「页面」「日志」这类
    高频工程词时无人发现。
    """
    cat, _conf, _alts = zes.classify_task_detailed(text)
    assert cat in expected, (
        "「%s」被路由到 %s，期望其中之一 %s" % (text, cat, sorted(expected))
    )


# ---------------------------------------------------------------------------
# 2. 兜底率断言：把 conf=0 从「通过」改成「失败」
# ---------------------------------------------------------------------------

def test_fallback_rate_below_threshold():
    """抓：词表缺口导致大量输入静默落入 DEFAULT_CATEGORY。

    既有 test_no_match_reports_zero_confidence 反而把「落默认兜底」
    写成了正确行为——这正是缺陷本身。
    """
    fell_back = [
        t for t, expected in GOLD
        if zes.classify_task_detailed(t)[0] == zes.DEFAULT_CATEGORY
        and zes.DEFAULT_CATEGORY not in expected
    ]
    rate = len(fell_back) / float(len(GOLD))
    assert rate <= 0.05, (
        "兜底率 %.0f%% 超阈值 5%%，落兜底的输入：%s" % (rate * 100, fell_back)
    )


def test_signal_coverage_not_starved():
    """抓：输入词元里能命中词表的比例过低（信号被饿死）。

    覆盖率 0% 时退化二 scored 为空，分类完全随机。
    """
    all_kw_tokens = set()
    for kws in zes.KEYWORD_MAP.values():
        all_kw_tokens |= zes._tokenize(" ".join(kws))

    starved = []
    for text, _expected in GOLD_ENGINEERING:
        tokens = zes._tokenize(text)
        effective = {t for t in tokens if t not in zes.STOP_TOKENS} or tokens
        if not effective:
            continue
        hit = effective & all_kw_tokens
        if len(hit) / float(len(effective)) == 0.0:
            starved.append(text)

    assert not starved, "以下输入零信号覆盖（词表一个词都没命中）：%s" % starved


# ---------------------------------------------------------------------------
# 3. 自洽断言：伪并列 Bug
# ---------------------------------------------------------------------------

PSEUDO_TIE = [
    # 同一分类命中多个等长关键词 → 不应被判为跨分类并列
    "把数据库慢查询优化一下",
    "训练一个大模型做rag",
    "做一套UI设计规范",
    "库存补货怎么算",
]


@pytest.mark.parametrize("text", PSEUDO_TIE)
def test_same_category_multi_hit_is_not_a_tie(text):
    """抓：hit_lengths 不去重导致同分类多次命中被误判为并列。

    缺陷表现：返回 conf=0.75（宣称"有并列"）但 alternatives=[]（宣称"无并列"），
    返回值自相矛盾，且置信度被无故压低。
    """
    _cat, conf, alts = zes.classify_task_detailed(text)
    assert not (conf < 1.0 and not alts), (
        "「%s」返回 conf=%.3f 但 alternatives=[] —— 自相矛盾（伪并列）" % (text, conf)
    )


def test_confidence_zero_implies_no_alternatives():
    """置信度与备选必须语义一致：0 置信度不该有备选，有备选必须降置信度。"""
    for text, _ in GOLD:
        _cat, conf, alts = zes.classify_task_detailed(text)
        if conf == 0.0:
            assert not alts, "「%s」conf=0 却有备选 %s" % (text, alts)
        if alts:
            assert conf < 1.0, "「%s」有备选 %s 却给满分置信度" % (text, alts)


# ---------------------------------------------------------------------------
# 4. 专家打分值域（_keyword_score 契约越界）
# ---------------------------------------------------------------------------

def test_keyword_score_within_documented_range():
    """抓：_keyword_score 文档称返回 0~1，但三项全中得 1.667。

    构造：一个在 name + description 上都完全命中的专家。
    """
    task = "登录接口"
    tokens = zes._tokenize(task)
    expert = {
        "name": "登录接口",
        "description": "登录接口",
        "file": "",  # 无提示词文件，prompt_hits=0
    }
    score = zes._keyword_score(tokens, expert)
    assert 0.0 <= score <= 1.0, (
        "_keyword_score 返回 %.3f，超出文档声称的 0~1 值域" % score
    )


# ---------------------------------------------------------------------------
# 5. 契约保真：classify_task 仍返回 str
# ---------------------------------------------------------------------------

def test_classify_task_str_contract():
    for text in ("实现用户登录接口", "", None):
        cat = zes.classify_task(text)
        assert isinstance(cat, str)
        assert cat in zes.CATEGORIES
