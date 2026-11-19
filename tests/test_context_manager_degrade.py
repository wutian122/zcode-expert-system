# -*- coding: utf-8 -*-
"""P2-5 回归测试：context-manager.py 缺失时路由照常工作（fail-open）。

**这个文件要抓的破坏**：`zcode_expert_system.py` 的 `build_context`（line 826-836）
动态加载 `context/context-manager.py` 做上下文持久化。该文件缺失或加载失败时
只设 `context_persist_warning`，路由照常工作——上下文存储是**可选组件**，
不能因为读不到历史摘要就让整条路由失败。

旧测试未覆盖此降级路径。本文件用 monkeypatch 把 `CONTEXT_DIR` 指向空目录
模拟「文件缺失」，不动真实文件、不产生并发写入。
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import zcode_expert_system as zes  # noqa: E402


def test_context_manager_缺失时路由照常工作(tmp_path, monkeypatch):
    """P2-5：context-manager.py 缺失时，zcode_expert_system 照常路由。

    monkeypatch CONTEXT_DIR 指向空目录（无 context-manager.py），
    模拟缺失。路由必须照常完成，返回结构完整，不抛异常。
    """
    monkeypatch.setattr(zes, "CONTEXT_DIR", str(tmp_path))

    r = zes.zcode_expert_system("实现用户登录接口", persist=True)

    # 路由照常：分类与专家选择不受影响
    assert r["category"], "分类不应因 context-manager 缺失而失败"
    assert "context" in r, "返回结构应含 context"
    assert r["context"]["category"] == r["category"], "context 应与路由一致"


def test_context_manager_缺失时_persist_false不抛(tmp_path, monkeypatch):
    """P2-5：persist=False 时（readonly 不写上下文）缺失也不抛。"""
    monkeypatch.setattr(zes, "CONTEXT_DIR", str(tmp_path))

    r = zes.zcode_expert_system("实现用户登录接口", persist=False)

    assert r["category"]
    assert r["semantic_selection_required"] is True, (
        "路由结果不应因上下文缺失而改变语义精判标记"
    )
