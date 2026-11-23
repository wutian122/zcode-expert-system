# -*- coding: utf-8 -*-
"""M1/M5/L3/L4 修复验收测试（RED 阶段先行落笔）。

  M1  棘轮（规模只能升不能降）：_apply_ledger_scale_conflict 已有 downgrade 判定，
      但 detail 仅 "（疑似降级）" 提示；本修复让降级时产独立 reason=ratchet_downgrade，
      使门禁报告可机械识别降级，而非混在 scale_conflict 里。
  M5  claude-hooks.json 与 hooks.json：两份配置各自正确加载，但缺一致性守卫测试，
      防止未来单侧改动漂移（如 timeout 单位、环境变量名、事件名）。
  L3  install.js:705 注释：经双平台核查确认注释与实际 hooks.json type:process 一致，
      无需修复（撤销此条）；本文件仅加守卫注释测试，锁定"注释与实际一致"。
  L4  覆盖盲区：为 openspec_engine cmd_status 的 specs/artifacts 分支、
      workflow_check normalize_scale 非字符串分支、_apply_ledger_scale_conflict
      的 recorded is None 且 scale_key != readonly 静默分支补测试。

TDD 铁律：本文件先红（生产代码未改），实现后转绿。
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts import workflow_check as wc  # noqa: E402

ENGINE = PROJECT_ROOT / "scripts" / "openspec_engine.py"
INSTALL_JS = PROJECT_ROOT / "scripts" / "install.js"
CLAUDE_HOOKS = PROJECT_ROOT / "hooks" / "claude-hooks.json"
ZCODE_HOOKS = PROJECT_ROOT / "hooks" / "hooks.json"


# ---------------------------------------------------------------------------
# M1：棘轮降级必须产独立 reason=ratchet_downgrade（可机械识别）
# ---------------------------------------------------------------------------

def _build_project_with_ledger_scale(proj, ledger_scale):
    """构造带指定 ## Scale 段的最小项目。"""
    (proj / "openspec/changes/demo/specs/auth").mkdir(parents=True)
    (proj / "openspec/specs/auth").mkdir(parents=True)
    (proj / "docs").mkdir()
    (proj / ".superpowers/sdd/p").mkdir(parents=True)
    (proj / "openspec/changes/demo/proposal.md").write_text("x\n", encoding="utf-8")
    (proj / "openspec/changes/demo/design.md").write_text("x\n", encoding="utf-8")
    (proj / "openspec/changes/demo/tasks.md").write_text("- [x] 1.1 a\n", encoding="utf-8")
    (proj / "openspec/changes/demo/specs/auth/spec.md").write_text("x\n", encoding="utf-8")
    (proj / "openspec/changes/demo/.openspec.yaml").write_text("n: d\n", encoding="utf-8")
    (proj / "openspec/specs/auth/spec.md").write_text("x\n", encoding="utf-8")
    (proj / "docs/p.md").write_text(
        "### Task 1: a\n## Baseline\nx\n## Review\nindependence: L0\nspec: ✅\n"
        "## Rulings\nx\n## Integration Verification\nx\n"
        "## Goal\nx\n## Architecture\nx\n## Tech Stack\nx\n## Spec\nx\n"
        "## Review Focus\nx\n## Global Constraints\nx\n## Dependencies\nx\n## File Scope\nx\n",
        encoding="utf-8")
    (proj / ".superpowers/sdd/p/progress.md").write_text(
        "# SDD ledger — plan: docs/p.md\n\nindependence: L0\n"
        "## Scale\n%s\nTask 1: complete (abc)\n" % ledger_scale,
        encoding="utf-8")


def test_m1_downgrade_produces_ratchet_downgrade_reason(tmp_path):
    """账本记录 large，--scale 传 light（降级）必须产 reason=ratchet_downgrade 的 FAIL。"""
    _build_project_with_ledger_scale(tmp_path, "large")
    rep, _ctx = wc.run(change="demo", plan="docs/p.md", scale="light", root=str(tmp_path))
    bad = [i for i in rep.items
           if i["status"] == wc.FAIL and i.get("reason") == "ratchet_downgrade"]
    assert bad, (
        "棘轮降级未产 reason=ratchet_downgrade——门禁报告无法机械识别降级。"
        "items=%s" % [(i["id"], i["status"], i.get("reason")) for i in rep.items
                      if i.get("reason")]
    )
    # detail 必须明示"降级"
    assert any("降级" in (i.get("detail") or "") for i in bad), (
        "ratchet_downgrade 的 detail 未写明降级：%s" % [i["detail"] for i in bad]
    )


def test_m1_upgrade_still_fails_without_downgrade_reason(tmp_path):
    """反向守卫：账本记录 light，--scale 传 large（升级）。

    注意：账本记录 light 而 --scale=large 本身就是「账本与 --scale 不一致」，
    按 P1-4 口径必须 FAIL（malformed:scale_conflict），但 reason 不得为
    ratchet_downgrade（升级不是降级）。
    """
    _build_project_with_ledger_scale(tmp_path, "light")
    rep, _ctx = wc.run(change="demo", plan="docs/p.md", scale="large", root=str(tmp_path))
    bad = [i for i in rep.items
           if i["id"] == "S0.SCALE_CONFLICT" and i["status"] == wc.FAIL
           and i.get("reason") == "ratchet_downgrade"]
    assert not bad, "规模升级被误判为 ratchet_downgrade：%s" % [
        (i["id"], i.get("reason")) for i in bad]


# ---------------------------------------------------------------------------
# M5：claude-hooks.json 与 hooks.json 关键字段一致性守卫
# ---------------------------------------------------------------------------

def test_m5_both_hooks_json_valid():
    """两份 hooks 配置均为合法 JSON，且注册同一事件 UserPromptSubmit。"""
    for p in (CLAUDE_HOOKS, ZCODE_HOOKS):
        data = json.loads(p.read_text(encoding="utf-8"))
        assert "UserPromptSubmit" in data.get("hooks", {}), (
            "%s 未注册 UserPromptSubmit" % p.name
        )


def test_m5_timeout_semantically_equivalent():
    """claude-hooks.json 的 timeout=3（秒）与 hooks.json 的 timeoutMs=3000（毫秒）语义等价。"""
    c = json.loads(CLAUDE_HOOKS.read_text(encoding="utf-8"))
    z = json.loads(ZCODE_HOOKS.read_text(encoding="utf-8"))
    c_timeout = c["hooks"]["UserPromptSubmit"][0]["hooks"][0].get("timeout")
    z_timeout = z["hooks"]["UserPromptSubmit"][0]["hooks"][0].get("timeoutMs")
    assert c_timeout is not None and z_timeout is not None, "两份配置均须声明超时"
    # 3 秒 == 3000 毫秒
    assert c_timeout * 1000 == z_timeout, (
        "超时语义不等价：claude timeout=%ss vs zcode timeoutMs=%sms" % (c_timeout, z_timeout)
    )


def test_m5_env_var_names_match_platform():
    """claude-hooks.json 用 CLAUDE_PLUGIN_ROOT，hooks.json 用 ZCODE_PLUGIN_ROOT。"""
    c = json.loads(CLAUDE_HOOKS.read_text(encoding="utf-8"))
    z = json.loads(ZCODE_HOOKS.read_text(encoding="utf-8"))
    c_cmd = c["hooks"]["UserPromptSubmit"][0]["hooks"][0].get("command", "")
    z_args = z["hooks"]["UserPromptSubmit"][0]["hooks"][0].get("args", [])
    assert "CLAUDE_PLUGIN_ROOT" in c_cmd, "claude-hooks.json 须用 CLAUDE_PLUGIN_ROOT"
    z_cmd_str = " ".join(z_args)
    assert "ZCODE_PLUGIN_ROOT" in z_cmd_str, "hooks.json 须用 ZCODE_PLUGIN_ROOT"


# ---------------------------------------------------------------------------
# L3：install.js 注释与 hooks.json 实际 type 一致（守卫，防漂移）
# ---------------------------------------------------------------------------

def test_l3_install_js_comment_matches_hooks_json_type():
    """install.js:705 注释称 hooks.json 为 type:process，hooks.json 实际须为 type:process。"""
    src = INSTALL_JS.read_text(encoding="utf-8")
    z = json.loads(ZCODE_HOOKS.read_text(encoding="utf-8"))
    z_type = z["hooks"]["UserPromptSubmit"][0]["hooks"][0].get("type")
    assert z_type == "process", "hooks.json 实际 type 应为 process，实际 %r" % z_type
    # 注释必须提到 type: process（大小写不敏感）
    assert re.search(r"type:\s*process", src, re.I), (
        "install.js 注释未声明 hooks.json 为 type:process——注释与实际漂移"
    )


# ---------------------------------------------------------------------------
# L4：openspec_engine cmd_status 的 specs/artifacts 分支覆盖
# ---------------------------------------------------------------------------

def _run_engine(*args, root):
    cmd = [sys.executable, str(ENGINE), "--root", str(root)] + list(args)
    return subprocess.run(cmd, capture_output=True, text=True, shell=False,
                          encoding="utf-8", errors="replace")


def test_l4_status_artifacts_dir_branch(tmp_path):
    """cmd_status 当 change 含 artifacts/ 目录时，扁平 artifactPaths 仍产出（M2 修复不破坏）。"""
    _run_engine("new-change", "my-change", root=tmp_path)
    # 构造 artifacts 文件
    art_dir = tmp_path / "openspec" / "changes" / "my-change" / "artifacts"
    art_dir.mkdir(parents=True)
    (art_dir / "notes.txt").write_text("note", encoding="utf-8")
    r = _run_engine("status", "--change", "my-change", root=tmp_path)
    assert r.returncode == 0, r.stderr
    data = json.loads(r.stdout)
    ap = data["artifactPaths"]
    # 扁平 artifacts 文件仍在
    assert "notes.txt" in ap, "artifacts/ 下文件的扁平映射应保留：%r" % ap
    # 嵌套 specs.existingOutputPaths 也在（M2 修复）
    assert "specs" in ap and "existingOutputPaths" in ap["specs"]


def test_l4_status_no_artifacts_no_specs(tmp_path):
    """cmd_status 无 artifacts 无 specs 时，artifactPaths.specs.existingOutputPaths=[]。"""
    _run_engine("new-change", "my-change", root=tmp_path)
    r = _run_engine("status", "--change", "my-change", root=tmp_path)
    data = json.loads(r.stdout)
    ap = data["artifactPaths"]
    assert ap.get("specs", {}).get("existingOutputPaths") == [], (
        "无 specs 时 existingOutputPaths 应为 []，实际 %r" % ap
    )


# ---------------------------------------------------------------------------
# L4：workflow_check normalize_scale 非字符串分支
# ---------------------------------------------------------------------------

def test_l4_normalize_scale_non_string_returns_invalid():
    """normalize_scale 对非字符串（None/int/list）返回 (空串, False)，不崩溃。"""
    wf = wc.load_workflow()
    for bad in (None, 123, [], {}, 0):
        key, valid = wc.normalize_scale(wf, bad)
        assert key == "" and valid is False, (
            "normalize_scale(%r) 应返回 ('', False)，实际 (%r, %r)" % (bad, key, valid)
        )


# ---------------------------------------------------------------------------
# L4：workflow_check _apply_ledger_scale_conflict recorded is None 且 scale_key != readonly
# ---------------------------------------------------------------------------

def test_l4_ledger_no_scale_section_non_readonly_no_fail(tmp_path):
    """账本缺 ## Scale 段且 scale_key != readonly 时，不产 S0.SCALE_CONFLICT FAIL（静默兼容）。"""
    (proj := tmp_path).mkdir(exist_ok=True)
    (proj / "openspec/changes/demo/specs/auth").mkdir(parents=True)
    (proj / "openspec/specs/auth").mkdir(parents=True)
    (proj / "docs").mkdir()
    (proj / ".superpowers/sdd/p").mkdir(parents=True)
    (proj / "openspec/changes/demo/proposal.md").write_text("x\n", encoding="utf-8")
    (proj / "openspec/changes/demo/design.md").write_text("x\n", encoding="utf-8")
    (proj / "openspec/changes/demo/tasks.md").write_text("- [x] 1.1 a\n", encoding="utf-8")
    (proj / "openspec/changes/demo/specs/auth/spec.md").write_text("x\n", encoding="utf-8")
    (proj / "openspec/changes/demo/.openspec.yaml").write_text("n: d\n", encoding="utf-8")
    (proj / "openspec/specs/auth/spec.md").write_text("x\n", encoding="utf-8")
    # 账本无 ## Scale 段
    (proj / ".superpowers/sdd/p/progress.md").write_text(
        "# SDD ledger — plan: docs/p.md\n\nindependence: L0\nTask 1: complete (abc)\n",
        encoding="utf-8")
    rep, _ctx = wc.run(change="demo", plan="docs/p.md", scale="medium", root=str(proj))
    # 非 readonly 且账本缺 Scale 段：不得产 S0.SCALE_CONFLICT FAIL
    bad = [i for i in rep.items
           if i["id"] == "S0.SCALE_CONFLICT" and i["status"] == wc.FAIL]
    assert not bad, (
        "账本缺 Scale 段且非 readonly 时被误判 SCALE_CONFLICT FAIL：%s"
        % [(i["id"], i.get("reason")) for i in bad]
    )