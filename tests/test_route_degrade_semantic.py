# -*- coding: utf-8 -*-
"""P1-5/P1-6 回归测试：_route_domain 路由异常时补全语义精判元数据。

**这个文件要抓的破坏**：`zcode_dev_workflow.py` 的 `_route_domain` 在捕获
路由异常时只返回 `{"error", "degraded"}`，丢失 `semantic_selection_required`
等字段。于是 `build_dispatch_plan` 的语义精判分支（`domain.get("semantic_selection_required")`）
永远不触发，**语义精判 blocking 静默消失**，W10 降级三件套（degraded + blocking）
不完整——主控拿到计划后无法判断「是路由崩溃」还是「只需语义复核」。

旧实现的失效模式：域路由失败时，计划看似可执行（degraded 标记虽有，但无语义
精判 blocking），主控可能误采信 general-purpose 降级实施者，违反「领域结论禁
由通用代理产出」。

**驱动真实行为**：monkeypatch `zcode_expert_system.zcode_expert_system`
函数使其抛异常，再调真实 `build_dispatch_plan`，不 mock 判定逻辑本身。
"""

import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

zcode_expert_system_mod = importlib.import_module("zcode_expert_system")
zcode_dev_workflow = importlib.import_module("zcode_dev_workflow")


def _scale():
    """构造一个带域路由的 scale（非只读，走 implementer 分支）。"""
    return zcode_dev_workflow.classify_scale("实现用户登录接口")


def _boom(*args, **kwargs):
    raise RuntimeError("模拟路由崩溃")


def test_route_domain_异常时补全语义精判元数据(monkeypatch):
    """P1-5：路由异常时，domain 应带 semantic_selection_required=True。

    旧实现 except 路径只返回 error/degraded，丢失该键；
    修复前本用例因 domain.get("semantic_selection_required") 为 None 而 RED。
    """
    monkeypatch.setattr(zcode_expert_system_mod, "zcode_expert_system", _boom)

    plan = zcode_dev_workflow.build_dispatch_plan(
        "实现用户登录接口", scale=_scale())

    domain = plan["domain"]
    assert domain.get("degraded") is True, "路由异常应标记 degraded"
    assert domain.get("semantic_selection_required") is True, (
        "P1-5：路由异常时 semantic_selection_required 应为 True，"
        "不得因元数据丢失而静默跳过语义精判"
    )


def test_route_domain_异常时置语义精判blocking(monkeypatch):
    """P1-6：路由异常时，计划应置语义精判 blocking，且 dispatch 含 semantic_recheck。

    旧实现 degraded 分支未插入语义精判 blocking，计划看似可执行。
    修复前本用例因 blocking 未置或 dispatch 无 semantic_recheck 而 RED。
    """
    monkeypatch.setattr(zcode_expert_system_mod, "zcode_expert_system", _boom)

    plan = zcode_dev_workflow.build_dispatch_plan(
        "实现用户登录接口", scale=_scale())

    blocking = plan.get("blocking")
    assert blocking, "P1-6：路由异常时计划必须有 blocking，不得静默可执行"

    # 语义精判 dispatch 动作必须被追加（不因 degraded 而跳过）
    actions = [d.get("action") for d in plan.get("dispatches", [])]
    assert "semantic_recheck" in actions, (
        f"P1-6：degraded 时 dispatches 应含 semantic_recheck 动作，"
        f"实际 actions：{actions}"
    )
