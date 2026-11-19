#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""P0 · 输出编码地基回归测试（缺陷 #3）

**这个文件要抓的破坏**：三个 CLI 入口在非 UTF-8 控制台（中文 Windows 默认 CP936）
下写 stdout 时抛 UnicodeEncodeError，导致命令 rc=1、无输出。
表现为「工具坏了」，实际是编码问题——最容易被误判为逻辑故障。

触发源（修前实测，PYTHONIOENCODING=cp936）：
- zcode_expert_system.py：config/experts.json 的 emoji 字段（⚙️ U+2699 等）经
  top_candidates 透出到 json.dumps(..., ensure_ascii=False)
- zcode_dev_workflow.py states：config/workflow.json 的 transitions[].trigger 含
  ❌(U+274C) / ✅(U+2705)
- zcode_dev_workflow.py plan：同上数据里的 ⇒(U+21D2)
- skill_entry.py：同 expert emoji 路径

**驱动真实行为**：用 subprocess 真跑命令并断言退出码，不 mock。这不是「慢/外部层」
以外的 mock 场景——被测对象就是进程边界本身。

**不测什么**：不测「中文是否被替换成 ?」。修复用 errors="replace" 只是最后兜底，
正常情况下 utf-8 重配后原文完整输出，这一点由 test_emoji_preserved_not_replaced 钉住。
"""

import json
import os
import subprocess
import sys

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 非 UTF-8 控制台模拟。CP936 是中文 Windows 的默认代码页，可编码 GB2312 汉字
# 但无法编码 emoji 与 ⇒/❌ 之类的符号——正是缺陷触发条件。
LEGACY_ENCODING = "cp936"


def run_cli(args, encoding=LEGACY_ENCODING):
    """在指定 PYTHONIOENCODING 下跑一个 CLI，返回 CompletedProcess。

    **为什么不用 `-I`**：isolated mode 会忽略全部 `PYTHON*` 环境变量，
    包括 `PYTHONIOENCODING`——那就既模拟不了 CP936，也测不到任何编码行为，
    整个文件会变成一批恒真断言（实测：加 `-I` 后 utf-8 用例同样 rc=1，
    因为 `-I` 下真实生效的是系统 locale，与传入的 encoding 无关）。
    改用 `-E`+`-s` 的组合达不到目的（`-E` 同样忽略环境变量），
    所以这里干脆不隔离环境变量，改为显式清理可能干扰的 `PYTHONUTF8` / `PYTHONPATH`。

    Windows 下必须给绝对路径，避免 cwd 影响。
    """
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = encoding
    # 关键：本机若设了 PYTHONUTF8=1（会强制 UTF-8）会掩盖缺陷，必须清掉。
    env.pop("PYTHONUTF8", None)
    env.pop("PYTHONUTF8_MODE", None)
    # 防止用户 site / PYTHONPATH 里的同名模块抢在仓库代码之前被导入
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    return subprocess.run(
        [sys.executable] + args,
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=False,  # 拿原始字节，自己解码，避免测试进程的编码干扰
        timeout=120,
    )


def as_text(raw):
    """把子进程输出解码成文本用于断言，永不因解码失败而炸。"""
    return (raw or b"").decode("utf-8", errors="replace")


# ---------------------------------------------------------------------------
# 核心用例：三条命令在 CP936 下必须 rc=0
# ---------------------------------------------------------------------------

ENCODING_CASES = [
    pytest.param(
        ["zcode_expert_system.py", "前端页面优化"],
        id="zcode_expert_system-emoji",
    ),
    pytest.param(
        ["zcode_dev_workflow.py", "states"],
        id="zcode_dev_workflow-states-crossmark",
    ),
    pytest.param(
        ["zcode_dev_workflow.py", "plan", "实现用户登录接口", "--files", "5"],
        id="zcode_dev_workflow-plan-arrow",
    ),
    pytest.param(
        ["skill_entry.py", "前端页面优化"],
        id="skill_entry-emoji",
    ),
]


@pytest.mark.parametrize("args", ENCODING_CASES)
def test_cli_exits_zero_under_cp936(args):
    """CP936 控制台下每个入口都必须 rc=0。

    修前：全部 rc=1，stderr 含 "UnicodeEncodeError: 'gbk' codec can't encode"。
    """
    proc = run_cli(args)
    assert proc.returncode == 0, (
        "%s 在 %s 下退出码 %d\nstderr:\n%s"
        % (args[0], LEGACY_ENCODING, proc.returncode, as_text(proc.stderr)[-1500:])
    )


@pytest.mark.parametrize("args", ENCODING_CASES)
def test_cli_produces_non_empty_stdout_under_cp936(args):
    """修编码不能靠「什么都不输出」蒙过去——必须真有内容。

    这条守卫防的破坏：把 print 包进 except 后静默吞掉输出，rc=0 但 stdout 为空，
    表面上「修好了」，实际把「崩溃」换成了「无声」。
    """
    proc = run_cli(args)
    assert proc.stdout.strip(), (
        "%s 在 %s 下 stdout 为空——疑似把异常静默吞掉"
        % (args[0], LEGACY_ENCODING)
    )


# ---------------------------------------------------------------------------
# 守卫：重配不能破坏 JSON 契约
# ---------------------------------------------------------------------------

def test_stdout_remains_valid_json_under_cp936():
    """states 的输出必须是可解析 JSON（下游 --json 消费方依赖它）。

    防的破坏：为躲编码问题改用 ensure_ascii=True，会让 JSON 合法但中文变 \\uXXXX；
    或用 print 拼字符串替代 json.dumps，直接破坏结构。这里只断言「可解析」，
    中文可读性由下一条盯着。
    """
    proc = run_cli(["zcode_dev_workflow.py", "states"])
    assert proc.returncode == 0
    data = json.loads(as_text(proc.stdout))
    assert isinstance(data, dict)
    assert data, "states 输出不应为空对象"


def test_expert_system_stdout_is_valid_json_under_cp936():
    """zcode_expert_system 的主输出是 JSON，同样不能被编码修复破坏。"""
    proc = run_cli(["zcode_expert_system.py", "设计一个支持高并发的后端 API 接口"])
    assert proc.returncode == 0
    data = json.loads(as_text(proc.stdout))
    assert "category" in data
    assert "selected_expert" in data


def test_emoji_preserved_not_replaced():
    """emoji 与中文必须完整落地，不得被替换成 ? 或 U+FFFD。

    防的破坏：用 errors="replace" 当主手段。它确实能让 rc=0（因为不再抛异常），
    但输出里 emoji 变成 "?"、⇒ 变成 "?"——数据被悄悄损坏，比崩溃更难发现。
    正确实现是 reconfigure(encoding="utf-8") 让终端按 UTF-8 解码，
    errors="replace" 只在 reconfigure 不可用时兜底。

    断言方式：CP936 下输出里必须能找到 CJK 专家名，且不得出现替换字符。
    """
    proc = run_cli(["zcode_dev_workflow.py", "plan", "实现用户登录接口", "--files", "5"])
    assert proc.returncode == 0
    text = as_text(proc.stdout)
    # 中文必须完好（这个任务的分类结果必然含中文专家名/中文分类说明）
    assert any("\u4e00" <= ch <= "\u9fff" for ch in text), "输出里没有中文，疑似被替换"
    assert "\ufffd" not in text, "输出含 U+FFFD 替换字符——数据被损坏"
    # ⇒ 是 plan 输出的分隔符（workflow.json 数据驱动），必须原样保留
    assert "\u21d2" in text, "⇒(U+21D2) 丢失——被替换说明 errors 策略当了主手段"


# ---------------------------------------------------------------------------
# 守卫：UTF-8 环境不得回归
# ---------------------------------------------------------------------------

def test_utf8_terminal_still_works():
    """本来就是 UTF-8 的环境不能因修复而变坏。

    防的破坏：重配逻辑写反（无条件转 cp936），把正常环境搞坏。
    """
    proc = run_cli(["zcode_dev_workflow.py", "states"], encoding="utf-8")
    assert proc.returncode == 0
    assert json.loads(as_text(proc.stdout))


def test_triage_still_works_under_cp936():
    """triage 是最常被调用的子命令，一并纳入。

    它当前不含 emoji，所以本就 rc=0——这条是回归护栏：
    修复后不得因统一重配而破坏它。
    """
    proc = run_cli(["zcode_dev_workflow.py", "triage", "修复登录失败", "--files", "2"])
    assert proc.returncode == 0
    assert "任务分类结果" in as_text(proc.stdout)


# ---------------------------------------------------------------------------
# P8 批次二 Task 4：workflow_check.py 补编码地基（四个入口中最后一个）
# ---------------------------------------------------------------------------

def test_workflow_check_exit_zero_under_cp936_with_emoji_root(tmp_path):
    """workflow_check 在 CP936 下必须 rc=0（修前：输出含 emoji → rc=1）。

    夹具设计说明（主控 Ruling，替代计划原 --change 方案）：`--change` 含 emoji
    与 `--scale readonly` 组合会撞 S0.SCALE_MISMATCH（readonly 禁止提供
    change/plan，必然 FAIL，rc=1 与编码无关）。改用 `--root` 指向含 emoji 的
    目录——`项目根：%s` 打印与 `--json` 的 root 字段（ensure_ascii=False）都会
    原样透出该路径；readonly + 空目录是天然零 FAIL 场景（S1-S8 全裁剪、
    无账本可查），保证修前 rc=1 只能来自编码崩溃而非门禁 FAIL。
    """
    root = tmp_path / "根⚙️目录"
    root.mkdir()
    proc = run_cli(["scripts/workflow_check.py", "--scale", "readonly",
                    "--root", str(root)])
    assert proc.returncode == 0, as_text(proc.stderr)[-1500:]


def test_workflow_check_json_stdout_decode_utf8(tmp_path):
    """--json 输出必须能用 utf-8 解码并 json.loads 成功（ensure_ascii=False 契约）。

    防的破坏：为躲编码问题改用 ensure_ascii=True——JSON 合法但 root 路径
    变 \\uXXXX，下游 human-readable 断言全部失效。
    """
    root = tmp_path / "根⚙️目录"
    root.mkdir()
    proc = run_cli(["scripts/workflow_check.py", "--scale", "readonly",
                    "--json", "--root", str(root)])
    assert proc.returncode == 0, as_text(proc.stderr)[-1500:]
    data = json.loads(as_text(proc.stdout))
    assert data["root"].endswith("根⚙️目录"), "root 路径未按原文透出（疑似被替换）"
