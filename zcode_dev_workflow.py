#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
ZCode Dev Workflow —— 规模轴分诊 + 状态机 + 派发计划

与 zcode_expert_system.py 的分工（两轴正交）：

    zcode_expert_system.py  →  域轴：派哪一位专家（32 类 → 331 专家）
    zcode_dev_workflow.py   →  规模轴：走不走流程、走多长（只读/轻量/中/大/Bug）

先规模后域：规模决定阶段裁剪，域决定 subagent_type。

唯一声明源：config/workflow.json。本模块不自带任何阶段/门禁常量，
全部从声明源读取，避免文档与实现漂移。

命令行用法：
    python zcode_dev_workflow.py triage "<任务描述>" [--files N] [--json]
    python zcode_dev_workflow.py stages <scale>
    python zcode_dev_workflow.py plan "<任务描述>" [--files N]
    python zcode_dev_workflow.py states
    python zcode_dev_workflow.py transition <from> <to>
"""

import io
import json
import os
import re
import sys
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WORKFLOW_PATH = os.path.join(BASE_DIR, "config", "workflow.json")


def _qualified_subagent_type(expert_name):
    """按运行平台决定子代理派发名。

    Claude Code 要求 <插件名>:<frontmatter.name> 的限定形式；
    ZCode 使用中文裸名。用 CLAUDE_PLUGIN_ROOT 是否注入作判据。

    与 zcode_expert_system.py 的同名函数保持同构（两处各自独立定义，
    测试互不依赖；改口径时须同步两处，tests/test_semantic_selection.py
    的 test_qualified_subagent_type_by_platform 会锁住 zcode_expert_system
    侧的行为）。

    expert_name 为 None/空（域路由降级）时原样返回，由调用方的降级分支
    处理（general-purpose 等内置类型不带插件前缀）。
    """
    if not expert_name:
        return expert_name
    if os.environ.get("CLAUDE_PLUGIN_ROOT"):
        return "zcode-expert-system:%s" % expert_name
    return expert_name


def _force_utf8_stdout():
    """让 stdout/stderr 用 UTF-8 输出，避免非 UTF-8 控制台抛 UnicodeEncodeError。

    背景（缺陷 #3）：中文 Windows 默认代码页 CP936 可编码 GB2312 汉字，但无法编码
    emoji（⚙️ U+2699）与 ⇒(U+21D2)、❌(U+274C) 之类的符号——而这些都是
    config/experts.json 与 config/workflow.json 里的真实数据。于是
    `print(json.dumps(..., ensure_ascii=False))` 在 CP936 终端直接抛异常、
    命令 rc=1、stdout 全空。表现像「工具坏了」，实为编码问题。

    为什么不改 ensure_ascii=True：那会把所有中文转成 \\uXXXX，破坏中文可读性，
    也会让按中文字面断言的下游（测试与消费方）失效。

    为什么 errors="replace" 只作兜底：它是「实在重配不了」时的最后手段。
    正常情况下 reconfigure 成功，UTF-8 终端按 UTF-8 解码，emoji 与中文完整保留。
    若把 replace 当主手段，符号会变成 "?"——rc 虽然变 0，但数据被悄悄损坏，
    比崩溃更难发现（tests/test_cli_encoding.py::test_emoji_preserved_not_replaced
    专门盯这一点）。

    幂等：重复调用无副作用（reconfigure 可重复执行）。
    """
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            # Python < 3.7 或已被重定向为不支持 reconfigure 的对象：保持原状。
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            # 已 detach / 已关闭 / 被替换成非标准流的场景：不影响主流程。
            pass


# ---------------------------------------------------------------------------
# 声明源加载
# ---------------------------------------------------------------------------

def load_workflow(path=None):
    """读取唯一声明源 config/workflow.json。缺失即抛错，不静默降级。"""
    p = path or WORKFLOW_PATH
    with io.open(p, "r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# 规模分诊
# ---------------------------------------------------------------------------

# Bug 信号词：**仅当同时存在「故障语境」时才判 Bug**（见 BUG_CONTEXT）。
# 单靠信号词命中会把「增加异常恢复逻辑」「设计失败重试机制」「重命名 prefix」
# 全部误判成 Bug，从而走错整条根因排查流程。
#
# 本表是「可能是 Bug 的线索」，不是「出现即 Bug」。判 Bug 需要另一个不同词
# 提供语境——**不允许同一个词自我满足**（见 classify_scale 的 self_satisfied 剔除）。
BUG_SIGNALS = (
    "bug", "缺陷", "报错", "异常", "崩溃", "闪退", "失败", "不工作", "没反应",
    "无法", "不能", "错误", "修复", "排查", "故障", "内存泄漏", "死锁",
    "regression", "crash", "error", "broken", "fix",
    # 纯现象陈述（口语/运维常用）
    "挂了", "超时", "白屏", "不恢复", "卡死", "卡住", "宕机",
    "5xx", "返回500", "返回 500",
)

# 故障语境标记：描述的是「已发生的坏行为」，而不是「要做的新东西」。
#
# **本表不得与 BUG_SIGNALS 有交集**（除 PHENOMENON_WORDS 走旁证通道外）：
# 交集会让同一个词自我满足「信号 + 语境共现」，条件自己就成立了。
# P6 之前的实现正是这样（`失败`/`无法`/`不能` 同时在两表），
# 导致「统计失败率」「失败回调处理」被判 Bug。
#
# 所以本表刻意只放**纯语境词**——它们本身不是 Bug 信号，
# 只用来给信号词提供「已发生坏行为」的旁证。
BUG_CONTEXT = (
    # 现状描述
    "为什么", "怎么回事", "怎么办", "老是", "总是", "一直", "忽然", "突然",
    "偶发", "复现", "重现", "抛出", "抛出异常", "返回", "卡住", "卡死",
    "崩溃了", "报错了", "失败了", "不生效", "不工作", "没反应",
    "500", "502", "503", "504", "timeout", "异常了", "有 bug",
    # 排查动作（明确指向已存在的问题）
    "排查", "定位", "根因", "为什么报",
)

# 否定语境：这些词把「Bug 信号词」变成「要做的新功能」
FEATURE_CONTEXT = (
    "设计", "实现", "增加", "新增", "添加", "开发", "重命名", "重构",
    "统一", "规划", "写一个", "写个", "做一个", "做个", "搭建", "建设",
    "机制", "策略", "规则", "流程", "页面", "模块", "功能",
)

# 只读信号：请求不含任何写动作
WRITE_SIGNALS = (
    # 基础改动动词
    "改", "加", "创建", "新建", "删除", "移除", "修复", "实现", "开发",
    "写", "重构", "优化", "迁移", "升级", "替换", "接入", "配置",
    # I-04：单字改动动词「变更/改变」。此前缺失导致「数据模型变更」
    # /「接口变更」这类纯名词短语式改动被判只读，进而合规跳过 S1-S8
    # 全部门禁（无账本、无 FAIL 可查）。对照「修改数据模型」能判 large。
    "变更", "改变",
    # 设计/规划类（中文语境下「设计一个 X」几乎总是要落地实现，
    # 纯只读分析会说「分析/解释/评估/看看」，不会说「设计一个」）
    "设计", "规划", "方案设计", "起草", "制定",
    # 口语化改动（原来缺失导致「修一下」「换到」被判只读）
    "修一下", "修下", "改一下", "改下", "调整", "换到", "换成", "替换成",
    "统一", "对齐", "拆分", "合并", "抽取", "封装", "补上", "补齐", "加上",
    "联通", "打通", "上线", "部署", "回滚", "覆盖", "重写",
    # 结构/命名类重构
    "重命名", "改名", "挪", "拆", "并", "抽",
    # 执行/运行类（「训练一个模型」「微调」「跑一次」都是动手做事，不是只读分析）
    "训练", "微调", "跑一次", "跑一下", "执行", "运行", "编译", "构建",
    "生成", "导出", "导入", "批量处理", "清洗",
    # I-N-NEW：搭建/建设此前只在 FEATURE_CONTEXT（:141 新功能语境）与
    # NEW_BUILD_VERBS（能力词守卫）登记，唯本主表缺失——「搭建一个博客系统」
    # 「建设一个数据中台」被判只读，合规跳过 S1-S8 全部门禁。与 I-04「变更」
    # 同族：语境表/守卫表登记了动词、主表缺席（表间一致性校验已固化于
    # test_p4_consistency.py，再缺主表必红）。刻意**不进 HARD_WRITE**：
    # 「帮我看看这个搭建方案合理吗」是评审请求，HARD_WRITE 会短路
    # readonly_hits 让它误落实施流程（守护反例已固化）。
    "搭建", "建设",
    # 「处理一下/处理下」只收**复合执行形态**（祈使句缓和词）。裸「处理」
    # 刻意不加：实测「怎么处理这个报错」（询问）会失守；「异常处理」
    # （名词语境）同。应急/事件响应是明确的执行任务（处置+复盘+整改），
    # 同样刻意不进 HARD_WRITE（「应急响应预案帮我评估一下」须保持只读）。
    "处理一下", "处理下", "应急响应", "事件响应",
    # I-2 处置复合形态（遗留-② 最小解）：与「处理一下/处理下」同族。
    # 裸「处置」实测误伤面大（「危废处置资质有哪些」名词语境、「怎么处置
    # 这个告警」询问语境），只收祈使复合形态；裸「处置」句是已知覆盖
    # 缺口（见 README 残余风险），守护反例已固化于 test_scale_triage.py。
    "处置一下", "处置下",
)

# 新建类动词守卫表：能力词（无法/不能）+ 本表动词共现 → 「要新增东西」，
# 不算故障陈述（「增加无法登录时的提示」）。I-1 提升为模块级：
# 一致性校验（test_p4_consistency.py）要求本表实施动词必须在 WRITE_SIGNALS
# 有登记（或显式豁免留档）——此前「搭建」在本表而主表缺席，
# 「搭建一个博客系统」误判只读，整条门禁链被合规跳过。
# 本表补「建设」：原表只有「搭建」，与 FEATURE_CONTEXT 不对称；
# 行为上只影响「无法…建设」的守卫覆盖（新功能方向，保守无实害）。
NEW_BUILD_VERBS = ("增加", "新增", "添加", "实现", "设计", "开发",
                   "做一个", "做个", "写一个", "写个", "搭建", "建设")

# 只读语境标记：明确的「只求理解、不求改动」表述。
# 出现这些词时，即使含「设计/方案/架构」等名词也判只读——
# 「帮我看看这个设计合理吗」是评审请求，不是实现请求。
READONLY_CONTEXT = (
    "分析", "解释", "说明", "评估", "审查", "评审", "看看", "看一下", "看下",
    "合理吗", "有没有问题", "有什么风险", "怎么理解", "是什么", "为什么",
    "对比", "比较", "调研", "排查一下原因", "诊断", "审计",
)

# 解释/科普意图：这些任务在「讲一个概念」，不是「修一个故障」。
# 用途仅限规模轴：抑制「纯现象陈述」单独成案，避免
# 「说明 Bug/失败 的判定」被判成 Bug 修复。
EXPLAIN_INTENT_WORDS = (
    "说明", "解释", "介绍", "科普", "对比", "是什么", "区别", "定义",
    "含义", "只读", "讲解", "怎么理解",
)

# 成对引号：引号内的短标签/名词通常是「被讨论的对象」，不是任务信号。
# 例如「说明 "Bug/失败" 的判定」里的 Bug/失败 是标签枚举。
META_QUOTE_PAIRS = (
    ('"', '"'), ("'", "'"), ("“", "”"), ("‘", "’"),
    ("「", "」"), ("『", "』"), ("《", "》"), ("`", "`"),
)
# 引号内若含实施动词，说明它是真实任务对象（如「修复「登录页」白屏」），
# 不得剥离——否则会把真正的故障对象一起清掉。
META_PROTECT_VERBS = (
    "修复", "修一下", "修下", "实现", "增加", "新增", "添加", "删除",
    "修改", "调整", "改", "写", "做", "搭建", "建设",
)

# 大任务信号：即使文件数少也升级
LARGE_SIGNALS = (
    "架构", "数据模型", "公共 api", "公共接口", "跨模块", "底层",
    "并发模型", "认证体系", "权限模型", "数据库迁移", "领域模型",
)

# 强故障标记：出现即无条件判 Bug（描述的就是坏现状）。
#
# 本表只放**无可歧义的完成态词**（`崩溃了`/`报错了`/`失败了`/`500`…）。
# 不放**可作名词/配置项的开放词**（`超时`/`白屏`/`挂了`/`闪退`/`失败`）——
# 那些是「现象词」，归 PHENOMENON_WORDS，见下方说明。
#
# **`无法` / `不能` 已移出本表**（缺陷 #9）：它们是「能力缺失」描述，
# 在新功能需求里出现频率高于故障报告
# （「增加无法登录时的提示」「实现一个不能重复提交的表单校验」）。
# 留在强故障表意味着：只要出现这两个词，「新功能语境占优」守卫就被
# `strong_hits` 自己抵消，守卫形同不存在。
STRONG_BUG = ("崩溃了", "报错了", "失败了", "不生效", "不工作", "没反应",
              "内存泄漏", "死锁", "500", "502", "503", "504",
              "为什么报", "老是", "总是", "一直", "偶发", "复现", "重现",
              "排查", "定位", "根因", "不恢复")

# 现象词：**既可作故障描述，也可作名词/配置项**。
#
# 这是 P6 修复的核心（复核审查发现 17/17 条正常需求被误判为 Bug）：
#   `超时` → 「设置请求超时时间为 30 秒」是配置项名，不是故障
#   `白屏` → 「白屏日志采集模块」是模块名
#   `闪退` → 「闪退率统计报表」是统计项
#   `挂了` → 「挂了自动重启策略」是策略名
#   `失败` → 「统计失败率」「失败回调处理」
#
# 判定规则：现象词单独出现**不足以**判 Bug，必须另有**完成态标记**或
# **具体故障语境**（见 PHENOMENON_FAILURE_MARKERS）。
# 把它们放进 STRONG_BUG（出现即判 Bug）会与「信号词 + 语境共现」形成自证：
# 同一个词同时是信号和语境，条件自己就满足了。
PHENOMENON_WORDS = ("挂了", "超时", "白屏", "闪退", "卡死", "卡住", "宕机",
                    "失败", "无法", "不能")

# 现象词要判 Bug，需要一个「确实已经坏了」的旁证。
#
# 两组标记的区别：
#   - 完成态后缀（`了`）：`页面白屏了` / `服务挂了` / `登录失败了`
#   - 持续/重复态（`一直`/`老是`/`总是`/`反复`）：`内存一直涨` / `一直不恢复`
#   - 故障主语（`生产`/`线上`/`接口`/`页面` + 现象词）：本机实测这些主语
#     与现象词的组合基本都是真故障报告，而不是配置动作
#
# 反面样本（必须不判 Bug）：`设置请求超时时间为 30 秒`（无完成态、有配置动词）、
# `超时重试机制`（纯名词）、`统计失败率`（统计动词 + 名词）。
PHENOMENON_FAILURE_MARKERS = (
    "了",            # 完成态：白屏了 / 挂了 / 失败了 / 超时了
    "一直", "老是", "总是", "反复", "持续", "不断",
    "不恢复", "无法恢复", "不可用", "连不上", "打不开",
)


# ---------------------------------------------------------------------------
# 信号词匹配纪律（P8 批次二 Task 5，对齐 zcode_expert_system._keyword_hits）
#
# 为什么不用 \b：Python3 的 \w 把汉字算作词字符，「返回5xx错误」里 `5xx`
# 紧邻汉字时 \b 判定失败——整词匹配会漏掉最常见的中文夹写。
# 这里手工判边界：命中位前一字符与后一字符不得是 [a-z0-9_]
# （汉字/空白/`-`/`.`/`+`/`#` 都算边界——`regression-test` 的 regression
# 仍算独立词，`接口返回500` 的 500 紧邻「回」也仍命中）。
# ---------------------------------------------------------------------------

_ASCII_WORD_CHARS = set("abcdefghijklmnopqrstuvwxyz0123456789_")


def _is_ascii_word(signal):
    """纯 ASCII 词（含 5xx 这类数字词）走整词匹配；含中文的词走子串。"""
    return all(ch.lower() in _ASCII_WORD_CHARS for ch in signal)


def _word_hit(signal, text):
    """信号词命中：ASCII 词整词、中文词子串（尾部数字段做边界）。

    修的破坏（裸子串 `s in text`）：`bug` 命中 de**bug**、`fix` 命中
    **fix**ture、`error` 命中 **error**s、STRONG_BUG 的 `500` 命中 **500**0——
    再叠加独立语境词就凑齐「信号 + 语境共现」，把正常需求判成 Bug。
    B-01：「返回500」尾部数字段被「返回5000」命中——中文词尾部数字段
    后不得紧跟数字（属更长数字串的一部分）。
    大小写维持既有行为：text 已在调用方 lower()，信号词本身全小写。
    """
    if not _is_ascii_word(signal):
        return _chinese_word_hit(signal, text)
    start = text.find(signal)
    n = len(signal)
    while start != -1:
        prev_ch = text[start - 1] if start > 0 else ""
        next_ch = text[start + n] if start + n < len(text) else ""
        if (prev_ch.lower() not in _ASCII_WORD_CHARS
                and next_ch.lower() not in _ASCII_WORD_CHARS):
            return True
        start = text.find(signal, start + 1)
    return False


def _chinese_word_hit(signal, text):
    """含中文信号词的子串匹配，尾部数字段做边界检查。

    修 B-01：「返回500」尾部数字段「500」，文本「返回5000行数据」中
    「500」后紧跟数字「0」，属「5000」的一部分，不得命中；而
    「接口返回500错误」中「500」后是「错」（非数字），仍命中。
    含中文且无数字尾部的词（如「修复」「异常」）维持裸子串，不受影响。
    """
    start = text.find(signal)
    while start != -1:
        n = len(signal)
        next_ch = text[start + n] if start + n < len(text) else ""
        if re.search(r'[0-9]+$', signal) and next_ch.isdigit():
            # 信号词以数字结尾且命中位置后紧跟数字 → 属更长数字串的一部分
            start = text.find(signal, start + 1)
            continue
        return True
    return False


def _is_explain_intent(text):
    """任务是否在解释/说明一个概念，而不是修复一个故障。"""
    return any(w in (text or "") for w in EXPLAIN_INTENT_WORDS)


def _strip_meta_spans(text):
    """剥离「被讨论的短标签」：引号内 ≤12 字且不含实施动词时替换为空格。

    真实故障对象会带实施动词（`修复「登录页」白屏`），因此保留；
    `说明 “Bug/失败” 的判定` 里的标签枚举会被清掉。
    代码块整体视为示例，不参与规模信号。
    """
    t = text or ""
    t = re.sub(r"```.*?```", " ", t, flags=re.S)
    for left, right in META_QUOTE_PAIRS:
        pattern = re.compile(
            re.escape(left) + r"([^" + re.escape(right) + r"\n]{1,12})"
            + re.escape(right)
        )

        def repl(m):
            inner = m.group(1)
            if any(v in inner for v in META_PROTECT_VERBS):
                return m.group(0)
            return " "

        t = pattern.sub(repl, t)
    return t


def classify_scale(task_description, file_count=None):
    """规模轴分诊。

    返回 dict：
      scale        只读/轻量/中任务/大任务/Bug 之一（英文键）
      label        中文显示名
      reasons      判定依据列表（必须可复核）
      trim         该规模的阶段裁剪表
      min_gates    该规模的最少门禁清单

    判定顺序（不可颠倒）：
      1. Bug 优先——Bug 有专门的根因流程，规模判定会让它走错路径
      2. 只读——无写动作则直接结束，不进入工程流程
      3. 大任务——架构级信号优先于文件数
      4. 中/轻量——按文件数
    """
    text = (task_description or "").lower()
    # N-03：清洗零宽/不可见字符后再匹配。「修​复登录 bug」中零宽空格
    # 把「修复」切成「修」「复」，导致写动作信号漏判、Bug 被误落只读。
    # 覆盖 ZWSP/ZWJ/ZWNJ/LRM/RLM/BOM/软连字符等常见不可见字符。
    text = re.sub(r"[​-‏⁠-⁤﻿­]", "", text)
    text = _strip_meta_spans(text)
    wf = load_workflow()
    scales = wf["scale"]
    reasons = []

    # --- 1. Bug 判定：信号词 + **独立的**故障语境 ---
    #
    # 两道门槛必须由**不同词**满足。只靠 BUG_SIGNALS 命中会误判新功能请求
    # （「增加异常恢复逻辑」「设计失败重试机制」「重命名 prefix」）；
    # 但若同一个词同时充当「信号」与「语境」，条件就自我满足了。
    #
    # 这正是 P6 复核审查发现的 17/17 误判的结构性根因：
    #   `超时` 同时在两张表 → 「超时重试机制」「统计失败率」全部判 Bug。
    #
    # 修法有两层：
    #   ① 自证剔除：既在 bug_hits 又在 ctx/strong 里的**同一词**剔掉，
    #      要求由另一个词提供语境；
    #   ② 现象词需旁证：`挂了`/`超时`/`白屏`/`闪退` 这类可作名词/配置项的
    #      开放词，必须有完成态或持续态标记（`了`/`一直`/`不恢复`…）才算故障。
    # 五张表统一走 _word_hit（Task 5 同根因不留半成品）：BUG_SIGNALS/BUG_CONTEXT/
    # STRONG_BUG 含 ASCII 词（bug/fix/error/500/timeout…），裸子串会在
    # debug/fixture/errors/5000 上误命中。
    bug_hits = [s for s in BUG_SIGNALS if _word_hit(s, text)]
    bug_ctx_hits = [s for s in BUG_CONTEXT if _word_hit(s, text)]
    feature_ctx_hits = [s for s in FEATURE_CONTEXT if _word_hit(s, text)]
    strong_hits = [s for s in STRONG_BUG if _word_hit(s, text)]
    phenomenon_hits = [s for s in PHENOMENON_WORDS if _word_hit(s, text)]

    independent_ctx = [s for s in bug_ctx_hits if s not in bug_hits]
    independent_strong = [s for s in strong_hits if s not in bug_hits]
    explain_intent = _is_explain_intent(text)

    # 现象词的判据（三层，见 _has_failure_marker / _phenomenon_as_nominal）：
    #   ① 有完成态/持续态旁证 → 算故障（`页面白屏了`）
    #   ② 现象词被用作名词/配置项 → **不算**故障（`超时重试机制`）
    #   ③ 都不成立时按陈述句处理 → 算故障（`登录失败`、`无法登录`）
    phenomenon_nominal = _phenomenon_as_nominal(text)
    phenomenon_backed = ([s for s in phenomenon_hits
                          if not phenomenon_nominal and _has_failure_marker(text)]
                         if phenomenon_hits else [])

    # 能力词（`无法`/`不能`）在新功能语境下不算故障。
    #
    # 「增加无法登录时的提示」「实现一个不能重复提交的表单校验」——
    # 这两句的主诉是**要新增东西**，`无法/不能` 只是在描述要新增的校验规则。
    # 而「无法登录模块」「不能提交的流程」没有新建动词（`模块`/`流程` 只是
    # 名词尾巴，不是「增加/实现/设计」这类动作），主诉仍是故障。
    #
    # 判据：能力词 + **新建类**动词 → 不算故障。
    # 只认新建/设计类动词，不认 `模块`/`流程`/`功能` 这类纯名词。
    ABILITY_WORDS = ("无法", "不能")
    # NEW_BUILD_VERBS 已提升为模块级常量（原为函数局部）：
    # 供 test_p4_consistency.py 的表间一致性校验锚定——它是守卫表，
    # 与 WRITE_SIGNALS 主表的成员对应关系必须有测试盯住（I-N-NEW 缺陷）。
    ability_hits = [w for w in ABILITY_WORDS if w in text]
    # 能力词 + 新建动词 → 新功能需求
    if ability_hits and any(v in text for v in NEW_BUILD_VERBS):
        phenomenon_backed = [s for s in phenomenon_backed if s not in ability_hits]
    # 能力词 + 「功能/校验/规则/逻辑/页面/模块」结尾，且能力词后跟长定语
    # （≥4 字）→ 是「某个规则的描述」，不是故障陈述。
    #   例：`不能同时上传两个文件的校验功能`（能力词后 10 字定语 + 「功能」）
    #   反例：`无法登录模块`（能力词后 2 字 `登录` + 「模块」）→ 仍判故障
    elif ability_hits and re.search(
            r"(?:无法|不能).{4,}?(?:功能|校验|规则|逻辑|页面|模块|流程)\s*$", text):
        phenomenon_backed = [s for s in phenomenon_backed if s not in ability_hits]

    if bug_hits and (
            independent_ctx
            or independent_strong
            or (phenomenon_backed and not explain_intent)):
        # 新功能语境占优且无独立强故障/无旁证 → 不判 Bug，按改动处理。
        if feature_ctx_hits and not (independent_strong or phenomenon_backed):
            reasons.append(
                "含 Bug 信号词（%s）但语境是新功能（%s），不判 Bug"
                % ("、".join(bug_hits[:3]), "、".join(feature_ctx_hits[:3]))
            )
        else:
            reasons.append("命中 Bug 信号词：%s" % "、".join(bug_hits[:5]))
            if independent_ctx:
                reasons.append("命中独立故障语境：%s" % "、".join(independent_ctx[:4]))
            if phenomenon_backed and not independent_ctx:
                reasons.append(
                    "现象词有故障旁证（%s）→ 判 Bug" % "、".join(phenomenon_backed[:3]))
            return _build("bug", scales, wf, reasons)

    # --- 1a（补救支路，R9）：显式修复动作 + 故障信号词，且无新功能语境 ---
    #
    # BUG_CONTEXT 与 BUG_SIGNALS 刻意零交集（P6 防自证），导致
    # 「修复登录接口的鉴权 bug」这类句子：bug/修复 皆是信号词，
    # 句中却无独立语境词（为什么/卡死/500...），走不到 :348 的
    # 门槛，误落 light，根因排查链路丢失。
    #
    # 此处补一条跨表通道：显式修复动词与信号词共现 → 判 Bug。不动
    # BUG_SIGNALS / BUG_CONTEXT 两表，保持零交集；只由修复类动词与
    # bug_hits 共同触发，避免单一词自证。
    #
    # I-01：语境判定改为「位置优先」而非「无新功能语境」。
    #   「修复登录接口的鉴权 bug，顺便增加日志采集」——修复动词在前、
    #   增加在后（次要从句），主诉是 Bug 修复 → 判 Bug。
    #   「增加修复后的日志采集功能」——增加在前（主诉）、修复在后
    #   （定语），主诉是新功能 → 维持 feature_ctx 拦截，不判 Bug。
    HARD_FIX_WORDS = ("修复", "修一下", "修下", "改修", "bugfix",
                      "hotfix", "补丁", "打补丁")
    fix_hits = [w for w in HARD_FIX_WORDS if w in text]
    # 位置优先：新功能动词出现在修复动词之前 → 主诉是新功能，拦截判 Bug
    feature_first = False
    if feature_ctx_hits and fix_hits:
        fix_pos = min(text.find(w) for w in fix_hits if text.find(w) != -1)
        feat_pos = min(text.find(v) for v in feature_ctx_hits if text.find(v) != -1)
        feature_first = feat_pos < fix_pos
    if fix_hits and bug_hits and not feature_first:
        # 自证剔除：`修复` 本身既是修复动作又是 BUG_SIGNALS 成员，
        # 不能自己给自己提供「故障信号」。必须存在第二个故障信号
        # （如 bug / 失败 / 报错），否则「修复 README 错别字」会被误判 Bug。
        other_bug_hits = [s for s in bug_hits if s not in fix_hits]
        if other_bug_hits:
            reasons.append(
                "命中显式修复动作（%s）与故障信号（%s）→ 判 Bug"
                % ("、".join(fix_hits[:3]), "、".join(other_bug_hits[:3]))
            )
            return _build("bug", scales, wf, reasons)

    # --- 1b. 纯现象陈述：有强故障词/有旁证的现象词，且无新功能语境 ---
    #
    # 这一支补的是「信号词/语境词都没命中，但描述明显是坏现状」的缺口。
    # 例：「内存一直涨」「线上 502 一直不恢复」——一个写动作词都没有，
    # 若走到下面第 2 步就会被判只读，整条根因流程被跳过。
    #
    # 判据保守：必须命中 STRONG_BUG（无可歧义的完成态词），或
    # 现象词 + 故障旁证；且不得有新功能语境。
    pure_signal = strong_hits or phenomenon_backed
    if pure_signal and not feature_ctx_hits and not explain_intent:
        reasons.append(
            "纯现象陈述：命中强故障词/现象旁证（%s）且无新功能语境 → 判 Bug"
            % "、".join(sorted(set(strong_hits + phenomenon_backed))[:4])
        )
        return _build("bug", scales, wf, reasons)
    if pure_signal and feature_ctx_hits:
        reasons.append(
            "命中强故障词/现象旁证（%s），但与新功能语境（%s）并存 → 不判 Bug"
            % ("、".join(sorted(set(strong_hits + phenomenon_backed))[:3]),
               "、".join(feature_ctx_hits[:3]))
        )

    # --- 2. 只读判定 ---
    #
    # 只读语境优先：含「分析/解释/看看/合理吗/有什么风险」等纯理解型表述时，
    # 即使出现「设计/方案/架构」这类名词也判只读——
    # 「帮我看看这个设计合理吗」是评审请求，不是实现请求。
    # 例外：同时含明确写动作（实现/改/加/重构…）时仍按改动处理。
    readonly_hits = [s for s in READONLY_CONTEXT if s in text]
    write_hits = [s for s in WRITE_SIGNALS if s in text]
    HARD_WRITE = ("实现", "开发", "重构", "改", "加", "创建", "新建", "删除",
                  "修复", "迁移", "升级", "替换", "接入", "配置", "写")
    hard_write_hits = [s for s in HARD_WRITE if s in text]
    # 解释意图只抑制「被解释的动词」，不能吞掉真正的实施动作。
    # 位置优先：`说明修复流程`（说明在前 → 只读） vs
    # `修改登录逻辑，并解释原因`（修改在前 → 仍是写任务）。
    explain_pos = min((text.find(w) for w in EXPLAIN_INTENT_WORDS
                       if text.find(w) != -1), default=None)
    hard_pos = min((text.find(w) for w in hard_write_hits
                    if text.find(w) != -1), default=None)
    explain_only = (
        explain_intent
        and (hard_pos is None or (explain_pos is not None and explain_pos < hard_pos))
    )
    effective_hard_write = [] if explain_only else hard_write_hits

    if readonly_hits and not effective_hard_write:
        reasons.append(
            "只读语境（%s）且无硬写动作 → 判只读"
            % "、".join(readonly_hits[:3])
        )
        return _build("readonly", scales, wf, reasons)
    if not write_hits:
        reasons.append("未命中任何写动作信号（改/加/创建/修复/实现/优化…）")
        return _build("readonly", scales, wf, reasons)

    # --- 3. 大任务 ---
    large_hits = [s for s in LARGE_SIGNALS if s in text]
    if large_hits:
        reasons.append("命中架构级信号：%s" % "、".join(large_hits[:5]))
        return _build("large", scales, wf, reasons)
    if file_count is not None and file_count >= scales["large"]["min_files"]:
        reasons.append("文件数 %d ≥ %d" % (file_count, scales["large"]["min_files"]))
        return _build("large", scales, wf, reasons)

    # --- 4. 中任务 / 轻量 ---
    if file_count is not None:
        if file_count <= scales["light"]["max_files"]:
            reasons.append("文件数 %d ≤ %d，且无架构级信号" % (file_count, scales["light"]["max_files"]))
            return _build("light", scales, wf, reasons)
        reasons.append("文件数 %d 落在 %d-%d 区间" % (
            file_count, scales["medium"]["min_files"], scales["medium"]["max_files"]))
        return _build("medium", scales, wf, reasons)

    # 无文件数：按描述中的多模块信号推断
    multi = [s for s in ("模块", "前端", "后端", "数据库", "接口", "服务", "组件") if s in text]
    if len(multi) >= 2:
        reasons.append("描述涉及多模块（%s），无文件数时保守判为中任务" % "、".join(multi[:4]))
        return _build("medium", scales, wf, reasons)

    reasons.append("未提供文件数且未命中多模块信号，按轻量处理（保守起点，可升级不可降级）")
    return _build("light", scales, wf, reasons)


def _has_failure_marker(text):
    """现象词是否以「故障陈述」形态出现（而非名词/配置项）。

    现象词（`挂了`/`超时`/`白屏`/`闪退`/`失败`/`无法`/`不能`）在中文里
    既可描述故障，也可作名词/配置项名。三档判据：

      ① 完整态/持续态旁证 → 是故障
         `页面白屏**了**` / `内存**一直**涨` / `502 **一直不恢复**`
      ② 「无法/不能 + 非空内容」→ 是故障（X 无法 Y ＝ 能力缺失陈述）
         `无法登录` / `无法登录模块` / `不能提交的流程`
      ③ 其余情况：**只要现象词没被名词化，就按陈述句处理**
         `登录失败` / `支付回调超时` → 故障
         `超时重试机制` / `统计失败率` → 名词化，非故障（交给
         `_phenomenon_as_nominal` 排除）

    第 ③ 条的偏置是刻意的：漏判只读 → 多走一趟流程；
    误判 Bug → 让人去查不存在的根因。后者代价更高，所以不确定时
    倾向于判 Bug。名词化排除法给了「非故障」一条明确出口。
    """
    t = (text or "")
    # ① 完整态/持续态
    if any(m in t for m in PHENOMENON_FAILURE_MARKERS):
        return True
    # ② 无法/不能 + 非空（X 无法 Y ＝ 能力缺失陈述）
    if _ends_with_phenomenon(t):
        return True
    # ③ 未被名词化的**非能力词**现象词 → 按陈述处理。
    #
    # 注意这里**排除 `无法`/`不能`**：它们是「能力缺失」，单独出现时
    # 在新功能需求里更常见（「增加无法登录时的提示」）。它们只走第 ② 档：
    # 必须构成「X 无法 Y」这种带主语的陈述才算故障。
    # 初版把 `无法`/`不能` 也算进第 ③ 档，导致三条新功能需求被判 Bug。
    ABILITY_WORDS = ("无法", "不能")
    remaining = [w for w in PHENOMENON_WORDS if w not in ABILITY_WORDS]
    return any(word in t for word in remaining)


def _ends_with_phenomenon(text):
    """现象词是否以「陈述」形态出现（而非纯名词短语）。

    `登录失败` → True（陈述句，故障报告）
    `统计失败率` → False（后面跟名词 `率`，由 _phenomenon_as_nominal 拦截）
    `无法登录` → True（「无法 + 动词」＝能力缺失陈述）
    `无法登录模块` → True（功能名词不改变主诉）

    实现上不做复杂的词性判断，只回答一个问题：
    **有没有以「无法/不能 + 非空后缀」的形式出现**。
    这类「X 无法 Y」结构在中文里几乎总是故障陈述，不是名词短语。
    """
    t = (text or "").rstrip(" \t\r\n。！？.!?，,；;")
    if not t:
        return False
    for word in ("无法", "不能"):
        idx = t.find(word)
        if idx >= 0:
            after = t[idx + len(word):].lstrip(" \t的")
            if after:            # 「无法」后面还有内容 → X 无法 Y，是陈述
                return True
    return False


def _phenomenon_as_nominal(text):
    """现象词是否被用作**名词/配置项**（而非故障陈述）。

    判据：现象词后面紧跟名词化尾巴，**且该现象词自身不带完成态**。

    最后那个条件很关键：`挂了自动重启策略` 里 `挂了` 已经带完成态后缀
    「了」，它描述的是「已经挂了」这个事实，即使后面跟「策略」也仍是故障陈述。
    初版只看「后面跟名词尾巴」就判名词化，把这条误判成了非故障。

    这条偏置方向的理由：漏判只读 → 多走一趟流程；
    误判 Bug → 让人去查一个不存在的根因。后者代价更高。
    """
    NOMINAL_TAILS = (
        "率", "回调", "机制", "策略", "设置", "配置", "页面", "模块",
        "报表", "日志", "方案", "功能", "提示", "处理", "优化", "采集",
        "监控", "统计", "样式", "流程", "参数", "选项", "开关", "代码",
        "字段", "接口", "文档", "说明", "列表", "表单", "组件", "库",
        # 复合名词尾巴：`超时` + `重试机制` 中 `after` 以「重试」开头，
        # 单靠「机制」匹配不上，所以补常见复合前缀。
        # 刻意**不含**「自动/恢复」——那会让「挂了自动重启」被排除，
        # 而它其实是「已经挂了，需要自动重启」的故障响应需求。
        "重试", "上报", "埋点", "告警", "分析", "校验",
        "时时间", "时长", "阈值", "上限", "下限",
        # 元语言名词：`失败场景` / `Bug 与失败的区别` / `失败的判定标准`
        # 是在讨论概念，不是故障陈述。
        "场景", "用例", "分类", "类型", "枚举", "区别", "定义",
        "含义", "说明", "判定",
        # 配置谓词：`超时时间为 30 秒` —— `超时` 后跟「时间」再跟「为」，
        # 属于「设置某个值」的表述，不是故障。
        "时间", "秒", "毫秒", "分钟",
    )
    t = (text or "")
    for word in PHENOMENON_WORDS:
        idx = 0
        while True:
            idx = t.find(word, idx)
            if idx < 0:
                break
            # 该处现象词自身已带完成态 → 是陈述，不是名词短语
            has_completion = (word.endswith("了")
                              or t[idx + len(word):].startswith("了"))
            if not has_completion:
                after = t[idx + len(word):].lstrip(" \t的")
                if any(after.startswith(n) for n in NOMINAL_TAILS):
                    return True
            idx += 1
    return False


def _build(scale_key, scales, wf, reasons):
    spec = scales[scale_key]
    return {
        "scale": scale_key,
        "label": spec["label"],
        "reasons": reasons,
        "criteria": spec["criteria"],
        "trim": wf["trim_matrix"][scale_key],
        "min_gates": wf["minimum_gates"].get(scale_key, []),
        # N-08：从唯一声明源读取，不再硬编码——workflow.json 顶层
        # scale_ratchet 是声明源（workflow_check.py:1826 注释引用它），
        # 硬编码会让配置与实现漂移。兜底保留原文案（配置缺失时不崩）。
        # 注意：不能放在 scale 对象内部——self_check 会把 scale 下每个键
        # 当成一个「规模」，要求 trim_matrix 有对应行（N-08 首版踩过）。
        "ratchet": wf.get("scale_ratchet", "规模只能升级不能降级"),
    }


def stages_for_scale(scale_key):
    """返回该规模下需要执行的阶段序列（跳过 trim 为 '-' 的阶段）。"""
    wf = load_workflow()
    trim = wf["trim_matrix"].get(scale_key)
    if trim is None:
        raise ValueError("未知规模：%s" % scale_key)
    out = []
    for st in wf["stages"]:
        mark = trim.get(st["id"], "-")
        if mark == "-":
            continue
        out.append({
            "id": st["id"],
            "name": st["name"],
            "mode": mark,          # 必 / 简 / 条
            "gate": st["gate"],
            "components": st["components"],
            "evidence_level": st["evidence_level"],
            "artifacts": st["artifacts"],
            "stop_for_owner": st.get("stop_for_owner", False),
        })
    return out


# ---------------------------------------------------------------------------
# 状态机
# ---------------------------------------------------------------------------

def validate_transition(from_state, to_state):
    """校验状态转移是否合法。非法转移即报错，不做「差不多就行」的放行。"""
    wf = load_workflow()
    st = wf["states"]
    if from_state not in st["list"]:
        return {"valid": False, "reason": "未知源状态：%s" % from_state}
    if to_state not in st["list"]:
        return {"valid": False, "reason": "未知目标状态：%s" % to_state}
    for t in st["transitions"]:
        if t["to"] != to_state:
            continue
        if t["from"] == from_state or t["from"] == "*":
            return {
                "valid": True,
                "transition": t["id"],
                "trigger": t["trigger"],
                "required_evidence": t["evidence"],
            }
    return {"valid": False, "reason": "状态机中不存在 %s → %s 的转移" % (from_state, to_state)}


def states_summary():
    wf = load_workflow()
    st = wf["states"]
    return {
        "states": st["list"],
        "transitions": st["transitions"],
        "invariants": st["invariants"],
        "sdd_report_mapping": st["sdd_report_mapping"],
    }


# ---------------------------------------------------------------------------
# 派发计划：角色 × 专家 二维组合
# ---------------------------------------------------------------------------

def _route_domain(task_description, persist=True):
    """域轴路由（D6 第二拍）：全规模（含 readonly）都必须完成。

    返回 (domain, implementer_type)。路由失败不抛——返回 degraded 域 dict，
    blocking 文案由调用方按规模分档（readonly 两档文案 / 非只读降级段）。

    persist（I2，Task 3）：透传给 zcode_expert_system——readonly 场景由
    build_dispatch_plan 传 False（只读分析不写 result-*.json），其余默认
    True 保持既有行为。

    monkeypatch 打点契约（I5）：zcode_expert_system 是**函数内 import**，
    禁止上提到模块顶层——上提即改变降级语义，破坏测试对源模块属性的打点
    （tests/test_domain_routing_mandatory.py 的 A3/A9）。
    """
    try:
        # M-2（修复轮 1）：去重——BASE_DIR 已在 sys.path 时不重复插入
        # （每次 build_dispatch_plan/triage 调用都 insert 会让 sys.path 无限膨胀）
        if BASE_DIR not in sys.path:
            sys.path.insert(0, BASE_DIR)
        from zcode_expert_system import zcode_expert_system
        route = zcode_expert_system(task_description, persist=persist)
        expert = route.get("selected_expert") or {}
        # 语义精判相关字段**必须原样透传**：
        # 本插件不配外部 LLM，Python 侧的 selected_expert 只是词元计数结果。
        # 丢掉 semantic_selection_required 会让消费方以为精判已完成，
        # 直接采信一个「描述里恰好出现某两个字」的巧合命中
        # （实测「修复用户登录接口的鉴权 bug」→ 飞书集成开发工程师）。
        domain = {
            "category": route.get("category"),
            "manager_id": route.get("manager_id"),
            "expert_name": expert.get("name"),
            "expert_id": expert.get("id"),
            "display_name": expert.get("name"),
            "display_label": (
                "专家：%s" % expert.get("name") if expert.get("name")
                else "专家：未选定"),
            "confidence": route.get("confidence"),
            "confidence_detail": route.get("confidence_detail"),
            "alternatives": route.get("alternatives"),
            "semantic_selection_required": route.get("semantic_selection_required"),
            "selection_basis": route.get("selection_basis"),
            "routing_warning": route.get("routing_warning"),
            # P4：判平标记必须透传——score_tied=True 时 expert_name 的取胜依据
            # 是「候选顺序」而非分值，主控必须改判或明示采信理由。
            "score_tied": route.get("score_tied"),
            "top_candidates": [
                {"name": c.get("name"), "score": c.get("score"),
                 "score_detail": c.get("score_detail")}
                for c in (route.get("top_candidates") or [])
            ],
        }
        return domain, expert.get("name")
    except Exception as exc:                       # 路由失败不阻断，但要留痕
        # I1 降级统一：except 是第一降级发射点，degraded 必须显式
        #
        # P1-5：补全语义精判元数据——降级时语义精判**依然待主控完成**
        # （路由都没成功，更不可能已完成语义判断），故置
        # semantic_selection_required=True，避免 build_dispatch_plan 的语义
        # 精判分支静默跳过（W10 降级三件套 degraded + blocking 才完整）。
        return {
            "error": str(exc),
            "degraded": True,
            "semantic_selection_required": True,
            "selection_basis": "heuristic",
            "routing_warning": (
                "域路由失败（%s）：语义精判尚未完成，派发前必须复核领域，"
                "不得采信任何未经领域判断的派发" % str(exc)
            ),
        }, None


def _write_dispatch_artifact(plan, root=None):
    """readonly 域路由成功时落盘 dispatch.json（裁决 2：文件级审计锚点）。

    位置：<项目根>/.superpowers/sdd/dispatch-<YYYYMMDD-HHMMSS+微秒>/dispatch.json
    （时间戳带微秒——同秒并发任务不互覆）。内容固定十字段（design §6）。
    只在「readonly + 域路由成功 + 专家已选」时写；conf=0 / 路由异常不写
    （那两种情形的 blocking 已记录原因）。
    M-3（修复轮 1）：payload 先于建目录构造——缺键异常不会留下半写目录。
    写盘失败不阻断派发计划生成——审计锚点不是派发前置条件，但留痕不静默。

    root 必须指向老板项目根，而不是插件/技能安装目录；None 时回退 cwd，
    兼容既有库调用。部署后安装目录可能只读或会被重装删除。
    """
    try:
        payload = {
            "task": plan["task"],
            "scale": plan["scale"]["scale"],
            "category": plan["domain"].get("category"),
            "expert_name": plan["domain"].get("expert_name"),
            "expert_id": plan["domain"].get("expert_id"),
            "subagent_type": _qualified_subagent_type(
                plan["domain"].get("expert_name")),
            "display_name": plan["domain"].get("expert_name"),
            "display_label": (
                "专家：%s" % plan["domain"].get("expert_name")
                if plan["domain"].get("expert_name") else "专家：未选定"),
            "role": "analyst",
            "confidence": plan["domain"].get("confidence"),
            "selection_basis": plan["domain"].get("selection_basis"),
            "generated_at": datetime.now().isoformat(),
        }
        project_root = os.path.abspath(root or os.getcwd())
        sdd_root = os.path.join(project_root, ".superpowers", "sdd")
        ts = datetime.now().strftime("%Y%m%d-%H%M%S%f")
        dispatch_dir = os.path.join(sdd_root, "dispatch-%s" % ts)
        os.makedirs(dispatch_dir, exist_ok=True)
        # 审计锚点是运行时产物，不应污染用户 git status。
        gitignore = os.path.join(sdd_root, ".gitignore")
        if not os.path.exists(gitignore):
            with io.open(gitignore, "w", encoding="utf-8") as f:
                f.write("*\n")
        path = os.path.join(dispatch_dir, "dispatch.json")
        with io.open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        plan["domain"]["dispatch_artifact"] = os.path.relpath(path, project_root)
    except OSError as exc:
        plan["domain"]["dispatch_artifact_error"] = str(exc)


READONLY_TOOL_POLICY = {
    "mode": "readonly",
    "allowed": [
        "Read", "Grep", "Glob", "SearchWorkspace", "SearchKnowledge",
        "WebFetch", "WebSearch",
        "只读 Bash（rg / ls / git status / git log / git diff / git show）",
    ],
    "denied": [
        "Write", "Edit", "NotebookEdit", "ImageGen", "VideoGen",
        "删除 / 移动 / 复制文件",
        "mkdir / touch / chmod / sed -i / tee",
        "shell 重定向写盘（> / >>）",
        "git add / commit / checkout / reset / restore / clean / stash / push",
        "npm install / pip install / 任何依赖安装或升级",
        "发布、发消息、写外部系统",
        "派发可写的 implementer / reviewer",
    ],
    "rule": "只读任务只能查看、搜索、读取、分析；不得新增、删除、修改任何文件或改变系统状态。",
}

P3_EVIDENCE_BY_SCALE = {
    "readonly": {
        "required": False,
        "reason": "只读任务不写代码；dispatch.json 是审计锚点，分析结论留在会话内",
    },
    "light": {
        "required": True,
        "primary": "计划文档 ## Baseline / ## Review / ## Rulings / ## Integration Verification",
    },
    "medium": {
        "required": True,
        "primary": "计划文档 ## Baseline / ## Review / ## Rulings / ## Integration Verification",
    },
    "large": {
        "required": True,
        "primary": "计划文档 ## Baseline / ## Review / ## Rulings / ## Integration Verification",
    },
    "bug": {
        "required": True,
        "primary": "计划文档 ## Bug Investigation",
        "also": "计划文档 ## Baseline / ## Review / ## Rulings / ## Integration Verification",
        "key_evidence": [
            "入口分诊", "根因调查（9 问）", "假设三段",
            "分级 + 方案（≥2 套）", "副作用自查", "双确认",
            "TDD RED 证据", "red-green 四段复验", "全量回归",
        ],
    },
}


def _p3_evidence_for(scale_key):
    """按规模返回 P3 证据契约；副本避免调用方改到模块常量。"""
    base = P3_EVIDENCE_BY_SCALE.get(scale_key, P3_EVIDENCE_BY_SCALE["medium"])
    out = {}
    for k, v in base.items():
        out[k] = list(v) if isinstance(v, list) else v
    return out


def build_dispatch_plan(task_description, scale=None, files=None, root=None):
    """生成派发计划：每条含 role / subagent_type / 契约优先级声明。

    域轴复用 zcode_expert_system（既有路由），不重复实现。

    D6 语句顺序契约（enforce-domain-routing，A9 顺序验收锁定）：
      规模分诊 → 域路由 → 语义精判 blocking → readonly analyst 分支
      → Implementer/Reviewer（非只读）。
    顺序不可颠倒：readonly 分支若抢在域路由/语义精判之前执行，会跳过
    semantic_recheck、按词元巧合派 analyst——正是 W10 要消灭的失效模式。

    root（P2-4，2026-11-19）：git 探测基准目录（项目根）。None 时回退
    进程 cwd（向后兼容既有调用与 monkeypatch.chdir 测试）。传入时
    detect_git 从 root 起探测而非 cwd——避免 cwd 恰位于无关 git 仓库内
    时假阳性伪造 L0 独立性（假阳性比假阴性更险）。
    """
    if scale is None:
        scale = classify_scale(task_description, files)

    # git 探测：决定「变更集从哪来」与「审查独立性能否算 L0」（W7）
    # P2-4：从 root（项目根）起探测，而非进程 cwd——防 cwd 假阳性。
    has_git = detect_git(root)

    plan = {
        "task": task_description,
        "scale": scale,
        "stages": stages_for_scale(scale["scale"]),
        "dispatches": [],
        # 证据模式：有 git 用 BASE..HEAD diff；无 git 用文件快照 sha256 差集。
        # 显式暴露，否则消费方无法判断「这次交付的证据链是什么形态」。
        "git": has_git,
        "evidence_mode": "diff(BASE..HEAD)" if has_git else "snapshot(sha256 差集)",
        # P3 证据契约：读到 plan 的人不需要再猜「这次要不要落盘、落到哪」。
        # readonly 不需要 P3；Bug 额外要求 ## Bug Investigation。
        "p3_evidence": _p3_evidence_for(scale["scale"]),
    }
    if scale["scale"] == "readonly":
        plan["tool_policy"] = {
            k: (list(v) if isinstance(v, list) else v)
            for k, v in READONLY_TOOL_POLICY.items()
        }

    # --- 域轴路由（W10 两轴强制：全规模必做，readonly 不再 early return） ---
    # I2 接线（Task 3）：readonly 路由传 persist=False——只读分析不写
    # result-*.json；非只读默认 True 保持既有行为。scale 在此之前已定
    # （规模分诊是 D6 第一拍）。
    domain, implementer_type = _route_domain(
        task_description,
        persist=(scale["scale"] != "readonly"),
    )
    plan["domain"] = domain

    # 路由异常 → 显式降级三件套（D5/I1）：degraded（_route_domain 已置）
    # + blocking，不再静默把「路由失败」伪装成正常计划。
    if domain.get("degraded"):
        plan["blocking"] = (
            "域路由失败（%s）：本次派发不构成领域判断——"
            "须向老板澄清任务领域，或用 zcode_expert_system."
            "build_dispatch_for_expert(专家名, 任务) 指定专家后重跑。"
            % domain.get("error")
        )

    # --- 语义精判未完成 → 必须显式要求主控复核，否则这一步永久丢失。 ---
    # 只透传布尔值不够：plan 是「按此派发」的契约，得有一条可执行动作。
    # （D6：本段必须先于 readonly analyst 分支执行，A9 锁序。）
    if domain.get("semantic_selection_required"):
        plan["dispatches"].append({
            "role": "orchestrator",
            "action": "semantic_recheck",
            "note": "Python 侧专家选择只是词元计数（selection_basis=%s）。"
                    "派发前必须复核 domain.top_candidates[].score_detail，"
                    "按业务语义定夺；要改判用 "
                    "zcode_expert_system.build_dispatch_for_expert(专家名, 任务)。"
                    "注意 token/jwt/oauth 按声明序落 security-compliance："
                    "若任务实为「实现/刷新/接入」等功能开发，应改判 "
                    "backend-architecture。"
                    % domain.get("selection_basis"),
        })
        # 高置信度只要求复核，不再制造 blocking；低置信度由下面的分支
        # 置 blocking 并阻断派发。blocking 与派发行并存是旧契约的自相矛盾。
        plan["semantic_recheck"] = {
            "required": True,
            "reason": "heuristic_selection",
            "confidence": domain.get("confidence"),
            "confidence_detail": domain.get("confidence_detail"),
        }

    # --- 只读任务：按域路由结论派 analyst（D3/D6；旧「不分派」契约已删） ---
    #
    # P2（2026-11-23）：只读分支此前只判 `expert_name` 是否为**空**，不判置信度——
    # 非只读路径有 low_conf_heuristic 阻断，只读路径没有，形成护栏不对称。
    # 实测代价：`plan "分析一下 zcode_expert_system.py 的结构"` → conf=0.0312，
    # 仍派发「无障碍审核员」（词元碰巧命中），blocking 只说「精判待完成」，
    # 不提示「分类本身可能是错的」。这里把同一判定搬进只读分支。
    #
    # 注意 semantics_selection_required 与 confidence 的关系：selection_basis
    # 恒为 heuristic（本插件不配 LLM），所以只要 top_candidates 非空就必然置位；
    # 真正决定「分类可不可靠」的是 confidence，不是这个布尔值。
    from zcode_expert_system import LOW_CONFIDENCE_THRESHOLD
    readonly_low_conf = bool(
        domain.get("semantic_selection_required")
        and (domain.get("confidence") or 0) < LOW_CONFIDENCE_THRESHOLD
    )

    if scale["scale"] == "readonly":
        plan["note"] = "只读任务：直接分析输出，不进入实施流程"
        plan["parallel"] = {"implementation": "n/a", "reason": "只读任务无实施"}
        expert_name = domain.get("expert_name")
        if expert_name and readonly_low_conf:
            # 低置信度 + heuristic：分类本身不可靠，不按词元兜底专家派 analyst。
            # 与 I-02 同口径，但用 action=blocked_low_confidence（非 analyst 派发），
            # 且**不落盘 dispatch.json**——未定领域的派发不构成审计锚点。
            plan["dispatches"].append({
                "role": "orchestrator",
                "action": "blocked_low_confidence",
                "note": "只读任务分类置信度 %.3f 低于阈值 %s 且语义精判未完成："
                        "分类本身不可靠，不按词元兜底专家（当前建议 %s）派 analyst。"
                        "请向老板澄清任务领域，或复核 domain.top_candidates[].score_detail "
                        "后用 zcode_expert_system.build_dispatch_for_expert(专家名, 任务) "
                        "指定专家后重跑。"
                        % (domain.get("confidence") or 0,
                           LOW_CONFIDENCE_THRESHOLD,
                           expert_name),
            })
            plan.setdefault("blocking", (
                "只读任务低置信度阻断（P2）：分类置信度 %.3f < %s 且语义精判未完成，"
                "词元兜底专家「%s」与任务语义可能无关，不得直接派发。"
                "须向老板澄清领域，或用 build_dispatch_for_expert(专家名, 任务) 指定后重跑。"
                % (domain.get("confidence") or 0, LOW_CONFIDENCE_THRESHOLD,
                   expert_name)
            ))
            plan["clarify_options"] = (
                [{"category": domain.get("category"), "expert": expert_name}]
                + [{"category": c, "expert": None}
                   for c in (domain.get("alternatives") or [])]
            )
        elif expert_name:
            # 域路由成功 + 专家已选 → 派 analyst + 落盘 dispatch.json（裁决 2）
            plan["dispatches"].append({
                "role": "analyst",
                "subagent_type": _qualified_subagent_type(expert_name),
                "display_name": expert_name,
                "display_label": f"专家：{expert_name}",
                "prompt_prefix": _role_contract_prefix("analyst"),
                "tool_policy": {
                    k: (list(v) if isinstance(v, list) else v)
                    for k, v in READONLY_TOOL_POLICY.items()
                },
                "note": "只读分析：仅允许查看/搜索/读取类工具；禁止新增、删除、修改"
                        "任何文件或改变系统状态。结论按「现象→原因→影响→建议」四段式"
                        "并带 file:line/URL 证据；领域判断由 analyst 承担，"
                        "不得留待主控",
            })
            _write_dispatch_artifact(plan, root=root)
        elif not domain.get("degraded"):
            # 域路由正常但无专家（conf=0 或无匹配）→ blocking 两档文案（I6/#2）。
            # 不做机械闲聊判定：两档并存陈述，归类交主控按语境判断。
            # I-1（修复轮 1）：用 setdefault——路由异常（degraded）与语义精判
            # 待复核先行设置的 blocking 都不覆盖，不吞已有信息。
            # N-01：conf=0 时 domain.category 只是 DEFAULT_CATEGORY 兜底
            # （business-support），不是真实的领域判断——加 no_signal 标记，
            # 避免消费方把「无信号」误读成「商务支持任务」。
            if not (domain.get("confidence") or 0):
                domain["no_signal"] = True
            plan.setdefault("blocking", (
                "readonly 域路由未产出专家（conf=%s，category=%s）：两档可能——"
                "① 疑似闲聊/问候（建议直接问候回应，不走专家体系）；"
                "② 真无信号（向老板澄清任务领域，或用 "
                "zcode_expert_system.build_dispatch_for_expert(专家名, 任务) "
                "指定后重跑）。"
                % (domain.get("confidence"), domain.get("category"))
            ))
        return plan

    # --- 非只读：语义 blocking 已定，按域结论派 Implementer/Reviewer ---
    # I-02：分类置信度低于阈值且语义精判未完成时，分类本身不可靠——
    # 词元兜底选出的专家（如 hr「招聘专家」命中 bigram「一个」）与任务
    # 语义无关，不得直接派发。高置信度 + heuristic（I-03）分类可靠，
    # 保留派发，semantic_recheck 动作与 blocking 提醒主控复核 score_detail。
    from zcode_expert_system import LOW_CONFIDENCE_THRESHOLD
    low_conf_heuristic = bool(
        domain.get("semantic_selection_required")
        and (domain.get("confidence") or 0) < LOW_CONFIDENCE_THRESHOLD
    )
    # Implementer
    if not low_conf_heuristic and implementer_type:
        plan["dispatches"].append({
            "role": "implementer",
            "subagent_type": _qualified_subagent_type(implementer_type),
            "display_name": implementer_type,
            "display_label": f"专家：{implementer_type}",
            "prompt_prefix": _role_contract_prefix("implementer"),
            "note": "实施者禁止派子代理；不得超出 brief 范围",
        })
    elif not low_conf_heuristic:
        # I1 降级统一：no-expert 是第二降级发射点，note 如实陈述——
        # general-purpose 只承接机械执行，领域结论禁由通用代理产出（不说谎话）
        domain["degraded"] = True
        plan["dispatches"].append({
            "role": "implementer",
            "subagent_type": "general-purpose",
            "display_name": "通用执行代理",
            "display_label": "代理：通用执行代理",
            "prompt_prefix": _role_contract_prefix("implementer"),
            "note": "域路由未产出领域专家（conf=%s）：实施降级为 general-purpose "
                    "仅承接机械执行；领域结论禁由通用代理产出，"
                    "须澄清领域或指定专家后重新路由"
                    % domain.get("confidence"),
        })
        # S6 终审修复（M-3）：no-expert 且 top_candidates 空（conf=0）时，
        # 语义精判段不会置 blocking——此处 setdefault 收口 R3 字面缺口
        # （degraded=true 必有 blocking；既有 blocking 不覆盖，与 I-1 同款口径）
        plan.setdefault("blocking", (
            "域路由未产出领域专家（conf=%s）：degraded=true——"
            "领域结论禁由 general-purpose 产出，须问老板澄清领域，"
            "或用 zcode_expert_system.build_dispatch_for_expert(专家名, 任务) "
            "指定后重新路由。"
            % domain.get("confidence")
        ))
    else:
        # I-02：低置信度 + heuristic，分类不可靠——不派 implementer/reviewer。
        # semantic_recheck 动作与 blocking 已在语义精判段置入，此处补明确
        # 的 blocked 说明，让主控看到「为什么没派、下一步怎么做」。
        # 用 role=orchestrator 而非 implementer：这是阻断说明，不是实际派发。
        plan["dispatches"].append({
            "role": "orchestrator",
            "action": "blocked_low_confidence",
            "note": "分类置信度 %.3f 低于阈值且语义精判未完成：分类本身不可靠，"
                    "不按词元兜底专家派发。请向老板澄清任务领域，或用 "
                    "zcode_expert_system.build_dispatch_for_expert(专家名, 任务) "
                    "指定专家后重跑。"
                    % (domain.get("confidence") or 0)
        })
        plan.setdefault("blocking", (
            "低置信度误派阻断（I-02）：分类置信度 %.3f < %s 且语义精判未完成，"
            "词元兜底专家与任务语义无关，不得直接派发。须向老板澄清领域，"
            "或用 build_dispatch_for_expert(专家名, 任务) 指定后重跑。"
            % (domain.get("confidence") or 0, LOW_CONFIDENCE_THRESHOLD)
        ))
        plan["clarify_options"] = (
            [{"category": domain.get("category"), "expert": implementer_type}]
            + [{"category": c, "expert": None}
               for c in (domain.get("alternatives") or [])]
        )

    # Reviewer：独立性由实际配对 + git 状态推导（含理由，便于账本记录）
    # 低置信度被阻断时无实施者，无需审查者（语义精判段的 semantic_recheck
    # 动作已覆盖主控复核动作）。
    if not low_conf_heuristic:
        reviewer_type, independence, independence_reason = _pick_reviewer(
            implementer_type,
            has_git=has_git,
            implementer_category=domain.get("category"))
        plan["dispatches"].append({
            "role": "reviewer",
            "subagent_type": _qualified_subagent_type(reviewer_type),
            "display_name": reviewer_type,
            "display_label": f"专家：{reviewer_type}",
            "independence": independence,
            "independence_reason": independence_reason,
            "prompt_prefix": _role_contract_prefix("reviewer"),
            "note": "只给 brief/report/变更集三件；Do Not Trust the Report",
        })

    # Investigator：仅当存在并行取证需求
    plan["parallel"] = {
        "implementation": "serial",
        "reason": "未使用 Git Worktree，无隔离工作区 ⇒ 实施永远串行（W1）",
        "investigation": "parallel-allowed",
        "review": "parallel-allowed",
    }
    return plan


def detect_git(start=None):
    """判断当前是否在 git 仓库内（含子目录、worktree、bare repo）。

    **不能只用 `os.path.isdir(cwd/.git)`**（P6 复核审查 A-5 实测三个错判方向）：

      | 场景 | 正确 | 旧实现 |
      |---|---|---|
      | 仓库根 | L0 | L0 ✅ |
      | 仓库子目录 | L0 | **L1** ❌ |
      | worktree（`.git` 是文件） | L0 | **L1** ❌ |
      | 空 `.git` 目录（非仓库） | L1 | **L0** ❌ 假绿 |

    最后一条最危险：`mkdir .git` 就让系统相信「有可信 diff 来源」，
    标 L0 并写 `evidence_mode=diff(BASE..HEAD)`，而 `git rev-parse` 在同目录会失败
    —— independence 是唯一硬性交付禁止项的依据，这就把它的依据伪造了。

    正确判据：向上逐级查找 `.git`（文件或目录皆可），并要求它**看起来是个真仓库**：
      - 目录形态：含 `HEAD`
      - 文件形态：内容以 `gitdir:` 开头（worktree / submodule）
    `HEAD` 这个额外要求正是排除「空 .git 目录」的关键。
    """
    cur = os.path.abspath(start or os.getcwd())
    while True:
        candidate = os.path.join(cur, ".git")
        if os.path.isdir(candidate):
            if os.path.isfile(os.path.join(candidate, "HEAD")):
                return True
        elif os.path.isfile(candidate):
            try:
                with open(candidate, "r", encoding="utf-8", errors="replace") as f:
                    head = f.read(64)
                if head.lstrip().startswith("gitdir:"):
                    return True
            except OSError:
                pass
        parent = os.path.dirname(cur)
        if parent == cur:
            return False
        cur = parent


def _pick_reviewer(implementer_type, has_git=True, implementer_category=None):
    """选审查者并给出**由实际配对 + git 状态推导**的独立性级别与理由。

    返回 (reviewer_type, independence, reason)。

    独立性级别语义（与 workflow_check.py 的 L2 拦截对齐）：
      L0 独立子代理审查 —— 审查者独立派发、类型不同，且所属 category 也
                            不同于实施者（异域）；变更集有可信来源（git diff）
      L1 主控自审降级   —— 无 git、实施者缺失，或无法证明异域
      L2 无审查         —— 不会由本函数产出；仅在完全跳过审查时由调用方标记

    文档要求 Reviewer 是「异域专家」。旧实现只比较专家名，导致
    实施者为 engineering-quality（代码审查员/最小变更工程师）时，
    审查者仍来自同一 category，却标 L0。这里在能拿到实施者 category 时
    强制选择不同 category 的审查者；无法证明时降为 L1。
    """
    primary = "代码审查员"
    primary_cat = "engineering-quality"
    alternates = [
        ("最小变更工程师", "engineering-quality"),
        ("软件架构师", "backend-architecture"),
        ("安全架构师", "security-compliance"),
    ]

    # 无 git：变更集无可靠来源，独立性按 W7 降为 L1（优先于配对判断——
    # 因为这是「证据形态」的缺陷，不是「人选配对」的缺陷）
    if not has_git:
        return primary, "L1", (
            "无 git 仓库（.git 不存在）：变更集只能靠主控计算的 sha256 快照差集，"
            "非原始 diff，不构成完全独立审查（W7 降级）；"
            "交付中须显式声明该降级"
        )

    # 实施者缺失（域路由失败已降级 general-purpose）：
    # 没有领域实施者时「独立审查」的语义已弱化，必须显式降级
    if not implementer_type:
        return primary, "L1", (
            "实施者缺失（域路由不可用，已降级 general-purpose），"
            "无从校验域级独立性；主控需人工确认审查有效性"
        )

    def different_domain(candidate, candidate_cat):
        if implementer_category:
            return candidate != implementer_type and candidate_cat != implementer_category
        return candidate != implementer_type

    # 首选审查者满足「类型不同 + 异域」→ 直接用。
    if different_domain(primary, primary_cat):
        return primary, "L0", (
            "审查者「%s」(%s) 与实施者「%s」(%s) 异域且独立派发"
            % (primary, primary_cat, implementer_type, implementer_category or "unknown")
        )

    # 首选同域 → 从备选中挑第一个异域且非同一专家者。
    for candidate, category in alternates:
        if different_domain(candidate, category):
            return candidate, "L0", (
                "实施者「%s」(%s) 与首选审查者同域；改用「%s」(%s) 保证异域审查"
                % (implementer_type, implementer_category or "unknown",
                   candidate, category)
            )

    # 所有候选都无法证明异域（或 expert 清单信息不足）。
    return primary, "L1", (
        "无法证明审查者与实施者异域（implementer_category=%s）；"
        "按 L1 声明降级，交付时须显式说明"
        % (implementer_category or "unknown")
    )


def _role_contract_prefix(role):
    """角色契约前置段。派发时拼在 prompt 最前面，压住专家人格。"""
    common = (
        "【流程契约优先】本 prompt 的流程契约优先于你的专家人格。\n"
        "人格只提供领域判断标准，不得改变任务范围、交付格式与停机条件。\n"
    )
    extra = {
        "implementer": (
            "【实施者约束】禁止派子代理；禁止超出 brief 列明的文件范围；"
            "不得隐瞒测试失败；未验证不得声称完成。\n"
        ),
        "analyst": (
            "【analyst 约束】只读分析：禁止改任何文件、禁止落地实现；"
            "每条结论必须带 file:line/URL 证据；"
            "输出固定四段式「现象→原因→影响→建议」（可选附加「未解疑点」段）；"
            "领域判断由 analyst 承担，不得留待主控。\n"
            "【只读工具权限】允许 Read/Grep/Glob/SearchWorkspace/SearchKnowledge/"
            "WebFetch/WebSearch 与只读 shell（rg/ls/git status/log/diff/show）；"
            "严禁 Write/Edit/NotebookEdit、删除/移动/复制、mkdir/touch/chmod/sed -i、"
            "shell 重定向写盘、git add/commit/checkout/reset/restore/clean/stash/push、"
            "安装依赖、发布或写外部系统。只读任务不得新增、删除、修改任何文件。\n"
        ),
        "reviewer": (
            "【审查者约束】只读，不得改文件；不采信实施者自评（只作待验证主张）；"
            "只使用 brief / report / 变更集三件输入；必须给出规格符合性与代码质量两个独立结论。\n"
        ),
        "investigator": (
            "【调查者约束】只读取证；不修改生产代码；不擅自实施修复；"
            "每条结论必须带 file:line 证据。\n"
        ),
    }
    return common + extra.get(role, "")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_files_arg(argv):
    """解析 --files N。返回 (file_count, error_msg)。

    统一各子命令的参数错误处理：非法值一律返回错误消息由调用方打印用法，
    不再让 int() 抛 traceback（此前 `plan --files abc` 会崩栈）。
    """
    if "--files" not in argv:
        return None, None
    i = argv.index("--files")
    if i + 1 >= len(argv):
        return None, "--files 缺少取值"
    try:
        value = int(argv[i + 1])
    except (TypeError, ValueError):
        return None, "--files 需为整数，收到：%r" % (argv[i + 1],)
    if value < 0:
        return None, "--files 不能为负数"
    return value, None


def _parse_root_arg(argv):
    """解析 --root <项目根>。返回 (root, error_msg)。

    P2-4（2026-11-19）：git 探测基准目录。缺省 None → detect_git 回退 cwd
    （向后兼容）。传入时 git 探测从该目录起，而非进程 cwd。
    """
    if "--root" not in argv:
        return None, None
    i = argv.index("--root")
    if i + 1 >= len(argv):
        return None, "--root 缺少取值"
    root = argv[i + 1]
    if not root or not os.path.isdir(root):
        return None, "--root 不是有效目录：%r" % root
    return os.path.abspath(root), None


def _main(argv):
    # 首个动作：把 stdout/stderr 切到 UTF-8。必须先于任何 print——
    # __doc__ 本身含中文，CP936 下同样可能触发编码异常。
    _force_utf8_stdout()
    if len(argv) < 2:
        print(__doc__)
        return 2
    cmd = argv[1]

    if cmd in ("--help", "-h"):
        print(__doc__)
        return 0

    if cmd == "triage":
        if len(argv) < 3:
            print("用法：triage \"<任务描述>\" [--files N] [--json]", file=sys.stderr)
            return 2
        task = argv[2]
        files, err = _parse_files_arg(argv)
        if err:
            print(err, file=sys.stderr)
            return 2
        json_out = "--json" in argv
        res = classify_scale(task, files)
        # 双轴合一（D2）：主控拿规模结论必须同时接受域路由。
        # 文本形态在三锚点①约束下输出：首行「任务分类结果」锚点不动，
        # 紧随其后追加领域路由两行。
        domain, _impl = _route_domain(
            task, persist=(res["scale"] != "readonly"))
        res["domain"] = domain
        if json_out:
            print(json.dumps(res, ensure_ascii=False, indent=2))
        else:
            print("任务分类结果：%s" % res["label"])
            if domain.get("degraded"):
                print("  领域路由：降级（%s）" % domain.get("error"))
                print("  领域专家：无——澄清领域或 build_dispatch_for_expert 指定后重跑")
            else:
                print("  领域路由：%s（conf=%s）" % (
                    domain.get("category"), domain.get("confidence")))
                print("  领域专家：%s（basis=%s%s）" % (
                    domain.get("expert_name") or "无",
                    domain.get("selection_basis"),
                    "，语义精判待复核"
                    if domain.get("semantic_selection_required") else "",
                ))
                # N-07：conf=0 且无专家时显式提示，对齐 build_dispatch_plan
                # 的 blocking 两档文案——否则主控只能从「领域专家：无」自行推断。
                if not domain.get("expert_name") and not (domain.get("confidence") or 0):
                    print("  ⚠️ 无信号（conf=0）：两档可能——"
                          "① 疑似闲聊/问候，可直接回应不走专家体系；"
                          "② 真无信号，须向老板澄清任务领域，或用 "
                          "build_dispatch_for_expert(专家名, 任务) 指定后重跑。")
            for r in res["reasons"]:
                print("  依据：%s" % r)
            print("  阶段裁剪：%s" % ", ".join(
                "%s=%s" % (k, v) for k, v in res["trim"].items() if v != "-"))
            if res["min_gates"]:
                print("  最少门禁：%d 道" % len(res["min_gates"]))
        return 0

    if cmd == "stages":
        if len(argv) < 3:
            print("用法：stages <readonly|light|medium|large|bug>", file=sys.stderr)
            return 2
        try:
            stages = stages_for_scale(argv[2])
        except ValueError as exc:
            print("%s" % exc, file=sys.stderr)
            print("可选规模：readonly | light | medium | large | bug", file=sys.stderr)
            return 2
        for s in stages:
            print("%s %-14s [%s] gate=%s evidence=%s" % (
                s["id"], s["name"], s["mode"], s["gate"], s["evidence_level"]))
        return 0

    if cmd == "plan":
        if len(argv) < 3:
            print("用法：plan \"<任务描述>\" [--files N] [--root <项目根>]",
                  file=sys.stderr)
            return 2
        files, err = _parse_files_arg(argv)
        if err:
            print(err, file=sys.stderr)
            return 2
        root, err = _parse_root_arg(argv)
        if err:
            print(err, file=sys.stderr)
            return 2
        print(json.dumps(build_dispatch_plan(argv[2], files=files, root=root),
                         ensure_ascii=False, indent=2))
        return 0

    if cmd == "states":
        print(json.dumps(states_summary(), ensure_ascii=False, indent=2))
        return 0

    if cmd == "transition":
        # 状态机的执行入口（缺陷 #24 族）。
        # 此前 validate_transition 全仓只有定义处一个引用——13 条转移
        # 只能靠人肉遵守，INV1-INV6 实际无执行。这里给它一个 CLU 入口：
        #   python zcode_dev_workflow.py transition REVIEW DONE
        if len(argv) < 4:
            print("用法：transition <from> <to>", file=sys.stderr)
            print("      可选状态：%s" % " | ".join(load_workflow()["states"]["list"]),
                  file=sys.stderr)
            return 2
        res = validate_transition(argv[2], argv[3])
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0 if res.get("valid") else 1

    print("未知命令：%s" % cmd, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(_main(sys.argv))
