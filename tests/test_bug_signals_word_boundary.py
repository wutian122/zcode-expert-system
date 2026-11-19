# -*- coding: utf-8 -*-
"""P8 批次二 Task 5：BUG_SIGNALS 族 ASCII 词整词匹配（对齐 _keyword_hits 纪律）。

抓的破坏：`bug_hits = [s for s in BUG_SIGNALS if s in text]` 的裸子串匹配让
ASCII 词误中嵌套位置——`bug` 命中 de**bug**、`fix` 命中 **fix**ture、
`error` 命中 **error**s、STRONG_BUG 的 `500` 命中 **500**0。裸子串再叠加
独立语境词（为什么/怎么回事）就凑齐「信号 + 语境共现」，把正常需求判成 Bug。

方向双向：
  - ASCII 词出现在词中嵌套位 → 不得触发（修前误判 Bug，RED）
  - ASCII 词独立出现（含紧邻汉字，如「返回500」「返回 5xx」）→ 必须仍触发
  - 中文词（无空格词边界）→ 子串匹配不回退
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import zcode_dev_workflow as wf  # noqa: E402

# 修前实测全部判 Bug（信号词经子串误命中 + 独立语境词凑齐共现）；
# 修后不得判 Bug。
NOT_BUG_CASES = [
    ("debug 模式怎么回事，日志前缀怎么配",
     "`bug` 误中 de**bug** +「怎么回事」凑齐语境"),
    ("metrics/errors 两个指标为什么对不上",
     "`error` 误中 **error**s +「为什么」凑齐语境"),
    ("错误码 5000 的映射表怎么理解",
     "STRONG_BUG 的 `500` 误中 **500**0 → 纯现象支路误判"),
    ("补 fixture 数据前为什么要先 review",
     "`fix` 误中 **fix**ture +「为什么」凑齐语境"),
]


@pytest.mark.parametrize("task,why", NOT_BUG_CASES)
def test_ascii_signal_whole_word_no_false_positive(task, why):
    assert wf.classify_scale(task)["scale"] != "bug", (
        "ASCII 词整词化后不得再判 Bug（%s）：%s" % (why, task))


# 修前修后都必须判 Bug——整词化不得把真故障洗白。
MUST_STAY_BUG = [
    ("登录接口报错 error 500，直接 crash",
     "报错/error/500/crash 全部独立成词，信号充足"),
    ("修复 regression 支付回调偶发 502",
     "修复/regression 信号 + 偶发/502 强故障"),
    ("线上服务一直返回 5xx",
     "「5xx」紧邻汉字——边界判定必须把汉字当边界，否则整词化会漏判"),
    ("线上 debug 环境数据库崩溃了",
     "即便 debug 不再供信号，「崩溃了」强故障词独立成立"),
]


@pytest.mark.parametrize("task,why", MUST_STAY_BUG)
def test_ascii_signal_no_miss_on_real_failure(task, why):
    assert wf.classify_scale(task)["scale"] == "bug", (
        "真故障被整词化洗白（%s）：%s" % (why, task))


# 中文词子串匹配不回退（P6 修复成果的守护）。
@pytest.mark.parametrize("task", ["页面白屏了", "接口老是超时", "数据库死锁了"])
def test_chinese_signals_still_substring(task):
    assert wf.classify_scale(task)["scale"] == "bug", (
        "中文信号词子串路径被误改：%s" % task)
