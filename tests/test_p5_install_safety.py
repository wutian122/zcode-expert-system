# -*- coding: utf-8 -*-
"""P5 · 安装/卸载安全回归测试（缺陷 #17 #18 #21 + postinstall）

**这个文件要抓的破坏**

P5 是**唯一会删改用户机器 `~/.zcode/` 的批次**。前面四批改坏了顶多测试红，
这批改坏了会删掉用户的真实数据。所以测试的第一要求不是「验功能」，
而是**绝不接触真实 `~/.zcode/`**。

### 安全闸（本文件最重要的一段）

所有用例通过 `USERPROFILE`（Windows）/ `HOME`（POSIX）重定向到 `tmp_path`，
并在 fixture 里**断言 `os.path.expanduser('~')` 确实落在 tmp_path 下**——
断言不过就整批 skip。这是防止测试误删真实目录的硬闸：
没有它，一条写错的用例就可能清掉用户的 363 个子代理。

### 要抓的破坏

1. **#17 先删后校验，半毁无回滚**
   现状执行序是「删插件缓存 → 删技能目录 → 写 → 校验 agents/ → 抛错」。
   `agents/` 缺失时，用户得到的是「旧的已删、新的没装」且无回滚。
   正确做法：所有前置校验必须在**任何 rmSync 之前**。

2. **#17b 无条件删除用户自己的技能目录**
   `~/.zcode/skills/<name>/` 是**用户目录**（不是缓存）。若用户在里面改过
   SKILL.md 或加了自己的 references，现状 `rmSync` 直接清空且**不备份**——
   而同一个脚本对 `installed_plugins.json` 是有 `.bak-<ts>` 备份的，策略不一致。

3. **#18 重装不清陈旧代理 → 幽灵永久残留**
   安装时按源目录逐个写 `~/.zcode/agents/`，但**从不删除**上次安装留下、
   本次源目录已不存在的文件；随后用新清单**整体覆盖** `deployed-agents.json`。
   于是旧文件还留在可派发列表里，而卸载按新清单永远删不掉它们。

4. **#21 install.js 自我拷贝成坏副本**
   `copyDir(PROJECT_ROOT, skillDest)` 把 `scripts/install.js` 一起拷进部署目录，
   而同一份拷贝里 `package.json` 被删了 → 该副本一运行就在 `readFileSync` 处抛错。
   `_deploy_run_tmp.js` 这类开发期残留也被一并分发。

5. **postinstall 绕过一切门禁**
   `package.json` 的 `postinstall` 直接挂 `node scripts/install.js`，
   意味着**任何 `npm install` 都会立刻改写 `~/.zcode/` 四个目录**——
   破坏性操作从「老板主动执行」退化为「装依赖的副作用」。

**运行方式**：`python -m pytest tests/test_p5_install_safety.py -v`
（需要 node；无 node 时整批 skip）
"""

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INSTALLER = PROJECT_ROOT / "scripts" / "install.js"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None, reason="环境无 node，跳过安装脚本测试")


# ===========================================================================
# 安全闸：沙箱 fixture
# ===========================================================================

@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """把 HOME/USERPROFILE 重定向到 tmp_path，返回 (env, home)。

    **两道硬闸**（任一不过即整批 skip）：

    1. Python 侧：`os.path.expanduser('~')` 必须落在沙箱。
       用 `monkeypatch.setenv` 改**真实的 `os.environ`**，而不是只改传给
       子进程的字典副本——否则本进程内的 `expanduser` 仍读真实路径，
       而「只改副本」正是初版失效的原因（11 条用例全被安全闸 skip）。
    2. node 侧：`os.homedir()` 也必须落在沙箱。安装脚本读的是它，
       不是 Python 的 `~`；两边都指向沙箱才算真隔离。
    """
    home = (tmp_path / "home").resolve()
    home.mkdir()

    # 同时改本进程环境（供 expanduser 与任何意外进程内调用）
    for key, value in (
        ("USERPROFILE", str(home)),
        ("HOME", str(home)),
        ("HOMEDRIVE", home.drive or "C:"),
        ("HOMEPATH", str(home)[len(home.drive):] if home.drive else str(home)),
    ):
        monkeypatch.setenv(key, value)

    env = dict(os.environ)
    # 本批用例验证的是文件部署/备份/回滚，不启动真实 Claude CLI；
    # 统一安装的 marketplace 注册由 test_unified_install_registers_claude 覆盖。
    env["ZES_CLAUDE_INSTALL"] = "legacy"

    # 安全闸 1：Python 侧
    resolved = Path(os.path.expanduser("~")).resolve()
    if resolved != home:
        pytest.skip(
            "无法把 HOME 重定向到沙箱（expanduser('~')=%s，期望 %s）——"
            "为免误删真实 ~/.zcode，整批跳过" % (resolved, home))

    # 安全闸 2：node 侧（安装脚本实际读的那个）
    probe = subprocess.run(
        ["node", "-e", "process.stdout.write(require('os').homedir())"],
        env=env, capture_output=True, text=True, timeout=30,
        encoding='utf-8', errors='replace')
    node_home = Path(probe.stdout.strip()).resolve()
    if node_home != home:
        pytest.skip(
            "无法把 node os.homedir() 重定向到沙箱（%s，期望 %s）——整批跳过"
            % (node_home, home))

    return env, home


def make_source(tmp_path, *, drop_agents=False, drop_config=False, drop_icon_manifest=False, extra=None):
    """复制一份可安全修改的源树到 tmp_path/src，返回其路径。

    只复制安装脚本关心的目录，避免整仓拷贝（`tests/`、`docs/`、`vendor/`
    等与安装脚本无关的内容不进沙箱）。drop_icon_manifest=True 模拟源树缺
    .claude-plugin/marketplace.json（图标注入跳过分支）。

    2026-11-24 更新（v3.2.3）：沙箱**默认也拷 .claude-plugin/plugin.json**
    并带全量 363 个真实 agent 文件——deployClaudeCode 的 manifest 缺失分支
    已从「⚠️ 跳过」改为 exit(1)（npm 3.2.2 静默部署事故的修复），沙箱必须
    走完整的 Claude Code 部署链；且多个用例断言 agent 内容更新/备份逻辑，
    必须拷贝真实文件（占位 0 字节文件过不了内容断言）。
    """
    src = tmp_path / "src"
    # v3.2.5：templates/ 与 references/ 是部署必需组件（install.js 预检 +
    # 部署后校验都会查），沙箱必须与真实源树同构，否则任何安装用例都会被
    # 预检正确拦下——那是夹具失真，不是被测行为。
    for rel in ("scripts", "config", "hooks", "commands", "templates", "references"):
        shutil.copytree(PROJECT_ROOT / rel, src / rel)
    for rel in ("package.json", "SKILL.md", "skill_entry.py",
                "zcode_expert_system.py", "zcode_dev_workflow.py"):
        shutil.copy2(PROJECT_ROOT / rel, src / rel)
    (src / ".zcode-plugin").mkdir()
    shutil.copy2(PROJECT_ROOT / ".zcode-plugin" / "plugin.json",
                 src / ".zcode-plugin" / "plugin.json")
    # .claude-plugin：marketplace.json（图标）+ plugin.json（部署清单）。
    # 两者默认都拷——缺 plugin.json 的部署分支自 v3.2.3 起 exit(1)（npm 3.2.2
    # 静默部署事故的修复），沙箱必须走完整的 Claude Code 部署链。
    (src / ".claude-plugin").mkdir(exist_ok=True)
    shutil.copy2(PROJECT_ROOT / ".claude-plugin" / "plugin.json",
                 src / ".claude-plugin" / "plugin.json")
    if not drop_icon_manifest:
        shutil.copy2(PROJECT_ROOT / ".claude-plugin" / "marketplace.json",
                     src / ".claude-plugin" / "marketplace.json")
    if not drop_agents:
        # 拷贝全量真实 agents（4.4M，363 个文件）：
        # deployClaudeCode 的「agents 必须是 363」硬校验需要真实数量，
        # 且多个用例断言 agent 内容更新/备份逻辑，占位 0 字节文件过不了。
        shutil.copytree(PROJECT_ROOT / "agents", src / "agents")
    if drop_config:
        shutil.rmtree(src / "config", ignore_errors=True)
    if extra:
        for name, content in extra.items():
            (src / name).write_text(content, encoding="utf-8")
    return src


def run_installer(src, env, *args, timeout=120):
    """在沙箱 HOME 下跑安装脚本。"""
    return subprocess.run(
        ["node", str(src / "scripts" / "install.js")] + list(args),
        env=env, capture_output=True, text=True, timeout=timeout, cwd=str(src),
        encoding='utf-8', errors='replace')


def zcode(home):
    return home / ".zcode"


def count_files(p):
    if not p.exists():
        return 0
    return sum(1 for _ in p.rglob("*") if _.is_file())


# ===========================================================================
# #17 先校验后动手：缺 agents/ 时必须零残留
# ===========================================================================

def test_missing_agents_fails_before_touching_disk(sandbox, tmp_path):
    """缺 `agents/` 时必须在删任何东西之前失败。

    修前实测：先 `rmSync(pluginRoot)`（插件缓存）、再 `rmSync(legacySkillDir)`
    （用户技能目录），然后才在 `if (!fs.existsSync(agentsSrc)) throw` 抛错。
    结果：沙箱里已留下 `plugin.json` / `hooks` / `commands` / `skills` 全套残骸。
    """
    env, home = sandbox
    src = make_source(tmp_path, drop_agents=True)

    proc = run_installer(src, env)
    assert proc.returncode != 0, "缺 agents/ 应当失败，实际 rc=0"
    assert "agents" in (proc.stderr + proc.stdout).lower()

    # 关键断言：磁盘零改动
    leftovers = [p for p in zcode(home).rglob("*") if p.is_file()]
    assert not leftovers, (
        "缺 agents/ 失败后仍留下 %d 个文件（半毁）：%s"
        % (len(leftovers), [str(p.relative_to(home)) for p in leftovers[:6]]))


def test_missing_config_fails_before_touching_disk(sandbox, tmp_path):
    """缺 `config/` 时同样必须零残留（同族缺陷，一并守住）。"""
    env, home = sandbox
    src = make_source(tmp_path, drop_config=True)

    proc = run_installer(src, env)
    assert proc.returncode != 0, "缺 config/ 应当失败，实际 rc=0"
    leftovers = [p for p in zcode(home).rglob("*") if p.is_file()]
    assert not leftovers, "缺 config/ 失败后仍留下 %d 个文件" % len(leftovers)


def test_preflight_does_not_delete_previous_install(sandbox, tmp_path):
    """已有旧版本时，一次失败的安装不得抹掉旧版本。

    这是 #17 最痛的形态：用户本来有个能用的旧版，跑一次失败的升级就没了。
    """
    env, home = sandbox
    src = make_source(tmp_path)
    ok = run_installer(src, env)
    assert ok.returncode == 0, "首次安装应成功：%s" % (ok.stderr or ok.stdout)[-500:]

    before = count_files(zcode(home))
    assert before > 0

    # 移除 agents/ 再装一次 → 失败，且旧版本必须完好
    src2 = make_source(tmp_path / "second", drop_agents=True)
    proc = run_installer(src2, env)
    assert proc.returncode != 0
    after = count_files(zcode(home))
    assert after >= before, (
        "失败的重装抹掉了旧版本：安装前 %d 个文件 → 失败后 %d 个" % (before, after))


# ===========================================================================
# #17b 删用户技能目录前必须备份
# ===========================================================================

def test_legacy_skill_dir_is_backed_up_before_delete(sandbox, tmp_path):
    """覆盖 `~/.zcode/skills/<name>/` 前必须备份用户改动。

    修前实测：`fs.rmSync(legacySkillDir, {recursive:true, force:true})` 无备份。
    而同一脚本对 `installed_plugins.json` 是有 `.bak-<ts>` 的——策略不一致。
    """
    env, home = sandbox
    legacy = zcode(home) / "skills" / "zcode-expert-system"
    legacy.mkdir(parents=True)
    user_file = legacy / "MY_LOCAL_EDIT.md"
    user_file.write_text("用户自己加的\n", encoding="utf-8")

    src = make_source(tmp_path)
    proc = run_installer(src, env)
    assert proc.returncode == 0, "安装应成功：%s" % (proc.stderr or proc.stdout)[-500:]

    # 用户文件应当仍能找到（原位或备份目录）
    survivors = list(zcode(home).rglob("MY_LOCAL_EDIT.md"))
    assert survivors, "用户的本地改动被无备份删除"


# ===========================================================================
# #18 重装不得留幽灵代理
# ===========================================================================

def test_reinstall_removes_stale_agents(sandbox, tmp_path):
    """源里删掉的 agent，重装后不得残留在 `~/.zcode/agents/`。

    修前实测：删 3 个源文件后重装 → 磁盘 363 个、新清单 360 个，
    **3 个幽灵永久残留**：它们仍在可派发列表里，而卸载按新清单永远删不掉。
    """
    env, home = sandbox
    src = make_source(tmp_path)
    # 本用例只验 ZCode 侧集合幂等：删源 agent 后源树 agents=362，
    # 走 Claude Code 部署链会被其「必须是 363」硬校验正确拦截（预期行为），
    # 故限定 --targets zcode。
    assert run_installer(src, env, "--targets", "zcode").returncode == 0

    agents_dir = zcode(home) / "agents"
    first = {p.name for p in agents_dir.glob("*.md")}
    assert first, "首次安装未产生任何 agent"

    # 删掉一个源 agent，重装
    victim = "expert-engineering-code-reviewer.md"
    (src / "agents" / victim).unlink()
    assert run_installer(src, env, "--targets", "zcode").returncode == 0

    now = {p.name for p in agents_dir.glob("*.md")}
    assert victim not in now, (
        "幽灵代理残留：%s 仍在磁盘上（源里已删）" % victim)


def test_manifest_matches_disk_after_reinstall(sandbox, tmp_path):
    """重装后 `deployed-agents.json` 必须与磁盘实际文件集合一致。

    清单与磁盘不一致是幽灵残留的另一半：清单说「已装 N 个」，
    磁盘上是 N+3 个——卸载按清单删，多出来的永远留着。
    """
    env, home = sandbox
    src = make_source(tmp_path)
    # 同上：只验 ZCode 侧清单-磁盘一致性，限定 --targets zcode
    assert run_installer(src, env, "--targets", "zcode").returncode == 0
    (src / "agents" / "expert-engineering-code-reviewer.md").unlink()
    assert run_installer(src, env, "--targets", "zcode").returncode == 0

    manifest = zcode(home) / "expert-system" / "deployed-agents.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    listed = set(data["agents"])
    on_disk = {p.name for p in (zcode(home) / "agents").glob("*.md")}

    assert not (on_disk - listed), (
        "磁盘有清单未记录的文件（卸载将漏删）：%s" % sorted(on_disk - listed)[:6])


# ===========================================================================
# #21 部署产物里不得有坏副本
# ===========================================================================

def test_installer_not_copied_into_skill_dir(sandbox, tmp_path):
    """部署出的技能目录里不得含 install.js 自身副本。

    修前实测：`copyDir(PROJECT_ROOT, skillDest)` 把 `scripts/install.js`
    一起拷进去，而同一份拷贝里 `package.json` 被删了 →
    该副本一运行就在 `readFileSync(package.json)` 处抛错。
    """
    env, home = sandbox
    src = make_source(tmp_path)
    assert run_installer(src, env).returncode == 0

    skill_scripts = zcode(home) / "skills" / "zcode-expert-system" / "scripts"
    if not skill_scripts.exists():
        pytest.skip("该部署形态不含 skills/<name>/scripts")
    assert not (skill_scripts / "install.js").exists(), (
        "部署目录里有之后无法运行的 install.js 副本")


def test_dev_leftovers_not_copied(sandbox, tmp_path):
    """开发期残留文件不得被分发进部署目录。"""
    env, home = sandbox
    src = make_source(tmp_path, extra={
        "scripts/_deploy_run_tmp.js": "// dev leftover\n",
    })
    assert run_installer(src, env).returncode == 0

    found = list(zcode(home).rglob("_deploy_run_tmp.js"))
    assert not found, "开发期残留被分发：%s" % [str(p) for p in found]


# ===========================================================================
# postinstall 不得绕过门禁
# ===========================================================================

def test_postinstall_does_not_run_installer():
    """`postinstall` 不得直接跑安装脚本。

    `npm install` 会触发 postinstall。若它挂的是 `node scripts/install.js`，
    则**任何装依赖的动作都会立刻改写 `~/.zcode/` 四个目录**——
    破坏性操作从「老板主动执行」退化为「装依赖的副作用」，绕过一切门禁。

    允许的做法：改成 `--dry-run`（只打印计划）、或改名为非 postinstall 的
    显式脚本（如 `npm run deploy`）。
    """
    pkg = json.loads((PROJECT_ROOT / "package.json").read_text(encoding="utf-8"))
    post = (pkg.get("scripts") or {}).get("postinstall", "")
    if not post:
        return                      # 没有 postinstall 是最干净的形态
    assert "--dry-run" in post or "--check" in post, (
        "postinstall 直接执行了安装脚本，npm install 会改写 ~/.zcode/：%r" % post)


# ===========================================================================
# 卸载安全
# ===========================================================================

def test_uninstall_without_manifest_does_not_prefix_sweep(sandbox, tmp_path):
    """卸载清单缺失时，不得按前缀扫 `~/.zcode/agents/` 删除。

    修前实测：清单缺失会回退前缀扫描，可能误删**其他插件**投放的
    `manager-*` / `expert-*` 文件。宁可留残留，不可误删。
    """
    env, home = sandbox
    # 造一个「别的插件」的 agent，以及一个本插件的残留
    agents = zcode(home) / "agents"
    agents.mkdir(parents=True)
    (agents / "expert-other-plugin.md").write_text("别人的\n", encoding="utf-8")
    (agents / "manager-other-plugin.md").write_text("别人的\n", encoding="utf-8")

    src = make_source(tmp_path)
    proc = subprocess.run(
        ["node", str(src / "scripts" / "install.js"), "--uninstall"],
        env=env, capture_output=True, text=True, timeout=120, cwd=str(src),
        encoding='utf-8', errors='replace')
    assert proc.returncode == 0, "卸载应成功：%s" % (proc.stderr or proc.stdout)[-500:]

    assert (agents / "expert-other-plugin.md").exists(), "误删了其他插件的 expert-*"
    assert (agents / "manager-other-plugin.md").exists(), "误删了其他插件的 manager-*"


def test_uninstall_removes_own_artifacts(sandbox, tmp_path):
    """卸载必须真的删掉本插件投放的产物（清单存在时）。"""
    env, home = sandbox
    src = make_source(tmp_path)
    assert run_installer(src, env).returncode == 0

    agents = zcode(home) / "agents"
    assert list(agents.glob("*.md")), "安装后应有 agent"

    proc = subprocess.run(
        ["node", str(src / "scripts" / "install.js"), "--uninstall"],
        env=env, capture_output=True, text=True, timeout=120, cwd=str(src),
        encoding='utf-8', errors='replace')
    assert proc.returncode == 0

    assert not list(agents.glob("*.md")), "卸载后仍残留 agent"
    assert not (zcode(home) / "skills" / "zcode-expert-system").exists(), \
        "卸载后仍残留技能目录"


# ===========================================================================
# dry-run：先看再删
# ===========================================================================

def test_dry_run_deletes_nothing(sandbox, tmp_path):
    """`--dry-run` 只打印计划，零写入。

    这是「先看再删」能力的机械保证：老板能在真正执行前
    看到将要删除的绝对路径清单。
    """
    env, home = sandbox
    src = make_source(tmp_path)
    assert run_installer(src, env).returncode == 0
    before = count_files(zcode(home))

    proc = run_installer(src, env, "--dry-run")
    assert proc.returncode == 0, "dry-run 应成功：%s" % (proc.stderr or proc.stdout)[-400:]
    after = count_files(zcode(home))
    assert after == before, "dry-run 改动了磁盘：%d → %d" % (before, after)
    out = proc.stdout + proc.stderr
    assert "dry-run" in out.lower() or "将删除" in out or "would" in out.lower(), \
        "dry-run 未打印将要执行的动作"


# ===========================================================================
# P8 批次三 Task 8：PLUGIN_OUTPUTS 去 tests + agents 覆盖前备份
# ===========================================================================

def test_user_tests_dir_blocks_backup_autodelete(sandbox, tmp_path):
    """用户自建的 tests/ 不得被当插件产物而连带删除。

    修前：'tests' 在 PLUGIN_OUTPUTS → 备份目录 hasUserFiles=False →
    重装后备份被自动 rmSync，用户文件丢失（数据销毁方向）。
    """
    env, home = sandbox
    src = make_source(tmp_path)
    assert run_installer(src, env).returncode == 0

    deployed = zcode(home) / "skills" / "zcode-expert-system"
    (deployed / "tests").mkdir(parents=True)
    (deployed / "tests" / "用户回归用例.py").write_text("assert True\n", encoding="utf-8")

    assert run_installer(src, env).returncode == 0

    baks = list((zcode(home) / "skills").glob("zcode-expert-system.bak-*"))
    assert baks, "含用户 tests/ 的备份目录被自动删除（hasUserFiles 把 tests 误判为插件产物）"
    kept = list(baks[0].rglob("用户回归用例.py"))
    assert kept and kept[0].read_text(encoding="utf-8") == "assert True\n", (
        "备份里的用户文件内容不完整")


def test_modified_agent_file_backed_up_before_overwrite(sandbox, tmp_path):
    """用户改过的 agent 文件在重装覆盖前必须有 .bak-* 备份。

    修前：agents 写入直接 writeFileSync 覆盖（技能目录有 backupDir，
    agents 目录没有）——用户/其他插件投放的同名文件静默丢失。
    """
    env, home = sandbox
    src = make_source(tmp_path)
    assert run_installer(src, env).returncode == 0

    agent = zcode(home) / "agents" / "expert-engineering-code-reviewer.md"
    original = agent.read_text(encoding="utf-8")
    agent.write_text("用户定制标记 user-customized\n", encoding="utf-8")

    assert run_installer(src, env).returncode == 0
    assert agent.read_text(encoding="utf-8") == original, "重装未把内容恢复为源版本"
    baks = list((zcode(home) / "agents").glob("expert-engineering-code-reviewer.md.bak-*"))
    assert baks, "覆盖前未备份，用户定制内容丢失"
    assert "用户定制标记" in baks[0].read_text(encoding="utf-8"), "备份内容不是用户定制版"


def test_agent_content_updated_when_unmodified(sandbox, tmp_path):
    """双向反例：未改动的重装——内容保持源版本，备份逻辑不得妨碍正常更新。"""
    env, home = sandbox
    src = make_source(tmp_path)
    assert run_installer(src, env).returncode == 0
    agent = zcode(home) / "agents" / "expert-engineering-code-reviewer.md"
    first = agent.read_text(encoding="utf-8")
    assert first.strip(), "首次部署无内容"

    assert run_installer(src, env).returncode == 0
    assert agent.read_text(encoding="utf-8") == first, "未改动重装后内容漂移"


# ===========================================================================
# P9 部署验证实测：#21 整目录剔除 scripts/ 让 /wf:* 命令引用落空
# ===========================================================================

def test_deployed_skill_has_runtime_scripts(sandbox, tmp_path):
    """部署后的技能目录必须带运行时脚本，且不得回流坏副本 install.js。

    `/wf:*` 命令按 `${ZCODE_PLUGIN_ROOT}/skills/zcode-expert-system/scripts/*.py`
    引用 workflow_check.py 等运行时脚本（deployed-commands 实测引用行）。
    P9 真机部署验证发现：缺陷 #21 的整目录 `scripts` 剔除把运行时脚本一并
    删了 → 部署布局下命令引用的路径不存在，命令族不可用。
    正确语义：只剔 install.js（#21 的真实病灶——坏副本）+ 开发期残留，
    保留运行时三件。
    """
    env, home = sandbox
    src = make_source(tmp_path)
    assert run_installer(src, env).returncode == 0
    sd = zcode(home) / "skills" / "zcode-expert-system" / "scripts"
    for f in ("workflow_check.py", "llm_client.py", "embedding_client.py"):
        assert (sd / f).is_file(), (
            "部署技能缺运行时脚本 %s——/wf:* 命令引用会落空" % f)
    assert not (sd / "install.js").exists(), (
        "#21 的 install.js 坏副本不得回流部署产物")


# ===========================================================================
# P2-3（2026-11-19，方案 B 单写对齐）：vendored 技能卸载 targets 只含插件缓存
#
# 抓的破坏：安装侧（1c' :475）只把 vendored zes-* 部署到插件缓存
# <pluginRoot>/skills/，但卸载侧（3c :796-799）targets 却同时列了
# 插件缓存 + ~/.zcode/skills/<name> 两条——后者是安装侧从未写入的死分支，
# 形成「卸载比安装多认一个位置」的单边缺口。
#
# 老板决策（2026-11-19）：方案 B 单写对齐——删卸载侧 zcodeDir/skills 死路径，
# 安装/卸载两侧都只认插件缓存一个位置。
# ===========================================================================

def test_vendored_uninstall_targets_only_plugin_cache():
    """P2-3：vendored 技能卸载 targets 必须只含插件缓存，不含用户技能目录死路径。

    源码级断言（避免依赖完整 vendor/skills 复制）：3c 卸载段的 targets 数组
    不得再出现 `path.join(zcodeDir, 'skills', name)` 这条安装侧从未写入的死分支。
    """
    src = INSTALLER.read_text(encoding="utf-8")
    # 截取 3c vendored 卸载段（从「移除 vendored 技能」注释到该 for 循环结束）
    seg_match = re.search(
        r"移除 vendored 技能.*?\n(.*?)\n\s*act\(`删除技能清单",
        src, re.DOTALL)
    assert seg_match, "install.js 3c vendored 卸载段未找到（结构变化需同步测试）"
    seg = seg_match.group(1)
    assert "zcodeDir, 'skills'" not in seg, (
        "P2-3：vendored 卸载 targets 仍含 zcodeDir/skills 死路径"
        "（安装侧从未写入，单边缺口）")
    # 正向锚：插件缓存那条必须仍在（否则删过头，vendored 技能永不清理）
    assert "pluginRoot, 'skills'" in seg, (
        "P2-3：vendored 卸载 targets 误删了插件缓存那条（删过头）")


# ===========================================================================
# I4（S6 修复，2026-11-23）：图标固化功能测试
#
# 抓的破坏：
# 1. injectIconMarketplace 零调用（C1：函数写完没接线，图标永不注入）
# 2. 步骤 4 注册按名全删导致 C2 现场 wutian122 记录被误删（C2 命名空间回退）
# 3. 卸载不对称（C3：装时注入 known/marketplace 目录/enabledPlugins，卸时不清）
# 4. dry-run 阶段经 act()/DRY_RUN 守卫漏写（写穿防线）
#
# 测试形态：subprocess 驱动真实 install.js，HOME 重定向到沙箱（复用
# sandbox fixture 的双道安全闸），绝不触碰真实 ~/.zcode。
# ===========================================================================

PLUGIN_ID = "zcode-expert-system@wutian122-expert-system"
LEGACY_ID = "zcode-expert-system@zcode-plugins-official"
ICON_MKT_ID = "wutian122-expert-system"


def read_json(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def known_entries(home):
    """返回 known_marketplaces.json 中 ICON_MKT_ID 的条目数。"""
    f = zcode(home) / "cli" / "plugins" / "known_marketplaces.json"
    if not f.exists():
        return 0
    data = read_json(f)
    return sum(1 for m in data.get("marketplaces", []) if m.get("id") == ICON_MKT_ID)


def installed_entries(home, plugin_id):
    """返回 installed_plugins.json 中指定 id 的记录数。"""
    f = zcode(home) / "cli" / "plugins" / "installed_plugins.json"
    if not f.exists():
        return 0
    data = read_json(f)
    return sum(1 for p in data.get("plugins", []) if p.get("id") == plugin_id)


def enabled_plugins(home):
    """返回 config.json 的 plugins.enabledPlugins 字典（缺失时返回 None）。"""
    f = zcode(home) / "cli" / "config.json"
    if not f.exists():
        return None
    return read_json(f).get("plugins", {}).get("enabledPlugins")


def test_icon_marketplace_injected_on_install(sandbox, tmp_path):
    """C1：安装后图标 marketplace 必须真的写入（injectIconMarketplace 已接线）。

    修前实测：injectIconMarketplace 零调用——函数写完但从没被 install() 调用，
    known_marketplaces.json / marketplace 目录 / enabledPlugins 三处全部为空，
    图标永远不显示。本用例验证接线后的落盘形态。
    """
    env, home = sandbox
    src = make_source(tmp_path)
    proc = run_installer(src, env)
    assert proc.returncode == 0, "安装应成功：%s" % (proc.stderr or proc.stdout)[-500:]

    # known_marketplaces.json 恰 1 条 wutian122 条目
    assert known_entries(home) == 1, (
        "known_marketplaces.json 应恰有 1 条 %s 条目，实际 %d 条"
        % (ICON_MKT_ID, known_entries(home)))

    # marketplace 实体清单与根级缓存清单都在
    mkt = zcode(home) / "cli" / "plugins" / "marketplaces" / ICON_MKT_ID
    assert (mkt / "marketplace.json").is_file(), "缺根级缓存清单 marketplace.json"
    assert (mkt / ".claude-plugin" / "marketplace.json").is_file(), \
        "缺实体清单 .claude-plugin/marketplace.json"
    # 清单里的 icon 必须是 https 完整 URL（渲染端只认 https）
    m = read_json(mkt / "marketplace.json")
    icon = m["plugins"][0]["icon"]
    assert icon.startswith("https://"), "icon 字段不是 https 完整 URL：%r" % icon

    # installed_plugins 注册在 wutian122 命名空间
    assert installed_entries(home, PLUGIN_ID) == 1
    assert installed_entries(home, LEGACY_ID) == 0, "不应注册到 legacy 官方命名空间"


def test_icon_marketplace_idempotent_reinstall(sandbox, tmp_path):
    """C2 幂等：跑两次安装后 known_marketplaces 恰 1 条、addedAt 保留。

    修前形态：filter 按名全删 → 第二次安装把第一次的记录删掉再 push，
    如果实现漏了 upsert 去重还会出现 2 条。addedAt 必须跨重装保留
    （addedAt 是「首次添加时间」，每次重装都刷新会丢历史信息）。
    """
    env, home = sandbox
    src = make_source(tmp_path)
    assert run_installer(src, env).returncode == 0

    known_file = zcode(home) / "cli" / "plugins" / "known_marketplaces.json"
    first = read_json(known_file)
    first_added = next(m["addedAt"] for m in first["marketplaces"]
                       if m.get("id") == ICON_MKT_ID)

    assert run_installer(src, env).returncode == 0

    assert known_entries(home) == 1, (
        "重装后 known_marketplaces 应有 1 条，实际 %d 条" % known_entries(home))
    second = read_json(known_file)
    second_added = next(m["addedAt"] for m in second["marketplaces"]
                        if m.get("id") == ICON_MKT_ID)
    assert second_added == first_added, (
        "addedAt 被重装刷新：%s → %s（应保留首次添加时间）"
        % (first_added, second_added))
    assert installed_entries(home, PLUGIN_ID) == 1, "重装后 installed_plugins 出现重复注册"


def test_c2_field_wutian122_record_survives_reinstall(sandbox, tmp_path):
    """C2 现场兼容：预置 wutian122 记录（带 custom 字段）后重装不得破坏。

    C2 现场的 installed_plugins.json 已是 wutian122 命名空间、enabledPlugins
    键已迁移。修前按名全删会把这些记录误删，导致命名空间回退。
    本用例预置一条带标记字段的记录，重装后断言它仍然存在（且被 upsert
    原地更新，不产生第二条）。
    """
    env, home = sandbox
    src = make_source(tmp_path)

    # 预置 C2 现场形态：installed_plugins 已有 wutian122 记录
    plugins_dir = zcode(home) / "cli" / "plugins"
    plugins_dir.mkdir(parents=True)
    (plugins_dir / "installed_plugins.json").write_text(json.dumps({
        "version": 1,
        "plugins": [{
            "id": PLUGIN_ID,
            "name": "zcode-expert-system",
            "marketplace": ICON_MKT_ID,
            "version": "3.2.2",
            "installPath": "C:/custom/path/keep-me",
            "installedAt": "2026-11-20T00:00:00.000Z",
            "updatedAt": "2026-11-20T00:00:00.000Z",
            "scope": "user",
            "source": {"source": "local", "type": "directory", "path": "zcode-expert-system"},
            "cacheTransactionId": "keep-existing-tx",
        }],
    }, indent=2), encoding="utf-8")

    # 预置 config.json 的 enabledPlugins 新键（显式 false，验证尊重）
    cli_dir = zcode(home) / "cli"
    (cli_dir / "config.json").write_text(json.dumps({
        "plugins": {"enabledPlugins": {PLUGIN_ID: False}},
    }, indent=2), encoding="utf-8")

    proc = run_installer(src, env)
    assert proc.returncode == 0, "安装应成功：%s" % (proc.stderr or proc.stdout)[-500:]

    # wutian122 记录仍在（upsert 原地更新，无第二条）
    assert installed_entries(home, PLUGIN_ID) == 1, (
        "C2 现场记录被误删或重复写入（应恰 1 条）")
    assert installed_entries(home, LEGACY_ID) == 0

    # cacheTransactionId / installedAt 保留（upsert 语义：保留首装信息）
    data = read_json(plugins_dir / "installed_plugins.json")
    rec = next(p for p in data["plugins"] if p["id"] == PLUGIN_ID)
    assert rec["cacheTransactionId"] == "keep-existing-tx", "upsert 丢了原 cacheTransactionId"
    assert rec["installedAt"] == "2026-11-20T00:00:00.000Z", "upsert 丢了原 installedAt"
    # marketplace 字段对齐到 ICON_MARKETPLACE_ID（旧 record 可能带别的值）
    assert rec["marketplace"] == ICON_MKT_ID

    # enabledPlugins 显式 false 必须保留（M3：不得被翻回 true）
    ep = enabled_plugins(home)
    assert ep.get(PLUGIN_ID) is False, (
        "用户显式 false 被迁移逻辑翻回启用：%r" % ep)


def test_uninstall_removes_icon_marketplace_symmetrically(sandbox, tmp_path):
    """C3：卸载对称性——卸载后 known/目录/enabledPlugins 三处皆清。

    修前形态：安装侧注入三处产物，卸载侧完全不清理——卸载后
    known_marketplaces.json 留孤儿条目、marketplaces/ 目录留垃圾、
    config.json 的 enabledPlugins 留死键。
    """
    env, home = sandbox
    src = make_source(tmp_path)
    assert run_installer(src, env).returncode == 0

    # 前置断言：known 条目与 marketplace 目录都在（证明安装真的注入了）。
    # config.json 的 enabledPlugins 只在「文件已存在」时才迁移/清理
    # （契约：绝不重建 config.json）——新装机没有 config.json 时该字段
    # 为 None 是正确行为，故这里不强制存在，改为在下方单独造一个
    # 带 enabledPlugins 死键的场景来验证第三处清理。
    assert known_entries(home) == 1
    assert (zcode(home) / "cli" / "plugins" / "marketplaces" / ICON_MKT_ID).is_dir()

    # 预置 config.json 的 enabledPlugins（模拟 C2 现场：已迁移的键），
    # 卸载必须把它清掉（第三处对称性）
    cli_dir = zcode(home) / "cli"
    (cli_dir / "config.json").write_text(json.dumps({
        "plugins": {"enabledPlugins": {PLUGIN_ID: True}},
    }, indent=2), encoding="utf-8")

    proc = subprocess.run(
        ["node", str(src / "scripts" / "install.js"), "--uninstall", "--zcode"],
        env=env, capture_output=True, text=True, timeout=120, cwd=str(src),
        encoding='utf-8', errors='replace')
    assert proc.returncode == 0, "卸载应成功：%s" % (proc.stderr or proc.stdout)[-500:]

    # known_marketplaces.json：wutian122 条目已移除
    assert known_entries(home) == 0, "卸载后 known_marketplaces 仍有孤儿条目"

    # marketplace 目录已删
    assert not (zcode(home) / "cli" / "plugins" / "marketplaces" / ICON_MKT_ID).exists(), \
        "卸载后 marketplaces/<id> 目录仍残留"

    # enabledPlugins 两个命名空间键都清了
    ep_after = enabled_plugins(home)
    assert ep_after is not None
    assert PLUGIN_ID not in ep_after, "卸载后 enabledPlugins 仍有新命名空间死键"
    assert LEGACY_ID not in ep_after, "卸载后 enabledPlugins 仍有 legacy 死键"


def test_dry_run_icon_ops_write_nothing(sandbox, tmp_path):
    """C1/C3 dry-run：图标注入与清理的所有写操作必须经 act() 守卫。

    修前形态：dry-run 阶段的注入/清理若漏 act() 收口，会写穿防线
    （writeFileSync / writeJsonWithBackup / mkdirSync 都是直接写）。
    本用例先在沙箱造出 C2 现场（wutian122 记录 + 已注入 marketplace），
    然后跑 --dry-run，断言全部写操作零发生（文件数、内容、条目数均不变）。
    """
    env, home = sandbox
    src = make_source(tmp_path)

    # 先真实安装一次，形成现场
    assert run_installer(src, env).returncode == 0
    before_files = count_files(zcode(home))
    before_known = (zcode(home) / "cli" / "plugins" / "known_marketplaces.json").read_text(encoding="utf-8")
    before_installed = (zcode(home) / "cli" / "plugins" / "installed_plugins.json").read_text(encoding="utf-8")
    before_mkt = (zcode(home) / "cli" / "plugins" / "marketplaces" / ICON_MKT_ID
                  / "marketplace.json").read_text(encoding="utf-8")
    cli_dir = zcode(home) / "cli"
    before_config = (cli_dir / "config.json").read_text(encoding="utf-8") if (cli_dir / "config.json").exists() else None

    # 安装 dry-run
    proc = run_installer(src, env, "--dry-run")
    assert proc.returncode == 0, "dry-run 应成功：%s" % (proc.stderr or proc.stdout)[-400:]
    out = proc.stdout + proc.stderr
    assert "将注入图标 marketplace" in out, "dry-run 未打印注入计划"

    # 卸载 dry-run
    proc2 = subprocess.run(
        ["node", str(src / "scripts" / "install.js"), "--uninstall", "--zcode", "--dry-run"],
        env=env, capture_output=True, text=True, timeout=120, cwd=str(src),
        encoding='utf-8', errors='replace')
    assert proc2.returncode == 0, "卸载 dry-run 应成功：%s" % (proc2.stderr or proc2.stdout)[-400:]
    out2 = proc2.stdout + proc2.stderr
    assert "将清理图标 marketplace" in out2, "卸载 dry-run 未打印清理计划"

    # 全部写操作零发生：文件数不变、关键文件内容不变
    assert count_files(zcode(home)) == before_files, (
        "dry-run 改动了磁盘文件数：%d → %d" % (before_files, count_files(zcode(home))))
    assert (zcode(home) / "cli" / "plugins" / "known_marketplaces.json").read_text(encoding="utf-8") == before_known, \
        "dry-run 写穿了 known_marketplaces.json"
    assert (zcode(home) / "cli" / "plugins" / "installed_plugins.json").read_text(encoding="utf-8") == before_installed, \
        "dry-run 写穿了 installed_plugins.json"
    assert (zcode(home) / "cli" / "plugins" / "marketplaces" / ICON_MKT_ID
            / "marketplace.json").read_text(encoding="utf-8") == before_mkt, "dry-run 写穿了 marketplace 清单"
    config_after = (cli_dir / "config.json").read_text(encoding="utf-8") if (cli_dir / "config.json").exists() else None
    assert config_after == before_config, "dry-run 写穿了 config.json"

    # 无新增 .bak-<ts> 文件——文件数断言已覆盖（bak 会改变文件数），
    # 这里补充断言 marketplace 相关无 bak 泄漏
    assert not list((zcode(home) / "cli" / "plugins" / "marketplaces").rglob("*.bak-*")), \
        "dry-run 在 marketplace 目录留下 .bak 残留"


def test_manifest_missing_skips_marketplace_injection(sandbox, tmp_path):
    """防御分支：源树缺 .claude-plugin/marketplace.json 时安装仍成功、图标跳过。

    injectIconMarketplace 对缺失清单只告警不中断（图标层失败不伤功能层）。
    """
    env, home = sandbox
    src = make_source(tmp_path, drop_icon_manifest=True)

    proc = run_installer(src, env, "--targets", "zcode")
    assert proc.returncode == 0, "缺清单时安装仍应成功（图标层可失败）：%s" % (proc.stderr or proc.stdout)[-500:]
    assert known_entries(home) == 0, "缺清单时不应注入 marketplace"
    assert installed_entries(home, PLUGIN_ID) == 1, "功能层注册不受图标层影响"


def test_deploy_claude_code_fails_when_manifest_missing(sandbox, tmp_path):
    """I2 + v3.2.3：缺 .claude-plugin/plugin.json 时必须 exit 1 且不碰旧缓存。

    修前形态：先 rmSync(claudePluginRoot) 清掉用户已有的插件缓存，
    再检查 manifestSrc 是否存在——manifest 缺失时用户得到
    「旧的已删、新的没装」。I2 修复后先查后删；v3.2.3 再进一步把
    「⚠️ 跳过后照常打印部署完成」的静默成功改为 exit 1（npm 3.2.2
    全局安装用户「以为装上了、/plugin 里却没有」的事故根因）。
    """
    env, home = sandbox
    src = make_source(tmp_path)
    # 故意删掉 manifest，模拟 npm 包 files 白名单漏 .claude-plugin/ 的场景
    (src / ".claude-plugin" / "plugin.json").unlink()

    # 预置一个「用户已有的旧版缓存」
    stale = (home / ".claude" / "plugins" / "cache" / "claude-plugins-official"
             / "zcode-expert-system" / "3.0.0")
    stale.mkdir(parents=True)
    (stale / "stale-marker.txt").write_text("用户的旧版缓存\n", encoding="utf-8")

    proc = run_installer(src, env, "--targets", "claude-code")
    # v3.2.3：源树完整性问题必须失败退出，不得静默成功
    assert proc.returncode == 1, "manifest 缺失时必须 exit 1：%s" % (proc.stderr or proc.stdout)[-500:]
    assert (stale / "stale-marker.txt").is_file(), (
        "manifest 缺失时 Claude Code 旧缓存被先删（先删后验未修复）")
    assert "部署失败" in (proc.stdout + proc.stderr), "未打印失败原因"
    assert "部署完成" not in (proc.stdout + proc.stderr), (
        "manifest 缺失仍打印「部署完成」——静默成功误导用户（npm 3.2.2 事故）")


# ===========================================================================
# Claude Code 注册回归：统一 install 必须走本地 marketplace，而非只复制文件
# ===========================================================================

def _install_fake_claude(bin_dir, enable=True):
    """写一个最小 claude CLI 替身：记录调用并模拟 marketplace add/install。

    enable=False 模拟「注册成功但 enabledPlugins 没写进去」的真实故障形态
    （I6）：CLI 装上了插件，但 /plugin 里是关闭态。
    """
    bin_dir.mkdir()
    fake = bin_dir / "fake-claude.js"
    fake.write_text(r'''const fs = require('fs');
const path = require('path');
const os = require('os');

const ENABLE = __ENABLE__;
const home = os.homedir();
const claude = path.join(home, '.claude');
const plugins = path.join(claude, 'plugins');
const args = process.argv.slice(2);
fs.mkdirSync(plugins, { recursive: true });
fs.appendFileSync(path.join(home, 'fake-claude-calls.log'), args.join(' ') + '\n');

if (args.includes('--version')) process.exit(0);

const now = new Date().toISOString();
const write = (file, data) => {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, JSON.stringify(data, null, 2), 'utf8');
};
const read = (file) => {
  try { return JSON.parse(fs.readFileSync(file, 'utf8')); } catch { return null; }
};

if (args[0] === 'plugin' && args[1] === 'marketplace' && args[2] === 'add') {
  const market = args[3];
  const file = path.join(plugins, 'known_marketplaces.json');
  const known = read(file) || {};
  known['zcode-local'] = {
    source: { source: 'directory', path: market },
    installLocation: market,
    lastUpdated: now,
  };
  write(file, known);
  process.exit(0);
}

if (args[0] === 'plugin' && args[1] === 'install') {
  const src = path.join(plugins, 'marketplaces', 'zcode-local', 'zcode-expert-system');
  const manifest = read(path.join(src, '.claude-plugin', 'plugin.json')) || {};
  const version = manifest.version || '0.0.0';
  const dest = path.join(plugins, 'cache', 'zcode-local', 'zcode-expert-system', version);
  fs.rmSync(dest, { recursive: true, force: true });
  fs.cpSync(src, dest, { recursive: true });

  const file = path.join(plugins, 'installed_plugins.json');
  const installed = read(file) || { version: 2, plugins: {} };
  installed.version = installed.version || 2;
  installed.plugins = installed.plugins || {};
  installed.plugins['zcode-expert-system@zcode-local'] = [{
    scope: 'user', installPath: dest, version, installedAt: now, lastUpdated: now,
  }];
  write(file, installed);

  if (ENABLE) {
    const settingsFile = path.join(claude, 'settings.json');
    const settings = read(settingsFile) || {};
    settings.enabledPlugins = settings.enabledPlugins || {};
    settings.enabledPlugins['zcode-expert-system@zcode-local'] = true;
    write(settingsFile, settings);
  }
  process.exit(0);
}

process.exit(0);
'''.replace('__ENABLE__', 'true' if enable else 'false'), encoding="utf-8")
    if os.name == "nt":
        (bin_dir / "claude.cmd").write_text(
            '@echo off\r\nnode "%~dp0fake-claude.js" %*\r\n', encoding="utf-8")
    else:
        shim = bin_dir / "claude"
        shim.write_text(
            '#!/bin/sh\nexec node "$(dirname "$0")/fake-claude.js" "$@"\n',
            encoding="utf-8")
        shim.chmod(0o755)
    return bin_dir


def test_unified_install_registers_claude_via_marketplace(sandbox, tmp_path):
    """统一 install 的 Claude 目标必须真正注册插件。

    只复制到旧缓存目录不会出现在 /plugin 中（v3.2.2 事故）。
    本用例用 claude CLI 替身确认：构建本地 marketplace →
    claude plugin marketplace add → claude plugin install →
    installed_plugins.json / enabledPlugins 均有 zcode-local 条目。
    """
    env, home = sandbox
    env = dict(env)
    env.pop("ZES_CLAUDE_INSTALL", None)  # 恢复默认 marketplace 路径

    fake_bin = _install_fake_claude(tmp_path / "fakebin")
    env["PATH"] = str(fake_bin) + os.pathsep + env.get("PATH", "")

    src = make_source(tmp_path)
    # make_source 已含 references/templates；这里只补 Claude 专属的 bin/context
    for rel in ("bin", "context"):
        shutil.copytree(PROJECT_ROOT / rel, src / rel)

    proc = run_installer(src, env, "--targets", "claude-code")
    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, out[-1000:]

    installed = read_json(home / ".claude" / "plugins" / "installed_plugins.json")
    assert "zcode-expert-system@zcode-local" in installed.get("plugins", {}), out[-1000:]

    settings = read_json(home / ".claude" / "settings.json")
    assert settings.get("enabledPlugins", {}).get(
        "zcode-expert-system@zcode-local") is True, "插件未启用"

    calls = (home / "fake-claude-calls.log").read_text(encoding="utf-8")
    assert "plugin marketplace add" in calls, calls
    assert "plugin install zcode-expert-system@zcode-local" in calls, calls

    legacy = (home / ".claude" / "plugins" / "cache" / "claude-plugins-official"
              / "zcode-expert-system")
    assert not legacy.exists(), "仍走旧缓存直拷路径——/plugin 不会加载"


# ===========================================================================
# C1（2026-11-26 复审）：卸载不得静默删除含用户文件的备份
#
# 抓的破坏：`--uninstall --zcode` 无 --purge 时无条件 rmSync
# `skills/zcode-expert-system.bak-*`。备份是安装时 rename 出来的**旧技能
# 目录**，里面可能有用户自己写的文件；无条件删除等于「卸个插件顺手销毁
# 用户数据」，而且真实模式经 act() 静默执行、连一行日志都没有。
#
# 口径：与安装侧共用一个 hasUserFiles 判定——空备份才自动删，含用户文件
# 的保留并打印路径；只有显式 --purge 才连同用户文件一起删。
# ===========================================================================

def _seed_user_file_in_backup(sandbox, tmp_path):
    """安装 → 往技能目录塞用户文件 → 重装（生成含用户文件的备份）。

    返回 (src, env, home, 备份目录, 用户文件)。
    """
    env, home = sandbox
    src = make_source(tmp_path)
    assert run_installer(src, env).returncode == 0, "首次安装应成功"

    deployed = zcode(home) / "skills" / "zcode-expert-system"
    user_note = deployed / "我的笔记.md"
    user_note.write_text("用户自建内容，不许被卸载删掉\n", encoding="utf-8")

    proc = run_installer(src, env)
    assert proc.returncode == 0, (proc.stdout + proc.stderr)[-800:]

    baks = [p for p in (zcode(home) / "skills").glob("zcode-expert-system.bak-*")]
    assert len(baks) == 1, "重装后应恰好留下一个备份目录，实际：%s" % baks
    bak = baks[0]
    assert (bak / "我的笔记.md").is_file(), "备份里没有用户文件——夹具不成立"
    return src, env, home, bak, bak / "我的笔记.md"


def test_uninstall_keeps_backup_with_user_files(sandbox, tmp_path):
    """`--uninstall --zcode`（无 --purge）必须保留含用户文件的备份。"""
    src, env, home, bak, user_note = _seed_user_file_in_backup(sandbox, tmp_path)

    proc = subprocess.run(
        ["node", str(src / "scripts" / "install.js"), "--uninstall", "--zcode"],
        env=env, capture_output=True, text=True, timeout=120, cwd=str(src),
        encoding="utf-8", errors="replace")
    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, out[-800:]

    assert bak.exists(), "卸载删掉了含用户文件的备份目录（数据销毁）"
    assert user_note.is_file(), "卸载删掉了备份里的用户文件"
    assert "用户自建内容" in user_note.read_text(encoding="utf-8")
    # 保留必须是可见事实：路径要打印出来，用户才知道去清
    assert "保留" in out and bak.name in out, (
        "保留备份未在日志中明确列出路径：%s" % out[-800:])


def test_uninstall_purge_deletes_backup_with_user_files(sandbox, tmp_path):
    """`--uninstall --zcode --purge` 才允许删除含用户文件的备份。"""
    src, env, home, bak, user_note = _seed_user_file_in_backup(sandbox, tmp_path)

    proc = subprocess.run(
        ["node", str(src / "scripts" / "install.js"),
         "--uninstall", "--zcode", "--purge"],
        env=env, capture_output=True, text=True, timeout=120, cwd=str(src),
        encoding="utf-8", errors="replace")
    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, out[-800:]

    assert not bak.exists(), "--purge 未删除备份目录：%s" % bak
    assert not user_note.exists(), "--purge 后用户文件仍残留"


def test_uninstall_deletes_empty_backup_without_purge(sandbox, tmp_path):
    """双向反例：只含插件产物的备份（无用户文件），无 --purge 也应清掉。"""
    env, home = sandbox
    src = make_source(tmp_path)
    assert run_installer(src, env).returncode == 0

    # 模拟一次中断/历史遗留的备份：里面只有插件自己的产物
    bak = zcode(home) / "skills" / "zcode-expert-system.bak-1000"
    (bak / "config").mkdir(parents=True)
    (bak / "SKILL.md").write_text("旧版技能说明\n", encoding="utf-8")
    (bak / "config" / "workflow.json").write_text("{}\n", encoding="utf-8")

    proc = subprocess.run(
        ["node", str(src / "scripts" / "install.js"), "--uninstall", "--zcode"],
        env=env, capture_output=True, text=True, timeout=120, cwd=str(src),
        encoding="utf-8", errors="replace")
    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, out[-800:]
    assert not bak.exists(), "只含插件产物的备份未被清理：%s" % bak


# ===========================================================================
# Claude Code 卸载：缓存目录对称清理
# ===========================================================================

def _seed_claude_uninstall(home):
    """造出 Claude 注册状态与四个缓存目录（两个本插件、两个他人插件）。"""
    plugins = home / ".claude" / "plugins"
    plugins.mkdir(parents=True, exist_ok=True)
    installed = plugins / "installed_plugins.json"
    installed.write_text(json.dumps({
        "version": 2,
        "plugins": {
            "zcode-expert-system@zcode-local": [{
                "scope": "user",
                "installPath": str(plugins / "cache" / "zcode-local"
                                  / "zcode-expert-system" / "3.2.5"),
                "version": "3.2.5",
            }],
        },
    }, indent=2), encoding="utf-8")
    known = plugins / "known_marketplaces.json"
    known.write_text(json.dumps({
        "zcode-local": {
            "source": {"source": "directory",
                       "path": str(plugins / "marketplaces" / "zcode-local")},
            "installLocation": str(plugins / "marketplaces" / "zcode-local"),
        },
    }, indent=2), encoding="utf-8")
    (home / ".claude" / "settings.json").write_text(json.dumps({
        "enabledPlugins": {"zcode-expert-system@zcode-local": True},
    }, indent=2), encoding="utf-8")

    dirs = [
        plugins / "cache" / "zcode-local" / "zcode-expert-system" / "3.2.5",
        plugins / "cache" / "claude-plugins-official" / "zcode-expert-system" / "3.2.1",
        plugins / "cache" / "claude-plugins-official" / "playwright" / "1.0.0",
        plugins / "cache" / "zcode-local" / "other-plugin" / "1.0.0",
        plugins / "marketplaces" / "zcode-local",
    ]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)
        (d / "marker.txt").write_text("x\n", encoding="utf-8")
    return dirs


def _claude_uninstall_env(env, tmp_path):
    env = dict(env)
    env.pop("ZES_CLAUDE_INSTALL", None)
    fake_bin = _install_fake_claude(tmp_path / "fakebin-uninstall")
    env["PATH"] = str(fake_bin) + os.pathsep + env.get("PATH", "")
    return env


def test_claude_uninstall_removes_plugin_cache_dirs(sandbox, tmp_path):
    """卸载必须清掉本插件两个缓存子目录，不能只删 marketplace 目录。"""
    env, home = sandbox
    env = _claude_uninstall_env(env, tmp_path)
    src = make_source(tmp_path)
    _seed_claude_uninstall(home)

    proc = subprocess.run(
        ["node", str(src / "scripts" / "install.js"), "--uninstall", "--claude-code"],
        env=env, capture_output=True, text=True, timeout=120, cwd=str(src),
        encoding="utf-8", errors="replace")
    assert proc.returncode == 0, (proc.stdout + proc.stderr)[-800:]

    plugins = home / ".claude" / "plugins"
    assert not (plugins / "cache" / "zcode-local" / "zcode-expert-system").exists(), \
        "卸载后 cache/zcode-local/zcode-expert-system 仍残留"
    assert not (plugins / "cache" / "claude-plugins-official"
                / "zcode-expert-system").exists(), \
        "卸载后旧官方缓存 zcode-expert-system 仍残留"
    assert not (plugins / "marketplaces" / "zcode-local").exists(), \
        "卸载后 marketplace 目录仍残留"


def test_claude_uninstall_keeps_other_plugins_cache(sandbox, tmp_path):
    """卸载只删本插件子目录，其他插件的缓存不得被误删。"""
    env, home = sandbox
    env = _claude_uninstall_env(env, tmp_path)
    src = make_source(tmp_path)
    _seed_claude_uninstall(home)

    proc = subprocess.run(
        ["node", str(src / "scripts" / "install.js"), "--uninstall", "--claude-code"],
        env=env, capture_output=True, text=True, timeout=120, cwd=str(src),
        encoding="utf-8", errors="replace")
    assert proc.returncode == 0, (proc.stdout + proc.stderr)[-800:]

    plugins = home / ".claude" / "plugins"
    assert (plugins / "cache" / "claude-plugins-official"
            / "playwright" / "1.0.0" / "marker.txt").is_file(), \
        "误删了其他插件（playwright）的缓存"
    assert (plugins / "cache" / "zcode-local"
            / "other-plugin" / "1.0.0" / "marker.txt").is_file(), \
        "误删了其他插件（other-plugin）的缓存"


# ===========================================================================
# I1（2026-11-26 复审）：无 claude CLI 时卸载必须清掉幽灵注册
#
# 抓的破坏：`claude plugin uninstall` / `marketplace remove` 失败时老实现
# 只打一句 ⚠️，随后照删缓存目录并打印「🎉 卸载完成」。用户机器上
# installed_plugins.json 与 settings.json.enabledPlugins 的条目仍在——
# 重装时撞「已安装」，排查半天找不到东西。
# ===========================================================================

def _path_without_claude(env):
    """PATH 去掉所有含 claude 可执行文件的目录——模拟「本机没装 Claude CLI」。"""
    exe = "claude.cmd" if os.name == "nt" else "claude"
    kept = []
    for part in env.get("PATH", "").split(os.pathsep):
        if not part:
            continue
        if (Path(part) / exe).exists():
            continue
        kept.append(part)
    return os.pathsep.join(kept)


def test_claude_uninstall_without_cli_clears_registration(sandbox, tmp_path):
    """无 claude CLI 时卸载：注册/启用键消失、缓存删除、rc=0、不碰其他插件。"""
    env, home = sandbox
    env = dict(env)
    env.pop("ZES_CLAUDE_INSTALL", None)
    env["PATH"] = _path_without_claude(env)
    assert shutil.which("claude", path=env["PATH"]) is None, (
        "夹具失真：PATH 里仍能解析到 claude CLI")

    src = make_source(tmp_path)
    _seed_claude_uninstall(home)

    # 另一个插件的注册与启用条目必须原样保留
    inst_file = home / ".claude" / "plugins" / "installed_plugins.json"
    inst = read_json(inst_file)
    inst["plugins"]["other-plugin@zcode-local"] = [{
        "scope": "user", "installPath": "x", "version": "1.0.0",
    }]
    inst_file.write_text(json.dumps(inst, indent=2), encoding="utf-8")
    set_file = home / ".claude" / "settings.json"
    settings = read_json(set_file)
    settings["enabledPlugins"]["other-plugin@zcode-local"] = True
    set_file.write_text(json.dumps(settings, indent=2), encoding="utf-8")

    proc = subprocess.run(
        ["node", str(src / "scripts" / "install.js"), "--uninstall", "--claude-code"],
        env=env, capture_output=True, text=True, timeout=120, cwd=str(src),
        encoding="utf-8", errors="replace")
    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, out[-1000:]

    installed = read_json(inst_file)
    assert "zcode-expert-system@zcode-local" not in installed["plugins"], (
        "installed_plugins.json 仍有本插件幽灵注册：%s" % installed["plugins"])
    assert "other-plugin@zcode-local" in installed["plugins"], "误删了其他插件的注册"

    settings = read_json(set_file)
    assert "zcode-expert-system@zcode-local" not in settings["enabledPlugins"], (
        "settings.json 仍有本插件启用键：%s" % settings["enabledPlugins"])
    assert settings["enabledPlugins"].get("other-plugin@zcode-local") is True, \
        "误删了其他插件的启用键"

    known = read_json(home / ".claude" / "plugins" / "known_marketplaces.json")
    assert "zcode-local" not in known, "known_marketplaces.json 仍有市场注册"

    plugins = home / ".claude" / "plugins"
    assert not (plugins / "cache" / "zcode-local" / "zcode-expert-system").exists(), \
        "无 CLI 时缓存目录未删除"
    assert not (plugins / "marketplaces" / "zcode-local").exists(), \
        "无 CLI 时市场目录未删除"
    assert "卸载完成" in out, "注册已清干净却未打印卸载完成：%s" % out[-600:]


# ===========================================================================
# Claude Code 独立安装脚本（scripts/install-claude-code.js）
#   I2：dry-run 必须跑预检，且不得打印「安装完成」
#   I6：enabledPlugins 未生效必须 rc≠0，不得打印「安装完成」
# ===========================================================================

CLAUDE_INSTALLER = PROJECT_ROOT / "scripts" / "install-claude-code.js"


def _run_claude_installer(src, env, *args):
    return subprocess.run(
        ["node", str(src / "scripts" / "install-claude-code.js")] + list(args),
        env=env, capture_output=True, text=True, timeout=180, cwd=str(src),
        encoding="utf-8", errors="replace")


def _make_claude_source(tmp_path):
    """make_source 之外补 Claude 专属的 bin/ context/（PLUGIN_COMPONENTS 成员）。"""
    src = make_source(tmp_path)
    for rel in ("bin", "context"):
        shutil.copytree(PROJECT_ROOT / rel, src / rel)
    return src


def test_claude_dry_run_never_reports_install_complete(sandbox, tmp_path):
    """dry-run 只输出计划：不得出现「安装完成」，且零写入。"""
    env, home = sandbox
    env = dict(env)
    env.pop("ZES_CLAUDE_INSTALL", None)
    src = _make_claude_source(tmp_path)

    proc = _run_claude_installer(src, env, "--dry-run", "--targets", "claude-code")
    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, out[-1000:]
    assert "安装完成" not in out, "dry-run 打印了「安装完成」——假完成：%s" % out[-600:]
    assert "dry-run 结束" in out, "dry-run 未给出计划收尾说明：%s" % out[-600:]
    # 双目标 dry-run 走 main() 的合并收尾分支，同样不得报完成
    proc2 = _run_claude_installer(src, env, "--dry-run", "--targets", "claude-code,zcode")
    out2 = proc2.stdout + proc2.stderr
    assert "安装完成" not in out2, "双目标 dry-run 打印了「安装完成」：%s" % out2[-600:]
    assert not (home / ".claude" / "plugins").exists(), "dry-run 改动了磁盘"


def test_claude_dry_run_runs_preflight(sandbox, tmp_path):
    """缺部署必需组件时，dry-run 也必须失败（否则预演无意义）。"""
    env, home = sandbox
    env = dict(env)
    env.pop("ZES_CLAUDE_INSTALL", None)
    src = _make_claude_source(tmp_path)
    shutil.rmtree(src / "templates")

    proc = _run_claude_installer(src, env, "--dry-run", "--targets", "claude-code")
    out = proc.stdout + proc.stderr
    assert proc.returncode != 0, "缺 templates/ 的 dry-run 仍 rc=0（跳过预检）：%s" % out[-600:]
    assert "preflight" in out or "templates" in out, "失败原因未指明缺失组件：%s" % out[-600:]
    assert "安装完成" not in out


def test_claude_install_fails_when_plugin_not_enabled(sandbox, tmp_path):
    """注册成功但 enabledPlugins 未写入 → rc≠0，且不打印「安装完成」（I6）。"""
    env, home = sandbox
    env = dict(env)
    env.pop("ZES_CLAUDE_INSTALL", None)
    fake_bin = _install_fake_claude(tmp_path / "fakebin-noenable", enable=False)
    env["PATH"] = str(fake_bin) + os.pathsep + env.get("PATH", "")

    src = _make_claude_source(tmp_path)
    proc = _run_claude_installer(src, env, "--targets", "claude-code")
    out = proc.stdout + proc.stderr

    assert proc.returncode != 0, "插件未启用却 rc=0（假成功）：%s" % out[-1000:]
    installed = read_json(home / ".claude" / "plugins" / "installed_plugins.json")
    assert "zcode-expert-system@zcode-local" in installed.get("plugins", {})
    assert "未启用" in out, "未提示「已注册但未启用」：%s" % out[-1000:]
    assert "安装完成" not in out, "未启用仍打印「安装完成」：%s" % out[-1000:]


# ===========================================================================
# v3.2.5 部署完整性校验：运行时组件缺一不可，缺失必须报错（不得只警告）
#
# 抓的破坏：v3.2.4 及以前安装器只校验 agents 数量。`scripts/workflow_check.py`
# 缺失（/wf:* 命令的机械核对入口）、`config/categories.json` 的 description
# 缺项（类目语义画像失效）、`templates/` `references/` 未随包分发时，
# 安装器仍然打印「部署完成」——用户拿到的是一个跑不起来的插件。
# ===========================================================================

RUNTIME_FILES = (
    "scripts/workflow_check.py",
    "config/categories.json",
    "config/experts.json",
    "config/workflow.json",
    "SKILL.md",
    "zcode_dev_workflow.py",
    "zcode_expert_system.py",
    "skill_entry.py",
)
RUNTIME_DIRS = ("templates", "references", "agents", "commands", "hooks")


def assert_runtime_components(root, host):
    """断言部署副本带齐全部运行时组件，且 32 类 description 可读。"""
    missing = [rel for rel in RUNTIME_FILES + RUNTIME_DIRS
               if not (root / rel).exists()]
    assert not missing, "%s 部署副本缺运行时组件：%s（%s）" % (host, missing, root)
    cats = json.loads((root / "config" / "categories.json").read_text(encoding="utf-8"))
    assert len(cats) == 32, "%s 的 categories.json 分类数为 %d（应为 32）" % (host, len(cats))
    no_desc = [k for k, v in cats.items()
               if not str((v or {}).get("description") or "").strip()]
    assert not no_desc, "%s 的 categories.json 有分类缺 description：%s" % (host, no_desc)


def test_zcode_deployed_skill_has_runtime_components(sandbox, tmp_path):
    """ZCode 安装后，技能目录与插件缓存技能都必须带齐运行时组件。"""
    env, home = sandbox
    src = make_source(tmp_path)
    proc = run_installer(src, env, "--targets", "zcode")
    assert proc.returncode == 0, (proc.stdout + proc.stderr)[-800:]

    assert_runtime_components(zcode(home) / "skills" / "zcode-expert-system", "ZCode 技能目录")
    cache_skill = (zcode(home) / "cli" / "plugins" / "cache" / "zcode-plugins-official"
                   / "zcode-expert-system")
    versions = [p for p in cache_skill.iterdir() if p.is_dir()] if cache_skill.exists() else []
    assert versions, "插件缓存未生成版本目录：%s" % cache_skill
    assert_runtime_components(versions[0] / "skills" / "zcode-expert-system",
                              "ZCode 插件缓存技能")

    assert "部署校验通过" in (proc.stdout + proc.stderr), (
        "安装器未打印部署校验结论——校验可能没接上")


def test_missing_workflow_check_fails_before_touching_disk(sandbox, tmp_path):
    """源树缺 scripts/workflow_check.py 时预检必须 fail-closed 且零写入。"""
    env, home = sandbox
    src = make_source(tmp_path)
    (src / "scripts" / "workflow_check.py").unlink()

    proc = run_installer(src, env, "--targets", "zcode")
    assert proc.returncode != 0, "缺 workflow_check.py 应当失败，实际 rc=0"
    out = proc.stdout + proc.stderr
    assert "workflow_check.py" in out, "失败原因未指出缺失组件：%s" % out[-400:]
    assert "部署完成" not in out, "缺组件仍打印「部署完成」——静默成功"
    leftovers = [p for p in zcode(home).rglob("*") if p.is_file()]
    assert not leftovers, "预检失败后仍留下 %d 个文件" % len(leftovers)


def test_missing_category_description_fails_install(sandbox, tmp_path):
    """32 类 description 缺项必须在预检阶段拦下（类目画像会失效）。"""
    env, home = sandbox
    src = make_source(tmp_path)
    cats_path = src / "config" / "categories.json"
    cats = json.loads(cats_path.read_text(encoding="utf-8"))
    cats["frontend-client"].pop("description", None)
    cats_path.write_text(json.dumps(cats, ensure_ascii=False), encoding="utf-8")

    proc = run_installer(src, env, "--targets", "zcode")
    assert proc.returncode != 0, "description 缺项应当失败，实际 rc=0"
    assert "description" in (proc.stdout + proc.stderr), "未指出 description 缺失"
    leftovers = [p for p in zcode(home).rglob("*") if p.is_file()]
    assert not leftovers, "预检失败后仍留下 %d 个文件（半毁）" % len(leftovers)


def test_claude_marketplace_has_runtime_components(sandbox, tmp_path):
    """Claude Code marketplace 副本必须带 workflow_check/categories/templates/references。"""
    env, home = sandbox
    env = dict(env)
    env.pop("ZES_CLAUDE_INSTALL", None)
    fake_bin = _install_fake_claude(tmp_path / "fakebin-runtime")
    env["PATH"] = str(fake_bin) + os.pathsep + env.get("PATH", "")

    src = make_source(tmp_path)
    for rel in ("bin", "context"):
        shutil.copytree(PROJECT_ROOT / rel, src / rel)

    proc = run_installer(src, env, "--targets", "claude-code")
    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, out[-1000:]

    plugin = (home / ".claude" / "plugins" / "marketplaces" / "zcode-local"
              / "zcode-expert-system")
    assert (plugin / "scripts" / "workflow_check.py").is_file(), \
        "marketplace 副本缺 scripts/workflow_check.py（/wf:* 命令会落空）"
    assert (plugin / "config" / "categories.json").is_file(), \
        "marketplace 副本缺 config/categories.json（类目画像失效）"
    assert (plugin / "templates").is_dir(), "marketplace 副本缺 templates/"
    assert (plugin / "references").is_dir(), "marketplace 副本缺 references/"
    assert (plugin / "context").is_dir(), "marketplace 副本缺 context/"
    assert (plugin / "bin").is_dir(), "marketplace 副本缺 bin/"
    assert_runtime_components(plugin, "Claude Code marketplace")
    assert "部署校验通过" in out or "验证通过" in out, "未打印校验结论"
