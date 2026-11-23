"""workflow.json component_registry 与 self_check 第 8 条回归测试。

验证：
1. 所有 stages[].components 都在 component_registry 登记（无遗漏）。
2. 每个登记项的 internal 路径在磁盘上存在。
3. required: true 的资产存在。
4. workflow.json 中 `openspec:` 冒号名已全部清零。
5. workflow_check.py --self_check 退出码 0（基线无漂移）。
6. 临时重命名一个 required 资产后 self_check 退出码非 0（再恢复）。
"""

import json
import os
import subprocess
import sys

import pytest

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKFLOW_JSON = os.path.join(PLUGIN_ROOT, "config", "workflow.json")
WORKFLOW_CHECK = os.path.join(PLUGIN_ROOT, "scripts", "workflow_check.py")


def load_workflow():
    with open(WORKFLOW_JSON, encoding="utf-8") as f:
        return json.load(f)


def test_registry_覆盖所有_components():
    wf = load_workflow()
    registry = wf.get("component_registry", {}) or {}
    for s in wf.get("stages", []):
        for comp in s.get("components", []):
            assert comp in registry, "组件 %r 在 stage %s 中未登记" % (comp, s["id"])


def test_registry_internal路径存在():
    wf = load_workflow()
    registry = wf.get("component_registry", {}) or {}
    for comp, entry in registry.items():
        if not isinstance(entry, dict):
            continue  # 跳过 "$comment" 等非条目键
        internal = entry.get("internal")
        assert internal is not None, "组件 %r 缺 internal 字段" % comp
        path = os.path.join(PLUGIN_ROOT, internal)
        assert os.path.exists(path), "组件 %r 的 internal 路径不存在：%s" % (comp, internal)


def test_registry_required资产存在():
    wf = load_workflow()
    registry = wf.get("component_registry", {}) or {}
    for comp, entry in registry.items():
        if not isinstance(entry, dict):
            continue  # 跳过 "$comment" 等非条目键
        if entry.get("required") is True:
            scripts = entry.get("scripts") or {}
            for script_name, script_rel in scripts.items():
                path = os.path.join(PLUGIN_ROOT, script_rel)
                assert os.path.exists(path), \
                    "组件 %r 的必需脚本 %s 路径不存在：%s" % (comp, script_name, script_rel)


def test_冒号名已清零():
    text = open(WORKFLOW_JSON, encoding="utf-8").read()
    assert "openspec:" not in text, "workflow.json 中仍有 openspec: 冒号名（应改为连字符名）"


def test_self_check_rc_0():
    proc = subprocess.run([sys.executable, WORKFLOW_CHECK, "--self-check"],
                          capture_output=True, text=True, cwd=PLUGIN_ROOT,
                          encoding='utf-8', errors='replace')
    assert proc.returncode == 0, "self_check 应返回 0，实际 %d：%s" % (
        proc.returncode, proc.stdout + proc.stderr)


def test_self_check_缺失资产即失败():
    # 临时重命名一个 required 资产（baseline-test 对应的阶段规格文件）
    target = os.path.join(PLUGIN_ROOT, "references", "stage-S4-env-baseline.md")
    backup = target + ".bak-registry-test"
    os.replace(target, backup)
    try:
        proc = subprocess.run([sys.executable, WORKFLOW_CHECK, "--self-check"],
                              capture_output=True, text=True, cwd=PLUGIN_ROOT,
                              encoding='utf-8', errors='replace')
        assert proc.returncode != 0, \
            "缺失 required 资产时 self_check 应非零退出，实际 %d" % proc.returncode
        assert "stage-S4-env-baseline.md" in (proc.stdout + proc.stderr), \
            "self_check 应点出缺失的资产文件"
    finally:
        os.replace(backup, target)
    proc = subprocess.run([sys.executable, WORKFLOW_CHECK, "--self-check"],
                          capture_output=True, text=True, cwd=PLUGIN_ROOT,
                          encoding='utf-8', errors='replace')
    assert proc.returncode == 0, "恢复后 self_check 应返回 0，实际 %d：%s" % (
        proc.returncode, proc.stdout + proc.stderr)
