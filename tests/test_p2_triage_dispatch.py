# -*- coding: utf-8 -*-
"""P2 · 分诊与派发保真回归测试（缺陷 #9 #10 #11 #25）

**这个文件要抓的破坏**

1. **#9 分诊双向误判**（本文件最重要的一组）
   现状实测：
     - `登录失败` / `接口返回500` / `生产数据库挂了` → **只读**
       后果：真 Bug 被判定为「无写动作」，整条根因排查流程（根因调查、
       TDD 复现、red-green 复验）被跳过，直接输出一句分析就结束。
     - `增加无法登录时的提示` / `实现一个不能重复提交的表单校验` → **Bug**
       后果：新功能被塞进根因流程，去查一个不存在的根因。
   这两个方向都错，而且**错的方向相反**——说明不是词表缺词，而是
   「能力缺失描述」与「坏现状描述」被混在同一张表里。

2. **#10 / #11 语义字段被中间层丢弃**
   `zcode_expert_system()` 已老实给出 `semantic_selection_required=True`
   与 `routing_warning`，但 `build_dispatch_plan()` 与 `handle_skill_invoke()`
   把这两个字段扔掉，产出一份看起来完整、可以直接派发的契约。
   主控若直接消费，语义精判这一步就永久丢失。

3. **#25 无 git 仍标 L0**
   W7 规定无 git 时独立性降为 L1（快照证据 + 主控自审）。
   现状恒输出 L0 且理由写「I1+I2+I3 满足」，账本记录与事实不符。

**驱动真实行为**：直接调用 `classify_scale` / `build_dispatch_plan` /
`handle_skill_invoke`，不 mock。这些是纯函数，mock 它们等于测自己。
"""

import glob
import os
import shutil
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import zcode_dev_workflow as wf  # noqa: E402

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _cleanup_new_dispatch_dirs(before):
    """按 glob 差集清理本轮新增的 dispatch-* 目录（测试自清）。

    带核验重试：Windows 上刚写完的文件可能被 AV/索引器短暂锁定，单次
    rmtree(ignore_errors=True) 会偶发静默失败——差集式清理漏网一次，
    后续任何 diff 都不再包含它，目录永久残留（Task 3 实测根因）。
    """
    all_dirs = set(glob.glob(os.path.join(_PROJECT_ROOT, ".superpowers",
                                          "sdd", "dispatch-*")))
    for d in all_dirs - set(before):
        # 预算 ~2s：首扫锁可超过短预算（Task 4 实测连漏 3 轮后放宽）
        for _ in range(20):
            shutil.rmtree(d, ignore_errors=True)
            if not os.path.isdir(d):
                break
            time.sleep(0.1)


# ===========================================================================
# #9 分诊：真 Bug 不得判只读
# ===========================================================================

MUST_BE_BUG = [
    ("登录失败", "裸『失败』是关键帧——现只有『失败了』在前置表中"),
    ("接口返回500", "『返回』在语境表而非信号表"),
    ("生产数据库挂了", "『挂了』完全缺失"),
    ("线上 Nginx 502 一直不恢复", "『502』+『不恢复』"),
    ("内存一直涨", "『一直』是强故障词，但无写动作时掉进只读"),
    ("页面白屏了", "『白屏』只在 margin 词表"),
    ("支付回调超时", "『超时』缺失"),
    ("用户登录不工作", "『不工作』在信号表，但缺语境词时掉只读"),
]


@pytest.mark.parametrize("task,why", MUST_BE_BUG)
def test_real_failure_is_bug_not_readonly(task, why):
    """描述「已发生的坏行为」必须判 Bug，不得判只读。

    修前实测：`登录失败`→只读、`接口返回500`→只读、`生产数据库挂了`→只读。
    """
    got = wf.classify_scale(task, None)["scale"]
    assert got == "bug", "%r 被判 %s（应 bug）——%s" % (task, got, why)


# ===========================================================================
# #9 分诊：新功能不得判 Bug
# ===========================================================================

MUST_NOT_BE_BUG = [
    ("增加无法登录时的提示", "『无法』是能力缺失描述，不是坏现状"),
    ("实现一个不能重复提交的表单校验", "『不能』同上"),
    ("不能同时上传两个文件的校验功能", "『不能』+『功能』，纯名词短语无写动作"),
    ("设计一个失败重试机制", "『设计…机制』是新功能"),
    ("增加异常恢复逻辑", "『增加…逻辑』是新功能"),
    ("重命名 prefix 变量", "`fix` 命中 prefix 的字母碎片"),
]


@pytest.mark.parametrize("task,why", MUST_NOT_BE_BUG)
def test_new_feature_is_not_bug(task, why):
    """描述「要做的新东西」不得判 Bug。

    修前实测：`增加无法登录时的提示`→Bug、`实现一个不能重复提交的表单校验`→Bug。
    """
    got = wf.classify_scale(task, None)["scale"]
    assert got != "bug", "%r 被判 bug（应非 bug）——%s" % (task, why)


def test_ability_words_not_in_strong_bug():
    """守卫：`无法`/`不能` 不得留在 STRONG_BUG 里。

    它们出现在**新功能需求**里的频率高于故障报告
    （「增加无法登录时的提示」「不能重复提交的校验」）。
    留在强故障表意味着：只要出现这两个词，`:155` 的「新功能语境占优」守卫
    就被 `strong_hits` 自己抵消——守卫形同不存在。
    """
    for word in ("无法", "不能"):
        assert word not in wf.STRONG_BUG, (
            "「%s」仍在 STRONG_BUG，会抵消新功能守卫" % word)


def test_feature_guard_still_works():
    """守卫：新功能语境 + 非强故障词时仍须判非 Bug。

    防的破坏：为了让 `登录失败` 判 Bug 而把守卫整个删掉，
    会导致「设计一个失败重试机制」又被判 Bug。
    """
    got = wf.classify_scale("设计一个失败重试机制", None)["scale"]
    assert got != "bug"


def test_real_failure_with_feature_words_not_readonly():
    """真故障里带了功能词时，至少不得判只读。

    「登录失败，顺便加个提示」= 报Bug + 顺带提需求。机械判定无法可靠区分
    「主诉是故障」还是「主诉是需求」，所以这里**只断言下限**：
    不得落到 readonly。理由：readonly 会跳过根因调查、TDD 复现、red-green 复验
    整条链；而落到 light/medium 仍走 TDD，最坏结果是流程偏重，不是漏检。
    这是「宁可偏重，不可漏检」在本体系的体现。
    """
    got = wf.classify_scale("登录失败，顺便加个提示", None)["scale"]
    assert got != "readonly", "真故障带功能词被判只读，整条根因流程被跳过"


# ===========================================================================
# #10 派发计划：语义字段不得丢
# ===========================================================================

def plan_for(task, files=None, **kw):
    return wf.build_dispatch_plan(task, files=files, **kw)


def test_plan_preserves_semantic_selection_flag():
    """`semantic_selection_required` 必须透传到 plan。

    修前实测：plan["domain"] 只有 4 个键（category/manager_id/expert_name/
    expert_id），`semantic_selection_required` / `selection_basis` /
    `routing_warning` 全部丢弃——产出一份看起来可直接派发的契约。
    """
    p = plan_for("实现用户登录接口", files=5)
    assert "domain" in p
    assert "semantic_selection_required" in p["domain"], (
        "domain 缺 semantic_selection_required；实际键=%s"
        % sorted(p["domain"].keys()))


def test_plan_preserves_selection_basis():
    """`selection_basis` 必须透传（heuristic / semantic / none）。"""
    p = plan_for("实现用户登录接口", files=5)
    assert "selection_basis" in p["domain"], (
        "domain 缺 selection_basis；实际键=%s" % sorted(p["domain"].keys()))


def test_plan_preserves_top_candidates():
    """`top_candidates` 必须透传，否则主控无法看 score_detail 复核。"""
    p = plan_for("实现用户登录接口", files=5)
    assert "top_candidates" in p["domain"], (
        "domain 缺 top_candidates；实际键=%s" % sorted(p["domain"].keys()))


def test_plan_preserves_routing_warning():
    """`routing_warning` 必须透传（低置信度/无专家时主控要据此澄清）。"""
    p = plan_for("实现用户登录接口", files=5)
    assert "routing_warning" in p["domain"], (
        "domain 缺 routing_warning；实际键=%s" % sorted(p["domain"].keys()))


def test_plan_adds_semantic_recheck_when_required():
    """语义精判未完成时，plan 必须显式要求主控复核。

    这是最关键的一条：只透传布尔值还不够——plan 是一份「按此派发」的契约，
    必须在 dispatches 里加一条 orchestrator 动作，否则主控会跳过复核。
    """
    p = plan_for("实现用户登录接口", files=5)
    domain = p["domain"]
    if not domain.get("semantic_selection_required"):
        pytest.skip("本次路由恰好语义确定，无需复核")
    actions = [d for d in p["dispatches"] if d.get("role") == "orchestrator"]
    assert actions, (
        "语义精判待完成但 plan 未要求 orchestrator 复核；dispatches=%s"
        % [(d.get("role"), d.get("action")) for d in p["dispatches"]])
    joined = " ".join(str(d) for d in actions)
    assert "semantic" in joined.lower() or "语义" in joined


def test_high_confidence_recheck_does_not_block_dispatch():
    """高置信度仍需语义复核，但不得同时置 blocking + 派发行。

    旧契约把“语义精判待完成”无条件写成 blocking，导致高置信度任务
    既 blocking 又派发。新契约：高置信度只要求 semantic_recheck 动作；
    只有低置信度/低 margin 才 blocking 并阻断派发。
    """
    p = plan_for("实现用户登录接口", files=5)
    if not p["domain"].get("semantic_selection_required"):
        pytest.skip("本次路由恰好语义确定")
    assert p.get("semantic_recheck", {}).get("required") is True
    assert not p.get("blocking"), "高置信度不得同时 blocking + 派发"


# ===========================================================================
# #11 包装层：语义字段不得丢
# ===========================================================================

def test_skill_entry_forwards_semantic_fields():
    """`handle_skill_invoke` 必须透传语义精判相关字段。

    修前实测：只挑 11 个键返回，
    `'semantic_selection_required' in out` → False，`routing_warning` → False。
    而 SKILL.md 明文要求主控「必须检查这两个字段后再派专家」——
    官方包装层却把强制动作需要的输入削掉了。
    """
    from skill_entry import handle_skill_invoke
    out = handle_skill_invoke("实现用户登录接口")
    for key in ("confidence", "alternatives", "routing_warning",
                "semantic_selection_required", "selection_basis"):
        assert key in out, "包装层丢了 %r；实际键=%s" % (key, sorted(out.keys()))


def test_skill_entry_forwards_top_candidates():
    """`top_candidates` 也要透传（主控靠 score_detail 复核）。"""
    from skill_entry import handle_skill_invoke
    out = handle_skill_invoke("实现用户登录接口")
    assert "top_candidates" in out


def test_skill_entry_error_shape_stable():
    """空任务的错误返回结构必须稳定（不得因透传改造而变）。"""
    from skill_entry import handle_skill_invoke
    out = handle_skill_invoke("")
    assert out["success"] is False
    assert "error" in out


# ===========================================================================
# #25 无 git 时独立性降级
# ===========================================================================

def test_no_git_degrades_independence_to_l1(tmp_path, monkeypatch):
    """无 git 仓库时，审查独立性必须降为 L1（W7）。

    修前实测：本项目无 `.git`，`build_dispatch_plan` 仍输出
    `independence = L0`，理由写「I1+I2+I3 满足」——
    账本记录与事实不符，且 W7 的降级纪律完全不可见。
    """
    monkeypatch.chdir(tmp_path)          # 干净目录，确定无 .git
    p = wf.build_dispatch_plan("实现用户登录接口", files=5)
    reviewer = [d for d in p["dispatches"] if d.get("role") == "reviewer"][0]
    assert reviewer["independence"] == "L1", (
        "无 git 时 independence=%s（应 L1）" % reviewer["independence"])
    assert "git" in reviewer["independence_reason"].lower() or \
        "快照" in reviewer["independence_reason"], (
        "理由未说明降级原因：%s" % reviewer["independence_reason"])


def test_git_repo_keeps_l0(tmp_path, monkeypatch):
    """有 git 仓库时不得无故降级（防一刀切）。

    防的破坏：为了满足 W7 而让 independence 恒为 L1，
    等于把「主控自审降级」变成常态，L0 失去意义。
    """
    # 空 .git 目录**不是**仓库——新版 detect_git 要求含 HEAD（P6 A-5 修复）。
    # 所以这里的夹具必须建成真仓库形态，否则测的是「空目录是否被误认」。
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    p = wf.build_dispatch_plan("实现用户登录接口", files=5)
    reviewer = [d for d in p["dispatches"] if d.get("role") == "reviewer"][0]
    assert reviewer["independence"] == "L0", (
        "有 git 时 independence=%s（应 L0）" % reviewer["independence"])


def test_plan_reports_git_state(tmp_path, monkeypatch):
    """plan 必须显式报告 git 状态与证据模式，便于消费方判断证据链。

    修前实测：plan 键为 ['dispatches','domain','parallel','scale','stages','task']，
    无任何 git 相关字段。
    """
    monkeypatch.chdir(tmp_path)
    p = wf.build_dispatch_plan("实现用户登录接口", files=5)
    assert "git" in p, "plan 缺 git 状态字段；实际键=%s" % sorted(p.keys())
    assert p["git"] is False
    assert "evidence_mode" in p, (
        "plan 缺 evidence_mode（无 git 应说明走快照证据）；实际键=%s"
        % sorted(p.keys()))


def test_git_repo_evidence_mode_is_diff(tmp_path, monkeypatch):
    """有 git 时证据模式为 diff（与无 git 的快照模式区分）。"""
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    p = wf.build_dispatch_plan("实现用户登录接口", files=5)
    assert p["git"] is True
    assert "diff" in str(p["evidence_mode"]).lower()


# ===========================================================================
# 只读路径的形状一致性
# ===========================================================================

def test_readonly_plan_has_consistent_shape():
    """只读分支的 plan 也应有 git/evidence_mode 字段（消费方不必写两套防御）。

    修前实测：只读分支返回的 plan 只有
    `task`/`scale`/`stages`/`dispatches`/`note`，没有 `domain`/`parallel`，
    消费方必须按分支写不同形状的读取代码。
    """
    sdd_root = os.path.join(_PROJECT_ROOT, ".superpowers", "sdd")
    before = set(glob.glob(os.path.join(sdd_root, "dispatch-*")))
    try:
        p = wf.build_dispatch_plan("分析一下这个模块的架构")
        assert p["scale"]["scale"] == "readonly"
        assert "git" in p, "只读分支缺 git 字段"
        assert "evidence_mode" in p, "只读分支缺 evidence_mode"
    finally:
        # 顺手微修（Task 2 审查 CONCERNS 裁决）：本测试的 readonly 派发会
        # 落盘 dispatch.json——按差集自清，防每次全量跑泄漏 1 个目录
        _cleanup_new_dispatch_dirs(before)


# ===========================================================================
# P2-4（2026-11-19）：git 探测基准 = 指定 root，而非进程 cwd
#
# 抓的破坏：detect_git() 无参调用，以 os.getcwd() 为探测起点。cwd 恰位于
# 无关 git 仓库内时 has_git 误判为 True → _pick_reviewer 标 L0 并写
# evidence_mode=diff(BASE..HEAD)，伪造审查独立性证据链（假阳性比假阴性更险，
# 假阴性仅降级 L1 有标记可声明）。
#
# 修法：build_dispatch_plan 增 root 参数 → detect_git(root)；CLI plan 增 --root。
# 对照 workflow_check.detect_env(root) 已有的正确范式。
# ===========================================================================

def _make_git_repo(path):
    """在 path 下建一个真 git 仓库形态（含 .git/HEAD，非空目录）。"""
    (path / ".git").mkdir(parents=True)
    (path / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")


def test_git_detection_uses_root_not_cwd(tmp_path, monkeypatch):
    """P2-4 假阳性回归：cwd 在无关 git 仓内、root 指向非 git 目录 → 应判无 git。

    修前实测：build_dispatch_plan 不接 root、detect_git 用 cwd → has_git=True、
    evidence_mode=diff、reviewer L0（伪造独立性）。修后必须 has_git=False、
    snapshot、reviewer L1。
    """
    fake_repo = tmp_path / "unrelated-repo"
    _make_git_repo(fake_repo)
    clean_dir = tmp_path / "clean"          # 非 git 目录
    clean_dir.mkdir()
    monkeypatch.chdir(fake_repo)            # cwd 在无关仓库内
    p = wf.build_dispatch_plan("实现用户登录接口", files=5, root=str(clean_dir))
    reviewer = [d for d in p["dispatches"] if d.get("role") == "reviewer"][0]
    assert p["git"] is False, (
        "P2-4：root 在非 git 目录时 git 应 False，实际 %s（cwd 假阳性未修）"
        % p["git"])
    assert p["evidence_mode"].startswith("snapshot"), (
        "P2-4：evidence_mode 应 snapshot，实际 %s" % p["evidence_mode"])
    assert reviewer["independence"] == "L1", (
        "P2-4：无 git 时 reviewer 应 L1，实际 %s（伪造 L0 未修）"
        % reviewer["independence"])


def test_root_in_git_repo_keeps_l0(tmp_path, monkeypatch):
    """P2-4 防过度修复：root 指向真 git 仓、cwd 在非仓目录 → 仍应 L0。"""
    real_repo = tmp_path / "real-repo"
    _make_git_repo(real_repo)
    clean_dir = tmp_path / "elsewhere"
    clean_dir.mkdir()
    monkeypatch.chdir(clean_dir)            # cwd 在非仓目录
    p = wf.build_dispatch_plan("实现用户登录接口", files=5, root=str(real_repo))
    reviewer = [d for d in p["dispatches"] if d.get("role") == "reviewer"][0]
    assert p["git"] is True, "P2-4：root 在真 git 仓时 git 应 True"
    assert reviewer["independence"] == "L0", (
        "P2-4：root 有 git 时 reviewer 应 L0，实际 %s（一刀切降级误伤）"
        % reviewer["independence"])


# ===========================================================================
# P3 证据契约 + 只读工具权限
# ===========================================================================

def test_bug_plan_declares_p3_evidence(tmp_path):
    """Bug 规模必须在 plan 中声明 P3 落盘位置与关键证据。"""
    p = wf.build_dispatch_plan("登录失败", root=str(tmp_path))
    assert p["scale"]["scale"] == "bug"
    ev = p.get("p3_evidence") or {}
    assert ev.get("required") is True
    assert "Bug Investigation" in str(ev.get("primary"))
    keys = " ".join(ev.get("key_evidence") or [])
    for needle in ("根因", "假设", "双确认", "RED", "red-green", "全量回归"):
        assert needle in keys, "Bug P3 证据清单缺 %r" % needle


def test_readonly_plan_exposes_tool_policy():
    """只读 plan 必须给出工具白名单/黑名单，且 analyst 派发携带同一策略。"""
    sdd_root = os.path.join(_PROJECT_ROOT, ".superpowers", "sdd")
    before = set(glob.glob(os.path.join(sdd_root, "dispatch-*")))
    try:
        p = wf.build_dispatch_plan("分析一下这个模块的架构")
        assert p["scale"]["scale"] == "readonly"
        policy = p.get("tool_policy") or {}
        assert policy.get("mode") == "readonly"
        assert (p.get("p3_evidence") or {}).get("required") is False, (
            "只读任务不写代码，P3 不应强制落盘；dispatch.json 是审计锚点")
        allowed = " ".join(policy.get("allowed") or [])
        denied = " ".join(policy.get("denied") or [])
        assert "Read" in allowed and "Grep" in allowed
        assert "Write" in denied and "Edit" in denied
        assert "git add" in denied or "git commit" in denied
        analysts = [d for d in p["dispatches"] if d.get("role") == "analyst"]
        assert analysts, "只读任务必须派 analyst"
        assert analysts[0].get("tool_policy", {}).get("mode") == "readonly"
        assert "只读工具权限" in analysts[0].get("prompt_prefix", "")
        roles = {d.get("role") for d in p["dispatches"]}
        assert "implementer" not in roles and "reviewer" not in roles
    finally:
        _cleanup_new_dispatch_dirs(before)


def test_nonreadonly_plan_has_p3_contract(tmp_path):
    """轻/中/大任务也必须显式声明 P3 四段，不能靠口头自觉。"""
    p = wf.build_dispatch_plan("增加用户登录接口", root=str(tmp_path))
    assert p["scale"]["scale"] in ("light", "medium", "large")
    ev = p.get("p3_evidence") or {}
    assert ev.get("required") is True
    assert "Baseline" in str(ev.get("primary"))
    assert "Review" in str(ev.get("primary"))
    assert "Integration Verification" in str(ev.get("primary"))


# ===========================================================================
# 批次 2：margin 置信度 + 低置信度硬门
# ===========================================================================

def test_router_meta_task_routes_to_search_relevance(tmp_path):
    """讨论“专家路由/准确率/误判”时，应路由到搜索相关性，而不是测试域。"""
    task = "分析为什么专家路由容易按词面误判，并设计提高准确率，包括测试/评估"
    p = wf.build_dispatch_plan(task, files=5, root=str(tmp_path))
    assert p["scale"]["scale"] == "readonly"
    assert p["domain"]["category"] == "data-database", p["domain"].get("confidence_detail")
    assert p["domain"]["expert_name"] == "搜索相关性工程师", p["domain"]
    assert p["domain"]["confidence"] >= 0.5
    roles = [d.get("role") for d in p["dispatches"]]
    assert "analyst" in roles, "只读任务应派 analyst：%r" % roles
    assert not p.get("blocking"), "分类已确定，不应误置 blocking"


def test_install_meta_task_routes_to_engineering_quality(tmp_path):
    """“安装注册 + 审计/操作”应归工程效能，而不是财务域。"""
    task = "修复两类问题：Claude Code 安装注册、审计与操作流程"
    p = wf.build_dispatch_plan(task, files=5, root=str(tmp_path))
    assert p["domain"]["category"] == "engineering-quality", p["domain"].get("confidence_detail")
    assert p["domain"]["confidence"] >= 0.5
    assert p["domain"].get("expert_name") == "开发者工具工程师", p["domain"].get("expert_name")
    roles = [d.get("role") for d in p["dispatches"]]
    assert "implementer" in roles, "非只读任务应派 implementer：%r" % roles
    assert not p.get("blocking"), "分类已确定，不应误置 blocking"


def test_confidence_detail_is_exposed():
    """路由结果必须暴露 confidence_detail，主控才能判断为何低分。"""
    r = wf._route_domain("分析为什么专家路由容易按词面误判")
    domain = r[0]
    detail = domain.get("confidence_detail") or {}
    for key in ("evidence", "top_score", "second_score", "margin",
                "intent", "intent_downgraded"):
        assert key in detail, "confidence_detail 缺 %s：%r" % (key, detail)
