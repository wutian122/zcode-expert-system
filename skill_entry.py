#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ZCode Expert System v3 技能调用包装层

提供可被 ZCode 技能系统直接调用的入口，使老板可以通过 /zcode-expert-system
技能直接下达任务。包装层负责：
1. 接收 ZCode 技能系统传入的任务描述
2. 调用 zcode_expert_system 三层路由编排流程
3. 返回结构化结果供 ZCode 会话消费
"""

import sys
import os
import json
import traceback
from datetime import datetime

# 确保可以导入 zcode_expert_system
SKILL_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SKILL_DIR)

from zcode_expert_system import zcode_expert_system


def handle_skill_invoke(task_description, context=None):
    """
    ZCode 技能调用入口函数。

    参数:
        task_description (str): 老板下达的任务描述
        context (dict, optional): 调用上下文，包含会话信息等

    返回:
        dict: 结构化执行结果
    """
    if not task_description or not task_description.strip():
        return {
            "success": False,
            "error": "任务描述不能为空",
            "timestamp": datetime.now().isoformat(),
        }

    try:
        result = zcode_expert_system(task_description.strip())

        # 提取 selected_expert 的 id
        selected_expert = result.get("selected_expert")
        selected_expert_id = selected_expert.get("id", "") if selected_expert else ""

        # 语义精判相关字段必须透传（缺陷 #11）：
        # SKILL.md 明文要求主控「必须检查 semantic_selection_required 与
        # routing_warning 后再派专家」。旧实现只挑 11 个键返回，把这两个字段
        # 静默削掉——文档要求的强制动作在官方包装层就没有输入可用，
        # 主控会默认采信一个词元计数的巧合命中。
        return {
            "success": True,
            "task_id": result.get("context", {}).get("task_id", ""),
            "category": result.get("category", ""),
            "confidence": result.get("confidence"),
            "alternatives": result.get("alternatives"),
            "routing_warning": result.get("routing_warning"),
            "semantic_selection_required": result.get("semantic_selection_required"),
            "selection_basis": result.get("selection_basis"),
            "manager_id": result.get("manager_id", ""),
            "selected_expert_id": selected_expert_id,
            "selected_expert": selected_expert,
            "top_candidates": result.get("top_candidates", []),
            "manager_result": result.get("manager_result", {}),
            "expert_result": result.get("expert_result", {}),
            "context": result.get("context", {}),
            "timestamp": datetime.now().isoformat(),
        }

    except Exception as exc:
        return {
            "success": False,
            "error": str(exc),
            "traceback": traceback.format_exc(),
            "timestamp": datetime.now().isoformat(),
        }


def handle_skill_invoke_batch(task_descriptions, context=None):
    """
    批量任务调用入口。

    参数:
        task_descriptions (list[str]): 多个任务描述
        context (dict, optional): 调用上下文

    返回:
        list[dict]: 每个任务的执行结果
    """
    results = []
    for task_desc in task_descriptions:
        result = handle_skill_invoke(task_desc, context)
        results.append(result)
    return results


def get_skill_info():
    """
    返回技能元信息，供 ZCode 技能系统发现和展示。

    返回:
        dict: 技能信息
    """
    return {
        "name": "zcode-expert-system",
        "version": "3.2.4",
        "description": "ZCode 专家体系 v3 - 基于 dsh-agency-agents 的 331 位专家，三层路由架构：LLM 分类（32 个一级大类）→ 32 个领域总经理任务分解 → 331 位领域专家执行",
        "input": {
            "task_description": {
                "type": "string",
                "required": True,
                "description": "待执行的任务描述",
            }
        },
        "output": {
            "success": "bool",
            "task_id": "string",
            "category": "string",
            "manager_id": "string",
            "selected_expert_id": "string",
            "selected_expert": "object",
            "top_candidates": "array",
            "manager_result": "object",
            "expert_result": "object",
            "context": "object",
            "error": "string (optional)",
            "timestamp": "string",
        },
        "categories": [
            "frontend-client", "backend-architecture", "data-database", "devops-operations",
            "ai-llm", "embedded-iot", "network-engineering", "engineering-quality",
            "security-compliance", "data-testing", "design-creative", "marketing-growth",
            "paid-media", "sales-customer", "business-strategy", "healthcare",
            "supply-chain", "legal-compliance", "hr", "finance-tax",
            "academic-research", "government-public", "business-support", "data-knowledge",
            "game-dev", "spatial-computing", "gis", "project-management",
            "product-management", "customer-support", "language-translation", "agent-governance",
        ],
        "manager_count": 32,
        "expert_count": 331,
        "features": [
            "三层路由架构（分类 → 总经理 → 专家）",
            "LLM 任务分类（32 个一级大类）",
            "32 个领域总经理（按大类划分）",
            "Embedding 粗筛 + LLM 精判",
            "331 位专家完整人格提示词",
            "上下文持久化传递",
        ],
    }


def _force_utf8_stdout():
    """让 stdout/stderr 用 UTF-8 输出，避免非 UTF-8 控制台抛 UnicodeEncodeError。

    背景（缺陷 #3）：本包装层返回的 selected_expert / top_candidates 直接来自
    config/experts.json，带 emoji 字段（⚙️ U+2699 等）；CP936 终端下
    `print(json.dumps(..., ensure_ascii=False))` 会抛 UnicodeEncodeError，
    命令 rc=1、stdout 全空。

    errors="replace" 仅作重配失败时的兜底；正常情况下 UTF-8 完整保留 emoji 与中文。
    与 zcode_expert_system.py / zcode_dev_workflow.py 的同名函数保持一致。
    """
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


if __name__ == "__main__":
    # 命令行测试
    import sys

    _force_utf8_stdout()
    if len(sys.argv) > 1 and sys.argv[1] in ("--help", "-h"):
        print("用法：python skill_entry.py \"<任务描述>\"")
        sys.exit(0)
    if len(sys.argv) < 2:
        print("用法：python skill_entry.py \"任务描述\"")
        sys.exit(1)

    task_desc = sys.argv[1]
    result = handle_skill_invoke(task_desc)
    print(json.dumps(result, ensure_ascii=False, indent=2))