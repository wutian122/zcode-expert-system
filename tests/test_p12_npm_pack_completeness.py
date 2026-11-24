# -*- coding: utf-8 -*-
"""发布包完整性守卫（npm pack 产物必须含全部部署必需组件）。

背景：npm 3.2.2 发布后用户全局安装、`zcode-expert-system install` 报
「⚠️ 跳过 Claude Code 部署：.claude-plugin/plugin.json 不存在」——
根因是 package.json 的 files 白名单漏了 .claude-plugin/ 目录（同类问题
还漏过 install-claude-code.js/cc-uninstall.js/target-menu.js）。
npm 的 files 是白名单语义：没列的就不打包，漏一个文件就让部署链断裂，
而 install.js 静默跳过后仍打印「部署完成」，用户无从发现。

本测试守护两类红线：
  A. files 白名单覆盖：部署必需组件全部列入 files（或在 always-included
     名单里），npm pack 产物逐项核对存在。
  B. 静默跳过禁止：deployClaudeCode 对 manifest 缺失必须 exit 1，
     不得 return 后继续「部署完成」。
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PKG = PROJECT_ROOT / "package.json"

# 部署链必需的顶层组件（install.js / install-claude-code.js 实际消费）
REQUIRED_PACKED = [
    ".claude-plugin/plugin.json",
    ".claude-plugin/marketplace.json",
    ".zcode-plugin/plugin.json",
    "SKILL.md",
    "package.json",
    "zcode_dev_workflow.py",
    "zcode_expert_system.py",
    "skill_entry.py",
    "icon.png",
    "bin/cli.js",
    "config/categories.json",
    "config/experts.json",
    "config/workflow.json",
    "context/context-manager.py",
    "hooks/claude-hooks.json",
    "hooks/hooks.json",
    "hooks/prepend-global-rules-reminder.mjs",
    "scripts/install.js",
    "scripts/install-claude-code.js",
    "scripts/cc-uninstall.js",
    "scripts/target-menu.js",
    "scripts/openspec_engine.py",
    "scripts/workflow_check.py",
    "commands/wf/triage.md",
]


def _pkg_files():
    return json.loads(PKG.read_text(encoding="utf-8")).get("files", [])


def _npm_pack_listing():
    """跑 npm pack --dry-run --json，返回产物文件列表（相对路径）。"""
    npm_cmd = "npm.cmd" if sys.platform == "win32" else "npm"
    r = subprocess.run(
        [npm_cmd, "pack", "--dry-run", "--json"],
        cwd=str(PROJECT_ROOT), capture_output=True, text=True, shell=False,
        encoding="utf-8", errors="replace", timeout=120,
    )
    assert r.returncode == 0, "npm pack 失败：%s" % r.stderr[:300]
    data = json.loads(r.stdout)
    # npm 12 输出 {name: {...}} 字典（旧版是数组）——两种都兼容
    entry = data[0] if isinstance(data, list) else next(iter(data.values()))
    files = []
    for f in entry.get("files", []):
        files.append(f["path"].replace("\\", "/"))
    return files


def test_files_whitelist_covers_required_components():
    """files 白名单必须覆盖全部部署必需组件（漏一个就断一条部署链）。"""
    files = _pkg_files()
    # files 支持目录与文件两种条目；目录条目覆盖其下所有内容
    # 注：npm 对 package.json/README/LICENSE/主入口（main）无条件包含，
    # 不需要显式列入 files——这些属于 npm always-included 集合。
    always_included = {"package.json", "README.md", "README_CN.md", "LICENSE", "bin/cli.js"}
    covered_dirs = [f.rstrip("/") for f in files if f.endswith("/")]
    covered_files = [f for f in files if not f.endswith("/")]
    missing = []
    for req in REQUIRED_PACKED:
        top = req.split("/")[0]
        if req in covered_files or top in covered_dirs or req in always_included:
            continue
        missing.append(req)
    assert not missing, (
        "package.json files 白名单漏了部署必需组件：%s。"
        "npm 是白名单语义，漏列=不打包=全局安装后部署链断裂。" % missing)


def test_npm_pack_artifact_contains_required_components():
    """npm pack 实际产物必须逐项包含部署必需组件（files 之外的第二道防线）。"""
    listing = _npm_pack_listing()
    # package.json 无条件包含（npm always-included）
    always_included = {"package.json"}
    missing = [r for r in REQUIRED_PACKED if r not in listing and r not in always_included]
    assert not missing, (
        "npm pack 产物缺失：%s（全局安装后将无法完成部署）" % missing)


def test_manifest_missing_must_exit_nonzero_not_silent_skip():
    """deployClaudeCode 对 .claude-plugin/plugin.json 缺失必须 exit 1。

    npm 3.2.2 事故：manifest 缺失时只 log ⚠️ 跳过，主流程继续打印
    「部署完成」——用户以为装上了，/plugin 里却没有。守卫：源码中该分支
    不得存在裸 return，必须调用 process.exit(1)。
    """
    src = (PROJECT_ROOT / "scripts" / "install.js").read_text(encoding="utf-8")
    # 定位 deployClaudeCode 内的 manifest 缺失分支（671 行附近，
    # 用函数名锚定而非行号：先切出 deployClaudeCode 函数体，再找
    # !fs.existsSync(manifestSrc) 判断）
    start = src.index("function deployClaudeCode")
    end = src.index("\nfunction ", start + 10)
    fn_body = src[start:end]
    idx = fn_body.find("!fs.existsSync(manifestSrc)")
    assert idx >= 0, "deployClaudeCode 内未找到 manifestSrc 缺失分支——代码结构变了，请人工核查"
    # 取该判断行起至其后 15 行作为分支体
    lines = fn_body[idx:].splitlines()[:15]
    branch = "\n".join(lines)
    assert "process.exit(1)" in branch, (
        "manifest 缺失分支必须 process.exit(1)，当前分支体：\n%s" % branch)
    assert "return;" not in branch, (
        "manifest 缺失分支不得裸 return（静默跳过后主流程会打印「部署完成」）：\n%s" % branch)