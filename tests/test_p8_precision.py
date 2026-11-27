# -*- coding: utf-8 -*-
"""P8 · 工具精度提升（A-9 / A-14 / A-15）—— 按老板裁决的范围

三位专家与主控实测共同确认了三条**精度缺陷**，并裁决了修法范围。
本文件按裁决结果写测试，并记录「为什么不按更大的方案做」。

### 裁决摘要

| 项 | 裁决 | 理由 |
|---|---|---|
| **A-15** | **改配置 3 个字符**，不写代码 | 实测：light + 全完成 + 无 plan → 3 条 FAIL **全部且仅有**来自 `plan_required`。实现 `条` 让它们 SKIP 后 **rc 变 0** —— 即「没有基线记录、没有集成重测也能过」，那是新假绿 |
| **A-14** | 最小范围：review 检查 + S8 跟随配置 + snapshot 降级 | 通用校验器要改 180+ 行、动 6 个检查器，回归面过大；真正需要的只有三处 |
| **A-9** | 修 2 处有 rc 后果的 + AST lint 防复发 | 只有 `_apply_ledger_scale_conflict` 与 `S8.PARKED` 有 rc/真实性后果，其余 4 处只是文案失真 |

### A-15 为什么不实现 `条`（留给后人的关键记录）

两位专家结论相反，主控实测后采纳「不实现」：

工作流架构师主张实现触发引擎（`apply_when` + 三道不变量）。
最小变更工程师主张改配置，理由是「`条` 的触发判据只能是调用方给没给 `--plan`，
而 `--plan` 是命令行参数不是项目属性 —— 等于『我不传参数 ⇒ 门禁不查我』，
与 P6 已判 FAIL 的 readonly 后门同构」。

**主控实证**：`light` + 任务全完成 + 无 `--plan` → 恰好 3 条 FAIL，全部是
`unverifiable:plan_required`。实现 `条` 让它们 SKIP ⇒ rc=0，而 tasks.md 是否
真有基线记录、计划是否真有 `## Integration Verification`，**一点都没被验证**。
最小变更工程师的预言成立。

另有一条支持「改配置」的代码内证据：`LIGHT_KEEP["S3"]` 把 `plan_exists`
列为 light 的机器承重项 —— 说明原作者意图是 **light 必须有（简化）计划**，
`trim_matrix.light.S3 = "条"` 是写错的标记，不是未实现的功能。

**不实现代码，但把「条 当前等价于必」写进设计文档**，消除三方口径不一
（`workflow.json` 说条 / `SKILL.md:93` 说「其余视情况」/ 代码按必执行）。
"""

import ast
import io
import os
import shutil
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts import workflow_check as wc  # noqa: E402

SOURCE = PROJECT_ROOT / "scripts" / "workflow_check.py"

PLAN_FULL = """### Task 1: a
## Baseline
x
## Review
independence: L0
implementer: 软件架构师
reviewer: 代码审查员
spec: \u2705
## Rulings
x
## Integration Verification
x
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
"""


@pytest.fixture
def proj(tmp_path):
    """证据齐备的最小项目（含 workspace）。"""
    (tmp_path / "openspec/changes/demo/specs/auth").mkdir(parents=True)
    (tmp_path / "openspec/specs/auth").mkdir(parents=True)
    (tmp_path / "docs").mkdir()
    (tmp_path / ".superpowers/sdd/p").mkdir(parents=True)
    for name in ("proposal.md", "design.md"):
        (tmp_path / "openspec/changes/demo" / name).write_text(
            "x\n", encoding="utf-8", newline="")
    (tmp_path / "openspec/changes/demo/tasks.md").write_text(
        "- [x] 1.1 a\n", encoding="utf-8", newline="")
    (tmp_path / "openspec/changes/demo/specs/auth/spec.md").write_text(
        "x\n", encoding="utf-8", newline="")
    (tmp_path / "openspec/changes/demo/.openspec.yaml").write_text(
        "n: d\n", encoding="utf-8", newline="")
    (tmp_path / "openspec/specs/auth/spec.md").write_text(
        "x\n", encoding="utf-8", newline="")
    (tmp_path / "docs/p.md").write_text(PLAN_FULL, encoding="utf-8", newline="")
    (tmp_path / ".superpowers/sdd/p/progress.md").write_text(
        "# SDD ledger — plan: docs/p.md\n\n"
        "## Dispatches\n\n"
        # G5/G6 派发证据（dispatch 门禁）：完成态必须有 implementer/reviewer
        # 派发行，专家名与 category 必须与 config/experts.json 一致。
        "dispatch 1 role=implementer agent=\"软件架构师\" "
        "category=backend-architecture instance=1 base=abc123 "
        "brief=.superpowers/sdd/p/task-1-brief.md "
        "report=.superpowers/sdd/p/task-1-report.md changeset=-\n"
        "dispatch 1 role=reviewer agent=\"代码审查员\" "
        "category=engineering-quality instance=1 base=abc123 "
        "brief=.superpowers/sdd/p/task-1-brief.md "
        "report=.superpowers/sdd/p/review-1.md changeset=-\n\n"
        "independence: L0\n"
        "Task 1: complete (abc)\n", encoding="utf-8", newline="")
    (tmp_path / ".superpowers/sdd/p/task-1-brief.md").write_text(
        "b\n", encoding="utf-8", newline="")
    (tmp_path / ".superpowers/sdd/p/task-1-report.md").write_text(
        "r\n", encoding="utf-8", newline="")
    return tmp_path


def item(rep, id_):
    for i in rep.items:
        if i.get("id") == id_:
            return i
    raise AssertionError("找不到 id=%r；实际 ids=%s"
                         % (id_, sorted(x.get("id") or "" for x in rep.items)))


# ===========================================================================
# A-15 —— 改配置消除声明与行为的不一致
# ===========================================================================

def test_light_trim_no_longer_claims_conditional():
    """`trim_matrix.light` 不得对 S4/S7 再声称「条」。

    裁决：`条` 在当前实现等价于 `必`（只有 S2/S8 有真触发实现）。
    既然不打算实现 S4/S7 的触发引擎，配置就必须说真话 —— 否则：
      - 读者以为 light 下 S4 会条件触发，实际必然要求 `--plan`
      - `workflow_check` 的报错文案与配置矛盾

    实测依据：`light` + 全完成 + 无 `--plan` → 恰好 3 条 FAIL，全部是
    `unverifiable:plan_required`。若实现 `条` 让它们 SKIP，rc 会变 0，
    而基线/集成重测从未被验证 —— 那是新假绿。

    **注意 S2 与 S8 保留「条」**：它们有真正的触发实现
    （`inapplicable:trigger:openspec` / `inapplicable:no_change`），
    触发条件是**项目属性**（openspec root 是否存在）而非调用方参数。
    """
    wf_data = wc.load_workflow()
    light = wf_data["trim_matrix"]["light"]
    bad = [sid for sid in ("S4", "S7") if light.get(sid) == "条"]
    assert not bad, (
        "trim_matrix.light 仍对 %s 声称「条」，但实现里「条」等价于「必」——"
        "配置在说谎。应改为「必」（行为不变，口径一致）" % bad)


def test_light_still_requires_plan_when_marked_required():
    """反例（关键）：light 仍必须要求计划文档 —— 不得因消除「条」而放宽。

    这是 A-15 的底线：改配置只是让**口径**一致，不是**放宽**门禁。
    `LIGHT_KEEP["S3"]` 把 `plan_exists` 列为机器承重项，说明原作者
    意图就是「light 必须有（简化）计划」。
    """
    rep, _ = wc.run(change="demo", plan=None, scale="light", root=str(proj))
    assert item(rep, "S3.PLAN")["status"] == wc.FAIL, (
        "light 无 plan 时 S3 未被判 FAIL —— 门禁被放宽了")


def test_light_without_plan_still_fails_on_baseline():
    """light 无 plan 时基线仍判 FAIL（同上：口径统一，不放宽）。

    记录现状：这是**正确行为**，不是缺陷。`minimum_gates.light` 未列基线
    确实与 `trim_matrix.light.S4` 的语义有张力，但把张力消解成「跳过」
    会造新假绿。正确做法是承认「light 也要一份极简计划（含 Baseline 段）」。
    """
    rep, _ = wc.run(change="demo", plan=None, scale="light", root=str(proj))
    assert item(rep, "S4.BASELINE")["status"] == wc.FAIL


def test_trim_modes_still_contain_all_four():
    """回归守卫：`条` 仍在合法取值集合里（S2 用它，且将来可能实现）。"""
    assert "条" in wc.TRIM_MODES
    wf_data = wc.load_workflow()
    assert wf_data["trim_matrix"]["light"].get("S2") == "条", (
        "S2 的「条」是真实现了的（openspec root 触发），不该被一起改掉")


def test_self_check_passes_after_config_change():
    """回归守卫：改配置后自检仍须通过。"""
    assert wc.self_check(wc.load_workflow()) == []


# ===========================================================================
# A-14 —— 最小范围：review 检查 + S8 跟随配置 + snapshot 降级
# ===========================================================================

def test_review_report_missing_is_not_silent(proj):
    """`review-<N>.md`（配置 required:true）从未被读 → 必须补检查。

    实测的满绿假绿：`review-1.md` 完全不存在，仍得到
    `rc=0 / OK 34 / FAIL 0 / SKIP 0`。S6 只读计划文档里人自己写的
    `spec ✅ / quality`，从不列 workspace 目录 —— 名义上核「审查双结论」，
    实际只核计划文档文本。

    本用例断言：workspace 存在但无任何 review 文件时，必须有检查项覆盖它
    （不能静默）。

    P8 真断言（原断言 `"review" in id` 被既有 S6.REVIEW 子串假满足——
    「测试假通过」教训复发）：workspace 存在但零个 review 文件时，
    S6.REVIEW_REPORT 必须 FAIL。
    """
    rep, _ = wc.run(change="demo", plan="docs/p.md", scale="medium", root=str(proj))
    it = item(rep, "S6.REVIEW_REPORT")
    assert it["status"] == wc.FAIL, (
        "workspace 存在但无任何 review 文件时 S6.REVIEW_REPORT 必须 FAIL，"
        "实际 %s / %s" % (it["status"], it["detail"]))


def test_review_report_present_is_ok(proj):
    """反例：review 文件存在时该项应通过（不误报）。"""
    (proj / ".superpowers/sdd/p/review-1.md").write_text(
        "## 审查\nspec: ✅\nquality: APPROVED\n", encoding="utf-8", newline="")
    rep, _ = wc.run(change="demo", plan="docs/p.md", scale="medium", root=str(proj))
    bad = [i for i in rep.items
           if "review" in (i.get("id") or "").lower() and i["status"] == wc.FAIL]
    assert not bad, "review 文件存在却被判 FAIL：%s" % [
        (i["id"], i["detail"]) for i in bad]


def test_review_report_skipped_when_workspace_deleted(proj):
    """反例（防跨阶段假红）：workspace 已按铁律 11 删除 → SKIP inapplicable。

    A-14 裁决的硬约束：交付后回查门禁，workspace 清理是正常终态，
    review 报告随之消失不是缺陷——必须 SKIP 而非 FAIL。
    """
    shutil.rmtree(str(proj / ".superpowers"))
    rep, _ = wc.run(change="demo", plan="docs/p.md", scale="medium", root=str(proj))
    it = item(rep, "S6.REVIEW_REPORT")
    assert it["status"] == wc.SKIP and (it.get("reason") or "").startswith("inapplicable:"), (
        "workspace 已删时 review 检查应 SKIP inapplicable（防跨阶段假红），"
        "实际 %s / %s" % (it["status"], it.get("reason")))


def test_snapshot_artifacts_are_not_required(proj):
    """`snapshot-before/after-<N>.json` 必须降级为非必需。

    实测：全仓 `grep snapshot-before|snapshot-after` 只有 `config/workflow.json`
    两处命中 —— **没有任何代码或指令产出它**，也没有 sha256 实现。
    `required: true` 等于让检查器去查一个从不产生的东西。

    降级而不实现，是「声明描述了一个不存在的动作」的正确处置。
    """
    wf_data = wc.load_workflow()
    s5 = [s for s in wf_data["stages"] if s["id"] == "S5"][0]
    snaps = [a for a in s5["artifacts"] if "snapshot-" in a["path"]]
    assert snaps, "找不到 snapshot 声明"
    still_required = [a["path"] for a in snaps if a.get("required")]
    assert not still_required, (
        "snapshot 产物仍标 required=true，但全仓无产出方：%s" % still_required)


def test_s8_spec_check_follows_config_path(proj):
    """S8 的主 spec 检查必须跟随配置声明的路径，而非硬编码 `openspec/specs`。

    实测：把配置改成 `specs2/<capability>/spec.md` 并把证据搬到 `specs2/`，
    修前 S8 仍报 `openspec/specs` 缺失 FAIL —— 它硬编码了路径。
    这是 A-14「读了但没按配置读」的活证：任何字面量扫描都会判它「有消费者」。
    """
    wf_data = wc.load_workflow()
    s8 = [s for s in wf_data["stages"] if s["id"] == "S8"][0]
    target = None
    for a in s8["artifacts"]:
        if a.get("glob") and "spec.md" in a["path"]:
            target = a
            break
    assert target is not None, "S8 无 spec glob 声明"

    target["path"] = target["path"].replace("openspec/specs", "specs2")
    (proj / "specs2/auth").mkdir(parents=True)
    (proj / "specs2/auth/spec.md").write_text("## Purpose\n认证\n", encoding="utf-8", newline="")
    shutil.rmtree(str(proj / "openspec/specs"), ignore_errors=True)

    orig = wc.load_workflow
    wc.load_workflow = lambda *a, **k: wf_data
    try:
        rep, _ = wc.run(change="demo", plan="docs/p.md", scale="medium", root=str(proj))
    finally:
        wc.load_workflow = orig

    it = item(rep, "S8.SPEC_SYNC")
    assert it["status"] == wc.OK, (
        "S8 未跟随配置路径：%s（%s）" % (it["status"], it["detail"]))


def test_s8_spec_check_fails_when_config_path_empty(proj):
    """反例：配置路径下确实没有 spec → 必须 FAIL（不能因为跟随配置就恒过）。"""
    wf_data = wc.load_workflow()
    s8 = [s for s in wf_data["stages"] if s["id"] == "S8"][0]
    for a in s8["artifacts"]:
        if a.get("glob") and "spec.md" in a["path"]:
            a["path"] = a["path"].replace("openspec/specs", "specs2")
    shutil.rmtree(str(proj / "openspec/specs"), ignore_errors=True)

    orig = wc.load_workflow
    wc.load_workflow = lambda *a, **k: wf_data
    try:
        rep, _ = wc.run(change="demo", plan="docs/p.md", scale="medium", root=str(proj))
    finally:
        wc.load_workflow = orig

    assert item(rep, "S8.SPEC_SYNC")["status"] == wc.FAIL, (
        "配置路径下无 spec 却判 OK")


def test_non_required_artifact_absence_is_not_fail(proj):
    """`required: false` 的产物缺失不得判 FAIL。

    修前实测：非必需产物缺失 emit WARN 但 `reason=None`，被
    `enforce_reasons()` 机械改判 FAIL —— 「非必需缺失」变成了 FAIL，
    与声明语义相反。
    """
    wf_data = wc.load_workflow()
    s2 = [s for s in wf_data["stages"] if s["id"] == "S2"][0]
    s2["artifacts"].append({
        "path": "openspec/changes/<change>/optional-extra.md",
        "producer": "test", "required": False,
    })

    orig = wc.load_workflow
    wc.load_workflow = lambda *a, **k: wf_data
    try:
        rep, _ = wc.run(change="demo", plan="docs/p.md", scale="medium", root=str(proj))
    finally:
        wc.load_workflow = orig

    bad = [i for i in rep.items
           if "optional-extra" in (i.get("id") or "") and i["status"] == wc.FAIL]
    assert not bad, "非必需产物缺失被判 FAIL：%s" % [
        (i["id"], i.get("reason")) for i in bad]


def test_required_artifact_absence_still_fails(proj):
    """反例：`required: true` 的产物缺失仍必须 FAIL。"""
    (proj / "openspec/changes/demo/design.md").unlink()
    rep, _ = wc.run(change="demo", plan="docs/p.md", scale="medium", root=str(proj))
    assert item(rep, "S2.ARTIFACT:design.md")["status"] == wc.FAIL


# ===========================================================================
# A-9 —— 修 2 处有 rc 后果的 + AST lint 防复发
# ===========================================================================

def test_unreadable_ledger_blocks_readonly_escape(proj):
    """readonly + 账本不可读时不得 rc=0（真实后门）。

    实测（修前）：`--scale readonly`、不传 change/plan、账本含无效 UTF-8 →
    `read()` 返回 `None` → `or ""` → `parse_scale_section("")` 返回 None →
    `_apply_ledger_scale_conflict` 静默 `return` → **rc=0，不发任何检查项**。

    注意这个场景的严重性：readonly 下 S1–S8 全部被 trim 裁剪，
    账本是**唯一**的检查对象。它被静默跳过，整次核对就什么都没查。
    """
    (proj / ".superpowers/sdd/p/progress.md").write_bytes(
        b"# SDD ledger \xff\xfe # \xd6\xd0\xc8\xce\xce\xf1\n"
        b"## Scale\n\xd6\xd0\xc8\xce\xce\xf1\n")
    assert wc.read(str(proj / ".superpowers/sdd/p/progress.md")) is None

    rep, _ = wc.run(change=None, plan=None, scale="readonly", root=str(proj))
    assert rep.has_fail(), (
        "账本不可读却 rc=0 —— S1-S8 全被裁剪后，整次核对什么都没查。"
        "items=%s" % [(i.get("id"), i["status"]) for i in rep.items])


def test_missing_scale_section_blocks_readonly_escape(proj):
    """反例（同一后门的另一条路）：账本可读但缺 `## Scale` 段也不得 rc=0。

    这是最小变更工程师指出的：只修 `or ""` 只是堵一条路 ——
    删掉 `## Scale` 段照样能放行（`section_body` 返回空 → 静默 return）。
    本用例确保两条路都堵。
    """
    (proj / ".superpowers/sdd/p/progress.md").write_text(
        "# SDD ledger — plan: docs/p.md\n\nindependence: L0\n"
        "Task 1: complete (abc)\n", encoding="utf-8", newline="")
    rep, _ = wc.run(change=None, plan=None, scale="readonly", root=str(proj))
    assert rep.has_fail(), (
        "账本缺 ## Scale 段却 rc=0 —— 降级检测静默失效")


def test_unreadable_ledger_is_not_ok_for_parked(proj):
    """账本不可读时 PARKED 检查不得判 OK「无残留」。

    修前实测：`read(ledger) or ""` → 空串 → `parked = 0` →
    `[OK] 无 PARKED 残留`。即「查不了」被印成「查过且干净」。
    """
    (proj / ".superpowers/sdd/p/progress.md").write_bytes(
        b"# SDD ledger \xff\xfe invalid\n")
    rep, _ = wc.run(change="demo", plan="docs/p.md", scale="medium", root=str(proj))
    assert item(rep, "S8.PARKED")["status"] != wc.OK, (
        "不可读账本被判 OK：%s" % item(rep, "S8.PARKED")["detail"])


def test_readable_ledger_without_parked_still_ok(proj):
    """反例（关键）：账本正常且无 PARKED → 仍必须判 OK。

    防的破坏：为了让「读不出来」不判 OK 而让所有情况都不判 OK。
    """
    rep, _ = wc.run(change="demo", plan="docs/p.md", scale="medium", root=str(proj))
    assert item(rep, "S8.PARKED")["status"] == wc.OK


def test_empty_ledger_is_not_ok_for_parked(proj):
    """反例：账本存在且确实为空 → 不是「无残留」，而是「无内容可查」。

    空文件对「无 PARKED」这个负谓词的证明力其实完备（空文件确实不含 PARKED），
    但它是**格式异常**（账本至少有身份行）。判 WARN 更诚实。
    """
    (proj / ".superpowers/sdd/p/progress.md").write_text(
        "", encoding="utf-8", newline="")
    rep, _ = wc.run(change="demo", plan="docs/p.md", scale="medium", root=str(proj))
    assert item(rep, "S8.PARKED")["status"] != wc.OK


def test_no_read_or_empty_coalescing_in_source():
    """AST lint：`read(...) or ""` 不得再有（A-9 防复发）。

    这是把教训变成机械约束。三个实现要点（都是踩过的坑）：

    1. **lint 自己必须用 `utf-8-sig` 读源码** —— 本机
       `getpreferredencoding()` 是 cp936，源文件含中文与 `—`，
       用默认编码读会 UnicodeDecodeError，这条护栏会自己先炸。
    2. **不放进 `self_check()`** —— 那是「配置↔代码结构一致性」，
       塞源码风格规则是类别错误。
    3. **不用 grep** —— `(item["reason"] or "")` 有十来处合法用法
       （dict 默认值、`parse_task_lines` 的 `text or ""`），
       字符串级规则全误报，必须走 AST 且限定被调名。
    """
    src = io.open(str(SOURCE), "r", encoding="utf-8-sig").read()
    bad = []
    for node in ast.walk(ast.parse(src)):
        if not (isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or)):
            continue
        core, rhs = node.values[0], node.values[-1]
        while isinstance(core, ast.IfExp):
            core = core.body
        name = (getattr(getattr(core, "func", None), "id", None)
                or getattr(getattr(core, "func", None), "attr", None))
        if name in ("read", "read_required") and \
                isinstance(rhs, ast.Constant) and rhs.value == "":
            bad.append((node.lineno, name))
    assert not bad, (
        "`read(...) or \"\"` 三态混同回潮（行号, 被调名）：%s\n"
        "它把「文件不存在 / 空 / 读不出」压成一格，"
        "于是「查不了」被印成「查过且干净」。要合流请显式判三态。" % sorted(bad))
