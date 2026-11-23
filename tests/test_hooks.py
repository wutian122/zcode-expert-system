# -*- coding: utf-8 -*-
"""P3 · UserPromptSubmit hook 健壮性回归测试（缺陷 #15 #16 + 注释失真）

**这个文件要抓的破坏**

1. **#15 非字符串 prompt 让 hook 崩栈**
   现状实测：stdin 为 `{"prompt":123}` → `TypeError: (input.prompt ?? "").trim
   is not a function`，stderr 打完整栈，**退出码 1**，stdout 空。
   危害不是「少了一条提示」——UserPromptSubmit hook 的 rc≠0 可能被宿主当作
   失败处理，最坏情况阻断该轮用户输入。而该文件头部与 `:41` 都写着
   「hook 绝不能因为读文件失败而阻断用户输入」——承诺与实现相反。
   现有代码只对 **JSON 解析失败**做了 try/catch，对「结构对但类型错」没有防线。

2. **#16 空 `.superpowers/sdd` 目录截断上溯**
   现状实测：子目录里存在空 `.superpowers/sdd`（哪怕是被清理过的空壳）时，
   `if (!best) return ''` 直接放弃，不再向上找——父层的活跃账本读不到，
   【当前工作流】摘要静默消失。`monorepo` / `worktree` / 任何子目录残留都会命中。

3. **注释与实现不一致**（`:40-41` vs `:46`/`:74`）
   注释写「只向上找 3 层，只读 progress.md 前 40 行」，代码是 `depth < 4` 与
   `.slice(0, 60)`。这类注释是后续判断「性能是否安全」的依据。

4. **32 领域名与 categories.json 有 24/32 不符**（第 5 份手写副本）

**驱动真实行为**：用 subprocess 真跑 node 进程并断言退出码 / stdout 结构，不 mock。

**安全说明**：涉及嵌套目录的用例全部使用 pytest 内置 `tmp_path` 夹具——
它由 pytest 在系统临时区内分配、自动清理，且测试代码只在其下用 `Path / "name"`
建子目录。所有路径都锚定在夹具根内，不接触仓库或任意文件系统位置。

**Windows 路径注意**：给 node 传 `cwd` 必须是原生 Windows 路径。
Git Bash 风格的 `/tmp/...` 会让 node 找不到目录——`tmp_path` 给出的正是原生路径。
"""

import json
import re
import shutil
import subprocess
import time
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
HOOK = PROJECT_ROOT / "hooks" / "prepend-global-rules-reminder.mjs"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None, reason="环境无 node，跳过 hook 测试")


def run_hook(payload, cwd=None):
    """把 payload（dict 或原始字符串）喂给 hook，返回 CompletedProcess。

    `text=False` 拿原始字节，自己解码——避免测试进程编码干扰。
    """
    stdin = payload if isinstance(payload, str) else json.dumps(payload)
    return subprocess.run(
        ["node", str(HOOK)],
        input=stdin.encode("utf-8"),
        cwd=str(cwd) if cwd else str(PROJECT_ROOT),
        capture_output=True,
        text=False,
        timeout=30,
    )


def stdout_json(proc):
    return json.loads((proc.stdout or b"").decode("utf-8"))


def additional_context(proc):
    return stdout_json(proc)["hookSpecificOutput"]["additionalContext"]


def hook_source():
    return HOOK.read_text(encoding="utf-8")


# ===========================================================================
# #15 非字符串 / 畸形 prompt：必须 fail-open（rc=0）
# ===========================================================================

BAD_PAYLOADS = [
    pytest.param({"prompt": 123}, id="prompt-int"),
    pytest.param({"prompt": None}, id="prompt-null"),
    pytest.param({"prompt": ["a", "b"]}, id="prompt-list"),
    pytest.param({"prompt": {"nested": 1}}, id="prompt-object"),
    pytest.param({"prompt": True}, id="prompt-bool"),
    pytest.param({"prompt": 3.14}, id="prompt-float"),
]


@pytest.mark.parametrize("payload", BAD_PAYLOADS)
def test_non_string_prompt_exits_zero(payload):
    """非字符串 prompt 不得让 hook 崩栈。

    修前实测：全部 `TypeError: ... .trim is not a function`，rc=1。
    hook 的契约是 fail-open——任何输入异常都必须 rc=0、静默放行。
    """
    proc = run_hook(payload)
    assert proc.returncode == 0, (
        "prompt=%r 导致 rc=%d\nstderr:\n%s"
        % (payload["prompt"], proc.returncode,
           (proc.stderr or b"").decode("utf-8", "replace")[-800:]))


@pytest.mark.parametrize("payload", BAD_PAYLOADS)
def test_non_string_prompt_does_not_print_stack(payload):
    """不得把完整 Node 栈写到 stderr（日志污染 + 暴露内部细节）。"""
    proc = run_hook(payload)
    err = (proc.stderr or b"").decode("utf-8", "replace")
    assert "TypeError" not in err, "stderr 出现 TypeError 栈：%s" % err[-400:]


def test_invalid_json_exits_zero():
    """回归守卫：JSON 解析失败本来就 fail-open，修复不得破坏它。"""
    assert run_hook("not-json-at-all").returncode == 0


def test_empty_stdin_exits_zero():
    """空 stdin 也必须 rc=0（宿主可能传空）。"""
    assert run_hook("").returncode == 0


@pytest.mark.parametrize("payload", BAD_PAYLOADS)
def test_non_string_prompt_treated_as_empty_not_crash(payload):
    """非字符串 prompt 必须被当作「空输入」处理，而不是崩或落兜底 catch。

    **这条精确刻画正确语义**（初版断言「必须注入提醒」，写错了）：
    非字符串 prompt 等价于「没有可路由的用户文本」，
    与空字符串、单 token 斜杠命令一样属于「无需注入」——
    所以正确行为是 **rc=0 + 零输出 + stderr 无噪音**。

    真正的破坏形态是「落到外层兜底 catch」：
    实测把类型守卫换成 `(promptValue ?? '').trim()` 后，rc 仍是 0
    （被 `main().catch()` 兜住），但 stderr 出现 `unexpected: ... is not
    a function`。只断言 rc=0 会让这种静默失效通过——所以这里额外禁止噪音。
    """
    proc = run_hook(payload)
    assert proc.returncode == 0
    err = (proc.stderr or b"").decode("utf-8", "replace")
    assert "unexpected" not in err, (
        "落到了兜底 catch（说明类型守卫失效）：%s" % err[-200:])
    assert "TypeError" not in err, "出现 TypeError 栈：%s" % err[-200:]
    # 等价于空输入：不注入、不报错
    assert not (proc.stdout or b"").strip(), (
        "非字符串 prompt 应视为空输入（不注入），实际有输出：%s"
        % (proc.stdout or b"")[:200])


def test_missing_prompt_key_exits_zero():
    """payload 里没有 prompt 键 → 视为空输入，rc=0 且不输出。"""
    proc = run_hook({"cwd": str(PROJECT_ROOT)})
    assert proc.returncode == 0


# ===========================================================================
# 正常路径不得回归
# ===========================================================================

def test_normal_prompt_emits_valid_payload():
    """正常输入的输出结构必须保持：hookSpecificOutput.additionalContext。

    防的破坏：为 fail-open 把输出段整体包 try/catch 后，正常路径也被改坏
    （比如少写 hookEventName）。
    """
    proc = run_hook({"prompt": "帮我写一个排序算法"})
    assert proc.returncode == 0
    data = stdout_json(proc)
    assert data["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
    assert "【专家体系路由】" in data["hookSpecificOutput"]["additionalContext"]


def test_slash_command_passthrough():
    """单 token 斜杠命令必须原样放行（不注入上下文）。"""
    proc = run_hook({"prompt": "/clear"})
    assert proc.returncode == 0
    assert not (proc.stdout or b"").strip(), "斜杠命令不应产生输出"


def test_slash_text_with_space_still_reminds():
    """带空格的斜杠文本仍应注入提醒。

    回归守卫：区分「单 token 命令」与「以 / 开头的普通提问」是刻意设计。
    """
    proc = run_hook({"prompt": "/etc/passwd 是什么？"})
    assert proc.returncode == 0
    assert "【专家体系路由】" in additional_context(proc)


# ===========================================================================
# #16 空 sdd 目录必须继续上溯
#
# 夹具结构（pytest tmp_path 一次性分配）：
#   <tmp_path>/ws          ← 「工作区」，放活跃账本
#   <tmp_path>/ws/sub      ← 「子目录」，模拟 monorepo 里被清理过的空壳
# 目的：让 hook 从 sub 出发向上找到 ws 的账本。
# ===========================================================================

LEDGER_OK = ("# SDD ledger — plan: x\n\n"
             "## Current Phase\nS5\n"
             "## Overall Status\nIN_PROGRESS\n")


def write_ledger(base, name="plan-a", body=LEDGER_OK):
    """在 base/.superpowers/sdd/<name>/progress.md 写一份账本夹具。"""
    d = base / ".superpowers" / "sdd" / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "progress.md").write_text(body, encoding="utf-8", newline="\n")


@pytest.fixture
def workspace(tmp_path):
    """返回 (工作区, 其子目录)，两者都在 tmp_path 之下。"""
    ws = tmp_path / "ws"
    sub = ws / "sub"
    sub.mkdir(parents=True)
    return ws, sub


def test_ascends_past_empty_sdd_dir(workspace):
    """子目录有空 `.superpowers/sdd` 时，仍必须读到工作区的账本。

    修前实测：输出不含【当前工作流】；删掉该空目录后才出现。
    `if (!best) return ''` 把「本层没有账本」误当成「到此为止」。
    """
    ws, sub = workspace
    write_ledger(ws)
    (sub / ".superpowers" / "sdd").mkdir(parents=True)      # 空壳目录

    proc = run_hook({"prompt": "继续", "cwd": str(sub)})
    assert proc.returncode == 0
    ctx = additional_context(proc)
    assert "【当前工作流】" in ctx, (
        "空 sdd 目录截断了上溯；实际上下文末尾：\n%s" % ctx[-400:])


# ===========================================================================
# I-06：tasks.md 未完成必须在每轮提醒中可见（门禁自动可见）
# ===========================================================================

def write_tasks(base, slug, body):
    """在 base/openspec/changes/<slug>/tasks.md 写勾选夹具。"""
    d = base / "openspec" / "changes" / slug
    d.mkdir(parents=True, exist_ok=True)
    (d / "tasks.md").write_text(body, encoding="utf-8", newline="\n")


def test_unchecked_tasks_warns_each_turn(workspace):
    """I-06：账本对应 tasks.md 有未勾选任务时，摘要必须显式告警。

    修复前门禁只在手动 /wf:check 时运行；hook 只输出通用提醒，
    「任务未完成却要交付/归档」不会在每轮可见。
    """
    ws, _sub = workspace
    write_ledger(ws, name="plan-a")
    write_tasks(ws, "plan-a", "- [x] 已完成任务\n- [ ] 未完成任务\n")

    proc = run_hook({"prompt": "继续", "cwd": str(ws)})
    assert proc.returncode == 0
    ctx = additional_context(proc)
    assert "未勾选" in ctx, "tasks.md 有未完成任务时必须在上下文里告警；实际：\n%s" % ctx[-600:]
    assert "1" in ctx, "告警应包含未完成数量"


def test_all_checked_tasks_no_warning(workspace):
    """I-06：tasks.md 全部勾选时不得出现未完成告警。"""
    ws, _sub = workspace
    write_ledger(ws, name="plan-b")
    write_tasks(ws, "plan-b", "- [x] 任务一\n- [x] 任务二\n")

    proc = run_hook({"prompt": "继续", "cwd": str(ws)})
    assert proc.returncode == 0
    ctx = additional_context(proc)
    assert "未勾选" not in ctx, "全部完成时不应告警；实际：\n%s" % ctx[-600:]


def test_missing_tasks_no_warning(workspace):
    """I-06：无 tasks.md 时不告警（fail-open，不阻断）且 hook 正常退出。"""
    ws, _sub = workspace
    write_ledger(ws, name="plan-c")
    proc = run_hook({"prompt": "继续", "cwd": str(ws)})
    assert proc.returncode == 0
    ctx = additional_context(proc)
    assert "未勾选" not in ctx
    assert "【当前工作流】" in ctx, "无 tasks.md 时摘要仍应输出"


def test_ascends_past_sdd_dir_without_ledger(workspace):
    """子目录的 sdd 下有子目录但没有 progress.md → 同样继续上溯。

    防的破坏：只处理「sdd 目录里无子目录」这一种形态，
    漏掉「有子目录但都无 progress.md」的另一种空壳。
    """
    ws, sub = workspace
    write_ledger(ws)
    (sub / ".superpowers" / "sdd" / "stale-plan").mkdir(parents=True)

    proc = run_hook({"prompt": "继续", "cwd": str(sub)})
    assert "【当前工作流】" in additional_context(proc)


def test_ascends_past_ledger_without_phase(workspace):
    """子目录账本里既无 Current Phase 也无 Overall Status → 继续上溯。

    修前实测：`if (!phase && !status) return ''` 同样截断上溯。
    """
    ws, sub = workspace
    write_ledger(ws, "plan-good")
    write_ledger(sub, "plan-empty", body="# 空账本\n\n没有阶段字段\n")

    proc = run_hook({"prompt": "继续", "cwd": str(sub)})
    ctx = additional_context(proc)
    assert "【当前工作流】" in ctx, "无阶段字段的账本截断了上溯"
    assert "plan-good" in ctx, "读到的是子目录空账本，应继续上溯到工作区账本"


def test_nearest_ledger_wins(workspace):
    """父子都有有效账本时，取最近的（子层优先）。

    防的破坏：改成「一直上溯到底」后变成「总是取最外层」，
    在 monorepo 里会读到错误的账本。
    """
    ws, sub = workspace
    write_ledger(ws, "plan-outer")
    write_ledger(sub, "plan-inner")

    proc = run_hook({"prompt": "继续", "cwd": str(sub)})
    ctx = additional_context(proc)
    assert "plan-inner" in ctx, "应取最近的账本，实际：%s" % ctx[-300:]


def test_no_ledger_anywhere_omits_summary(workspace):
    """全树上溯都无账本时，只注入提醒、不加【当前工作流】（不得崩）。"""
    _ws, sub = workspace
    proc = run_hook({"prompt": "继续", "cwd": str(sub)})
    assert proc.returncode == 0
    ctx = additional_context(proc)
    assert "【专家体系路由】" in ctx
    assert "【当前工作流】" not in ctx


def test_single_line_summary_has_expected_fields(workspace):
    """摘要必须含账本名与阶段，且是单行（注入成本可控）。"""
    ws, sub = workspace
    write_ledger(ws, "plan-a")
    proc = run_hook({"prompt": "继续", "cwd": str(sub)})
    ctx = additional_context(proc)
    summary = [ln for ln in ctx.splitlines() if "【当前工作流】" in ln]
    assert summary, "找不到摘要行"
    assert "plan-a" in summary[0]
    assert "S5" in summary[0]


# ===========================================================================
# 注释与实现一致 / 领域名同源 / 性能预算
# ===========================================================================

def test_comment_matches_actual_depth():
    """注释里声明的「上溯层数」必须与代码一致。

    修前实测：注释写「3 层」，代码是 `depth < 4`。
    这类注释是后续判断「性能是否安全」的依据，写错会误导调参。
    """
    src = hook_source()
    m = re.search(r"depth\s*<\s*(\d+)", src)
    assert m, "找不到上溯循环"
    n = int(m.group(1))
    assert ("%d 层" % n) in src or ("向上找 %d" % n) in src, (
        "注释未写明实际层数（代码 depth < %d）" % n)


def test_comment_matches_actual_line_limit():
    """注释里声明的「读取行数」必须与代码一致（修前 40 vs 60）。"""
    src = hook_source()
    m = re.search(r"slice\(\s*0\s*,\s*(\d+)\s*\)", src)
    assert m, "找不到 slice 行数上限"
    n = int(m.group(1))
    assert ("前 %d 行" % n) in src, "注释未写明实际行数上限（代码 slice(0, %d)）" % n


def test_domain_names_derive_from_categories():
    """hook 注入的 32 领域名必须与 categories.json 同源。

    修前实测：hook 手写 32 名，与 categories.json 的 `name` 有 24/32 不符
    （hook「工程效能」vs 配置「工程效能与质量」）。名字不同步会让模型
    按 hook 的名字去猜 `subagent_type`，而派发只认 `experts.json` 的 `name`。

    **断言的是运行时输出，不是源码文本**：正确实现是运行时从配置读取，
    源码里根本不会出现这些名字。检查源码只能验证「有没有手写副本」，
    反而会把「动态读取」这一正确做法误判为失败（初版就踩了这个坑）。
    """
    cats = json.loads((PROJECT_ROOT / "config" / "categories.json")
                      .read_text(encoding="utf-8"))
    names = [v["name"] for v in cats.values()]
    proc = run_hook({"prompt": "帮我写一个排序算法"})
    ctx = additional_context(proc)
    missing = [n for n in names if n not in ctx]
    assert not missing, (
        "hook 实际输出缺这些领域名（%d/%d 不符）：%s"
        % (len(missing), len(names), missing))


def test_domain_names_not_hardcoded_in_source():
    """源码里不得再维护一份手写的 32 领域名副本。

    这是与上一条互补的守卫：上一条保证输出正确，这一条保证
    「唯一的做法是读配置」。否则有人补一版手写名单让上一条通过，
    漂移会再次发生（只是这次更隐蔽）。

    判据：只看**非注释代码行**。注释里出现领域名（例如说明「此处曾写
    `工程效能`，现配置为 `工程效能与质量`」）是正当的记录，
    不属于副本——初版把注释也算进去，误报 1 处。
    """
    src = hook_source()
    code_only = "\n".join(
        ln for ln in src.splitlines()
        if not ln.lstrip().startswith("*")
        and not ln.lstrip().startswith("//")
        and not ln.lstrip().startswith("/*"))
    cats = json.loads((PROJECT_ROOT / "config" / "categories.json")
                      .read_text(encoding="utf-8"))
    names = [v["name"] for v in cats.values()]
    inline = [n for n in names if n in code_only]
    assert not inline, (
        "非注释代码里出现了 %d 个领域名字面量（应为运行时读取）：%s"
        % (len(inline), inline[:6]))


def test_domain_line_points_to_config_when_load_fails(monkeypatch):
    """读配置失败时，领域行应指向权威出处而不是留空或崩掉。

    fail-open 校验：hook 不能因为读配置文件失败而阻断用户输入。
    （此处只断言正常部署下该退路不影响输出——读配置失败的场景
    由 test_non_string_prompt_* 一组覆盖的 fail-open 架构保证。）
    """
    proc = run_hook({"prompt": "帮我写一个排序算法"})
    ctx = additional_context(proc)
    assert "32 领域" in ctx


def test_reminder_forbids_skipping_domain_routing():
    """A5（enforce-domain-routing）：REMINDER 必须含「不得跳过域路由」并删除机械豁免。

    三锚点（C5）：①「【专家体系路由】」头行保留；②输出 JSON schema 不变；
    ③非注释行零领域名字面量（由 test_domain_names_not_hardcoded_in_source
    继续守卫）。口径更新（design §7）：triage 双轴合一（先规模后域，对齐
    全局 AGENTS.md Step1→Step2）；删「不强制派专家」机械豁免，改 analyst
    派发；豁免仅两级且老板明示豁免须记 Ruling（W10）。
    """
    proc = run_hook({"prompt": "帮我写一个排序算法"})
    ctx = additional_context(proc)
    assert "【专家体系路由】" in ctx, "三锚点①：头行锚点「【专家体系路由】」必须保留"
    assert "不得跳过域路由" in ctx, "A5 主断言：REMINDER 缺「不得跳过域路由」"
    assert "不强制派专家" not in ctx, (
        "旧机械豁免文案「不强制派专家」必须删除（W10：所有任务都须两轴分诊）")
    assert "可用 general-purpose 或 Explore" not in ctx, (
        "旧机械豁免整句（可用 general-purpose 或 Explore）必须删除")
    assert "双轴合一" in ctx, "triage 双轴合一口径必须写入（D2，修先域后规模顺序矛盾）"
    assert "analyst" in ctx, "只读任务派 analyst 的口径必须写入（D3）"
    assert "记 Ruling" in ctx, "老板明示豁免须记 Ruling 的口径必须写入（W10）"


def test_hook_emits_within_timeout_budget():
    """冷启动必须在 statusMessage 的 3000ms 预算内（留足余量）。"""
    t0 = time.time()
    proc = run_hook({"prompt": "帮我写一个排序算法"})
    elapsed_ms = (time.time() - t0) * 1000
    assert proc.returncode == 0
    assert elapsed_ms < 2500, "hook 耗时 %.0fms，超预算" % elapsed_ms


# ===========================================================================
# P8 批次五 Task 15：账本字段白名单消毒（fail-open：只丢字段，永不 rc≠0）
#
# 抓的破坏：phase/status/scale 用 (\S+) 从账本（自由文本）裸捕获后
# 未消毒即拼进 additionalContext，注入每一轮用户上下文——恶意或意外内容
# （控制字符、超长值、注入语法）原样进入 prompt。
# 捕获 (\S+) 值天然不含空格，白名单亦不含空格，两处口径一致。
# ===========================================================================

def test_control_chars_stripped_not_injected(workspace):
    """捕获值内嵌控制字符 → 原值与控制字符不得进入 additionalContext。

    命名与语义说明（P9 复审 🟡 收口）：实现的语义是「剥离控制字符后，
    若剩余部分通过白名单则注入清洗值」——本测试锁的安全属性是
    原始值（含控制字符形态）不出现在注入内容里，而非「整个字段丢弃」；
    超长/白名单外字符才走整字段丢弃（见后两条用例）。
    """
    ws, sub = workspace
    write_ledger(ws, "plan-ctrl", body=(
        "# SDD ledger — plan: x\n\n"
        "## Current Phase\nS5\x00INJ\n"
        "## Overall Status\nIN_PROGRESS\n"))
    proc = run_hook({"prompt": "继续", "cwd": str(sub)})
    assert proc.returncode == 0
    ctx = additional_context(proc)
    assert "\x00" not in ctx, "控制字符原样进入每轮注入上下文"
    assert "S5\x00INJ" not in ctx, "带控制字符的原始值未消毒即注入"


def test_field_overlong_dropped(workspace):
    """超长（>40 字符）捕获值 → 整个字段丢弃，不注入。"""
    ws, sub = workspace
    write_ledger(ws, "plan-long", body=(
        "# SDD ledger — plan: x\n\n"
        "## Current Phase\n" + "A" * 41 + "\n"
        "## Overall Status\nIN_PROGRESS\n"))
    proc = run_hook({"prompt": "继续", "cwd": str(sub)})
    assert proc.returncode == 0
    ctx = additional_context(proc)
    assert "A" * 41 not in ctx, "超长值原样进入注入上下文（注入成本失控）"


def test_field_with_injection_syntax_dropped(workspace):
    """含注入语法的值（尖括号/模板插值）→ 整个字段丢弃。"""
    ws, sub = workspace
    write_ledger(ws, "plan-inj", body=(
        "# SDD ledger — plan: x\n\n"
        "## Current Phase\n<script>alert(1)</script>\n"
        "## Overall Status\nIN_PROGRESS\n"
        "## Scale\n${process.env}\n"))
    proc = run_hook({"prompt": "继续", "cwd": str(sub)})
    assert proc.returncode == 0
    ctx = additional_context(proc)
    assert "<script>" not in ctx, "注入语法原样进入每轮 prompt"
    assert "${process.env}" not in ctx, "模板插值语法原样进入每轮 prompt"


def test_chinese_field_values_pass_through(workspace):
    """双向反例：合法中文值（无空格形式）必须正常注入，白名单不误伤。

    捕获 (\\S+) 不含空格，夹具值写无空格形式；既有合法夹具值
    （S5 / IN_PROGRESS，见 test_single_line_summary_has_expected_fields）
    继续通过。
    """
    ws, sub = workspace
    write_ledger(ws, "plan-zh", body=(
        "# SDD ledger — plan: x\n\n"
        "## Current Phase\nS5实施\n"
        "## Overall Status\nIN_PROGRESS\n"
        "## Scale\n中任务\n"))
    proc = run_hook({"prompt": "继续", "cwd": str(sub)})
    assert proc.returncode == 0
    ctx = additional_context(proc)
    assert "S5实施" in ctx, "合法中文值被白名单误杀"
    assert "中任务" in ctx, "合法中文规模值被白名单误杀"
    assert "IN_PROGRESS" in ctx, "既有合法值被白名单误杀"


# ===========================================================================
# R-1 / R-2（2026-11-19）：hook 触发条件全称化 + 复核自己产出须派独立专家
#
# 抓的破坏（本会话域路由被跳过的两个根因）：
#   R-1：:71 触发条件是「领域关键词式」——「任务属32领域之一，或提到
#        「专家/会诊/...」时」。元任务（复核/复查/汇总主控自己的产出）不带
#        领域词，主控据此自我判定「无需路由」而跳过 triage。且与 :73
#        「所有任务（含只读与机械任务）都必须完成两轴分诊」自相矛盾。
#   R-2：:76 「机械任务一旦需要领域解释或决策→升级派专家」边界模糊，
#        主控把「复核是否属实/误报/严重度/数字」自我归类为机械核对规避，
#        未明确「复核自己产出=领域判断，必须派独立专家」。
# ===========================================================================

def test_reminder_trigger_is_universal_not_keyword():
    """R-1：触发句必须全称化，删除「领域关键词式」条件从句。

    修前实测：ctx 含「任务属下列 32 领域之一，或提到」的条件触发句，
    元任务（不含领域词）据此不触发。修后必须改为全称式，且与 :73 全称句
    （所有任务都必须完成两轴分诊）一致。
    """
    proc = run_hook({"prompt": "帮我写一个排序算法"})
    ctx = additional_context(proc)
    # 条件式触发句必须删除
    assert "任务属下列 32 领域之一" not in ctx, (
        "R-1：条件式触发句「任务属下列 32 领域之一」必须删除"
        "（元任务不带领域词会漏触发）")
    assert "或提到「专家/会诊" not in ctx, (
        "R-1：关键词枚举触发句「或提到「专家/会诊」必须删除")
    # 全称句必须在
    assert "所有任务都必须" in ctx and "两轴路由" in ctx, (
        "R-1：全称触发句「所有任务都必须…两轴路由」必须写入")


def test_reminder_review_own_output_needs_independent_expert():
    """R-2：必须明确「复核/审查自己产出=领域判断，派独立专家，不得自审」。

    修前实测：ctx 无「复核自己产出=领域判断」的明确表述，主控借「机械核对」
    自我归类规避派专家。修后必须有该锚点，封死自我归类空间。
    """
    proc = run_hook({"prompt": "帮我写一个排序算法"})
    ctx = additional_context(proc)
    assert "复核" in ctx, "R-2：缺「复核」锚点"
    assert "独立专家" in ctx, (
        "R-2：缺「独立专家」锚点——复核自己产出必须派独立专家")
    assert "实施者" in ctx and "审查者" in ctx, (
        "R-2：缺「实施者≠审查者」锚点（复核自己产出不得自审）")
