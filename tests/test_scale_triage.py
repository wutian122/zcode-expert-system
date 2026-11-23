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
    # I-04：「变更」是明确的改动动词，纯名词短语式大任务（数据模型变更）
    # 此前因 WRITE_SIGNALS 缺「变更」判只读，合规跳过 S1-S8 全部门禁。
    ("数据模型变更", "变更 = 改动动作，不得判只读"),
    ("接口变更", "变更 = 改动动作，不得判只读"),
    ("数据库变更", "变更 = 改动动作，不得判只读"),
    # I-N-NEW：执行/运行类复合形态。「搭建/建设」此前已在 FEATURE_CONTEXT
    # （新功能语境表）与 NEW_BUILD_VERBS（能力词守卫）登记，唯主表
    # WRITE_SIGNALS 缺失——与 I-04「变更」同族：语境表/守卫表登记了动词，
    # 主表却缺席，「搭建一个博客系统」「建设一个数据中台」被判只读，
    # 合规跳过 S1-S8 全部门禁（表间一致性校验见 test_p4_consistency.py）。
    ("搭建一个博客系统", "搭建 = 实施动作，不得判只读"),
    ("搭建测试环境", "搭建 = 实施动作，不得判只读"),
    ("建设一个数据中台", "建设 = 实施动作，不得判只读"),
    # 「处理一下/处理下」只收**复合执行形态**（祈使句缓和词「一下/下」）。
    # 裸「处理」刻意不进主表：实测「怎么处理这个报错」（询问语境）会失守。
    ("处理一下这个报错", "处理一下 = 执行动作，不得判只读"),
    # 应急/事件响应是明确的执行任务（处置+复盘+整改），不是只读分析。
    # 刻意不进 HARD_WRITE：「帮我看看这个应急响应预案合理吗」仍须判只读
    # （READONLY_CONTEXT 优先于非硬写信号，见下方守护反例）。
    ("JWT令牌泄漏应急响应处理", "应急响应 = 执行任务，不得判只读"),
    ("线上安全事件响应处置", "事件响应 = 执行任务，不得判只读"),
    # I-2 处置复合形态（遗留-② 最小解）：与「处理一下/处理下」同族。
    # 裸「处置」实测误伤面大（「危废处置资质有哪些」「应急处置预案」），
    # 只收祈使复合形态；裸「处置」句是已知覆盖缺口，见 README 残余风险。
    ("帮我处置一下这个告警", "处置一下 = 执行动作，不得判只读"),
    ("处置一下这个告警", "处置一下 = 执行动作，不得判只读"),
    ("应急处置一下", "处置一下 = 执行动作，不得判只读"),
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
    # R9：「修复+bug」类真实修复请求，无独立故障语境词，应判 Bug。
    # 修复前因 BUG_SIGNALS 与 BUG_CONTEXT 零交集，修复/bug 皆是信号词
    # 无法互相提供独立语境，落 light 漏判。
    "修复登录接口的鉴权 bug",
    "修复 bug",
    "修一下登录报错",
    # I-01：修复 + 新功能混合任务，主诉仍是 Bug 修复，应判 Bug。
    # 此前 R9 通道的 not feature_ctx_hits 限制让「增加」占优误落 light。
    "修复登录接口的鉴权 bug，顺便增加日志采集",
    "修复 bug 并增加日志",
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
    # R9 守护反例：显式修复动词 + 新功能语境 → 不得判 Bug（补救支路需 feature_ctx 拦下）
    "增加修复后的日志采集功能",
    # B-01：「返回500」是含中文+数字的信号词，裸子串匹配会被「返回5000行数据」
    # 命中（「500」紧邻数字「0」，实为「5000」的一部分），不得判 Bug。
    "登录接口返回5000行数据",
    "接口返回5000条记录",
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
    # I-N-NEW 守护反例：新词不得劫持只读评审请求。
    # 「搭建/建设」刻意不进 HARD_WRITE——否则 hard_write_hits 会短路
    # readonly_hits，「帮我看看这个搭建方案合理吗」这类评审请求会误落
    # 实施流程（guard 语句 readonly_hits and not hard_write_hits）。
    "帮我看看这个搭建方案合理吗",
    "帮我看看这个建设方案合理吗",
    # S6 审查 F1 修复（2026-11-23）：README_CN.md「残余风险留档」声称
    # 守护测试锁定「搭建方案是什么」仍 readonly——但本列表此前并无此句，
    # 文档声称的守护覆盖不存在（文档漂移）。按审查路径 (a) 补入：
    # 名词短语「搭建方案」+「是什么」问句，实测判 readonly，零行为风险。
    "搭建方案是什么",
    # 「处理一下/处理下」只收复合执行形态：裸「处理」的询问语境不得被
    # 连带升级为写动作。
    "怎么处理这个报错",
    # 应急/事件响应的名词与预案语境：问流程、评估预案都是只读求理解，
    # 不是「执行应急响应」这个任务本身。
    "事件响应流程是什么",
    "应急响应预案帮我评估一下",
    "应急响应预案是什么",
    # I-2 守护反例（遗留-② 配套）：「处置一下」入表后，裸「处置」的
    # 询问/名词语境不得被连带劫持。「处置这个安全事件」是已知覆盖缺口
    # （裸「处置」误伤面大，本轮不加，见 README 残余风险），此处锁的是
    # 「复合形态修复不得反向劣化这些句子」。
    "危废处置资质有哪些",
    "怎么处置这个告警",
    "处置这个安全事件",
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


# ---------------------------------------------------------------------------
# N-03：零宽/不可见字符不得绕过信号词匹配
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "修​复登录 bug",      # ZWSP 拆开「修复」
    "修﻿复登录 bug",      # BOM
    "修­复登录 bug",      # 软连字符
    "​修复登录 bug",      # 前置零宽
])
def test_zero_width_chars_do_not_bypass_bug_detection(text):
    """N-03：零宽字符插入信号词中间时，不得绕过 Bug 判定。

    修前：「修\\u200b复登录 bug」因「修复」被切成「修」「复」，
    写动作信号漏判 → 误落 readonly，整条根因流程被跳过。
    """
    r = wf.classify_scale(text)
    assert r["scale"] == "bug", (
        "零宽字符绕过了 Bug 判定：「%r」实际 %s" % (text, r["scale"]))
