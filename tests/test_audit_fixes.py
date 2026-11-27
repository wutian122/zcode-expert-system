# -*- coding: utf-8 -*-
"""审计修复批次回归：上下文隔离、派发根目录、workspace 归属、Reviewer 异域、
专家名称可见性、命令核对参数、Claude 部署组件。"""

import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import zcode_dev_workflow as wf  # noqa: E402
import zcode_expert_system as zes  # noqa: E402
from scripts import workflow_check as wc  # noqa: E402


def _load_context_manager():
    path = ROOT / "context" / "context-manager.py"
    spec = importlib.util.spec_from_file_location("context_manager_audit", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_context_store_is_host_scoped(monkeypatch, tmp_path):
    cm = _load_context_manager()
    monkeypatch.delenv("ZCODE_EXPERT_CONTEXT_DIR", raising=False)

    monkeypatch.setenv("QODER_HOME", str(tmp_path / ".qoder"))
    assert cm._default_store_dir().replace("\\", "/").endswith(
        ".qoder/expert-system/context")

    monkeypatch.delenv("QODER_HOME", raising=False)
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(tmp_path / "plugin"))
    assert cm._default_store_dir().replace("\\", "/").endswith(
        ".claude/expert-system/context")

    monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)
    assert cm._default_store_dir().replace("\\", "/").endswith(
        ".zcode/expert-system/context")

    override = tmp_path / "custom-context"
    monkeypatch.setenv("ZCODE_EXPERT_CONTEXT_DIR", str(override))
    assert cm._default_store_dir() == str(override.resolve())


def test_readonly_triage_does_not_persist_context(capsys, monkeypatch):
    store = Path(os.environ["ZCODE_EXPERT_CONTEXT_DIR"])
    before = set(store.glob("result-*.json"))
    rc = wf._main([
        "zcode_dev_workflow.py", "triage", "分析一下这个模块的架构", "--json",
    ])
    assert rc == 0
    assert set(store.glob("result-*.json")) == before, (
        "readonly triage 不得写 result-*.json（I2）")


def test_dispatch_artifact_uses_project_root(tmp_path):
    plan = wf.build_dispatch_plan("分析一下这个模块的架构", root=str(tmp_path))
    artifact = plan["domain"].get("dispatch_artifact")
    assert artifact, plan["domain"]
    target = (tmp_path / artifact).resolve()
    assert target.is_file()
    assert str(target).startswith(str(tmp_path.resolve()))
    assert (tmp_path / ".superpowers" / "sdd" / ".gitignore").read_text(
        encoding="utf-8") == "*\n"
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["display_name"]
    assert data["display_label"].startswith("专家：")


def test_find_workspace_prefers_plan_path_marker(tmp_path):
    root = tmp_path
    parent = "feature"
    slug = "plan"
    plan_dir = root / "docs" / parent
    plan_dir.mkdir(parents=True)
    plan_file = plan_dir / f"{slug}.md"
    plan_file.write_text("# plan\n", encoding="utf-8")

    base = root / ".superpowers" / "sdd"
    misleading = base / slug
    misleading.mkdir(parents=True)
    (misleading / "plan-path").write_text("docs/other/plan.md\n", encoding="utf-8")

    right = base / f"{slug}-{parent}"
    right.mkdir()
    (right / "plan-path").write_text(f"docs/{parent}/{slug}.md\n", encoding="utf-8")

    found = wc.find_workspace(str(root), str(plan_file))
    assert found == str(right)


def test_git_root_detected_from_subdirectory(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True)
    (root / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    sub = root / "src" / "deep"
    sub.mkdir(parents=True)
    monkeypatch.chdir(sub)
    assert Path(wc.detect_git_root()).resolve() == root.resolve()


def test_plan_identity_normalizes_git_bash_drive_path():
    expected = "c:/users/x/plan.md"
    assert wc._normalize_identity("/c/Users/x/plan.md").lower() == expected
    assert wc._normalize_identity("C:\\Users\\x\\plan.md").lower() == expected


def test_reviewer_must_be_different_domain():
    reviewer, level, reason = wf._pick_reviewer(
        "代码审查员", has_git=True, implementer_category="engineering-quality")
    assert reviewer == "软件架构师"
    assert level == "L0"
    assert "异域" in reason

    reviewer, level, _ = wf._pick_reviewer(
        "后端架构师", has_git=True, implementer_category="backend-architecture")
    assert reviewer == "代码审查员"
    assert level == "L0"


def test_plan_and_dispatch_expose_expert_display_name(tmp_path):
    plan = wf.build_dispatch_plan(
        "实现用户登录接口", files=6, root=str(tmp_path))
    implementer = [d for d in plan["dispatches"] if d["role"] == "implementer"][0]
    reviewer = [d for d in plan["dispatches"] if d["role"] == "reviewer"][0]
    assert implementer["display_name"] == implementer["subagent_type"]
    assert implementer["display_label"].startswith("专家：")
    assert reviewer["display_name"] == reviewer["subagent_type"]
    assert reviewer["display_label"].startswith("专家：")

    expert = next(e for e in zes.load_experts() if e["name"] == "后端架构师")
    out = zes.dispatch_expert(expert, "评审这个模块的设计")
    assert out["display_name"] == "后端架构师"
    assert out["dispatch"]["description"] == "专家：后端架构师"


def test_wf_check_commands_always_pass_change_plan_scale():
    for name in ("check", "plan", "verify", "resume", "archive"):
        text = (ROOT / "commands" / "wf" / f"{name}.md").read_text(encoding="utf-8")
        lines = [ln for ln in text.splitlines() if "workflow_check.py" in ln]
        assert lines, f"{name}.md 缺 workflow_check 核对命令"
        for ln in lines:
            assert "--change" in ln, f"{name}.md 核对缺 --change：{ln}"
            assert "--plan" in ln, f"{name}.md 核对缺 --plan：{ln}"
            assert "--scale" in ln, f"{name}.md 核对缺 --scale：{ln}"


def test_cli_exposes_only_install_and_uninstall():
    src = (ROOT / "bin" / "cli.js").read_text(encoding="utf-8")
    for kept in ("case 'install'", "case 'uninstall'", "case '--help'"):
        assert kept in src, f"CLI 缺少必要入口：{kept}"
    for removed in (
        "cc-install", "cc-uninstall", "qoder-install", "qoder-uninstall",
        "qoder-status", "case 'version'", "case 'help'",
    ):
        assert removed not in src, f"CLI 仍暴露已删除入口：{removed}"

    pkg = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    scripts = pkg.get("scripts") or {}
    for removed in ("cc:install", "cc:uninstall", "qoder:install",
                    "qoder:uninstall", "qoder:status"):
        assert removed not in scripts, f"package.json 仍暴露已删除脚本：{removed}"


def test_claude_deploy_includes_context_and_skill():
    src = (ROOT / "scripts" / "install-claude-code.js").read_text(encoding="utf-8")
    assert "'context'" in src
    assert "'SKILL.md'" in src
    legacy = (ROOT / "scripts" / "install.js").read_text(encoding="utf-8")
    assert "'bin', 'context'" in legacy
    assert "'SKILL.md', 'zcode_dev_workflow.py'" in legacy


def test_installers_verify_runtime_components():
    """三平台安装器都必须校验 workflow_check / categories / templates / references。

    v3.2.5 缺口：安装器只查 agents 数量，`scripts/workflow_check.py` 或
    `config/categories.json` 缺失时仍打印「部署完成」——插件装上了但 `/wf:*`
    命令与类目画像不可用。这里锁定三处校验存在（行为由 tests/test_p5_* 与
    tests/test_qoder_install.py 覆盖）。
    """
    zcode = (ROOT / "scripts" / "install.js").read_text(encoding="utf-8")
    for needle in ("scripts/workflow_check.py", "config/categories.json",
                   "'templates'", "'references'"):
        assert needle in zcode, "install.js 未校验运行时组件：%s" % needle
    assert "verifyDeployment" in zcode, "install.js 缺部署后校验调用"

    claude = (ROOT / "scripts" / "install-claude-code.js").read_text(encoding="utf-8")
    for needle in ("scripts/workflow_check.py", "config/categories.json",
                   "'templates'", "'references'"):
        assert needle in claude, "install-claude-code.js 未校验运行时组件：%s" % needle

    qoder = (ROOT / "scripts" / "install-qoder.js").read_text(encoding="utf-8")
    for needle in ("scripts/workflow_check.py", "config/categories.json",
                   "'templates'", "'references'"):
        assert needle in qoder, "install-qoder.js 未校验运行时组件：%s" % needle
    assert "verifyDeployment" in qoder, "install-qoder.js 缺部署后校验调用"
