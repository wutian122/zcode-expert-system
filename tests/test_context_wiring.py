# -*- coding: utf-8 -*-
"""P8 批次四 Task 13/14：context 持久化接线复活。

抓的破坏：zcode_expert_system.py 每次经 spec_from_file_location + exec_module
全新加载 context-manager（新实例、新空 store），get_context_summary 只读内存、
load_result 从不接线 → _load_context_summary 恒 ""——SKILL.md 宣称的
「前序上下文注入」是死特性，而每次路由仍在写盘（纯 I/O 浪费）。

修法：get_context_summary 内存 miss 时扫盘上 result-*.json 回填
（跨进程接线的另一半），坏文件跳过；顺手收口两个精度项
（结果文件名微秒时间戳防碰撞、sys.path 一次性注入）与死代码兜底。

测试必须覆盖「全新实例 / 全新进程」读盘路径——exec_module 不进 sys.modules，
进程内复用是假象，所以接线验收以「第二个全新实例/进程能读到」为准。

主控 Ruling（对计划 Task 14 的修正）：计划的 subprocess 方案假设 CLI 支持
`--task-id`，实测 zcode_expert_system.py 的 __main__ 只取 argv[1] 作任务文本
（:986-988），无该参数。改用进程内双调用（monkeypatch HOME/USERPROFILE 落
沙箱，_default_store_dir 经 expanduser 落在沙箱内）断言全链；CLI 面不扩。
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

CM_PATH = PROJECT_ROOT / "context" / "context-manager.py"


def load_cm():
    """与 zcode_expert_system.py 相同的方式加载 context-manager（exec_module）。"""
    spec = importlib.util.spec_from_file_location(
        "context_manager_under_test", str(CM_PATH))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run_py(code):
    """在全新进程里跑一段 Python（验证跨进程读盘路径）。

    手动解码：text=True 会用 locale（cp936）解码子进程输出，与子进程
    PYTHONIOENCODING=utf-8 不一致——拿原始字节自己按 utf-8 解。
    """
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    p = subprocess.run([sys.executable, "-c", code],
                       capture_output=True, timeout=60, env=env)
    return (p.returncode,
            p.stdout.decode("utf-8", "replace"),
            p.stderr.decode("utf-8", "replace"))


CM_BOOT = (
    "import importlib.util\n"
    "spec = importlib.util.spec_from_file_location('cm', r'%s')\n"
    "mod = importlib.util.module_from_spec(spec)\n"
    "spec.loader.exec_module(mod)\n"
    "ctx = mod.ExpertContext(context_dir=r'%s')\n"
)


def test_summary_survives_process_restart(tmp_path):
    """跨进程接线：A 进程 save_context 落盘 → B 进程（全新实例）读盘出摘要。

    修前 B 恒返回 ""（内存 store 必空、磁盘从不读）——死特性的直接证据。
    """
    ctx_dir = tmp_path / "ctxstore"
    boot = CM_BOOT % (CM_PATH, ctx_dir)
    rc, out, err = _run_py(
        boot + "ctx.save_context('t1', 'exp-x', {'task_id': 't1', "
               "'selected_expert': {'id': 'exp-x'}, 'note': '第一步结论'})\n"
               "print('SAVED')\n")
    assert rc == 0 and "SAVED" in out, "save 进程失败：%s" % err[-500:]

    rc, out, err = _run_py(
        boot + "print('SUMMARY::' + ctx.get_context_summary('t1'))\n")
    assert rc == 0, "read 进程失败：%s" % err[-500:]
    summary = out.split("SUMMARY::", 1)[1].strip() if "SUMMARY::" in out else ""
    assert summary and "[exp-x]" in summary, (
        "全新进程读盘回填失败——修前恒空串：%r" % summary)


def test_summary_empty_without_any_evidence(tmp_path):
    """双向反例：新实例 + 空目录 → 返回 ""，不得编造摘要。"""
    mod = load_cm()
    ctx = mod.ExpertContext(context_dir=str(tmp_path / "empty"))
    assert ctx.get_context_summary("t-none") == ""


def test_bad_result_file_skipped_not_fatal(tmp_path):
    """双向反例：目录里混入写坏字节的 result 文件 → 摘要仍由好文件生成。"""
    store = tmp_path / "store"
    mod = load_cm()
    ctx1 = mod.ExpertContext(context_dir=str(store))
    ctx1.save_context("t1", "exp-ok",
                      {"task_id": "t1", "selected_expert": {"id": "exp-ok"},
                       "note": "好文件"})
    (store / "result-t1-junk-20260101-000000.json").write_bytes(b"\xff\xfe{broken")

    ctx2 = mod.ExpertContext(context_dir=str(store))    # 全新实例，内存必空
    summary = ctx2.get_context_summary("t1")
    assert summary and "[exp-ok]" in summary, (
        "单个坏文件毁掉整个摘要：%r" % summary)


def test_result_filename_collision_safe(tmp_path):
    """精度项①：同 task+expert 同一秒连续两次 save → 两个文件，第一次不被覆盖。"""
    mod = load_cm()
    ctx = mod.ExpertContext(context_dir=str(tmp_path / "s"))
    r1 = ctx.save_context("t1", "exp-x", {"task_id": "t1", "n": 1})
    r2 = ctx.save_context("t1", "exp-x", {"task_id": "t1", "n": 2})
    assert r1 != r2, "结果文件名秒级时间戳碰撞（修前同名互相覆盖）"
    assert json.loads(Path(r1).read_text(encoding="utf-8"))["n"] == 1
    assert json.loads(Path(r2).read_text(encoding="utf-8"))["n"] == 2


def test_scripts_dir_inserted_once(tmp_path):
    """精度项②：sys.path 一次性注入——模块加载时插入一次，调用不重复插入。

    脚本插入发生在模块**加载时**（context-manager.py:59-61 顶部一次性执行），
    _llm_summarize 调用时不再插入。全量跑时前序测试可能已把 scripts 插入
    sys.path——先清成干净基线再 load_cm，保证模块加载时从基线插入恰好一次，
    避免从污染态开始计数导致假 FAIL。
    """
    scripts_dir = os.path.join(str(PROJECT_ROOT), "scripts")
    while scripts_dir in sys.path:
        sys.path.remove(scripts_dir)
    mod = load_cm()
    ctx = mod.ExpertContext(context_dir=str(tmp_path / "s"))
    # _call_llm 恒 None（刻意设计），两次调用都走降级截断，不触网
    try:
        ctx._llm_summarize("x")
        ctx._llm_summarize("y")
        assert sys.path.count(scripts_dir) == 1, (
            "sys.path 每调用重复 insert（修前同实例两次调用后 ==2）：%d"
            % sys.path.count(scripts_dir))
    finally:
        # 计划 Task 13 的夹具卫生要求（P9 复审 🟡 收口）：不向 pytest 进程
        # 遗留 sys.path 条目，避免改变后续测试的导入解析面
        while scripts_dir in sys.path:
            sys.path.remove(scripts_dir)


def test_full_chain_second_call_has_context(tmp_path, monkeypatch):
    """Task 14 全链集成：同 task_id 第二次路由必须注入【前序上下文】。

    进程内双调用（Ruling 见文件头）：第一次 build_context 落盘，
    第二次 _load_context_summary（exec_module 全新实例）读盘回填 →
    派发单 prompt 带【前序上下文】头。HOME/USERPROFILE 落沙箱，
    不污染真实 ~/.zcode。
    """
    home = tmp_path / "home"
    home.mkdir()
    for k, v in (("USERPROFILE", str(home)), ("HOME", str(home))):
        monkeypatch.setenv(k, v)

    from zcode_expert_system import zcode_expert_system
    task = "设计一个支持高并发的后端 API 接口"
    r1 = zcode_expert_system(task, task_id="t-wire")
    assert r1["context"]["task_id"] == "t-wire"
    assert r1["expert_result"].get("context_summary") == "", (
        "第一次调用不该有历史")

    r2 = zcode_expert_system(task, task_id="t-wire")
    assert r2["selected_expert"] is not None, "路由未选出专家，无法验证派发单"
    er = r2["expert_result"]
    assert er.get("context_summary"), "第二次调用未注入前序上下文（接线断裂）"
    assert "【前序上下文】" in er["dispatch"]["prompt"], (
        "prompt 未拼【前序上下文】头")


def test_one_shot_without_task_id_has_empty_context(tmp_path, monkeypatch):
    """双向反例：不传 task_id → context_summary 为空串，prompt 不含注入头。"""
    home = tmp_path / "home2"
    home.mkdir()
    for k, v in (("USERPROFILE", str(home)), ("HOME", str(home))):
        monkeypatch.setenv(k, v)

    from zcode_expert_system import zcode_expert_system
    r = zcode_expert_system("实现一个限流中间件")
    assert r["selected_expert"] is not None, "路由未选出专家，无法验证派发单"
    er = r["expert_result"]
    assert er.get("context_summary") == "", "一次性路由不应注入历史摘要"
    assert "【前序上下文】" not in (er.get("dispatch") or {}).get("prompt", ""), (
        "空摘要仍被拼进 prompt（防空段注入头）")


# ---------------------------------------------------------------------------
# N-06：不传 task_id 时默认生成值必须同秒不碰撞（微秒级）
# ---------------------------------------------------------------------------

def test_default_task_id_unique_within_same_second(tmp_path, monkeypatch):
    """N-06：同一秒内两次不传 task_id 的 build_context，必须生成不同 task_id。

    秒级精度（%Y%m%d-%H%M%S）下同秒两次调用生成相同 task_id，
    _load_context_summary 按 task_id 回填时第二个任务会读到第一个任务的
    历史摘要并注入派发单（归属串扰）。改用微秒级（%f）后不再碰撞。
    """
    home = tmp_path / "home3"
    home.mkdir()
    for k, v in (("USERPROFILE", str(home)), ("HOME", str(home))):
        monkeypatch.setenv(k, v)

    from zcode_expert_system import build_context
    # 连续两次调用（同一秒内），不传 task_id
    c1 = build_context(None, "frontend-client", None, [], None, None, None,
                       persist=False)
    c2 = build_context(None, "frontend-client", None, [], None, None, None,
                       persist=False)
    assert c1["task_id"] != c2["task_id"], (
        "同秒两次调用生成相同 task_id（%s）——秒级精度未改为微秒级"
        % c1["task_id"])
    # 格式核验：必须以 %Y%m%d-%H%M%S%f 形态出现（微秒 6 位）
    import re
    assert re.match(r"^task-\d{8}-\d{6}\d{6}$", c1["task_id"]), (
        "task_id 格式不是微秒级：%s" % c1["task_id"])
