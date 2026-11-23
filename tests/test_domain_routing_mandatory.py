# -*- coding: utf-8 -*-
"""两轴强制串联（enforce-domain-routing）验收测试 —— A1/A2/A3/A4/A6/A7/A9

对应 openspec/changes/enforce-domain-routing/design.md §11 验收索引：
  A1 五规模含非空 domain（含 readonly——旧实现 readonly 跳过域路由）
  A2 readonly 派 analyst + dispatch.json 存在且字段齐备（裁决 2）
  A3 路由失败显式降级三件套：domain.degraded=true + plan.blocking（D5）
  A4 triage CLI 双轴输出：--json 含 domain 键；文本保「任务分类结果」首行锚点
     并追加领域路由行（D2 / 三锚点①）
  A6 config/workflow.json domain_routing.mandatory + trim readonly/light S0=必
  A7 workflow_check S0.DOMAIN 判定表六格（design.md §3，夹具驱动）
  A9 readonly 顺序验收：路由返回 semantic_selection_required=True 时 plan 必含
     blocking——锁 D6「规模分诊 → 域路由 → 语义精判 blocking → readonly analyst
     分支」顺序，杜绝 v1 示意的「readonly 分支在 blocking 之前」

本文件在 Task 1（RED 阶段）落笔：生产代码未改，A1 readonly 格 / A2 / A3 / A4 /
A6 / A7 四格 / A9 先红；A1 其余四格当前路由已产出 domain，为绿（防止实现期
把既有行为改坏）。A5（hook 锚点）归 Task 6、A8（文档级豁免口径一致性）归
Task 8 验收，本轮不写。

monkeypatch 打点纪律（I5/A3 裁决）：build_dispatch_plan 对 zcode_expert_system
是**函数内 import**，patch 必须打在源模块 zcode_expert_system 的属性上；
禁止把该 import 上提到模块顶层（上提即改变降级语义、破坏本文件打点）。

运行：
    python -m pytest tests/test_domain_routing_mandatory.py -v
"""

import glob
import io
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PROJECT_ROOT)

import zcode_dev_workflow as wf  # noqa: E402
import zcode_expert_system as zes  # noqa: E402  —— monkeypatch 打点 = 本模块属性
from scripts import workflow_check as wc  # noqa: E402  —— A7 驱动面


def _expert_names():
    """config/experts.json 的真实专家名集合（读文件实核，非硬编码）。"""
    path = os.path.join(_PROJECT_ROOT, "config", "experts.json")
    with io.open(path, "r", encoding="utf-8") as f:
        return set(e["name"] for e in json.load(f)["experts"])


def _valid_subagent_types():
    """子代理派发名的合法集合（中文裸名 + Claude Code 限定名）。"""
    names = _expert_names()
    return names | {f"zcode-expert-system:{n}" for n in names}


def plan_for(task, **kw):
    r = wf.classify_scale(task, kw.get("files"))
    return wf.build_dispatch_plan(task, scale=r, files=kw.get("files"))


def _retry_remove(path, attempts=20, is_dir=False):
    """带核验的重试删除。

    为什么必须重试：Windows 上刚写完的文件可能被 AV/索引器短暂锁定，
    rmtree/os.remove 会偶发失败——而本文件的清理全是 glob 差集式（只删
    「本次新增」），一旦某轮漏网，后续任何 diff 都不再包含它 → 永久残留
    （实测：首次 RED 跑残留 1 个目录，后续每轮清理都对它无能为力）。
    每轮删除后核对目标确实消失，未消失才继续等下一轮。
    预算 ~2s（20×100ms）：Task 4 实测首扫锁可超过 5×50ms 的旧预算，
    全量跑曾连漏 3 轮；放宽预算后再未复现。
    """
    for _ in range(attempts):
        if is_dir:
            shutil.rmtree(path, ignore_errors=True)
        else:
            try:
                os.remove(path)
            except OSError:
                pass
        if not os.path.exists(path):
            return
        time.sleep(0.1)


# ---------------------------------------------------------------------------
# 测试语料（2026-11-17 主控裁决口径，规模分类已实测对表）
# ---------------------------------------------------------------------------

SCALE_CORPUS = [
    ("readonly", "分析一下这个模块的架构", None),
    ("light", "给登录接口加缓存", 1),
    ("medium", "设计一个支持高并发的后端 API 接口", None),
    ("large", "重构认证体系", None),
    ("bug", "登录报错了排查", None),
]


# ---------------------------------------------------------------------------
# A1：五规模 domain 非空（含 readonly）
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("expect_scale,task,files", SCALE_CORPUS,
                         ids=[c[0] for c in SCALE_CORPUS])
def test_a1_domain_routing_present_for_all_scales(expect_scale, task, files):
    """五个规模产出的派发计划都必须含非空 domain（真实路由结果，非占位桩）。

    旧实现 readonly 在域路由之前 early return，domain 是
    {"skipped": "readonly 任务不做域路由"}——没有 category/confidence，判红；
    Task 2 按 D6 顺序把域路由提到 readonly 分支之前后转绿。
    """
    scale = wf.classify_scale(task, files)
    assert scale["scale"] == expect_scale, (
        "语料漂移：「%s」实测规模 %s，预期 %s——请先对表主控裁决语料"
        % (task, scale["scale"], expect_scale)
    )
    sdd_root = os.path.join(_PROJECT_ROOT, ".superpowers", "sdd")
    before = set(glob.glob(os.path.join(sdd_root, "dispatch-*")))
    try:
        plan = plan_for(task, files=files)
        domain = plan.get("domain")
        assert isinstance(domain, dict) and domain, (
            "规模 %s 的派发计划缺非空 domain（W10：所有规模必须完成域轴路由）"
            % expect_scale
        )
        assert domain.get("category"), (
            "规模 %s 的 domain 缺 category（只读旧桩 %r 不算域路由）"
            % (expect_scale, domain)
        )
        assert domain.get("confidence") is not None, (
            "规模 %s 的 domain 缺 confidence——无法判断路由可信度" % expect_scale
        )
    finally:
        # readonly 语料会触发 dispatch.json 落盘（Task 2 裁决 2）：
        # 按 glob 差集自清，测试不残留 dispatch-*
        for d in set(glob.glob(os.path.join(sdd_root, "dispatch-*"))) - before:
            _retry_remove(d, is_dir=True)


# ---------------------------------------------------------------------------
# A2：readonly 派 analyst + dispatch.json 存在且字段齐备
# ---------------------------------------------------------------------------

def test_a2_readonly_analyst_writes_dispatch_json():
    """readonly 域路由成功时：派发单含 analyst，且 dispatch.json 落盘字段齐备。

    dispatch.json = readonly 路由的文件级审计锚点（裁决 2 / design §6）：
    位置 .superpowers/sdd/dispatch-<YYYYMMDD-HHMMSS>/dispatch.json，
    内容必含 task/scale/category/expert_name/expert_id/subagent_type/
    role/confidence/selection_basis/generated_at 十字段；
    域路由成功才写（conf=0 不写）——本语料 conf=1.0，必须落盘。
    落盘目录由时间戳命名，测试用 glob 前后差集定位新目录并在 finally 清理。
    """
    task = "分析一下这个模块的架构"
    sdd_root = os.path.join(_PROJECT_ROOT, ".superpowers", "sdd")
    before = set(glob.glob(os.path.join(sdd_root, "dispatch-*")))
    try:
        # ① 审查移交：plan_for 移入 try——派发计划生成（含 dispatch.json 落盘）
        # 期间任何异常都走 finally 的 glob 差集兜底清理，不残留 dispatch-*
        plan = plan_for(task)
        analysts = [d for d in plan["dispatches"] if d.get("role") == "analyst"]
        assert analysts, (
            "readonly 应派发 role=analyst（实际 roles=%s）"
            % [d.get("role") for d in plan["dispatches"]]
        )
        sub = analysts[0].get("subagent_type")
        assert sub in _valid_subagent_types(), (
            "analyst.subagent_type=%r 不是 config/experts.json 中的真实专家名" % sub
        )

        after = set(glob.glob(os.path.join(sdd_root, "dispatch-*")))
        created = after - before
        assert created, (
            "readonly analyst 派发必须落盘 dispatch-<ts>/dispatch.json"
            "（裁决 2：readonly 的文件级审计锚点）"
        )
        dispatch_dir = sorted(created)[-1]
        dj_path = os.path.join(dispatch_dir, "dispatch.json")
        assert os.path.isfile(dj_path), "dispatch.json 不存在：%s" % dj_path
        with io.open(dj_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        required = ("task", "scale", "category", "expert_name", "expert_id",
                    "subagent_type", "role", "confidence", "selection_basis",
                    "generated_at")
        missing = [k for k in required if k not in data]
        assert not missing, "dispatch.json 缺字段：%s" % missing
        assert data["role"] == "analyst", "dispatch.json role 必须=analyst"
        assert data["task"] == task, "dispatch.json task 必须回填任务原文"
        assert data["subagent_type"] in _expert_names(), (
            "dispatch.json subagent_type=%r 不是真实专家名" % data["subagent_type"]
        )
    finally:
        # 测试自清：按 glob 差集兜底（比记录 created 更稳——断言失败、
        # plan_for 中途异常都不残留）。交付物与验证证据不在清理之列，
        # 本目录是测试产物而非交付物。
        for d in set(glob.glob(os.path.join(sdd_root, "dispatch-*"))) - before:
            _retry_remove(d, is_dir=True)


# ---------------------------------------------------------------------------
# A3：路由失败 → 显式降级三件套（degraded + blocking）
# ---------------------------------------------------------------------------

def test_a3_routing_failure_degrades_with_blocking(monkeypatch):
    """域路由抛异常时：domain.degraded=true 且 plan.blocking 非空（D5/I1）。

    旧实现 except 路径只写 domain={"error": ...} 然后静默降级 general-purpose，
    无 degraded 标记、无 blocking——主控拿到计划看不出路由失败过（M1 变异
    即删 degraded 标记，本测试必红）。
    monkeypatch 打在源模块 zcode_expert_system 的属性上（I5：函数内 import，
    禁止上提）。
    """
    def _boom(task_description, task_id=None, persist=True):
        # 签名跟随真实函数（Task 3 I2 增 persist）——打点语义不变：
        # patch 源模块属性，路由调用即抛异常
        raise RuntimeError("模拟域路由服务不可用")

    monkeypatch.setattr(zes, "zcode_expert_system", _boom)
    plan = plan_for("给登录接口加缓存", files=1)
    assert plan["domain"].get("degraded") is True, (
        "路由失败必须置 domain.degraded=true（D5 显式降级三件套），实际 domain=%r"
        % plan.get("domain")
    )
    assert plan.get("blocking"), (
        "路由失败必须置 plan.blocking 非空——静默降级 = 领域结论不可信却照常派发"
    )


# ---------------------------------------------------------------------------
# A4：triage CLI 双轴合一输出（D2 / 三锚点①）
# ---------------------------------------------------------------------------

def _run_cli(args):
    """真跑 CLI 子进程（对齐 tests/test_cli_encoding.py 的「驱动真实行为」纪律）。"""
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env.pop("PYTHONUTF8", None)
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    return subprocess.run(
        [sys.executable] + args,
        cwd=_PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=False,          # 拿原始字节自己解码，避免测试进程编码干扰
        timeout=120,
    )


def _as_text(raw):
    return (raw or b"").decode("utf-8", errors="replace")


def test_a4_triage_json_has_domain_key():
    """triage --json 必须输出 domain 键（D2：主控拿规模结论必须同时接受域路由）。"""
    p = _run_cli(["zcode_dev_workflow.py", "triage",
                  "给登录接口加缓存", "--files", "1", "--json"])
    assert p.returncode == 0, "triage --json rc=%d：%s" % (
        p.returncode, _as_text(p.stderr))
    data = json.loads(_as_text(p.stdout))
    assert "scale" in data, "triage --json 缺 scale 键（规模轴回归）"
    assert "domain" in data, (
        "triage --json 缺 domain 键——双轴合一（D2）未落地，主控拿规模结论时"
        "拿不到域路由"
    )
    assert data["domain"].get("category"), "triage --json 的 domain 缺 category"


def test_a4_triage_text_keeps_first_line_and_appends_domain():
    """triage 文本输出：保「任务分类结果」首行锚点，之后追加领域路由行。

    三锚点①：首行锚点不动（下游按首行判规模）。领域行内容断言用
    classify_task 的实测 category 值，不锁文案措辞（防过度约束实现）。
    """
    task = "给登录接口加缓存"
    expected_category = zes.classify_task(task)
    assert expected_category, "语料分类失败，先修语料"

    p = _run_cli(["zcode_dev_workflow.py", "triage", task, "--files", "1"])
    assert p.returncode == 0, "triage rc=%d：%s" % (
        p.returncode, _as_text(p.stderr))
    out = _as_text(p.stdout)
    lines = [ln for ln in out.splitlines() if ln.strip()]
    assert lines, "triage 文本输出为空"
    assert lines[0].startswith("任务分类结果"), (
        "首行锚点「任务分类结果」必须保留且居首（三锚点①），实际首行：%r"
        % lines[0]
    )
    assert expected_category in out, (
        "首行之后必须追加领域路由行（含 category=%s）——双轴合一文本形态缺失"
        % expected_category
    )


# ---------------------------------------------------------------------------
# A6：config/workflow.json 声明 domain_routing 强制块 + trim S0 简→必
# ---------------------------------------------------------------------------

def test_a6_workflow_json_declares_domain_routing_mandatory():
    """config/workflow.json 必须声明 domain_routing 块并加严 trim（design §5）。

    §5.1 domain_routing：mandatory=true / order="scale-then-domain" /
    readonly_role="analyst"；§5.3 trim_matrix readonly 与 light 的 S0
    「简」→「必」（A6 验收索引点名 readonly，light 同批加严，一并锁定）。
    """
    path = os.path.join(_PROJECT_ROOT, "config", "workflow.json")
    with io.open(path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    dr = cfg.get("domain_routing")
    assert isinstance(dr, dict), (
        "config/workflow.json 缺顶层 domain_routing 声明块（§5.1）"
    )
    assert dr.get("mandatory") is True, "domain_routing.mandatory 必须=true"
    assert dr.get("order") == "scale-then-domain", (
        'domain_routing.order 必须="scale-then-domain"（先规模后域，D6）'
    )
    assert dr.get("readonly_role") == "analyst", (
        'domain_routing.readonly_role 必须="analyst"（D3）'
    )
    assert cfg["trim_matrix"]["readonly"]["S0"] == "必", (
        "trim_matrix.readonly.S0 必须「简」→「必」（§5.3）"
    )
    assert cfg["trim_matrix"]["light"]["S0"] == "必", (
        "trim_matrix.light.S0 必须「简」→「必」（§5.3 同批）"
    )


# ---------------------------------------------------------------------------
# A7：S0.DOMAIN 判定表六格（design.md §3，夹具驱动 wc.run）
# ---------------------------------------------------------------------------

PLAN_MD = """# Plan

## Goal
x
## Architecture
x
## Tech Stack
x
## Spec
x
## Review Focus
x
## Global Constraints
x
## Dependencies
x
## File Scope
x

## Baseline
- command: pytest -q
- exit: 0

## Review
independence: L0
reviewer: 代码审查员

## Rulings
Ruling: x — y — z

## Integration Verification
- command: pytest -q
- exit: 0

### Task 1: alpha

do a
"""

PLAN_REL = "docs/superpowers/plans/p.md"


def _write(root: Path, rel: str, content: str) -> Path:
    """在临时根内安全写文件：解析后必须仍在 root 之下。"""
    target = (root / rel).resolve()
    root_resolved = root.resolve()
    if root_resolved not in target.parents and target != root_resolved:
        raise ValueError("路径逃出临时根：%s" % rel)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target


def _ledger_text(with_domain=True, scale_label="中任务"):
    """构造 SDD 账本。域路由两行的行格式对齐本仓真实账本
    （.superpowers/sdd/2026-11-17-enforce-domain-routing/progress.md ## Triage 段）：
    | 领域（category） | ... | 与 | 专家（name/basis） | ... |
    """
    domain_rows = ""
    if with_domain:
        domain_rows = (
            "| 领域（category） | backend-architecture |\n"
            "| 专家（name/basis） | 软件架构师（主控语义精判改判） |\n"
        )
    return (
        "# SDD ledger — plan: docs/superpowers/plans/p.md\n\n"
        "## Scale\n\n%s\n\n"
        "## Triage\n\n| 项 | 值 |\n|---|---|\n"
        "| 任务名 | 双轴分诊夹具 |\n"
        "%s" % (scale_label, domain_rows)
    )


def _items_with_reason(rep, reason):
    return [i for i in rep.items if i.get("reason") == reason]


def test_a7_s0_domain_missing_rows_fail(tmp_path):
    """判定表核心格：非只读 + 有账本可读 + 缺 Triage 域路由行 → FAIL
    （s0_domain_missing，A 案执法核心）。"""
    _write(tmp_path, PLAN_REL, PLAN_MD)
    _write(tmp_path, ".superpowers/sdd/p/progress.md",
           _ledger_text(with_domain=False))
    rep, _ctx = wc.run(plan=PLAN_REL, scale="medium", root=str(tmp_path))
    fails = [i for i in _items_with_reason(rep, "s0_domain_missing")
             if i["status"] == wc.FAIL]
    assert fails, (
        "非只读账本缺 Triage 域路由行必须 FAIL（reason=s0_domain_missing）——"
        "A 案执法核心格未生效；实际 items=%s"
        % [(i["id"], i["status"], i["reason"]) for i in rep.items
           if i.get("reason")]
    )


def test_a7_s0_domain_rows_present_not_fail(tmp_path):
    """判定表 OK 格：非只读 + 有账本可读 + 域路由行齐 → 不得因 s0_domain_missing 判 FAIL。

    该格锁「不误杀」：按规格做对的项目（含本变更自身账本的行格式）不得假红。
    """
    _write(tmp_path, PLAN_REL, PLAN_MD)
    _write(tmp_path, ".superpowers/sdd/p/progress.md",
           _ledger_text(with_domain=True))
    rep, _ctx = wc.run(plan=PLAN_REL, scale="medium", root=str(tmp_path))
    bad = [i for i in _items_with_reason(rep, "s0_domain_missing")
           if i["status"] == wc.FAIL]
    assert not bad, (
        "Triage 域路由行齐备却被判 s0_domain_missing（假红）：%s"
        % [i["detail"] for i in bad]
    )


def test_a7_no_ledger_is_skip(tmp_path):
    """判定表第 1 行：任何规模 + 无账本 → SKIP（inapplicable:no_ledger）。"""
    _write(tmp_path, PLAN_REL, PLAN_MD)   # 不写 progress.md
    rep, _ctx = wc.run(plan=PLAN_REL, scale="medium", root=str(tmp_path))
    skips = _items_with_reason(rep, "inapplicable:no_ledger")
    assert skips, (
        "无账本必须 SKIP（reason=inapplicable:no_ledger）——无账本不可执法也不可静默；"
        "实际 reasons=%s" % sorted({i.get("reason") for i in rep.items if i.get("reason")})
    )
    assert skips[0]["status"] == wc.SKIP, (
        "无账本格状态应为 SKIP，实际 %s" % skips[0]["status"]
    )


def test_a7_readonly_with_ledger_is_skip(tmp_path):
    """判定表第 3 行：readonly + 有账本 → SKIP（inapplicable:readonly_no_ledger_expected）。

    D4：readonly 保留无账本形态，S0.DOMAIN 对其判 SKIP 不造假绿。
    不传 plan/change（避免 S0.SCALE_MISMATCH），账本经 discover_ledger 命中。
    """
    _write(tmp_path, ".superpowers/sdd/p/progress.md",
           _ledger_text(with_domain=False, scale_label="只读"))
    rep, _ctx = wc.run(scale="readonly", root=str(tmp_path))
    skips = _items_with_reason(rep, "inapplicable:readonly_no_ledger_expected")
    assert skips, (
        "readonly + 有账本必须 SKIP（reason=inapplicable:readonly_no_ledger_expected）"
        "——对 readonly 执法账本违背 D4；实际 reasons=%s"
        % sorted({i.get("reason") for i in rep.items if i.get("reason")})
    )
    assert skips[0]["status"] == wc.SKIP


def test_a7_malformed_ledger_fails(tmp_path):
    """判定表第 2 行：任何规模 + 账本不可读 → FAIL（malformed_ledger）。

    用「progress.md 是目录」构造不可读：run() 以 os.path.exists 探测
    （目录也算存在），read() 抛 OSError 返回 None——账本存在但读不出。
    """
    _write(tmp_path, PLAN_REL, PLAN_MD)
    ws = tmp_path / ".superpowers" / "sdd" / "p"
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "progress.md").mkdir()
    rep, _ctx = wc.run(plan=PLAN_REL, scale="medium", root=str(tmp_path))
    fails = [i for i in _items_with_reason(rep, "malformed_ledger")
             if i["status"] == wc.FAIL]
    assert fails, (
        "账本不可读必须 FAIL（reason=malformed_ledger）——「查不了」不允许静默放行；"
        "实际 reasons=%s"
        % sorted({i.get("reason") for i in rep.items if i.get("reason")})
    )


# ---------------------------------------------------------------------------
# A9：readonly 顺序验收（锁 D6）
# ---------------------------------------------------------------------------

def test_a9_readonly_blocking_when_semantic_recheck_required(monkeypatch):
    """readonly 路由返回 semantic_selection_required=True 时 plan 必含 blocking。

    D6 顺序契约：规模分诊 → 域路由 → 语义精判 blocking（复用现 661-676）→
    readonly analyst 分支。旧实现 readonly 在域路由之前 early return，
    monkeypatched 路由根本不会被调用、blocking 永不出现——恢复 early return
    的变异（M2）会让本测试与 A2 双双变红。
    monkeypatch 打在源模块 zcode_expert_system 的属性上（I5）。
    """
    fake_route = {
        "category": "backend-architecture",
        "manager_id": "manager-backend-architecture",
        # ② 审查移交：夹具 expert 用真实专家名与真实 id（config/experts.json
        # 实核：软件架构师 / expert-engineering-software-architect）。
        # A9 本身只断言 blocking、不断言该 expert——但它会触发 Task 2 的
        # readonly analyst 派发与 dispatch.json 落盘，故 finally 段按 glob
        # 差集自清，防测试残留。
        "selected_expert": {"name": "软件架构师",
                            "id": "expert-engineering-software-architect"},
        "confidence": 1.0,
        "alternatives": [],
        "semantic_selection_required": True,
        "selection_basis": "heuristic",
        "routing_warning": "语义精判待完成（夹具注入）",
        "top_candidates": [{"name": "软件架构师", "score": 1.0,
                            "score_detail": {}}],
    }
    # 签名跟随真实函数（Task 3 I2 增 persist）——打点语义不变
    monkeypatch.setattr(zes, "zcode_expert_system",
                        lambda task, task_id=None, persist=True: fake_route)
    sdd_root = os.path.join(_PROJECT_ROOT, ".superpowers", "sdd")
    before = set(glob.glob(os.path.join(sdd_root, "dispatch-*")))
    try:
        plan = plan_for("分析一下这个模块的架构")
        assert plan.get("blocking"), (
            "readonly 域路由返回 semantic_selection_required=True 时 plan 必含 "
            "blocking（D6：语义精判 blocking 必须发生在 readonly 分支之前）——"
            "缺 blocking 说明 readonly 分支仍抢在域路由/语义精判之前执行"
        )
    finally:
        # readonly expert 夹具会触发 dispatch.json 落盘：按 glob 差集自清
        for d in set(glob.glob(os.path.join(sdd_root, "dispatch-*"))) - before:
            _retry_remove(d, is_dir=True)


# ---------------------------------------------------------------------------
# Task 3：zcode_expert_system 可选参数（I3 role_prefix / I2 persist）
# ---------------------------------------------------------------------------

_ROLE_PREFIX_SENTINEL = "【任务 3 前缀哨兵】只读分析约束，禁止改文件"


def _result_files():
    """用户级上下文存储里的 result-*.json 集合。

    context-manager.py 的 _default_store_dir() 把运行时数据放在
    ~/.zcode/expert-system/context/（MAX_RESULT_FILES=200 自剪枝）——
    断言用 glob 差集，只看「本次调用新写了什么」。
    """
    store = os.path.join(os.path.expanduser("~"), ".zcode",
                         "expert-system", "context")
    return set(glob.glob(os.path.join(store, "result-*.json")))


def test_t3_rebuild_dispatch_prompt_starts_with_role_prefix():
    """I3：build_dispatch_for_expert 的 role_prefix 必须拼在 dispatch.prompt 首段。

    改判路径（主控用 build_dispatch_for_expert 覆盖 Python 建议）此前会
    丢失角色契约——派发单 prompt 裸任务描述，专家人格压不住流程契约。
    """
    out = zes.build_dispatch_for_expert(
        "软件架构师", "评审这个模块的设计",
        role_prefix=_ROLE_PREFIX_SENTINEL)
    prompt = out["dispatch"]["prompt"]
    assert prompt.startswith(_ROLE_PREFIX_SENTINEL), (
        "role_prefix 必须拼在 dispatch.prompt 首段（I3：改判路径不丢角色契约），"
        "实际 prompt 开头：%r" % prompt[:40]
    )
    assert "评审这个模块的设计" in prompt, "role_prefix 不得挤掉任务原文"


def test_t3_rebuild_dispatch_default_keeps_prompt_unchanged():
    """I3 反向：默认 role_prefix="" 必须保持既有行为（prompt=任务原文）。

    既有消费方（tests/test_semantic_selection.py 主控改判用例、skill_entry）
    不传新参数时行为必须一字不差。
    """
    out = zes.build_dispatch_for_expert("软件架构师", "评审这个模块的设计")
    assert out["dispatch"]["prompt"] == "评审这个模块的设计", (
        "默认 role_prefix='' 时 prompt 必须保持既有行为，实际：%r"
        % out["dispatch"]["prompt"]
    )


def test_t3_persist_false_skips_result_json():
    """I2：persist=False 必须跳过 result-*.json 落盘，返回结构不变。

    反向对照（默认 persist=True 写 1 个新文件）证明检测手段有效——
    否则「没写」可能是持久化本身坏了造成的假绿。
    新文件在 finally 中清理；历史存量（含 MAX_RESULT_FILES 剪枝）不动。
    """
    task = "给登录接口加缓存"
    before = _result_files()
    new_files = set()
    try:
        result = zes.zcode_expert_system(task, persist=False)
        assert _result_files() == before, (
            "persist=False 不得写 result-*.json（I2：readonly 不写上下文）；"
            "新增：%s" % sorted(set(_result_files()) - before)
        )
        assert "context" in result, (
            "persist=False 只跳过落盘，返回结构必须不变（context 仍在）"
        )
        # 反向对照：默认 persist=True 会写
        zes.zcode_expert_system(task)
        new_files = _result_files() - before
        assert len(new_files) == 1, (
            "默认 persist=True 必须恰好新写 1 个 result-*.json"
            "（行为差异必须真实存在，防假绿）；实际新增 %d 个"
            % len(new_files)
        )
    finally:
        for f in new_files:
            _retry_remove(f)


def test_t3_readonly_routing_skips_result_json():
    """接线验收：build_dispatch_plan 对 readonly 语料的路由必须传 persist=False。

    readonly 只做分析不落上下文（I2）；非只读语料路由保持默认 persist=True。
    路由真实性用 domain.category 守卫（防止路由没发生导致的假绿）。
    """
    task = "分析一下这个模块的架构"
    sdd_root = os.path.join(_PROJECT_ROOT, ".superpowers", "sdd")
    before_dispatch = set(glob.glob(os.path.join(sdd_root, "dispatch-*")))
    before = _result_files()
    try:
        plan = plan_for(task)
        assert plan["domain"].get("category"), (
            "readonly 路由未发生（domain 缺 category）——本测试的前提失效"
        )
        new_results = set(_result_files()) - before
        assert not new_results, (
            "readonly 路由必须以 persist=False 调用 zcode_expert_system"
            "（I2：readonly 不写 result-*.json）；新增：%s"
            % sorted(new_results)
        )
    finally:
        # readonly 派发会落盘 dispatch.json：按 glob 差集自清
        for d in set(glob.glob(os.path.join(sdd_root, "dispatch-*"))) - before_dispatch:
            _retry_remove(d, is_dir=True)
        # RED 阶段接线缺失会写 result-*.json：同样自清
        for f in set(_result_files()) - before:
            _retry_remove(f)


def test_t3_nonreadonly_routing_writes_result_json():
    """T3 审查 Important-1 反向对照：非只读路由必须真实写 result-*.json。

    守卫 build_dispatch_plan 域路由调用点的 persist 传参被误改成一刀切
    persist=False——那会让 I2 的「readonly 不写」失去对照组，非只读任务的
    上下文摘要链路静默断粮。与 test_t3_persist_false_skips_result_json
    互为正反对照（那边守 persist=False 语义，这边守 persist=True 语义）。
    """
    task = "给登录接口加缓存"   # light 语料（非只读）
    before = _result_files()
    new_files = set()
    try:
        plan = plan_for(task, files=1)
        assert plan["scale"]["scale"] == "light", "语料漂移：预期 light，先对表"
        assert plan["domain"].get("category"), "路由未发生（domain 缺 category）"
        new_files = set(_result_files()) - before
        assert len(new_files) == 1, (
            "非只读路由必须以 persist=True 恰好新写 1 个 result-*.json"
            "（I2 反向对照：守卫接线被误改 persist=False 时本测试变红）；"
            "实际新增 %d 个" % len(new_files)
        )
    finally:
        for f in new_files:
            _retry_remove(f)
