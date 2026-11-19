#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LLM 调用辅助模块：任务分类与专家选型

提供 classify_task_with_llm 和 select_expert_with_llm 两个核心函数。
它们只负责"问模型"，模型不可用时返回 None，由主入口统一降级
（关键词最长匹配 + 词元重叠打分），避免两处维护会失配的兜底表。
"""

import json
import os

# 32 个一级大类（与 config/categories.json 顶层键保持一致）
TASK_CATEGORIES = [
    "frontend-client",
    "backend-architecture",
    "data-database",
    "devops-operations",
    "ai-llm",
    "embedded-iot",
    "network-engineering",
    "engineering-quality",
    "security-compliance",
    "data-testing",
    "design-creative",
    "marketing-growth",
    "paid-media",
    "sales-customer",
    "business-strategy",
    "healthcare",
    "supply-chain",
    "legal-compliance",
    "hr",
    "finance-tax",
    "academic-research",
    "government-public",
    "business-support",
    "data-knowledge",
    "game-dev",
    "spatial-computing",
    "gis",
    "project-management",
    "product-management",
    "customer-support",
    "language-translation",
    "agent-governance",
]

EXPERTS_CONFIG = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "config", "experts.json"
)
EXPERTS_CONFIG = os.path.abspath(EXPERTS_CONFIG)

# 说明：关键词兜底与默认分类统一由主入口（zcode_expert_system.classify_task）维护，
# 本模块只负责真正的 LLM 调用，避免两处关键词表失配。

def _call_llm(messages, temperature=0.1, max_tokens=200):
    """调用 LLM 服务，返回生成的文本内容；未配置服务时直接返回 None（降级）。
    
    注意：本插件完全依赖会话中正在使用的模型，不额外配置 LLM 服务。
    如果需要直接调用外部 LLM API，请在此处添加实现。
    """
    return None


def load_experts():
    """加载专家配置列表。"""
    try:
        with open(EXPERTS_CONFIG, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("experts", [])
    except Exception:
        return []


def classify_task_with_llm(task_description):
    """
    使用当前模型对任务进行分类。

    参数:
        task_description (str): 待分类的任务描述。

    返回:
        str | None: 命中的分类名；未命中或 LLM 不可用时返回 None，
                     由调用方（主入口 classify_task）统一做降级。
    """
    if not task_description:
        return None

    system_prompt = (
        "你是一个任务分类专家。请将以下任务描述分类为32个一级大类之一："
        + ", ".join(TASK_CATEGORIES)
        + "。只回答分类名称，不要包含其他内容。"
    )
    user_prompt = "任务描述：" + task_description

    content = _call_llm(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.1,
        max_tokens=30,
    )
    if content:
        # 提取第一个匹配的分类名
        for cat in TASK_CATEGORIES:
            if cat in content:
                return cat

    # 未命中：交由调用方（主入口 classify_task）统一做关键词/词元降级，
    # 避免此处再维护一份会与主入口失配的关键词表。
    return None


def select_expert_with_llm(task_description, top5_experts, expert_stats=None):
    """
    从候选专家中选出最合适的专家 ID。

    参数:
        task_description (str): 任务描述。
        top5_experts (list): 最多 5 个候选专家，每个元素为专家 ID（str）或包含 "id" 字段的 dict。
        expert_stats (dict, optional): 专家历史表现统计，格式为 {expert_id: {total_calls, success_rate, avg_duration, ...}}

    返回:
        str: 选中的专家 ID。
    """
    if not top5_experts:
        return ""

    # 提取专家 ID 列表
    ids = []
    expert_info = []
    for e in top5_experts:
        if isinstance(e, dict):
            eid = e.get("id", "")
            name = e.get("name", "")
            desc = e.get("description", "")
            caps = e.get("capabilities", [])
            if eid:
                ids.append(eid)
                # 构建带性能信息的专家描述
                stats = expert_stats.get(eid, {}) if expert_stats else {}
                success_rate = stats.get("success_rate", 0.0)
                avg_duration = stats.get("avg_duration", 0.0)
                total_calls = stats.get("total_calls", 0)
                perf_info = f"[历史：{total_calls}次调用，成功率{success_rate:.0%}，平均{duration_str(avg_duration)}s]" if total_calls > 0 else "[新专家，无历史数据]"
                expert_info.append(f"- {name} ({eid}): {desc}; 能力：{', '.join(caps)}; {perf_info}")
        elif isinstance(e, str):
            ids.append(e)
            expert_info.append(f"- {e}")

    if not ids:
        return ""

    # 构造 LLM 置判提示词
    system_prompt = (
        "你是一个专家选择助手。根据任务描述和候选专家列表（含历史表现），选择最合适的一个专家。"
        + "优先选择成功率高、响应快的专家。新专家（无历史数据）也可考虑。"
        + "只回答专家 ID，不要包含其他内容。"
    )
    candidates_text = "\n".join(expert_info)
    user_prompt = (
        "任务描述：" + task_description
        + "\n\n候选专家：\n" + candidates_text
        + "\n\n请输出最匹配的专家 ID："
    )

    content = _call_llm(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.1,
        max_tokens=50,
    )
    if content:
        for eid in ids:
            if eid in content:
                return eid

    # 未命中：返回空串，交由调用方（llm_verdict）做相关性打分降级。
    # 不可在此返回 ids[0]——那会短路调用方的打分逻辑，
    # 使「选专家」退化为「永远取候选列表第一个」，与任务语义无关。
    return ""


def duration_str(seconds):
    """将秒数转换为人类可读的时长字符串。"""
    if seconds < 1:
        return f"{seconds*1000:.0f}ms"
    elif seconds < 60:
        return f"{seconds:.1f}s"
    else:
        return f"{seconds/60:.1f}min"


if __name__ == "__main__":
    # 简单自测
    print(classify_task_with_llm("设计一个后端 API 接口"))
    print(select_expert_with_llm("设计一个后端 API 接口", ["expert-001", "expert-002"]))