# -*- coding: utf-8 -*-
"""workflow_check.py 与 openspec_engine.py 内置模块集成测试

TDD：先写失败测试（RED），再实现（GREEN），最后重构。
测试通过 subprocess 调用 python scripts/workflow_check.py，使用 tmp_path 临时目录。

覆盖：
1. test_check_S2_无CLI环境不误报
2. test_check_S2_缺失产物报错
3. test_check_S8_归档条件通过
4. test_check_S8_PARKED禁止归档
"""

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

WKC = Path(__file__).resolve().parent.parent / "scripts" / "workflow_check.py"


def run_check(*args, root=None):
    """在给定根目录下运行 workflow_check.py，返回 CompletedProcess。

    安全说明：cmd 为参数列表形式，所有元素均来自测试代码硬编码字符串
    或 pytest tmp_path 生成的绝对路径，不含外部用户输入；subprocess.run
    使用 shell=False（默认），不会经过 shell 解释，不存在命令注入风险。
    """
    cmd = [sys.executable, str(WKC)]
    cmd += list(args)
    return subprocess.run(cmd, capture_output=True, text=True, shell=False,
                          cwd=str(root) if root else None,
                          encoding='utf-8', errors='replace')


def _write(root: Path, rel: str, content: str) -> Path:
    """在临时根内安全写文件：解析后必须仍在 root 之下。"""
    target = (root / rel).resolve()
    root_resolved = root.resolve()
    if root_resolved not in target.parents and target != root_resolved:
        raise ValueError("路径逃出临时根：%s" % rel)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target


@pytest.fixture
def tmp_root():
    d = Path(tempfile.mkdtemp(prefix="wfc_openspec_")).resolve()
    yield d
    shutil.rmtree(str(d), ignore_errors=True)


def test_expect_archive_checks_s2_in_archive_dir(tmp_root):
    """F-5：归档后核验必须切到 archive 副本，S2.CHANGE_DIR 不得永久 FAIL。"""
    change = "demo"
    archived = tmp_root / "openspec" / "changes" / "archive" / ("2026-11-25-" + change)
    for rel, content in {
        "proposal.md": "## Why\nx\n",
        "design.md": "## Design\nx\n",
        "tasks.md": "- [x] 1.1 alpha\n",
        "specs/auth/spec.md": "## Purpose\n认证能力\n\n## Requirements\n- 登录\n",
        ".openspec.yaml": "name: demo\nstatus: archived\n",
    }.items():
        _write(archived, rel, content)

    r = run_check(
        "--change", change, "--scale", "medium", "--expect-archive",
        "--root", str(tmp_root), "--json")
    data = json.loads(r.stdout)
    items = data["items"]
    s2_dir = [i for i in items if i["id"] == "S2.CHANGE_DIR"]
    assert s2_dir, "缺 S2.CHANGE_DIR 检查项"
    assert s2_dir[0]["status"] == "OK", s2_dir[0]
    assert "archive" in s2_dir[0]["detail"].replace("\\", "/")
    s2_fails = [i for i in items if i["id"].startswith("S2") and i["status"] == "FAIL"]
    assert not s2_fails, s2_fails


# ---------- S2：规格产物存在性 ----------

def test_check_S2_无CLI环境不误报(tmp_root):
    """无 openspec CLI 的临时目录下，手动创建 change 目录 + 五件必需产物，
    S2 检查不报 FAIL（产物已存在）。"""
    change = "my-change"
    _write(tmp_root, f"openspec/changes/{change}/proposal.md", "## Why\nx\n")
    _write(tmp_root, f"openspec/changes/{change}/design.md", "## Design\nx\n")
    _write(tmp_root, f"openspec/changes/{change}/tasks.md", "- [x] 1.1 alpha\n")
    _write(tmp_root, f"openspec/changes/{change}/specs/auth/spec.md", "## Purpose\n认证能力\n")
    _write(tmp_root, f"openspec/changes/{change}/.openspec.yaml", "name: my-change\n")

    r = run_check("--change", change, "--scale", "medium", "--root", str(tmp_root), "--json")
    assert r.returncode in (0, 1), f"workflow_check 退出码异常：{r.returncode}\n{r.stderr}"

    data = json.loads(r.stdout)
    items = data["items"]
    s2_items = [i for i in items if i["id"].startswith("S2")]
    s2_fails = [i for i in s2_items if i["status"] == "FAIL"]
    assert not s2_fails, (
        f"S2 出现 FAIL 项（产物已存在不应误报）：{[i['check'] for i in s2_fails]}\n"
        f"全部 S2 项：{[(i['check'], i['status']) for i in s2_items]}"
    )


def test_check_S2_缺失产物报错(tmp_root):
    """change 目录存在但缺 proposal.md，S2 报 FAIL。"""
    change = "my-change"
    _write(tmp_root, f"openspec/changes/{change}/design.md", "## Design\nx\n")
    _write(tmp_root, f"openspec/changes/{change}/tasks.md", "- [x] 1.1 alpha\n")
    _write(tmp_root, f"openspec/changes/{change}/specs/auth/spec.md", "## Purpose\n认证能力\n")
    _write(tmp_root, f"openspec/changes/{change}/.openspec.yaml", "name: my-change\n")
    # 故意不创建 proposal.md

    r = run_check("--change", change, "--scale", "medium", "--root", str(tmp_root), "--json")
    assert r.returncode in (0, 1), f"workflow_check 退出码异常：{r.returncode}\n{r.stderr}"

    data = json.loads(r.stdout)
    items = data["items"]
    s2_items = [i for i in items if i["id"].startswith("S2")]
    s2_fails = [i for i in s2_items if i["status"] == "FAIL"]
    assert s2_fails, "缺少 proposal.md 时 S2 应报 FAIL"
    assert any("proposal.md" in i["check"] for i in s2_fails), (
        f"S2 FAIL 项未指向 proposal.md：{[(i['check'], i['status']) for i in s2_fails]}"
    )


# ---------- S8：归档条件 ----------

def test_check_S8_归档条件通过(tmp_root):
    """临时目录下有 tasks.md（全勾选）+ .status.json（无 PARKED），check_S8 不报 FAIL。"""
    change = "my-change"
    _write(tmp_root, f"openspec/changes/{change}/tasks.md", "- [x] 1.1 alpha\n- [x] 1.2 beta\n")
    _write(tmp_root, f"openspec/changes/{change}/.status.json",
           json.dumps({"parked": False, "PARKED": False}, ensure_ascii=False))
    # 主 spec 已同步（S8 逐能力核对）
    _write(tmp_root, f"openspec/changes/{change}/specs/auth/spec.md", "## Purpose\n认证能力\n")
    _write(tmp_root, "openspec/specs/auth/spec.md", "## Purpose\n认证主规格\n")

    r = run_check("--change", change, "--scale", "medium", "--root", str(tmp_root), "--json")
    assert r.returncode in (0, 1), f"workflow_check 退出码异常：{r.returncode}\n{r.stderr}"

    data = json.loads(r.stdout)
    items = data["items"]
    s8_items = [i for i in items if i["id"].startswith("S8")]
    s8_fails = [i for i in s8_items if i["status"] == "FAIL"]
    assert not s8_fails, (
        f"S8 出现 FAIL 项：{[(i['check'], i['status'], i.get('detail','')) for i in s8_fails]}\n"
        f"全部 S8 项：{[(i['check'], i['status']) for i in s8_items]}"
    )


def test_check_S8_PARKED禁止归档(tmp_root):
    """`.status.json` 中 parked=true，check_S8 报 FAIL。"""
    change = "my-change"
    _write(tmp_root, f"openspec/changes/{change}/tasks.md", "- [x] 1.1 alpha\n")
    _write(tmp_root, f"openspec/changes/{change}/.status.json",
           json.dumps({"parked": True, "PARKED": False}, ensure_ascii=False))

    r = run_check("--change", change, "--scale", "medium", "--root", str(tmp_root), "--json")
    assert r.returncode in (0, 1), f"workflow_check 退出码异常：{r.returncode}\n{r.stderr}"

    data = json.loads(r.stdout)
    items = data["items"]
    s8_items = [i for i in items if i["id"].startswith("S8")]
    s8_fails = [i for i in s8_items if i["status"] == "FAIL"]
    assert s8_fails, "parked=true 时 S8 应报 FAIL"
    assert any("PARKED" in i["check"] for i in s8_fails), (
        f"S8 FAIL 项未提及 PARKED：{[(i['check'], i['status']) for i in s8_fails]}"
    )


def test_check_S8_主spec缺Purpose报FAIL(tmp_root):
    """P0-1：主 spec 文件存在但缺 ## Purpose，S8 必须报 FAIL（真实内容校验）。

    旧实现仅用 os.path.isfile 判断文件存在（workflow_check.py:1270-1271），
    从不调用 validate-specs 做真实内容校验——缺 ## Purpose 的主 spec 也会
    被判 OK，S8 门禁形同虚设（假绿）。本用例在修复前会因不报 FAIL 而 RED。
    """
    change = "my-change"
    _write(tmp_root, f"openspec/changes/{change}/tasks.md", "- [x] 1.1 alpha\n")
    _write(tmp_root, f"openspec/changes/{change}/.status.json",
           json.dumps({"parked": False, "PARKED": False}, ensure_ascii=False))
    # delta spec 有 Purpose，但主 spec 缺 ## Purpose（sync 后主 spec 被污染）
    _write(tmp_root, f"openspec/changes/{change}/specs/auth/spec.md", "## Purpose\n认证能力\n")
    _write(tmp_root, "openspec/specs/auth/spec.md", "## Requirements\n- 无 Purpose\n")

    r = run_check("--change", change, "--scale", "medium", "--root", str(tmp_root), "--json")
    assert r.returncode in (0, 1), f"workflow_check 退出码异常：{r.returncode}\n{r.stderr}"

    data = json.loads(r.stdout)
    items = data["items"]
    s8_items = [i for i in items if i["id"].startswith("S8")]
    s8_fails = [i for i in s8_items if i["status"] == "FAIL"]
    assert s8_fails, (
        "缺 ## Purpose 的主 spec 未被 S8 检出——S8 仅查文件存在，未做真实内容校验（P0-1）\n"
        f"全部 S8 项：{[(i['check'], i['status']) for i in s8_items]}"
    )
    assert any("Purpose" in i.get("detail", "") or "purpose" in i.get("detail", "").lower()
               for i in s8_fails), (
        f"S8 FAIL 项未指向 Purpose 缺失：{[(i['check'], i['status'], i.get('detail','')) for i in s8_fails]}"
    )
