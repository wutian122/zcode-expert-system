# -*- coding: utf-8 -*-
"""SDD 三脚本内化回归测试

背景：本插件把 superpowers 7.0.1 的 sdd-workspace / task-brief /
review-package 内化到 scripts/sdd/。本插件设计基线默认无 git，而源版
三个脚本都假定 git 存在——sdd-workspace 在无 git 时因
`git rev-parse` 返回 128 + `set -e` 直接崩溃，review-package 则先报
误导性的 `bad BASE`。本文件锁死修复后的行为：

  - sdd-workspace：无 git 回落 cwd，rc=0，不写 .gitignore；
    plan-path 标记机制在无 git 下仍然防同名计划串账
  - task-brief：按 `### Task N:` 抽取；未命中 exit 3
  - review-package：无 git 时 exit 4 并提示文件快照 sha256 差集
  - 有 git 的两个正例：行为与源版一致（仓库根 + .gitignore；diff 包）

运行：
    python -m pytest tests/test_sdd_scripts.py -v
"""

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SDD_DIR = ROOT / "scripts" / "sdd"
BASH = shutil.which("bash")
GIT = shutil.which("git")

pytestmark = pytest.mark.skipif(not BASH, reason="需要 Git Bash 才能运行 SDD 脚本")

PLAN_TEXT = """# 计划：脚本内化

## Goal
验证抽取与无 git 回落。

### Task 1: 甲组件
内容一。

### Task 2: 乙组件
内容二。

### Task 3: 丙组件
内容三。
"""


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------

def _posix(path):
    """把 Windows 路径转成 Git Bash 可接受的 E:/foo/bar 形式。"""
    return str(path).replace("\\", "/")


def _script(name):
    return _posix(SDD_DIR / name)


def _write(path, text):
    """按 UTF-8 / LF 写文件，避免 Windows 默认 CRLF 干扰 awk 行处理。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))


def _run(args, cwd):
    return subprocess.run(
        [BASH] + args,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _git(cwd, *args):
    assert GIT, "需要 git"
    return subprocess.run(
        [GIT] + list(args),
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )


def _require_non_git(path):
    """确保临时目录不在任何 git 仓库内，否则无 git 分支根本没被验证。"""
    if not GIT:
        return
    probe = subprocess.run(
        [GIT, "rev-parse", "--show-toplevel"],
        cwd=str(path),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if probe.returncode == 0:
        pytest.skip("临时目录位于 git 仓库内（%s），无法验证无 git 分支" % probe.stdout.strip())


# ---------------------------------------------------------------------------
# sdd-workspace
# ---------------------------------------------------------------------------

def test_sdd_workspace_无git时回落到cwd(tmp_path):
    """无 git 时工作区根 = cwd。

    源版 `root=$(cd "$(git rev-parse --show-toplevel)" && pwd -P)` 在
    `set -e` 下遇 git 返回 128 会直接终止脚本（本插件主路径必挂）。
    """
    _require_non_git(tmp_path)
    _write(tmp_path / "plan.md", PLAN_TEXT)

    r = _run([_script("sdd-workspace"), "plan.md"], cwd=tmp_path)

    assert r.returncode == 0, "rc=%s stderr=%s" % (r.returncode, r.stderr)
    assert ".superpowers/sdd/" in r.stdout, r.stdout
    # 探测失败必须是静默回落：源版经由 `cd ""` 偶然回落，却把
    # `fatal: not a git repository` 泄漏到 stderr（本机 Git Bash 5.2 实测）。
    assert "fatal" not in r.stderr, "无 git 探测把 fatal 泄漏到 stderr：%s" % r.stderr
    ws = tmp_path / ".superpowers" / "sdd" / "plan"
    assert ws.is_dir(), "工作区未落在 cwd 下：%s" % ws
    assert (ws / "plan-path").read_text(encoding="utf-8").strip() == "plan.md"


def test_sdd_workspace_无git时不写gitignore(tmp_path):
    """无 git 时不需要 .gitignore（写了也无害，但要求明确只在有 git 时写）。"""
    _require_non_git(tmp_path)
    _write(tmp_path / "plan.md", PLAN_TEXT)

    r = _run([_script("sdd-workspace"), "plan.md"], cwd=tmp_path)

    assert r.returncode == 0, "rc=%s stderr=%s" % (r.returncode, r.stderr)
    assert not (tmp_path / ".superpowers" / "sdd" / ".gitignore").exists()


def test_sdd_workspace_同一计划重复调用返回同一目录(tmp_path):
    """重复调用必须幂等，否则任务产物会散落在多个工作区。"""
    _require_non_git(tmp_path)
    _write(tmp_path / "plan.md", PLAN_TEXT)

    r1 = _run([_script("sdd-workspace"), "plan.md"], cwd=tmp_path)
    r2 = _run([_script("sdd-workspace"), "plan.md"], cwd=tmp_path)

    assert r1.returncode == 0, r1.stderr
    assert r2.returncode == 0, r2.stderr
    assert r1.stdout.strip() == r2.stdout.strip()


def test_sdd_workspace_同名计划不同目录互不串账(tmp_path):
    """plan-path 标记机制必须保留：同名 plan.md 不得共用工作区。"""
    _require_non_git(tmp_path)
    _write(tmp_path / "a" / "plan.md", "# A\n\n### Task 1: a\n")
    _write(tmp_path / "b" / "plan.md", "# B\n\n### Task 1: b\n")

    ra = _run([_script("sdd-workspace"), "a/plan.md"], cwd=tmp_path)
    rb = _run([_script("sdd-workspace"), "b/plan.md"], cwd=tmp_path)

    assert ra.returncode == 0, ra.stderr
    assert rb.returncode == 0, rb.stderr
    assert ra.stdout.strip() != rb.stdout.strip(), "同名计划复用了同一工作区"
    marker_a = tmp_path / ".superpowers" / "sdd" / "plan" / "plan-path"
    marker_b = tmp_path / ".superpowers" / "sdd" / "plan-b" / "plan-path"
    assert marker_a.read_text(encoding="utf-8").strip() == "a/plan.md"
    assert marker_b.read_text(encoding="utf-8").strip() == "b/plan.md"


def test_sdd_workspace_git仓库内落在仓库根并写gitignore(tmp_path):
    """有 git 时行为原样：工作区挂仓库根，不是 cwd。"""
    if not GIT:
        pytest.skip("需要 git")
    repo = tmp_path / "repo"
    sub = repo / "sub"
    sub.mkdir(parents=True)
    _git(repo, "init", "-q")
    _write(sub / "plan.md", PLAN_TEXT)

    r = _run([_script("sdd-workspace"), "plan.md"], cwd=sub)

    assert r.returncode == 0, "rc=%s stderr=%s" % (r.returncode, r.stderr)
    assert ".superpowers/sdd/" in r.stdout, r.stdout
    base = repo / ".superpowers" / "sdd"
    assert (base / ".gitignore").read_text(encoding="utf-8") == "*\n"
    ws = base / "plan"
    assert ws.is_dir(), "工作区未落在仓库根：%s" % ws
    assert (ws / "plan-path").read_text(encoding="utf-8").strip() == "sub/plan.md"


# ---------------------------------------------------------------------------
# task-brief
# ---------------------------------------------------------------------------

def test_task_brief_按Task编号抽取(tmp_path):
    """只输出指定 Task 段，前序/后继任务不得混入。"""
    _require_non_git(tmp_path)
    _write(tmp_path / "plan.md", PLAN_TEXT)

    r = _run([_script("task-brief"), "plan.md", "2"], cwd=tmp_path)

    assert r.returncode == 0, "rc=%s stderr=%s" % (r.returncode, r.stderr)
    outs = list((tmp_path / ".superpowers" / "sdd").glob("*/task-2-brief.md"))
    assert len(outs) == 1, "默认输出文件数量不对：%s" % outs
    text = outs[0].read_text(encoding="utf-8")
    assert "### Task 2: 乙组件" in text
    assert "内容二。" in text
    assert "### Task 1" not in text
    assert "内容一" not in text
    assert "### Task 3" not in text
    assert "内容三" not in text


def test_task_brief_任务不存在时退出3(tmp_path):
    """编号未命中时必须 exit 3，不能写空简报当成功。"""
    _require_non_git(tmp_path)
    _write(tmp_path / "plan.md", PLAN_TEXT)

    r = _run([_script("task-brief"), "plan.md", "9"], cwd=tmp_path)

    assert r.returncode == 3, "rc=%s stderr=%s" % (r.returncode, r.stderr)
    assert "not found" in r.stderr, r.stderr


# ---------------------------------------------------------------------------
# review-package
# ---------------------------------------------------------------------------

def test_review_package_无git时exit4(tmp_path):
    """无 git 时明确 exit 4 并指向文件快照流程，不得先报 bad BASE。"""
    _require_non_git(tmp_path)
    _write(tmp_path / "plan.md", PLAN_TEXT)

    r = _run(
        [_script("review-package"), "plan.md", "abc1234", "def5678"],
        cwd=tmp_path,
    )

    assert r.returncode == 4, "rc=%s stderr=%s" % (r.returncode, r.stderr)
    assert "快照" in r.stderr, r.stderr
    assert "stage-S5-implement.md" in r.stderr, r.stderr
    assert "bad BASE" not in r.stderr, "无 git 被误报成参数错误：%s" % r.stderr


def test_review_package_git仓库内生成diff包(tmp_path):
    """有 git 时行为原样：BASE..HEAD 的提交列表 + stat + diff 写入文件。"""
    if not GIT:
        pytest.skip("需要 git")
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "SDD Test")
    _git(repo, "config", "commit.gpgsign", "false")
    _write(repo / "app.txt", "one\n")
    _git(repo, "add", "app.txt")
    _git(repo, "commit", "-q", "-m", "one")
    base = _git(repo, "rev-parse", "HEAD").stdout.strip()
    _write(repo / "app.txt", "one\ntwo\n")
    _git(repo, "add", "app.txt")
    _git(repo, "commit", "-q", "-m", "two")
    head = _git(repo, "rev-parse", "HEAD").stdout.strip()
    _write(repo / "plan.md", PLAN_TEXT)

    r = _run(
        [_script("review-package"), "plan.md", base, head, "review.diff"],
        cwd=repo,
    )

    assert r.returncode == 0, "rc=%s stderr=%s" % (r.returncode, r.stderr)
    pkg = (repo / "review.diff").read_text(encoding="utf-8")
    assert "# Review package" in pkg
    assert "## Commits" in pkg
    assert "## Diff" in pkg
    assert "+two" in pkg
    assert "1 commit(s)" in r.stdout
