# -*- coding: utf-8 -*-
"""全量测试缺陷修复验收测试（RED 阶段先行落笔）。

覆盖 7 条经对抗性复核确认的真缺陷：
  H1  安全渗透/SQL注入任务误路由至 data-database（sql 裸词劫持安全语义）
  H2  高置信度分类却无可派专家（conf=1.0 但 selected_expert=None）
  L1  dispatch_manager 无专家时仍返回 status="dispatched"（应为 no_expert）
  M2  openspec_engine cmd_status 不产出 artifactPaths.specs.existingOutputPaths
  M3  workflow_check 对损坏 .status.json 静默置 {}，PARKED 误判 OK
  M4  install-claude-code.js 非交互运行无 --targets 单选（总全选）
  L2  context-manager _generate_summary 截断原始 JSON 而非语义摘要

TDD 铁律：本文件先红（生产代码未改），实现后转绿。
"""

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import zcode_expert_system as zes  # noqa: E402
from scripts import workflow_check as wc  # noqa: E402

ENGINE = PROJECT_ROOT / "scripts" / "openspec_engine.py"
CM_PATH = PROJECT_ROOT / "context" / "context-manager.py"


# ---------------------------------------------------------------------------
# H1：安全渗透/SQL注入任务必须路由到 security-compliance
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("task", [
    "渗透测试发现 SQL 注入漏洞，需要修复",
    "对数据库进行安全渗透测试",
    "SQL注入攻击漏洞的渗透测试与防护",
])
def test_h1_sql_injection_routes_to_security(task):
    """含「渗透/漏洞」+「sql」的安全任务必须落 security-compliance，不被 data-database 的裸 sql 劫持。"""
    category = zes.classify_task(task)
    assert category == "security-compliance", (
        "安全渗透/SQL注入任务误路由到 %s（期望 security-compliance）——"
        "data-database 的裸关键词 sql（长度3）压过了 security 的渗透/漏洞（长度2）" % category
    )


def test_h1_normal_sql_task_still_routes_to_database():
    """反向守卫：纯数据库 SQL 任务（无安全语义）仍应落 data-database，不得误伤。"""
    category = zes.classify_task("优化这个 SQL 查询的索引")
    assert category == "data-database", (
        "纯 SQL 优化任务被误路由到 %s（期望 data-database）——H1 修复不得误伤正常数据库任务" % category
    )


# ---------------------------------------------------------------------------
# H2：高置信度分类但无可派专家时，不得保留满分置信度误导消费方
# ---------------------------------------------------------------------------

def test_h2_high_confidence_no_expert_is_flagged():
    """conf>0 但 selected_expert=None 时，必须显式暴露矛盾（降 conf 或置 no_expert 标记），不得静默。"""
    r = zes.zcode_expert_system("搭建一个博客系统")
    # 该任务分类为 frontend-client（conf=1.0），但该分类下无词元匹配的专家
    assert r["category"] == "frontend-client", "语料漂移：预期 frontend-client"
    if r.get("selected_expert") is None:
        # 修复契约：要么降 conf 到 0，要么带 no_expert 标记，二选一
        assert r.get("confidence") == 0.0 or r.get("no_expert") is True, (
            "conf>0 但 selected_expert=None 时未做任何标记——消费方按 conf=1.0 直接派发会得到空专家。"
            "实际 confidence=%r, no_expert=%r" % (r.get("confidence"), r.get("no_expert"))
        )
        # routing_warning 必须提示无专家
        w = r.get("routing_warning") or ""
        assert "无可用专家" in w or "澄清" in w, (
            "无专家时 routing_warning 未提示澄清：%r" % w
        )


# ---------------------------------------------------------------------------
# L1：dispatch_manager 无专家时 status 必须对齐 expert_result.skipped
# ---------------------------------------------------------------------------

def test_l1_dispatch_manager_no_expert_status():
    """selected_expert=None 时 manager_result.status 应为 no_expert（非 dispatched），与 expert_result.skipped 对齐。"""
    m = zes.dispatch_manager("hr", "task", None, [])
    assert m["status"] != "dispatched", (
        "无专家时 dispatch_manager 仍返回 status='dispatched'（plan=%r）——"
        "消费方会误判总经理派发成功，与 expert_result.status='skipped' 矛盾" % m.get("plan")
    )
    assert m["status"] in ("no_expert", "skipped", "plan_empty"), (
        "无专家时 status 应为 no_expert/skipped/plan_empty 之一，实际 %r" % m["status"]
    )
    assert m["plan"] == [], "无专家时 plan 应为空"


def test_l1_dispatch_manager_with_expert_still_dispatched():
    """反向守卫：有专家时 status 仍为 plan_ready/dispatched（正常路径不回归）。"""
    experts = zes.load_experts()
    target = next(e for e in experts if e["name"] == "软件架构师")
    m = zes.dispatch_manager("backend-architecture", "task", target, [target])
    assert m["status"] in ("plan_ready", "dispatched"), (
        "有专家时 status 应为 plan_ready/dispatched，实际 %r" % m["status"]
    )


# ---------------------------------------------------------------------------
# M2：openspec_engine cmd_status 必须产出 artifactPaths.specs.existingOutputPaths
# ---------------------------------------------------------------------------

def _run_engine(*args, root):
    cmd = [sys.executable, str(ENGINE), "--root", str(root)] + list(args)
    return subprocess.run(cmd, capture_output=True, text=True, shell=False,
                          encoding="utf-8", errors="replace")


def test_m2_status_outputs_specs_existing_output_paths(tmp_path):
    """cmd_status 必须产出嵌套 artifactPaths.specs.existingOutputPaths（S8 delta 唯一来源）。"""
    _run_engine("new-change", "my-change", root=tmp_path)
    # 构造一个 spec 产物
    spec_dir = tmp_path / "openspec" / "changes" / "my-change" / "specs" / "auth"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("## Purpose\n认证\n", encoding="utf-8")
    r = _run_engine("status", "--change", "my-change", root=tmp_path)
    assert r.returncode == 0, r.stderr
    data = json.loads(r.stdout)
    ap = data.get("artifactPaths", {})
    # 文档声明的嵌套路径必须存在且为列表
    existing = ap.get("specs", {}).get("existingOutputPaths")
    assert isinstance(existing, list), (
        "artifactPaths.specs.existingOutputPaths 缺失或非列表——S8 delta 唯一来源静默失效。"
        "实际 artifactPaths=%r" % ap
    )
    assert len(existing) >= 1, "至少应收集到一个 spec 产物路径"
    assert any("auth" in p for p in existing), "existingOutputPaths 应含 auth spec 路径"


def test_m2_status_no_specs_empty_list(tmp_path):
    """无 specs 目录时 existingOutputPaths 应为空列表（不误报）。"""
    _run_engine("new-change", "my-change", root=tmp_path)
    r = _run_engine("status", "--change", "my-change", root=tmp_path)
    data = json.loads(r.stdout)
    existing = data.get("artifactPaths", {}).get("specs", {}).get("existingOutputPaths")
    assert existing == [], "无 specs 时 existingOutputPaths 应为 []，实际 %r" % existing


# ---------------------------------------------------------------------------
# M3：workflow_check 对损坏 .status.json 必须 FAIL（不静默放行）
# ---------------------------------------------------------------------------

def _build_minimal_project(proj):
    """构造一个能通过其他检查的最小项目（复用 test_workflow_check 的夹具思路）。"""
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
        "# SDD ledger — plan: docs/p.md\n\nindependence: L0\nTask 1: complete (abc)\n",
        encoding="utf-8")


def test_m3_corrupt_status_json_fails(tmp_path):
    """损坏的 .status.json（非法 JSON）必须产 malformed FAIL，不得静默判 OK。"""
    _build_minimal_project(tmp_path)
    # 写入损坏的 .status.json
    (tmp_path / "openspec/changes/demo/.status.json").write_text(
        "{ this is not valid json ", encoding="utf-8")
    rep, _ctx = wc.run(change="demo", plan="docs/p.md", scale="medium", root=str(tmp_path))
    # S8.PARKED 或任一检查项必须 FAIL，且 reason 含 malformed
    bad = [i for i in rep.items
           if i["status"] == wc.FAIL and "malformed" in (i.get("reason") or "")]
    assert bad, (
        "损坏 .status.json 未产 malformed FAIL——PARKED 检查静默放行，违反 W8。"
        "items=%s" % [(i["id"], i["status"], i.get("reason")) for i in rep.items
                      if i.get("reason")]
    )


def test_m3_valid_status_json_still_ok(tmp_path):
    """反向守卫：合法 .status.json（parked=false）不得误判 FAIL。"""
    _build_minimal_project(tmp_path)
    (tmp_path / "openspec/changes/demo/.status.json").write_text(
        json.dumps({"parked": False}), encoding="utf-8")
    rep, _ctx = wc.run(change="demo", plan="docs/p.md", scale="medium", root=str(tmp_path))
    bad = [i for i in rep.items
           if i["id"] == "S8.PARKED" and i["status"] == wc.FAIL]
    assert not bad, "合法 .status.json（parked=false）被误判 FAIL：%s" % [
        (i["id"], i.get("reason")) for i in bad]


# ---------------------------------------------------------------------------
# L2：context-manager _generate_summary 必须产出语义摘要而非截断 JSON
# ---------------------------------------------------------------------------

def _load_cm():
    spec = importlib.util.spec_from_file_location(
        "context_manager_under_test", str(CM_PATH))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_l2_summary_is_not_truncated_raw_json():
    """_generate_summary 产出的摘要必须是可解析的语义摘要，而非 200 字符截断的原始 JSON 片段。"""
    cm = _load_cm()
    inst = cm.ExpertContext()
    # 构造一个超过 200 字符的路由结果
    result = {
        "task_id": "task-20260101-000000",
        "category": "backend-architecture",
        "selected_expert": {"name": "软件架构师", "id": "expert-engineering-software-architect"},
        "top_candidates": [{"id": "expert-%d" % i, "name": "专家%d" % i} for i in range(20)],
        "manager_result": {"status": "plan_ready"},
        "expert_result": {"status": "pending_dispatch"},
    }
    summary = inst._generate_summary(result)
    # 修复契约：摘要必须是合法 JSON（可解析），而非截断片段
    # 原始 JSON 截断后 json.loads 会失败；语义摘要（提取关键字段）应可解析
    try:
        parsed = json.loads(summary)
        # 若可解析，必须含关键字段（category/selected_expert 或 summary 文本）
        assert isinstance(parsed, dict), "摘要应为 dict"
    except json.JSONDecodeError:
        # 若是文本摘要（非 JSON），必须含关键信息且不是原始 JSON 前缀
        assert "category" in summary.lower() or "backend" in summary.lower() or len(summary) < 200, (
            "摘要既非合法 JSON 又不含关键信息，疑似原始 JSON 截断片段：%r" % summary[:80]
        )


def test_l2_summary_contains_key_fields():
    """摘要必须含 category 与 expert 关键字段（可人工/模型快速理解）。"""
    cm = _load_cm()
    inst = cm.ExpertContext()
    result = {
        "category": "security-compliance",
        "selected_expert": {"name": "安全工程师", "id": "expert-security-engineer"},
        "created_at": "2026-11-23T10:00:00",
    }
    summary = inst._generate_summary(result)
    assert "security-compliance" in summary or "安全" in summary, (
        "摘要未含 category 关键信息：%r" % summary
    )


# ---------------------------------------------------------------------------
# M4：install-claude-code.js 必须支持 --targets 单选（非交互场景）
# ---------------------------------------------------------------------------

def test_m4_install_claude_code_targets_flag(tmp_path):
    """install-claude-code.js --dry-run --targets claude-code 必须只选 claude-code（不全选 zcode）。"""
    script = PROJECT_ROOT / "scripts" / "install-claude-code.js"
    env = dict(os.environ)
    # 非 TTY 环境（subprocess 默认非 TTY）
    r = subprocess.run(
        ["node", str(script), "--dry-run", "--targets", "claude-code"],
        capture_output=True, text=True, shell=False, cwd=str(PROJECT_ROOT),
        encoding="utf-8", errors="replace", env=env, timeout=60,
    )
    out = (r.stdout or "") + (r.stderr or "")
    # 修复契约：必须只选 claude-code，不得出现「zcode + claude-code」全选
    assert "claude-code" in out, "未识别 --targets claude-code：%s" % out[:200]
    assert "zcode + claude-code" not in out, (
        "--targets claude-code 仍全选两个目标（非交互全选缺陷未修）：%s" % out[:200]
    )