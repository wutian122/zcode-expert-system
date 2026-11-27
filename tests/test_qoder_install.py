# -*- coding: utf-8 -*-
"""Qoder Desktop 适配回归测试。

覆盖：
  1. QODER_HOME 指向沙箱，不写真实 ~/.qoder
  2. dry-run 零写入
  3. Skill / Commands / Agents / Hook 全部部署
  4. 命令与 SKILL.md 中的宿主路径被重写为 Qoder 安装目录
  5. settings.json 只合并且保留用户已有配置
  6. 重复安装幂等，不重复 Hook
  7. 卸载只删本插件内容，保留其他 Hook / 设置
  8. ZCode / Claude Code 目录完全不被触碰
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INSTALLER = PROJECT_ROOT / "scripts" / "install-qoder.js"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None, reason="环境无 node，跳过 Qoder 安装测试"
)


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """把 QODER_HOME 与 HOME 都指向临时目录。

    Qoder Desktop 会注入真实 QODER_HOME（例如 C:/Users/x/.qoder），
    所以只改 HOME 不够——安装脚本必须优先使用沙箱 QODER_HOME。
    """
    home = (tmp_path / "home").resolve()
    home.mkdir()
    qoder = home / ".qoder"

    for key, value in (
        ("HOME", str(home)),
        ("USERPROFILE", str(home)),
        ("HOMEDRIVE", home.drive or "C:"),
        ("HOMEPATH", str(home)[len(home.drive):] if home.drive else str(home)),
        ("QODER_HOME", str(qoder)),
    ):
        monkeypatch.setenv(key, value)
    env = dict(os.environ)

    # node 侧硬闸：若 QODER_HOME 仍指向真实目录，整批 skip，绝不冒险写入。
    probe = subprocess.run(
        ["node", "-e", "process.stdout.write(process.env.QODER_HOME || '')"],
        env=env, capture_output=True, text=True, timeout=30,
        encoding="utf-8", errors="replace",
    )
    if Path(probe.stdout.strip()).resolve() != qoder.resolve():
        pytest.skip("无法把 QODER_HOME 重定向到沙箱，跳过 Qoder 安装测试")
    return env, home, qoder


def run_qoder(env, *args, timeout=180):
    return subprocess.run(
        ["node", str(INSTALLER), *args],
        env=env, cwd=str(PROJECT_ROOT), capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=timeout,
    )


def seed_settings(qoder):
    qoder.mkdir(parents=True, exist_ok=True)
    data = {
        "enabledPlugins": {"existing@market": True},
        "providers": {"demo": {"baseUrl": "https://example.invalid"}},
        "hooks": {
            "UserPromptSubmit": [
                {"hooks": [{"type": "command", "command": "echo keep-me", "name": "keep"}]}
            ],
            "Stop": [
                {"hooks": [{"type": "command", "command": "echo stop", "name": "stop"}]}
            ],
        },
    }
    (qoder / "settings.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return data


def run_unified(env, *args, timeout=180):
    return subprocess.run(
        ["node", str(PROJECT_ROOT / "scripts" / "install.js"), *args],
        env=env, cwd=str(PROJECT_ROOT), capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=timeout,
    )


def test_qoder_home_cannot_point_to_zcode_or_claude(sandbox):
    """QODER_HOME 误指向其他宿主时必须 fail-closed，且零写入。"""
    env, home, _qoder = sandbox
    for bad_name in (".zcode", ".claude"):
        bad_env = dict(env, QODER_HOME=str(home / bad_name))
        proc = run_qoder(bad_env, "--dry-run")
        assert proc.returncode != 0
        assert "受保护" in (proc.stdout + proc.stderr)
        assert not (home / bad_name).exists()


def test_invalid_user_prompt_submit_shape_is_rejected(sandbox):
    """hooks.UserPromptSubmit 不是数组时必须中止，不静默覆盖用户配置。"""
    env, _home, qoder = sandbox
    qoder.mkdir(parents=True, exist_ok=True)
    original = {
        "enabledPlugins": {"x@y": True},
        "hooks": {"UserPromptSubmit": {"preserve": "me"}},
    }
    (qoder / "settings.json").write_text(
        json.dumps(original, ensure_ascii=False, indent=2), encoding="utf-8")
    proc = run_qoder(env, "--dry-run")
    assert proc.returncode != 0
    assert "UserPromptSubmit 必须是数组" in (proc.stdout + proc.stderr)
    assert json.loads((qoder / "settings.json").read_text(encoding="utf-8")) == original


def test_unified_install_accepts_qoder_target(sandbox):
    """`zcode-expert-system install --targets qoder` 必须走 Qoder 分支。"""
    env, home, qoder = sandbox
    seed_settings(qoder)
    proc = run_unified(env, "--targets", "qoder")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert (qoder / "skills" / "zcode-expert-system" / "SKILL.md").is_file()
    assert len(list((qoder / "commands" / "wf").glob("*.md"))) == 12
    assert len(list((qoder / "agents").glob("*.md"))) == 363
    assert not (home / ".zcode").exists(), "只选 Qoder 时不得部署 ZCode"
    assert not (home / ".claude").exists(), "只选 Qoder 时不得部署 Claude Code"


def test_interactive_default_does_not_auto_install_qoder(sandbox):
    """非交互终端保持历史默认：ZCode + Claude Code，不自动选 Qoder。"""
    env, home, qoder = sandbox
    proc = run_unified(env, "--dry-run")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "跳过 Qoder 部署（未选择）" in proc.stdout
    assert not qoder.exists()
    assert not (home / ".zcode").exists()
    assert not (home / ".claude").exists()


def test_dry_run_writes_nothing(sandbox):
    env, home, qoder = sandbox
    proc = run_qoder(env, "--dry-run")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "dry-run" in proc.stdout
    assert not qoder.exists(), "dry-run 不得创建 ~/.qoder"
    assert not (home / ".zcode").exists()
    assert not (home / ".claude").exists()


def test_install_deploys_all_components_and_rewrites_paths(sandbox):
    env, home, qoder = sandbox
    seed_settings(qoder)
    proc = run_qoder(env)
    assert proc.returncode == 0, proc.stdout + proc.stderr

    skill = qoder / "skills" / "zcode-expert-system"
    commands = qoder / "commands" / "wf"
    agents = qoder / "agents"
    assert (skill / "SKILL.md").is_file()
    assert len(list((qoder / "skills").glob("zes-*/SKILL.md"))) == 15
    assert len(list(commands.glob("*.md"))) == 12
    assert len(list(agents.glob("*.md"))) == 363

    skill_posix = skill.as_posix()
    for rel in ("triage", "plan", "check", "implement", "verify", "archive"):
        text = (commands / f"{rel}.md").read_text(encoding="utf-8")
        assert "${ZCODE_PLUGIN_ROOT}" not in text
        assert "${CLAUDE_PLUGIN_ROOT}" not in text
    # 这些命令原本直接引用宿主插件根，必须落到 Qoder 技能绝对路径。
    for rel in ("triage", "plan", "check", "verify", "archive"):
        text = (commands / f"{rel}.md").read_text(encoding="utf-8")
        assert skill_posix in text, f"{rel}.md 未重写为 Qoder 技能路径"

    skill_md = (skill / "SKILL.md").read_text(encoding="utf-8")
    assert skill_posix in skill_md
    assert "${ZCODE_PLUGIN_ROOT}" not in skill_md
    assert "${CLAUDE_PLUGIN_ROOT}" not in skill_md

    manager = (agents / "manager-backend-architecture.md").read_text(encoding="utf-8")
    assert "metadata:" not in manager
    assert "input:" not in manager
    assert "output:" not in manager
    assert 'name: "manager-backend-architecture"' in manager
    assert "zcode-expert-system:qoder-adapter" in manager

    settings = json.loads((qoder / "settings.json").read_text(encoding="utf-8"))
    assert settings["enabledPlugins"] == {"existing@market": True}
    assert settings["providers"] == {"demo": {"baseUrl": "https://example.invalid"}}
    assert len(settings["hooks"]["Stop"]) == 1
    groups = settings["hooks"]["UserPromptSubmit"]
    assert any(g["hooks"][0].get("command") == "echo keep-me" for g in groups)
    ours = [h for g in groups for h in g["hooks"] if h.get("name") == "zcode-expert-system-routing"]
    assert len(ours) == 1
    assert (skill / "hooks" / "prepend-global-rules-reminder.mjs").as_posix() in ours[0]["command"]

    manifest = json.loads(
        (qoder / "expert-system" / "qoder-deployed.json").read_text(encoding="utf-8"))
    assert manifest["version"] == json.loads(
        (PROJECT_ROOT / "package.json").read_text(encoding="utf-8"))["version"]
    assert len(manifest["agents"]) == 363
    assert len(manifest["commands"]) == 12
    assert len(manifest["vendorSkills"]) == 15

    assert not (home / ".zcode").exists(), "Qoder 安装不得写 ~/.zcode"
    assert not (home / ".claude").exists(), "Qoder 安装不得写 ~/.claude"


def test_installed_hook_emits_qoder_additional_context(sandbox):
    env, _home, qoder = sandbox
    proc = run_qoder(env)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    hook = qoder / "skills" / "zcode-expert-system" / "hooks" / "prepend-global-rules-reminder.mjs"
    r = subprocess.run(
        ["node", str(hook)],
        input=json.dumps({"hook_event_name": "UserPromptSubmit", "prompt": "修复登录接口的鉴权 bug"}),
        env=env, cwd=str(PROJECT_ROOT), capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=30,
    )
    assert r.returncode == 0
    payload = json.loads(r.stdout)
    assert payload["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
    assert "专家体系路由" in payload["hookSpecificOutput"]["additionalContext"]


def test_reinstall_is_idempotent(sandbox):
    env, _home, qoder = sandbox
    seed_settings(qoder)
    first = run_qoder(env)
    assert first.returncode == 0, first.stdout + first.stderr
    settings1 = (qoder / "settings.json").read_text(encoding="utf-8")

    second = run_qoder(env)
    assert second.returncode == 0, second.stdout + second.stderr
    settings2 = (qoder / "settings.json").read_text(encoding="utf-8")

    assert settings1 == settings2
    settings = json.loads(settings2)
    ours = [
        h for g in settings["hooks"]["UserPromptSubmit"]
        for h in g["hooks"] if h.get("name") == "zcode-expert-system-routing"
    ]
    assert len(ours) == 1
    assert len(list((qoder / "commands" / "wf").glob("*.md"))) == 12
    assert len(list((qoder / "agents").glob("*.md"))) == 363
    assert "已是当前版本" in second.stdout


def test_status_reports_installed_and_not_installed(sandbox):
    env, _home, qoder = sandbox
    before = run_qoder(env, "--status", "--json")
    assert before.returncode == 1
    assert json.loads(before.stdout)["installed"] is False

    assert run_qoder(env).returncode == 0
    after = run_qoder(env, "--status", "--json")
    assert after.returncode == 0
    data = json.loads(after.stdout)
    assert data["installed"] is True
    assert data["agents"]["count"] == 363
    assert data["commands"]["count"] == 12
    assert data["hook"]["present"] is True
    assert qoder.as_posix() in data["qoderDir"].replace("\\", "/")


def test_uninstall_only_removes_our_content(sandbox):
    env, _home, qoder = sandbox
    seed_settings(qoder)
    assert run_qoder(env).returncode == 0

    proc = run_qoder(env, "--uninstall")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    settings = json.loads((qoder / "settings.json").read_text(encoding="utf-8"))
    assert settings["enabledPlugins"] == {"existing@market": True}
    assert settings["providers"] == {"demo": {"baseUrl": "https://example.invalid"}}
    assert len(settings["hooks"]["Stop"]) == 1
    groups = settings["hooks"]["UserPromptSubmit"]
    assert len(groups) == 1
    assert groups[0]["hooks"][0]["command"] == "echo keep-me"
    assert not (qoder / "skills" / "zcode-expert-system").exists()
    if (qoder / "commands" / "wf").exists():
        assert not list((qoder / "commands" / "wf").glob("*.md"))
    if (qoder / "agents").exists():
        assert not list((qoder / "agents").glob("*.md"))
    assert (qoder / "expert-system" / "backups").exists(), "默认应保留安装备份"


def test_uninstall_purge_removes_backups(sandbox):
    env, _home, qoder = sandbox
    seed_settings(qoder)
    assert run_qoder(env).returncode == 0
    proc = run_qoder(env, "--uninstall", "--purge")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert not (qoder / "expert-system").exists()


def test_uninstall_without_flags_uses_historical_non_tty_default(sandbox):
    """非 TTY 的无标志 uninstall 不自动卸载 Qoder，仍回退 ZCode + Claude。"""
    env, _home, qoder = sandbox
    assert run_qoder(env).returncode == 0
    proc = run_unified(env, "--uninstall", "--dry-run")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "Claude Code + ZCode（历史默认）" in proc.stdout
    assert (qoder / "skills" / "zcode-expert-system" / "SKILL.md").exists()


def test_unified_uninstall_qoder_only(sandbox):
    """统一卸载的 --qoder 分支只清 Qoder，且不动其他宿主目录。"""
    env, home, qoder = sandbox
    seed_settings(qoder)
    assert run_unified(env, "--targets", "qoder").returncode == 0
    proc = run_unified(env, "--uninstall", "--qoder")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    settings = json.loads((qoder / "settings.json").read_text(encoding="utf-8"))
    ours = [
        h for g in settings.get("hooks", {}).get("UserPromptSubmit", [])
        for h in g.get("hooks", []) if h.get("name") == "zcode-expert-system-routing"
    ]
    assert ours == []
    assert any(
        h.get("name") == "keep"
        for g in settings.get("hooks", {}).get("UserPromptSubmit", [])
        for h in g.get("hooks", [])
    )
    assert not (qoder / "skills" / "zcode-expert-system").exists()
    assert not (home / ".zcode").exists()
    assert not (home / ".claude").exists()


def test_install_does_not_embed_vendor_skills_in_main_skill(sandbox):
    env, _home, qoder = sandbox
    assert run_qoder(env).returncode == 0
    main_skill = qoder / "skills" / "zcode-expert-system"
    assert not (main_skill / "vendor" / "skills").exists(), (
        "主技能目录不得嵌套 vendor/skills；vendor 只应作为兄弟技能部署")
    assert len(list((qoder / "skills").glob("zes-*/SKILL.md"))) == 15


def test_user_owned_command_is_not_overwritten(sandbox):
    env, _home, qoder = sandbox
    user_cmd = qoder / "commands" / "wf" / "triage.md"
    user_cmd.parent.mkdir(parents=True, exist_ok=True)
    user_cmd.write_text("USER OWNED TRIAGE\n", encoding="utf-8")
    proc = run_qoder(env)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert user_cmd.read_text(encoding="utf-8") == "USER OWNED TRIAGE\n"
    assert "保留用户同名资产" in proc.stdout
    manifest = json.loads(
        (qoder / "expert-system" / "qoder-deployed.json").read_text(encoding="utf-8"))
    assert "wf/triage.md" not in manifest["commands"]
    assert "wf/triage.md" in manifest["conflicts"]


def test_uninstall_continues_when_settings_are_corrupt(sandbox):
    env, _home, qoder = sandbox
    assert run_qoder(env).returncode == 0
    settings = qoder / "settings.json"
    settings.write_text("{ broken json", encoding="utf-8")
    proc = run_qoder(env, "--uninstall")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "settings.json 无法解析" in proc.stdout
    # Hook 仍指向主技能；settings 修复前必须保留它，避免每轮执行不存在的文件。
    assert (qoder / "skills" / "zcode-expert-system" / "SKILL.md").exists()
    assert "保留主技能目录" in proc.stdout
    assert not list((qoder / "agents").glob("*.md"))
    assert not list((qoder / "commands" / "wf").glob("*.md"))
    assert settings.read_text(encoding="utf-8") == "{ broken json"
    assert list((qoder / "expert-system" / "backups" / "settings").glob("*"))


def test_qoder_failure_does_not_block_zcode_dry_run(sandbox):
    env, home, _qoder = sandbox
    bad_qoder = home / "not-a-qoder-dir"
    env["QODER_HOME"] = str(bad_qoder)
    proc = run_unified(env, "--targets", "zcode,qoder", "--dry-run")
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "Qoder 部署失败（继续部署其他已选目标）" in proc.stdout
    assert "插件清单已写入" in proc.stdout, (
        "Qoder 失败后仍应继续 ZCode 预检/部署流程")
    assert not bad_qoder.exists()


def test_foreign_hook_pointing_to_same_filename_is_preserved(sandbox):
    env, _home, qoder = sandbox
    qoder.mkdir(parents=True, exist_ok=True)
    foreign = {
        "hooks": {
            "UserPromptSubmit": [
                {"hooks": [{
                    "type": "command",
                    "name": "foreign",
                    "command": "node \"/tmp/zcode-expert-system/hooks/prepend-global-rules-reminder.mjs\"",
                }]}
            ]
        }
    }
    (qoder / "settings.json").write_text(
        json.dumps(foreign, ensure_ascii=False, indent=2), encoding="utf-8")
    assert run_qoder(env).returncode == 0
    assert run_qoder(env, "--uninstall").returncode == 0
    settings = json.loads((qoder / "settings.json").read_text(encoding="utf-8"))
    names = [
        h.get("name") for g in settings.get("hooks", {}).get("UserPromptSubmit", [])
        for h in g.get("hooks", [])
    ]
    assert "foreign" in names


def test_uninstall_recovers_without_manifest(sandbox):
    """部署清单丢失时，靠 ownership marker 仍能精确清理本插件文件。"""
    env, _home, qoder = sandbox
    seed_settings(qoder)
    assert run_qoder(env).returncode == 0
    manifest = qoder / "expert-system" / "qoder-deployed.json"
    manifest.unlink()
    proc = run_qoder(env, "--uninstall")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "ownership marker" in proc.stdout
    assert not (qoder / "skills" / "zcode-expert-system").exists()
    assert not list((qoder / "commands" / "wf").glob("*.md"))
    assert not list((qoder / "agents").glob("*.md"))
    assert not list((qoder / "skills").glob("zes-*"))


# ===========================================================================
# v3.2.5：Qoder 技能必须带齐运行时组件，且不得把 tests/vendor 带进技能
# ===========================================================================

RUNTIME_FILES = (
    "scripts/workflow_check.py",
    "config/categories.json",
    "SKILL.md",
    "zcode_dev_workflow.py",
    "zcode_expert_system.py",
    "skill_entry.py",
)
RUNTIME_DIRS = ("templates", "references", "agents", "commands", "hooks")


def test_skill_carries_runtime_components(sandbox):
    """技能目录必须含 workflow_check/categories/templates/references 等运行时组件。"""
    env, _home, qoder = sandbox
    assert run_qoder(env).returncode == 0
    skill = qoder / "skills" / "zcode-expert-system"
    missing = [rel for rel in RUNTIME_FILES + RUNTIME_DIRS if not (skill / rel).exists()]
    assert not missing, "Qoder 技能缺运行时组件：%s" % missing

    cats = json.loads((skill / "config" / "categories.json").read_text(encoding="utf-8"))
    assert len(cats) == 32, "categories.json 分类数 %d（应为 32）" % len(cats)
    no_desc = [k for k, v in cats.items()
               if not str((v or {}).get("description") or "").strip()]
    assert not no_desc, "categories.json 有分类缺 description：%s" % no_desc


def test_skill_does_not_contain_tests_or_vendor(sandbox):
    """技能目录不得夹带 tests/ 与 vendor/（源码仓库的回归防线不属于运行时）。"""
    env, _home, qoder = sandbox
    assert run_qoder(env).returncode == 0
    skill = qoder / "skills" / "zcode-expert-system"
    assert not (skill / "tests").exists(), "tests/ 被复制进 Qoder 技能"
    assert not (skill / "vendor").exists(), "vendor/ 被复制进 Qoder 技能"
    assert not (skill / ".pytest_cache").exists(), ".pytest_cache 被复制进 Qoder 技能"


# ===========================================================================
# v3.2.5：--purge 才删运行时 context；默认保留用户数据
# ===========================================================================

def test_purge_is_required_to_delete_runtime_context(sandbox):
    """卸载默认保留 `expert-system/context`（用户运行时数据），--purge 才删。"""
    env, _home, qoder = sandbox
    assert run_qoder(env).returncode == 0
    ctx = qoder / "expert-system" / "context"
    ctx.mkdir(parents=True, exist_ok=True)
    (ctx / "result-keep.json").write_text("{}", encoding="utf-8")

    assert run_qoder(env, "--uninstall").returncode == 0
    assert (ctx / "result-keep.json").is_file(), "默认卸载删了用户运行时 context"

    assert run_qoder(env).returncode == 0
    proc = run_qoder(env, "--uninstall", "--purge")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert not ctx.exists(), "--purge 未删除运行时 context"


def test_uninstall_preserves_user_agent_with_same_name(sandbox):
    """用户接过同名子代理文件（去掉 marker）时，卸载必须保留用户版本。"""
    env, _home, qoder = sandbox
    assert run_qoder(env).returncode == 0
    user_agent = qoder / "agents" / "expert-engineering-code-reviewer.md"
    assert user_agent.is_file()
    user_agent.write_text("USER OWNED AGENT\n", encoding="utf-8")

    proc = run_qoder(env, "--uninstall")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert user_agent.read_text(encoding="utf-8") == "USER OWNED AGENT\n", (
        "卸载删掉了用户接管的同名子代理")
    assert "保留用户版本" in proc.stdout
