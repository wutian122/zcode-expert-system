# -*- coding: utf-8 -*-
"""路由评估集：32 类正例 + hard negatives + 指标阈值。

目标：把“路由准确率”从口头承诺变成 CI 可核验的数字。
不引入外部 LLM/Embedding，全部走离线 fallback。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from zcode_expert_system import zcode_expert_system  # noqa: E402


# 32 类 × 2 条正例。每条都必须落在期望一级大类。
POSITIVE = [
    ("写一个 React 登录页", "frontend-client"),
    ("微信小程序真机调试", "frontend-client"),
    ("设计高并发后端 API", "backend-architecture"),
    ("接入飞书审批流", "backend-architecture"),
    ("优化 MySQL 慢查询", "data-database"),
    ("搭建数据仓库 ETL", "data-database"),
    ("配置 Kubernetes 蓝绿发布", "devops-operations"),
    ("排查线上 502 故障", "devops-operations"),
    ("给 RAG 管线做检索优化", "ai-llm"),
    ("设计多智能体协作系统", "ai-llm"),
    ("开发 STM32 固件", "embedded-iot"),
    ("设计 MQTT 物联网平台", "embedded-iot"),
    ("配置 OSPF 路由", "network-engineering"),
    ("排查华为交换机 VLAN 故障", "network-engineering"),
    ("代码审查并重构模块", "engineering-quality"),
    ("开发命令行 CLI 工具", "engineering-quality"),
    ("做一次渗透测试", "security-compliance"),
    ("设计零信任安全架构", "security-compliance"),
    ("用 pytest 写自动化测试", "data-testing"),
    ("分析测试覆盖率", "data-testing"),
    ("设计一套 UI 设计规范", "design-creative"),
    ("做用户可用性测试", "design-creative"),
    ("制定小红书内容策略", "marketing-growth"),
    ("优化 SEO 关键词排名", "marketing-growth"),
    ("优化 Google Ads PPC 竞价", "paid-media"),
    ("做广告归因追踪", "paid-media"),
    ("设计售前 POC 方案", "sales-customer"),
    ("制定赢单策略", "sales-customer"),
    ("制定公司三年战略", "business-strategy"),
    ("做并购整合计划", "business-strategy"),
    ("分析临床研究证据", "healthcare"),
    ("处理医疗账单 ICD 编码", "healthcare"),
    ("优化库存预测", "supply-chain"),
    ("设计物流配送路线", "supply-chain"),
    ("审查商业合同条款", "legal-compliance"),
    ("编写隐私政策", "legal-compliance"),
    ("设计招聘流程", "hr"),
    ("做绩效管理体系", "hr"),
    ("编制财务预算", "finance-tax"),
    ("做税务筹划", "finance-tax"),
    ("设计统计学实验", "academic-research"),
    ("做文献系统综述", "academic-research"),
    ("编写政务数字化方案", "government-public"),
    ("准备等保合规标书", "government-public"),
    ("规划日本旅行行程", "business-support"),
    ("处理酒店宾客投诉", "business-support"),
    ("做研究证据综合", "data-knowledge"),
    ("搭建 Zettelkasten 知识库", "data-knowledge"),
    ("设计 Unity 游戏关卡", "game-dev"),
    ("开发 Godot 多人游戏", "game-dev"),
    ("开发 visionOS 空间应用", "spatial-computing"),
    ("设计 XR 座舱交互", "spatial-computing"),
    ("做 GIS 地图制图", "gis"),
    ("开发 Web GIS 应用", "gis"),
    ("制定项目排期", "project-management"),
    ("写会议纪要", "project-management"),
    ("制定产品路线图", "product-management"),
    ("分析用户反馈", "product-management"),
    ("处理客户投诉工单", "customer-support"),
    ("设计客户成功流程", "customer-support"),
    ("中英技术翻译", "language-translation"),
    ("做产品本地化", "language-translation"),
    ("设计智能体身份信任", "agent-governance"),
    ("搭建 MCP 服务", "agent-governance"),
]

# (任务, 禁止落入的分类, 期望分类或 None)
HARD_NEGATIVE = [
    ("说明 Bug 与失败的区别", {"finance-tax", "data-testing"}, None),
    ("分析路由误判，包括测试/评估", {"finance-tax"}, None),
    ("修复安装注册、审计与操作", {"finance-tax"}, "engineering-quality"),
    ("统计失败率报表", {"hr", "finance-tax"}, None),
    ("设计一个失败重试机制", {"hr", "finance-tax"}, None),
]

EXPERT_TOP1 = [
    ("搜索相关性优化怎么做", "搜索相关性工程师"),
    ("中英技术翻译", "技术翻译专家"),
    ("用 pytest 写自动化测试", "测试自动化工程师"),
    ("部署 Kubernetes 集群", "DevOps 自动化师"),
    ("做一次渗透测试", "渗透测试员"),
    ("修复安装注册、审计与操作", "开发者工具工程师"),
    ("设计多智能体协作系统", "多智能体系统架构师"),
    ("准备等保合规标书", "政务数字化售前顾问"),
    ("设计客户成功流程", "客户成功经理"),
]


def _route(task):
    return zcode_expert_system(task, persist=False)


def test_positive_top1_accuracy():
    hits = 0
    misses = []
    for task, expected in POSITIVE:
        r = _route(task)
        if r["category"] == expected:
            hits += 1
        else:
            misses.append((task, expected, r["category"], r["confidence"]))
    acc = hits / float(len(POSITIVE))
    assert acc >= 0.95, "top1 accuracy %.3f < 0.95（%d/%d）；misses=%r" % (
        acc, hits, len(POSITIVE), misses)


def test_hard_negatives_never_fall_into_disallowed_categories():
    bad = []
    for task, disallowed, _expected in HARD_NEGATIVE:
        r = _route(task)
        # 低置信度会触发阻断；真正危险的是“高置信 + 禁忌分类”。
        if r["category"] in disallowed and r["confidence"] >= 0.5:
            bad.append((task, r["category"], r["confidence"]))
    assert not bad, "hard negative 高置信落入禁忌分类：%r" % bad


def test_hard_negatives_are_correct_or_blocked():
    """hard negative 要么路由正确，要么低置信度被阻断；不允许“自信地错”。"""
    blocked = 0
    for task, _disallowed, expected in HARD_NEGATIVE:
        r = _route(task)
        correct = expected is not None and r["category"] == expected
        low = r["confidence"] < 0.5
        if correct or low:
            blocked += 1
    rate = blocked / float(len(HARD_NEGATIVE))
    assert rate >= 0.8, "hard negative 正确处理/阻断率 %.2f < 0.8" % rate


def test_expert_top1_for_unambiguous_tasks():
    misses = []
    for task, expected in EXPERT_TOP1:
        r = _route(task)
        got = (r.get("selected_expert") or {}).get("name")
        if got != expected:
            misses.append((task, expected, got, r["confidence"]))
    assert not misses, "专家 top1 不符：%r" % misses


def test_eval_cases_expose_confidence_detail():
    for task in ("搜索相关性优化怎么做", "分析路由误判，包括测试/评估"):
        r = _route(task)
        detail = r.get("confidence_detail") or {}
        assert detail.get("evidence"), "缺 confidence_detail.evidence：%r" % detail
        assert "margin" in detail, "缺 confidence_detail.margin：%r" % detail


def test_category_descriptions_are_loadable():
    """32 个类目都必须有可加载的 description 语义画像。"""
    from zcode_expert_system import _category_descriptions, CATEGORIES

    desc = _category_descriptions()
    assert isinstance(desc, dict)
    missing = [c for c in CATEGORIES if not desc.get(c)]
    assert not missing, "类目 description 缺失：%s" % missing
    assert "微信小程序调试" in desc.get("frontend-client", "")
