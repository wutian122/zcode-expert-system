# -*- coding: utf-8 -*-
"""P6 · 复核审查发现项的回归测试（双向断言）

**这批测试的由来**：P1–P5 交付后做了异域复核审查，发现 5 项必须修 + 4 项强烈建议。
其中两条是**零门槛假绿**（BOM、readonly 逃逸），一条是**大面积误判**（17/17）。

**为什么上一轮 322 条测试全绿却漏掉这些**：因为断言是**单向的**——
只测了「该判 bug 的判了 bug」，没测「不该判 bug 的没判」。
本文件刻意对每一处修复都写**正例 + 反例**。

**安全边界**：所有文件路径都由 pytest `tmp_path` 直接拼出，
不使用任何通用的「按传入路径写文件」辅助函数——
每一处写入都在用例内联，路径写死，便于审阅。夹具由 pytest 自动清理。

分组：
  A. P1-A1 BOM 导致假绿（与 OpenSpec 真相源对拍）
  B. P1-A2 readonly 逃逸（账本发现不依赖 --plan）
  C. P1-A3 ## Scale 中文与模板照抄
  D. P2-A1 classify_scale 重复定义
  E. P2-A2 现象词自证共现（17 条误判）
  F. P2-A4 移除 无法/不能 后的功能词回归
  G. P2-A5 git 探测四场景
  H. P3 EPIPE 与静默空输出
"""

import ast
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import zcode_dev_workflow as wf  # noqa: E402
from scripts import workflow_check as wc  # noqa: E402

HOOK = PROJECT_ROOT / "hooks" / "prepend-global-rules-reminder.mjs"

PLAN = """### Task 1: a
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

DEFAULT_LEDGER = ("# SDD ledger — plan: docs/p.md\n\n"
                  # G5/G6 派发证据（dispatch 门禁）：完成态必须有
                  # implementer/reviewer 派发行
                  "## Dispatches\n\n"
                  "dispatch 1 role=implementer agent=\"软件架构师\" "
                  "category=backend-architecture instance=1 base=abc "
                  "brief=.superpowers/sdd/p/task-1-brief.md "
                  "report=.superpowers/sdd/p/task-1-report.md changeset=-\n"
                  "dispatch 1 role=reviewer agent=\"代码审查员\" "
                  "category=engineering-quality instance=1 base=abc "
                  "brief=.superpowers/sdd/p/task-1-brief.md "
                  "report=.superpowers/sdd/p/review-1.md changeset=-\n\n"
                  "independence: L0\nTask 1: complete (abc)\n")


@pytest.fixture
def proj(tmp_path):
    """证据齐备的最小项目。所有写入都是内联的固定路径。"""
    (tmp_path / "openspec/changes/demo/specs/auth").mkdir(parents=True)
    (tmp_path / "openspec/specs/auth").mkdir(parents=True)
    (tmp_path / "docs").mkdir()
    (tmp_path / ".superpowers/sdd/p").mkdir(parents=True)

    (tmp_path / "openspec/changes/demo/proposal.md").write_text(
        "x\n", encoding="utf-8", newline="")
    (tmp_path / "openspec/changes/demo/design.md").write_text(
        "x\n", encoding="utf-8", newline="")
    (tmp_path / "openspec/changes/demo/tasks.md").write_text(
        "- [x] 1.1 a\n", encoding="utf-8", newline="")
    (tmp_path / "openspec/changes/demo/specs/auth/spec.md").write_text(
        "x\n", encoding="utf-8", newline="")
    (tmp_path / "openspec/changes/demo/.openspec.yaml").write_text(
        "n: d\n", encoding="utf-8", newline="")
    (tmp_path / "openspec/specs/auth/spec.md").write_text(
        "x\n", encoding="utf-8", newline="")
    (tmp_path / "docs/p.md").write_text(PLAN, encoding="utf-8", newline="")
    (tmp_path / ".superpowers/sdd/p/progress.md").write_text(
        DEFAULT_LEDGER, encoding="utf-8", newline="")
    (tmp_path / ".superpowers/sdd/p/task-1-brief.md").write_text(
        "b\n", encoding="utf-8", newline="")
    (tmp_path / ".superpowers/sdd/p/task-1-report.md").write_text(
        "r\n", encoding="utf-8", newline="")
    return tmp_path


# ===========================================================================
# A. P1-A1 —— BOM 导致假绿（与 OpenSpec 真相源对拍）
# ===========================================================================

def test_bom_tasks_first_line_not_dropped(proj):
    """BOM 开头的未完成任务必须被计入。

    **假绿方向（极易漏测）**：BOM 让首行未完成任务从分子分母同时消失 →
    done==total → 归档门禁通过，而 OpenSpec 判 1/2 未完成。
    Windows 记事本、多数编辑器默认存 UTF-8 with BOM。
    """
    (proj / "openspec/changes/demo/tasks.md").write_text(
        "\ufeff- [ ] 1.1 未完成\n- [x] 1.2 完成\n", encoding="utf-8", newline="")

    text = wc.read(str(proj / "openspec/changes/demo/tasks.md"))
    c = wc.count_checkboxes(text)
    assert c["todo"] + c["other"] == 1, (
        "BOM 让首行未完成任务消失了：%s（应为 done=1, todo=1）" % c)

    rep, _ = wc.run(change="demo", plan="docs/p.md", scale="medium", root=str(proj))
    item = [i for i in rep.items if i["id"] == "S8.COUNT"][0]
    assert item["status"] == wc.FAIL, (
        "有未完成任务却判 %s：%s" % (item["status"], item["detail"]))


def test_bom_plan_sections_still_detected(proj):
    """BOM 开头的计划文档不得让首段检测失效（反向假红）。"""
    (proj / "docs/p.md").write_text("\ufeff" + PLAN, encoding="utf-8", newline="")
    rep, _ = wc.run(change="demo", plan="docs/p.md", scale="medium", root=str(proj))
    item = [i for i in rep.items if i["id"] == "S3.SECTION:Goal"][0]
    assert item["status"] == wc.OK, "BOM 让首段 Goal 检测失败：%s" % item["detail"]


def test_count_matches_openspec_truth_source():
    """勾选计数必须与 OpenSpec 真相源逐一对拍。

    覆盖 BOM / 全角数字 / CRLF / 各种列表符。这条测试的价值在于
    **验证的是「与真相源一致」，而不是「与我的实现一致」**——
    上一轮的错误正是拿实现当标准。
    """
    node = shutil.which("node")
    if not node:
        pytest.skip("无 node，跳过真相源对拍")

    cases = [
        "- [ ] a\n- [x] b\n",
        "\ufeff- [ ] a\n- [x] b\n",
        "* [ ] a\n* [x] b\n",
        "+ [ ] a\n",
        "1. [ ] a\n2. [x] b\n",
        "  - [ ] nested\n",
        "- [~] wip\n",
        "- [] empty\n",
        "- [Some doc](./d.md)\n",
        "- [ ] crlf\r\n- [x] b\r\n",
    ]
    payload = json.dumps(cases)
    script = (
        "const P=/^\\s*(?:[-*+]|\\d{1,9}[.)])\\s*\\[(?:\\s*([^\\]\\s]?)\\s*\\]"
        "(?![([])|\\s+\\])\\s*(.*)/;"
        "const cs=JSON.parse(process.argv[1]);"
        "const out=cs.map(t=>{let d=0,u=0;"
        "for(const l of t.split('\\n')){const m=l.match(P);"
        "if(!m)continue;"
        "const mk=(m[1]||'').toLowerCase(); if(mk==='x')d++; else u++;}"
        "return [d,u];});"
        "process.stdout.write(JSON.stringify(out));"
    )
    proc = subprocess.run([node, "-e", script, payload],
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr[-400:]
    expected = json.loads(proc.stdout)

    mismatches = []
    for case, (js_done, js_undone) in zip(cases, expected):
        c = wc.count_checkboxes(case)
        py = (c["done"], c["todo"] + c["other"])
        if py != (js_done, js_undone):
            mismatches.append((repr(case), py, (js_done, js_undone)))
    assert not mismatches, (
        "与 OpenSpec 真相源不一致（我的实现, 真相源）：\n%s"
        % "\n".join("  %-32s %s vs %s" % m for m in mismatches))


# ===========================================================================
# B. P1-A2 —— readonly 逃逸（账本发现不依赖 --plan）
# ===========================================================================

def test_readonly_escape_without_plan_is_blocked(proj):
    """有未完成任务时，`--scale readonly` + 不给 `--plan` 也必须是 FAIL。

    **实测的洞**：同一夹具
      不给 --plan → rc=0（8 个阶段合法 SKIP，唯一信号是 WARN）
      给   --plan → rc=1（账本 scale 冲突）
    因为 `ctx["ledger"]` 依赖 `ctx["plan"]`，账本交叉校验整体短路。
    """
    (proj / "openspec/changes/demo/tasks.md").write_text(
        "- [ ] 1.1 未完成\n", encoding="utf-8", newline="")
    (proj / ".superpowers/sdd/p/progress.md").write_text(
        "# SDD ledger — plan: docs/p.md\n\n## Scale\nmedium\n"
        "independence: L0\nTask 1: complete (a)\n",
        encoding="utf-8", newline="")

    rep, _ = wc.run(change="demo", plan=None, scale="readonly", root=str(proj))
    assert rep.has_fail(), (
        "有未完成任务 + readonly + 无 --plan 竟 rc=0：FAIL=%d WARN=%d SKIP=%d"
        % (rep.count(wc.FAIL), rep.count(wc.WARN), rep.count(wc.SKIP)))


def test_readonly_with_completed_change_still_ok(proj):
    """反例：变更真的全完成、且没指名 --change 时，readonly 不应被误拦。

    防的破坏：为了堵后门而让 readonly 一律 FAIL —— 那会把合法用法判死。
    注意本用例**不传 --change**：传了就是「声明只读却指名变更」的自相矛盾，
    那是上一条用例要堵的情形。
    """
    (proj / ".superpowers/sdd/p/progress.md").write_text(
        "# SDD ledger — plan: docs/p.md\n\n## Scale\n只读\n"
        "independence: L0\n",
        encoding="utf-8", newline="")
    rep, _ = wc.run(change=None, plan=None, scale="readonly", root=str(proj))
    assert not rep.has_fail(), (
        "合法 readonly 被误拦：%s"
        % [(i["id"], i["reason"]) for i in rep.items if i["status"] == wc.FAIL])


def test_readonly_with_change_name_is_fail(proj):
    """`--scale readonly` 同时指名 `--change` 本身就是矛盾声明 → FAIL。"""
    rep, _ = wc.run(change="demo", plan=None, scale="readonly", root=str(proj))
    assert rep.has_fail(), "readonly + --change 未被判为矛盾声明"


# ===========================================================================
# C. P1-A3 —— ## Scale 中文与模板照抄
# ===========================================================================

@pytest.mark.parametrize("value,expect", [
    ("readonly", "readonly"), ("light", "light"), ("medium", "medium"),
    ("large", "large"), ("bug", "bug"),
    ("只读", "readonly"), ("轻量", "light"), ("中任务", "medium"),
    ("大任务", "large"), ("Bug", "bug"),
])
def test_scale_section_accepts_chinese_and_english(value, expect):
    """`## Scale` 段必须同时接受英文键与中文标签。

    修前实测：只认英文键。`templates/progress.md` 规定填中文，
    于是「如实填中文 → 正则不命中 → 检测静默失效」（假绿）。
    """
    assert wc.parse_scale_section("## Scale\n%s\n" % value) == expect


def test_scale_section_template_placeholder_not_misread():
    """模板占位符 `<只读 | 轻量 | ... | Bug>` 不得被当成真实规模。

    修前实测：正则命中占位符里的 `Bug` → 判 `scale=bug` 冲突 →
    **照抄官方模板就是 FAIL**。
    """
    tpl_scale = "## Scale\n<只读 | 轻量 | 中任务 | 大任务 | Bug>\n"
    assert wc.parse_scale_section(tpl_scale) is None, (
        "模板占位符被当成真实规模：%r" % wc.parse_scale_section(tpl_scale))


def test_scale_section_ambiguous_is_none():
    """同一段里出现两个不同规模 → 判 None（视为无法确定，不猜）。"""
    assert wc.parse_scale_section("## Scale\nmedium\nlarge\n") is None


# ===========================================================================
# D. P2-A1 —— classify_scale 重复定义
# ===========================================================================

def test_classify_scale_defined_once():
    """`classify_scale` 只能有一处定义。

    修前实测：158 行与 207 行各有一个 `def classify_scale`，
    第一份被切断在 `feature_ctx_hits` 赋值处、无 return。
    """
    src = (PROJECT_ROOT / "zcode_dev_workflow.py").read_text(encoding="utf-8")
    count = len(re.findall(r"^def classify_scale\b", src, re.M))
    assert count == 1, "classify_scale 被定义了 %d 次（应 1 次）" % count


def test_no_duplicate_module_level_functions():
    """模块级函数不得重名（防「被切断的函数体」残骸）。"""
    src = (PROJECT_ROOT / "zcode_dev_workflow.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    names = [n.name for n in tree.body if isinstance(n, ast.FunctionDef)]
    dup = sorted({n for n in names if names.count(n) > 1})
    assert not dup, "模块级函数重名：%s" % dup


# ===========================================================================
# E. P2-A2 —— 现象词自证共现（17 条误判）
# ===========================================================================

NOT_BUG_BUT_CONTAINS_PHENOMENON = [
    ("解释一下超时机制", "只读请求，含现象词"),
    ("设置请求超时时间为 30 秒", "配置动作"),
    ("增加请求超时配置", "新功能"),
    ("实现超时重试机制", "新功能"),
    ("优化接口超时处理", "优化动作"),
    ("超时重试机制", "名词短语"),
    ("超时设置页面", "新页面"),
    ("设计一个白屏监控上报方案", "新功能"),
    ("增加白屏监控功能", "新功能"),
    ("白屏日志采集模块", "名词短语"),
    ("采集 Android 闪退日志", "只读/采集"),
    ("闪退率统计报表", "统计"),
    ("统计失败率", "统计"),
    ("失败回调处理", "名词短语"),
    ("失败提示样式优化", "优化动作"),
]


@pytest.mark.parametrize("task,why", NOT_BUG_BUT_CONTAINS_PHENOMENON)
def test_phenomenon_word_in_normal_context_is_not_bug(task, why):
    """现象词出现在**配置/统计/名词/优化**语境时不得判 Bug。

    修前实测：17/17 全部误判为 bug。根因是把 `挂了`/`超时`/`白屏`/`闪退`
    同时放进 `BUG_SIGNALS` 与 `STRONG_BUG`，判定要求「信号词 + 故障语境共现」
    —— 同一个词自己就把条件满足了（自证共现）。
    """
    got = wf.classify_scale(task, None)["scale"]
    assert got != "bug", "%r 被判 bug（应非 bug）——%s" % (task, why)


TRUE_BUG_WITH_PHENOMENON = [
    ("登录失败", "标准 bug 报告"),
    ("接口返回500", "标准 bug 报告"),
    ("生产数据库挂了", "完成态，已是坏现状"),
    ("页面白屏了", "完成态"),
    ("支付回调超时", "现象陈述"),
    ("内存一直涨", "持续坏现状"),
    ("线上 Nginx 502 一直不恢复", "持续坏现状"),
    ("服务挂了", "完成态"),
    # 下面两条是我在修复过程中**修正了预期**的用例（留档）。
    # 初版把它们归入「不该判 Bug」，理由是含「策略」「守护进程」等名词。
    # 实测再想一遍：「服务挂了自动重启」的主诉确实是「服务会挂」这个故障，
    # 后续的「自动重启」是应对手段。判 Bug 后走根因流程是正确的——
    # 要先搞清为什么挂，才谈得上重启策略。
    # 这属于我的初版预期错了，不是实现错了。
    ("实现服务挂了自动重启的守护进程", "主诉是「挂了」这个故障，自动重启是应对"),
    ("挂了自动重启策略", "同上：故障响应需求，主诉仍是故障"),
]


@pytest.mark.parametrize("task,why", TRUE_BUG_WITH_PHENOMENON)
def test_true_failure_still_bug(task, why):
    """反例（关键）：修上一条不能把真故障也放过。

    防的破坏：简单把现象词移出 `STRONG_BUG` —— 实测误判降到 0，
    但 `生产数据库挂了`/`页面白屏了`/`支付回调超时` 会退回只读。
    """
    got = wf.classify_scale(task, None)["scale"]
    assert got == "bug", "%r 被判 %s（应 bug）——%s" % (task, got, why)


def test_no_duplicate_words_in_signal_table():
    """信号表内不得有重复词（会让 `reasons` 输出「闪退、闪退」）。"""
    dup = sorted({w for w in wf.BUG_SIGNALS if wf.BUG_SIGNALS.count(w) > 1})
    assert not dup, "信号表有重复词：%s" % dup


# ===========================================================================
# F. P2-A4 —— 移除 无法/不能 后的功能词回归
# ===========================================================================

@pytest.mark.parametrize("task", [
    "无法登录模块", "不能提交的流程", "无法支付功能",
])
def test_ability_word_with_feature_noun_stays_bug(task):
    """`无法/不能` 后接功能名词时仍应判 Bug（不能退回只读）。

    修前实测：这三条从 bug 退回 **readonly** —— 因为含 `模块`/`流程`/`功能`
    命中 FEATURE_CONTEXT 守卫，而 STRONG_BUG 里已无 `无法`/`不能` 兜底。
    """
    got = wf.classify_scale(task, None)["scale"]
    assert got == "bug", "%r 被判 %s（应 bug）" % (task, got)


# ===========================================================================
# G. P2-A5 —— git 探测四场景
# ===========================================================================

def _plan_in(dirpath):
    orig = os.getcwd()
    try:
        os.chdir(str(dirpath))
        p = wf.build_dispatch_plan("实现用户登录接口", files=5)
        rev = [d for d in p["dispatches"] if d.get("role") == "reviewer"][0]
        return p, rev
    finally:
        os.chdir(orig)


def test_git_repo_root_is_l0(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").write_text(
        "ref: refs/heads/main\n", encoding="utf-8")
    p, rev = _plan_in(tmp_path)
    assert p["git"] is True and rev["independence"] == "L0"


def test_git_worktree_file_is_recognized(tmp_path):
    """`.git` 是**文件**（worktree/submodule）时必须识别为仓库。

    修前实测：`isdir` 判 False → L1（应为 L0）。
    """
    (tmp_path / ".git").write_text("gitdir: somewhere/worktrees/x\n", encoding="utf-8")
    p, rev = _plan_in(tmp_path)
    assert p["git"] is True, "worktree 的 .git 是文件，未被识别"
    assert rev["independence"] == "L0"


def test_git_subdirectory_is_recognized(tmp_path):
    """从仓库子目录调用时必须向上找到 `.git`。

    修前实测：`isdir(cwd/.git)` 在子目录里判 False → L1（应为 L0）。
    """
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").write_text(
        "ref: refs/heads/main\n", encoding="utf-8")
    sub = tmp_path / "src"
    sub.mkdir()
    p, rev = _plan_in(sub)
    assert p["git"] is True, "子目录未向上找到 .git"
    assert rev["independence"] == "L0"


def test_empty_git_dir_is_not_a_repository(tmp_path):
    """空的 `.git` 目录不是仓库，必须降 L1（防假绿）。

    修前实测：`mkdir .git` 就让系统相信「有可信 diff 来源」→ 标 L0，
    而 `git rev-parse` 在同一目录会失败。**这是一条假绿**。
    """
    (tmp_path / ".git").mkdir()
    p, rev = _plan_in(tmp_path)
    assert p["git"] is False, "空 .git 目录被误认为仓库"
    assert rev["independence"] == "L1"


def test_no_git_degrades_to_l1(tmp_path):
    p, rev = _plan_in(tmp_path)
    assert p["git"] is False and rev["independence"] == "L1"


# ===========================================================================
# H. P3 —— EPIPE 与静默空输出
# ===========================================================================

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="环境无 node")


@needs_node
def test_hook_survives_epipe():
    """下游提前关闭管道（EPIPE）时 hook 不得 rc≠0。

    修前实测：`node hook.mjs < in | head -c 0` → 完整 `Error: EPIPE` 栈 +
    **rc=1**。`main().catch()` 只兜 Promise rejection，而
    `process.stdout.write` 的失败走 stream 的 `'error'` 事件。
    """
    script = (
        "const {spawn}=require('child_process');"
        "const c=spawn(process.execPath,[process.argv[1]],{stdio:['pipe','pipe','pipe']});"
        "c.stdout.destroy();"
        "c.stdin.end(JSON.stringify({prompt:'测试 EPIPE'}));"
        "c.on('close',(code)=>{process.stdout.write('RC='+code);});"
    )
    proc = subprocess.run(["node", "-e", script, str(HOOK)],
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr[-400:]
    assert "RC=0" in proc.stdout, (
        "EPIPE 让 hook 返回非零码：%s（stderr: %s）"
        % (proc.stdout.strip(), proc.stderr[-300:]))


@needs_node
def test_hook_always_emits_on_normal_prompt():
    """正常 prompt 必须有输出（防「rc=0 但 stdout 空」的静默失效）。"""
    proc = subprocess.run(
        ["node", str(HOOK)],
        input=json.dumps({"prompt": "帮我写一个排序算法"}).encode(),
        capture_output=True, timeout=60)
    assert proc.returncode == 0
    data = json.loads(proc.stdout.decode("utf-8"))
    ctx = data["hookSpecificOutput"]["additionalContext"]
    assert ctx.strip(), "正常 prompt 下 additionalContext 为空"
    assert "【专家体系路由】" in ctx
