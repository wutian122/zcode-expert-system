#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""分类器同分决胜缺陷的回归测试（Bug: 字母序决胜取代声明优先级）。

每个测试命名它要抓的破坏：

1. test_tie_resolves_by_declared_priority_not_alphabet
   抓：`scored.sort(reverse=True)` 对 (score, cat) 元组整体排序，
      同分时按分类名字母序倒序决胜，而非 KEYWORD_MAP 声明的优先级。

2. test_stop_tokens_downweighted_not_dominant
   抓：退化二不剔除也不降权泛化动作词（设计/开发/优化/需求/处理），
      导致低信息词制造大量假并列。

3. test_tie_returns_confidence_and_alternatives
   抓：同分并列时静默返回单一分类，调用方无从知晓置信度低。

4. test_no_match_reports_zero_confidence
   抓：完全无命中时静默落 DEFAULT_CATEGORY，调用方以为是正常分类。

5. test_llm_verdict_tie_not_first_element
   抓：`max(candidates, key=...)` 同分时恒取列表首元素，与相关性无关。

运行：python -m pytest tests/ -v
"""

import os
import sys

import pytest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

import zcode_expert_system as zes  # noqa: E402


# ---------------------------------------------------------------- 1. A 方案

def test_tie_resolves_by_declared_priority_not_alphabet():
    """同分并列时必须按 KEYWORD_MAP 声明优先级取，而非分类名字母序。

    '这个数据怎么处理' 在退化二下 customer-support / gis 同分。

    使用例自身推导期望值（并列集中声明序最靠前者），而**不写死分类名**——
    否则会把当前词表顺序固化成契约，日后调整词表顺序就要改测试。
    同时断言该期望值必须与字母序胜者不同，确保这条用例真能区分新旧行为。
    """
    task = "这个数据怎么处理"
    declared_order = list(zes.KEYWORD_MAP)

    # 复算退化二的并列集合（不依赖被测函数的内部实现）
    tokens = zes._tokenize(task)
    descriptions = zes._category_descriptions()
    scored = []
    for cat, keywords in zes.KEYWORD_MAP.items():
        score = zes._category_affinity_score(
            tokens, keywords, description=descriptions.get(cat, ""))
        if score > 0:
            scored.append((score, cat))

    best = max(s for s, _ in scored)
    tied = [c for s, c in scored if s == best]
    assert len(tied) > 1, "该用例必须产生并列，否则测试失去意义"

    expected = min(tied, key=declared_order.index)
    alphabet_winner = max(tied)  # 旧算法：字母序倒序取最大

    assert expected != alphabet_winner, (
        "该用例的声明序胜者与字母序胜者必须不同，否则无法区分新旧行为"
    )

    actual, _conf, _alts = zes.classify_task_detailed(task)
    assert actual == expected, (
        f"同分决胜错误：并列集 {tied}，声明序应选 {expected}，"
        f"实际返回 {actual}（字母序倒序胜者 {alphabet_winner}）"
    )


def test_tie_break_uses_declared_order_across_corpus():
    """批量锁定：所有产生并列的输入，胜者都必须是声明序最靠前者。

    打分用实现暴露的 `_category_affinity_score` 复算（降权口径是否生效
    由 test_stop_tokens_downweighted_not_dominant 独立把关）；
    本用例只锁「给定分数，决胜必须按声明优先级」这一条契约。
    """
    corpus = [
        "这个数据怎么解读",
        "总结一下这次会议",
        "帮我评估一下风险",
        "分析一下公司的现状",
        "这个功能怎么设计",
        "帮我看看这个设计对不对",
        "处理一下这个需求",
        "给我做个分析",
    ]
    declared_order = list(zes.KEYWORD_MAP)
    mismatches = []
    checked_ties = 0

    for task in corpus:
        tokens = zes._tokenize(task)
        if not tokens:
            continue
        scored = []
        descriptions = zes._category_descriptions()
        for cat, keywords in zes.KEYWORD_MAP.items():
            score = zes._category_affinity_score(
                tokens, keywords, description=descriptions.get(cat, ""))
            if score > 0:
                scored.append((score, cat))
        if not scored:
            continue
        best = max(s for s, _ in scored)
        tied = [c for s, c in scored if s == best]
        if len(tied) < 2:
            continue

        checked_ties += 1
        expected = min(tied, key=declared_order.index)
        actual, _conf, _alts = zes.classify_task_detailed(task)
        if actual != expected:
            mismatches.append((task, tied, expected, actual))

    assert checked_ties >= 3, (
        f"语料必须覆盖至少 3 个并列场景才有说服力，实际 {checked_ties}"
    )
    assert not mismatches, f"同分决胜未按声明优先级：{mismatches}"


# ---------------------------------------------------------------- 2. C 方案

def test_stop_tokens_downweighted_not_dominant():
    """泛化动作词必须降权，不能与领域词等权制造假并列。

    取同样大小的两组词元，一组全是泛化词、一组全是领域词，
    对同一份关键词表打分：领域词组必须严格更高。

    （C 方案采用「降权」而非「剔除」——若直接剔除，纯泛化词输入会
     连兜底候选都没有，比现状更差；降权则保留信号但压低其影响力。）
    """
    keywords = ["处理", "需求", "渗透", "漏洞"]
    generic_tokens = {"处理", "需求"}
    specific_tokens = {"渗透", "漏洞"}

    for tok in generic_tokens:
        assert tok in zes.STOP_TOKENS, f"{tok} 应属泛化词表，否则测试前提不成立"
    for tok in specific_tokens:
        assert tok not in zes.STOP_TOKENS, f"{tok} 不应属泛化词表"

    generic_score = zes._category_affinity_score(generic_tokens, keywords)
    specific_score = zes._category_affinity_score(specific_tokens, keywords)

    assert generic_score > 0, "泛化词应仍参与打分（降权而非剔除）"
    assert specific_score > generic_score, (
        f"领域词分值 {specific_score} 必须高于泛化词 {generic_score}"
    )


def test_generic_weight_is_below_one():
    """降权系数必须严格小于 1，否则降权不成立。"""
    assert 0 < zes.GENERIC_TOKEN_WEIGHT < 1


def test_pure_generic_input_is_flagged_low_confidence():
    """纯泛化词输入必须被标记为低置信度，而不是当成正常分类。"""
    _cat, conf, _alts = zes.classify_task_detailed("处理一下这个需求")
    assert conf < zes.LOW_CONFIDENCE_THRESHOLD, (
        f"纯泛化词输入置信度应低于阈值 {zes.LOW_CONFIDENCE_THRESHOLD}，实际 {conf}"
    )


# ---------------------------------------------------------------- 3. 置信度

def test_tie_returns_confidence_and_alternatives():
    """并列时返回值必须携带置信度与备选分类。"""
    cat, conf, alts = zes.classify_task_detailed("这个数据怎么解读")
    assert 0.0 <= conf <= 1.0
    assert isinstance(alts, list)
    assert len(alts) >= 1, "并列场景必须给出备选分类"
    assert cat not in alts, "备选列表不应包含已选中的分类"
    assert conf < 1.0, "存在并列时置信度不该是满分"


def test_clear_winner_gets_high_confidence():
    """信号明确且无并列的输入必须拿到高置信度、备选为空。

    '写一个 React 登录页'：frontend-client 靠「前端/react」唯一命中，
    其他分类无同分竞争者 → conf 应为 1.0。

    （不用「帮我做一次渗透测试」：它同时命中 security-compliance 的
      「渗透」与 data-testing 的「测试」，本就是真并列场景，
      会返回备选，不适合当"唯一赢家"用例。）
    """
    cat, conf, alts = zes.classify_task_detailed("写一个 React 登录页")
    assert cat == "frontend-client"
    assert conf >= zes.LOW_CONFIDENCE_THRESHOLD
    assert alts == []


def test_tie_winner_prefers_declared_order_over_alphabet():
    """真并列场景：胜者按声明序，落败者进备选，置信度打折。

    语料调整（H1 修复后）：'帮我做一次渗透测试' 现命中 security-compliance 的
    「渗透测试」（4字复合词，H1 新增），不再与 data-testing 的「测试」（2字）并列。
    改用「实现 token 刷新」：token 同时在 backend-architecture 与 security-compliance
    声明，但 security-compliance 在 KEYWORD_MAP 声明序中更靠前（第一组 vs 第 16 组），
    故胜者为 security-compliance，backend-architecture 进 alternatives。
    """
    cat, conf, alts = zes.classify_task_detailed("实现 token 刷新")
    declared_order = list(zes.KEYWORD_MAP)
    assert cat == "security-compliance", "token 并列应落声明序靠前的 security-compliance"
    assert "backend-architecture" in alts or len(alts) > 0, "并列落败者应进 alternatives"
    assert declared_order.index(cat) < declared_order.index("backend-architecture")
    assert conf < 1.0, "存在并列时置信度必须打折"


# ---------------------------------------------------------------- 4. 兜底

def test_no_match_reports_zero_confidence():
    """完全无命中时必须显式给 0 置信度，不得伪装成正常分类。"""
    cat, conf, _alts = zes.classify_task_detailed("写个季度汇报")
    assert cat == zes.DEFAULT_CATEGORY
    assert conf == 0.0, f"无命中场景置信度必须为 0，实际 {conf}"


# ---------------------------------------------------------------- 5. 不回归

def test_classify_task_public_signature_unchanged():
    """classify_task 仍返回 str，既有调用方不受影响。"""
    result = zes.classify_task("帮我做一次渗透测试")
    assert isinstance(result, str)
    assert result == "security-compliance"


def test_classify_task_handles_empty_input():
    assert zes.classify_task("") == zes.DEFAULT_CATEGORY
    assert zes.classify_task(None) == zes.DEFAULT_CATEGORY


def test_zero_confidence_does_not_pick_expert():
    """分类零置信度时不得继续挑专家。

    抓：「写个季度汇报」与 32 个分类毫无匹配（conf=0），但旧实现在
    DEFAULT_CATEGORY 里靠泛化词元微小重叠（旅行规划师 score=0.067）
    硬选出一个专家——纯数字巧合，语义上完全无关。
    零置信度必须返回 selected_expert=None，交调用方澄清。
    """
    result = zes.zcode_expert_system("写个季度汇报")
    assert result["confidence"] == 0.0
    assert result["selected_expert"] is None, (
        f"零置信度不应派专家，实际派了 {result['selected_expert']}"
    )
    assert result["top_candidates"] == []
    assert result["routing_warning"], "零置信度必须给出告警"


def test_low_but_nonzero_confidence_still_picks_expert():
    """非零置信度仍需正常选专家（不能因上面的修复而一刀切不选）。"""
    result = zes.zcode_expert_system("这个数据怎么看")
    assert result["confidence"] > 0.0
    assert result["selected_expert"] is not None, "有信号时必须给出专家"
    assert result["top_candidates"]


# ---------------------------------------------------------------- 6. llm_verdict

def test_llm_verdict_tie_not_first_element():
    """llm_verdict 同分时不得恒取候选列表首元素。

    两个专家对任务毫无相关性（均 0 分）时，反转候选顺序不应改变选择，
    或至少在无区分度时应返回 None 交由上层处理，而不是盲取第一个。
    """
    cand_a = {"id": "a", "name": "甲专家", "description": "", "category": ""}
    cand_b = {"id": "b", "name": "乙专家", "description": "", "category": ""}
    task = "完全无关的任务描述"

    picked_forward = zes.llm_verdict(task, [cand_a, cand_b])
    picked_reversed = zes.llm_verdict(task, [cand_b, cand_a])

    assert picked_forward == picked_reversed, (
        "候选顺序改变导致选择改变：说明同分时靠列表位置决胜，与相关性无关"
    )


def test_llm_verdict_still_picks_best_on_clear_signal():
    """有明确区分度时仍需选出最优候选，不能因修复同分而退化为不选。"""
    cand_weak = {"id": "w", "name": "通用助手", "description": "处理杂务", "category": ""}
    cand_strong = {
        "id": "s",
        "name": "渗透测试员",
        "description": "授权渗透测试、红队行动、漏洞评估",
        "category": "",
    }
    picked = zes.llm_verdict("做一次授权渗透测试", [cand_weak, cand_strong])
    assert picked is not None
    assert picked["id"] == "s", f"应选相关性更高的专家，实际选了 {picked}"


# ---------------------------------------------------------------- 7. margin 置信度

def test_weak_single_keyword_is_capped():
    """单个 2 字关键词不得给出高置信度。"""
    _cat, conf, _alts, detail = zes.classify_task_with_evidence("测试")
    assert detail["weak_single"] is True
    assert conf <= 0.5


def test_tied_categories_are_capped_below_threshold():
    """真并列时置信度必须降到阻断区。"""
    _cat, conf, alts, detail = zes.classify_task_with_evidence("实现 token 刷新")
    assert detail["tied"] is True
    assert alts
    assert conf < zes.LOW_CONFIDENCE_THRESHOLD
