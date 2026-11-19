# -*- coding: utf-8 -*-
"""skill_entry.py 回归测试（P1-7）

**这个文件要抓的破坏**：`skill_entry.py` 是技能调用包装层（ZCode 技能系统
直接调用入口），承担 `semantic_selection_required`/`routing_warning` 透传
（缺陷 #11，已在 line 62-63 修复）与 `handle_skill_invoke` 结构化返回职责，
却长期未纳入测试矩阵——后续重构容易回退（如再次把语义精判字段静默削掉）。

覆盖：
1. 空任务返回 success:False + error
2. semantic_selection_required / routing_warning 原样透传（缺陷 #11 锁定）
3. 异常时返回 success:False 并带 traceback
4. get_skill_info 版本与计数一致

**不污染真实目录**：skill_entry 内部经 zcode_expert_system 构建上下文会写
result-*.json，monkeypatch CONTEXT_DIR 指向 tmp_path。
"""

import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import skill_entry  # noqa: E402
import zcode_expert_system as zes  # noqa: E402


@pytest.fixture(autouse=True)
def _isolated_context(tmp_path, monkeypatch):
    """把 CONTEXT_DIR 指向 tmp_path，避免持久化污染真实目录。"""
    monkeypatch.setattr(zes, "CONTEXT_DIR", str(tmp_path))


def test_空任务返回错误():
    """空任务描述必须返回 success:False，不抛异常。"""
    out = skill_entry.handle_skill_invoke("")
    assert out["success"] is False
    assert "error" in out and out["error"], "应返回错误信息"


def test_空白任务返回错误():
    """纯空白任务描述同样视为空。"""
    out = skill_entry.handle_skill_invoke("    \n\t")
    assert out["success"] is False
    assert "error" in out


def test_语义精判字段透传():
    """P1-7/缺陷 #11：routing_warning 与 semantic_selection_required 必须原样透传。

    旧实现只挑 11 个键返回，把这两个字段静默削掉——文档要求的强制动作在
    官方包装层就没有输入可用，主控会默认采信词元计数的巧合命中。
    """
    out = skill_entry.handle_skill_invoke("实现用户登录接口")
    assert out["success"] is True, out.get("error")
    # 这两个字段是缺陷 #11 修复的核心，缺失即回退
    assert "routing_warning" in out, (
        "skill_entry 未透传 routing_warning —— 缺陷 #11 回退"
    )
    assert "semantic_selection_required" in out, (
        "skill_entry 未透传 semantic_selection_required —— 缺陷 #11 回退"
    )
    assert out["semantic_selection_required"] is True, (
        "无 LLM 时 semantic_selection_required 应为 True"
    )
    assert out["routing_warning"], "routing_warning 应非空（提示主控复核）"


def test_返回结构完整():
    """handle_skill_invoke 返回结构应含完整路由字段。"""
    out = skill_entry.handle_skill_invoke("实现用户登录接口")
    assert out["success"] is True
    for key in ("category", "confidence", "manager_id",
                "selected_expert_id", "top_candidates", "timestamp"):
        assert key in out, f"返回结构缺 {key}"


def test_异常时返回失败并带traceback(monkeypatch):
    """路由内部抛异常时，包装层应返回 success:False + traceback，不向上抛。

    skill_entry.py 用 `from zcode_expert_system import zcode_expert_system`
    做了名称绑定，故须 monkeypatch skill_entry 模块内的引用，
    patch zes 模块属性不影响已绑定名称。
    """
    def _boom(*a, **k):
        raise RuntimeError("模拟路由崩溃")
    monkeypatch.setattr(skill_entry, "zcode_expert_system", _boom)

    out = skill_entry.handle_skill_invoke("实现用户登录接口")
    assert out["success"] is False
    assert "error" in out and out["error"], "应含错误信息"
    assert "traceback" in out, "应带 traceback 便于排查"


def test_批量调用逐任务返回():
    """handle_skill_invoke_batch 逐任务返回，结构与单次一致。"""
    out = skill_entry.handle_skill_invoke_batch(
        ["实现用户登录接口", "前端登录页开发"])
    assert isinstance(out, list) and len(out) == 2
    for item in out:
        assert item["success"] is True
        assert "semantic_selection_required" in item


def test_get_skill_info版本与计数一致():
    """get_skill_info 的 version 与插件版本一致，计数声明真实。"""
    info = skill_entry.get_skill_info()
    assert info["name"] == "zcode-expert-system"
    # 动态读 package.json 版本，避免每次升版本改测试（防复发，同 test_version_strings_agree）
    pkg_version = json.loads(
        (ROOT / "package.json").read_text(encoding="utf-8"))["version"]
    assert info["version"] == pkg_version, (
        f"skill_entry 版本应与插件一致 {pkg_version}，实际 {info['version']}"
    )
    # 计数声明应与 experts.json 实际一致
    experts = zes.load_experts()
    assert info["expert_count"] == len(experts), (
        f"expert_count={info['expert_count']} 与实际 {len(experts)} 不符"
    )
    assert info["manager_count"] == 32
