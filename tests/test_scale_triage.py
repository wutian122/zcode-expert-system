# -*- coding: utf-8 -*-
"""规模分诊层回归测试

对应 2026-11-16 审计发现 #3：分诊正反双向误判
  - 「修一下登录不了的问题」→ 只读（`修复` 不匹配 `修一下`）
  - 「把数据库从 MySQL 换到 PostgreSQL」→ 只读（无 `迁移`）
  - 「统一全站鉴权中间件」→ 只读
  - 「设计一个失败重试机制」→ Bug（`失败` 触发）
  - 「重命名 prefix 变量」→ Bug（`fix` 命中 `prefix`）
  - 「增加异常恢复逻辑」→ Bug（`异常` 触发）

本文件此前完全缺失——分诊层零测试，上述误判永远不会被发现。

运行：
    python -m pytest tests/test_scale_triage.py -v
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import zcode_dev_workflow as wf  # noqa: E402


# ---------------------------------------------------------------------------
# 双向断言：写动作不得判只读，新功能不得判 Bug
# ---------------------------------------------------------------------------

MUST_BE_WRITE = [
    # (输入, 说明) —— 这些明确是改动，不得判只读
    ("修一下登录不了的问题", "修一下 = 修复动作"),
    ("把数据库从 MySQL 换到 PostgreSQL", "换 = 迁移动作"),
    ("统一全站鉴权中间件", "统一 = 改造动作"),
    ("调整首页布局", "调整 = 改动"),
    ("接入支付宝支付", "接入 = 新增集成"),
    ("增加异常恢复逻辑", "增加 = 新功能，非 Bug"),
    ("设计一个失败重试机制", "设计机制 = 新功能，非 Bug"),
    ("重命名 prefix 变量", "重命名 = 重构动作，非 Bug"),
]


@pytest.mark.parametrize("text,why", MUST_BE_WRITE, ids=[t for t, _ in MUST_BE_WRITE])
def test_write_action_not_readonly(text, why):
    """明确的改动请求不得被判为只读。"""
    r = wf.classify_scale(text)
    assert r["scale"] != "readonly", "「%s」被判只读（%s）" % (text, why)


MUST_BE_BUG = [
    "登录接口报错 500",
    "页面崩溃了",
    "支付回调返回异常",
]


@pytest.mark.parametrize("text", MUST_BE_BUG)
def test_real_bug_detected(text):
    """真实故障描述必须判 Bug。"""
    r = wf.classify_scale(text)
    assert r["scale"] == "bug", "「%s」应判 Bug，实际 %s" % (text, r["scale"])


MUST_NOT_BE_BUG = [
    # 这些含 Bug 信号词但是新功能/重构请求
    "增加异常恢复逻辑",
    "设计一个失败重试机制",
    "重命名 prefix 变量",
    "实现错误码统一映射",
    "写一个报错页面",
]


@pytest.mark.parametrize("text", MUST_NOT_BE_BUG)
def test_new_feature_not_misjudged_as_bug(text):
    """含 Bug 信号词的新功能/重构请求不得判 Bug。

    「增加异常恢复逻辑」有「异常」，「设计失败重试机制」有「失败」，
    「重命名 prefix」含 `fix` —— 单靠信号词命中会全部误判成 Bug，
    从而走错整条根因排查流程。
    """
    r = wf.classify_scale(text)
    assert r["scale"] != "bug", "「%s」被误判为 Bug" % text


# ---------------------------------------------------------------------------
# 只读任务仍应正确识别
# ---------------------------------------------------------------------------

READONLY = [
    "分析一下这个模块的架构",
    "解释一下这段代码在做什么",
    "这个方案有什么风险",
    "帮我看看这个设计合理吗",
]


@pytest.mark.parametrize("text", READONLY)
def test_pure_analysis_is_readonly(text):
    r = wf.classify_scale(text)
    assert r["scale"] == "readonly", "「%s」应判只读，实际 %s" % (text, r["scale"])


# ---------------------------------------------------------------------------
# 分诊结果结构契约
# ---------------------------------------------------------------------------

def test_triage_result_shape():
    r = wf.classify_scale("实现用户登录接口", file_count=6)
    for key in ("scale", "label", "reasons", "trim", "ratchet"):
        assert key in r, "分诊结果缺字段 %s" % key
    assert r["ratchet"] == "规模只能升级不能降级"


def test_file_count_drives_scale():
    assert wf.classify_scale("调整文案", file_count=1)["scale"] == "light"
    assert wf.classify_scale("实现登录功能", file_count=8)["scale"] == "medium"
    assert wf.classify_scale("实现登录功能", file_count=20)["scale"] == "large"


def test_empty_input_does_not_crash():
    r = wf.classify_scale("")
    assert r["scale"] in ("readonly", "light")


def test_none_input_does_not_crash():
    r = wf.classify_scale(None)
    assert r["scale"] in ("readonly", "light")
