# -*- coding: utf-8 -*-
"""P4 · 声明源与文档一致性回归测试（缺陷 #13 #14 #19 #22 #23 #24 + 一致性族）

**这个文件要抓的破坏**

P1/P2/P3 修的是「代码做错了」，P4 修的是「**文档说错了**」。
后者的危害形式不同：代码错了会报错，文档错了会让人**按文档操作然后撞墙**，
而撞墙的人会以为是自己不会用。

1. **#13 计划模板缺 6 个必备段**
   `templates/plan-sections.md` 只有 6 段，`workflow.json` 的
   `required_sections` 要 8 段。照模板写 → G3 门禁判 6 个 FAIL。
   **模板与门禁互相矛盾**：被明确指示的路径必然走不通。

2. **#14 S8 缺 stop_for_owner**
   `workflow.json` 的 S8 块没有 `stop_for_owner`，实测 `stages_for_scale`
   输出 `S8 stop=False`；而 `SKILL.md` 九阶段表与 `gates.G8b.stop` 都说要停。
   归档是高代价不可逆动作（`openspec/` 目录搬迁 + 主 spec 覆盖）。

3. **#19 版本号两处停在 3.0.0**
   `skill_entry.py:101` 与 `config/experts.json:2` 是 3.0.0，其余四处是 3.1.0。

4. **#22 `docs/` 与 `docs/workflow-fusion-design.md` 不存在**
   `package.json` 的 `files` 声明发布它，`SKILL.md` 把它列为「融合设计基线」。

5. **#23 README 双份停在 v3.0**
   零命中「九阶段/两轴/workflow」，缺 `zcode_dev_workflow.py`、`config/workflow.json`、
   `commands/`、`references/` 的目录结构说明。

6. **#24 `decisions.md` 无产出者却被 4 处引用**
   `SKILL.md` 的 P2 证据位置、`workflow.json` 的 evidence_levels、
   `commands/wf/resume.md` 的恢复读序第 7 项、`references/workflow-tree.md`。
   恢复流程会读一个永远不存在的文件。

7. **一致性族**：`requests` 未使用的硬依赖、`bin/cli.js` 的 `--help` 自指、
   `validate_transition` 死代码、`templates/progress.md` 缺「是否需隔离」与七态枚举。

**这类测试的性质**：多数是「契约测试」——断言两个声明源之间的一致性，
而不是「先红后绿」的行为测试。没有「错误行为」可复现，只有「错误事实」可断言。
"""

import json
import os
import re
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import zcode_dev_workflow as wf  # noqa: E402


def read(rel):
    return (PROJECT_ROOT / rel).read_text(encoding="utf-8")


def load_json(rel):
    return json.loads(read(rel))


# ===========================================================================
# #13 计划模板必须覆盖全部必备段
# ===========================================================================

def test_plan_template_has_all_required_sections():
    """模板必须含 workflow.json 声明的全部必备段。

    修前实测：模板 6 段 vs 声明 8 段，缺 Goal / Architecture / Tech Stack /
    Spec / Global Constraints / Dependencies。
    后果：照模板写计划 → G3 判 6 个 FAIL，而 SKILL.md 指示「复制模板并填充」。
    """
    req = [s for s in load_json("config/workflow.json")["stages"]
           if s["id"] == "S3"][0]["required_sections"]
    tpl = read("templates/plan-sections.md")
    missing = [sec for sec in req
               if not re.search(r"^#{1,6}[ \t]+%s[ \t]*$" % re.escape(sec), tpl, re.M)]
    assert not missing, "模板缺这些必备段：%s" % missing


def test_plan_template_covers_all_evidence_sections():
    """模板还必须覆盖 P3/P4 证据段（Baseline / Review / Rulings / IV）。

    与上一条互补：必备段是 G3 的要求，这四段是 S4/S6/S7 的要求。
    两者都必须在同一个模板里，否则用户填完必备段仍会在后续门禁撞墙。
    """
    tpl = read("templates/plan-sections.md")
    for sec in ("Baseline", "Review", "Rulings", "Integration Verification"):
        assert re.search(r"^#{1,6}[ \t]+%s[ \t]*$" % re.escape(sec), tpl, re.M), (
            "模板缺证据段 `## %s`" % sec)


def test_template_plan_passes_g3_gate(tmp_path):
    """照模板生成的计划必须能通过 G3 门禁（端到端验证）。

    这是 #13 的真正验收标准：不是「模板里有这些字」，而是
    「按模板写出来的计划能过门禁」。修前：6 个必备段 FAIL。
    """
    from scripts import workflow_check as wc

    plan = tmp_path / "p.md"
    tpl = read("templates/plan-sections.md")
    # 模板正文里带 `> 用法：复制到 ...` 之类说明，直接整体当作计划使用，
    # 只补一个任务标题（模板不含，S3 要求有）。
    plan.write_text(tpl + "\n### Task 1: alpha\n", encoding="utf-8")

    rep, _ = wc.run(change=None, plan=str(plan), scale="light", root=str(tmp_path))
    section_fails = [i for i in rep.items
                     if "必备段" in i["check"] and i["status"] == wc.FAIL]
    assert not section_fails, (
        "照模板写的计划未通过必备段：%s" % [i["check"] for i in section_fails])


# ===========================================================================
# #14 stop_for_owner 必须与 SKILL.md 表格一致
# ===========================================================================

DOC_STOP_STAGES = ("S1", "S2", "S7", "S8")


def test_stop_for_owner_matches_skill_md():
    """SKILL.md 标注「停老板」的阶段，配置里必须有 stop_for_owner。

    修前实测：S8 缺该字段 → `stages_for_scale` 输出 `S8 stop=False`。
    归档是不可逆的高代价动作（目录搬迁 + 主 spec 覆盖），
    而配置层面没有任何机械依据要求停。
    """
    wf_data = load_json("config/workflow.json")
    by_id = {s["id"]: s for s in wf_data["stages"]}
    missing = [sid for sid in DOC_STOP_STAGES
               if not by_id[sid].get("stop_for_owner")]
    assert not missing, "这些阶段在 SKILL.md 标了「停老板」但配置缺 stop_for_owner：%s" % missing


def test_stages_for_scale_reports_s8_stop():
    """`stages_for_scale` 输出里 S8 的 stop_for_owner 必须为真。

    消费者读的是这个函数的输出，不是原始 JSON——
    所以要在这里断言，否则改 JSON 但不改读取路径也测不出来。
    """
    for scale in ("medium", "large"):
        stages = {s["id"]: s for s in wf.stages_for_scale(scale)}
        assert stages["S8"]["stop_for_owner"] is True, (
            "scale=%s 时 S8 stop_for_owner=%r（应 True）"
            % (scale, stages["S8"]["stop_for_owner"]))


def test_gates_stop_agrees_with_stage_stop():
    """`gates.*.stop` 与 `stages.*.stop_for_owner` 不得互相矛盾。

    两个声明源描述同一事实，必须一致——这正是本项目声称要防的「漂移」。
    """
    wf_data = load_json("config/workflow.json")
    gates = wf_data["gates"]
    bad = []
    for s in wf_data["stages"]:
        gate = gates.get(s["gate"].split("+")[0])
        if not gate:
            continue
        gate_stop = gate.get("stop")
        if gate_stop is True and not s.get("stop_for_owner"):
            bad.append((s["id"], s["gate"], True, s.get("stop_for_owner")))
    assert not bad, "门禁说 stop=true 但阶段没标记：%s" % bad


# ===========================================================================
# #19 版本号一致
# ===========================================================================

def test_version_strings_agree():
    """五处版本号必须一致。

    修前实测：package.json / plugin.json / SKILL.md / workflow.json 是 3.1.0，
    skill_entry.py:101 与 config/experts.json:2 是 3.0.0。
    """
    versions = {
        "package.json": load_json("package.json")["version"],
        ".zcode-plugin/plugin.json": load_json(".zcode-plugin/plugin.json")["version"],
        "config/workflow.json": load_json("config/workflow.json")["version"],
        "SKILL.md": re.search(r"^version:\s*\"?([\d.]+)",
                              read("SKILL.md"), re.M).group(1),
        "skill_entry.py": re.search(r"\"version\":\s*\"([\d.]+)\"",
                                    read("skill_entry.py")).group(1),
    }
    distinct = set(versions.values())
    assert len(distinct) == 1, "版本号不一致：%s" % versions


def test_experts_json_version_is_data_version():
    """`config/experts.json` 的 version 是**数据版本**，不应与插件版本混同。

    两种正当做法：改成与插件同版本，或改名为 data_version 明确区分。
    这里只断言「不产生第三种取值」——避免让它成为第三个互相矛盾的版本号。
    """
    pkg = load_json("package.json")["version"]
    experts = load_json("config/experts.json")
    v = experts.get("version")
    assert v is not None, "experts.json 缺 version 字段"
    assert v == pkg or "data_version" in experts, (
        "experts.json version=%r 既不等同插件版本 %r，又未标为 data_version"
        % (v, pkg))


# ===========================================================================
# #22 package.json files 声明的路径必须存在
# ===========================================================================

def test_package_files_paths_exist():
    """`files` 里声明的每一项必须真实存在。

    修前实测：`docs/` 不存在。`npm pack` 不报错但静默缺少内容——
    即发布包少了「融合设计基线」，而 SKILL.md 仍在引用它。
    """
    pkg = load_json("package.json")
    missing = [f for f in pkg["files"] if not (PROJECT_ROOT / f.rstrip("/")).exists()]
    assert not missing, "package.json files 声明了不存在的路径：%s" % missing


def test_skill_md_referenced_docs_exist():
    """SKILL.md「相关文件」表里列的路径必须存在（修前 docs/ 那条 404）。

    例外：**运行时产物目录**。`docs/superpowers/specs/`、`docs/superpowers/plans/`
    这些由使用者在自己的项目里创建，仓库里不该有——把它们判成「引用不存在的路径」
    是把「产出位置」误当成「随包分发的文件」（初版误报 1 处）。
    """
    RUNTIME_DIRS = ("docs/superpowers/",)
    src = read("SKILL.md")
    refs = set(re.findall(r"`((?:config|scripts|context|references|templates|docs)/[^`\s]+)`", src))
    missing = []
    for r in refs:
        if r.startswith(RUNTIME_DIRS):
            continue                      # 运行时产物目录，仓库本不该有
        p = r.rstrip("/").replace("<change>", "demo")
        if "*" in p or "<" in p:
            continue
        if not (PROJECT_ROOT / p).exists():
            missing.append(r)
    assert not missing, "SKILL.md 引用了不存在的路径：%s" % missing


# ===========================================================================
# #23 README 必须反映当前架构
# ===========================================================================

@pytest.mark.parametrize("readme", ["README.md", "README_CN.md"])
def test_readme_mentions_two_axes_and_nine_stages(readme):
    """两份 README 都必须提到两轴与九阶段。

    修前实测：零命中「九阶段 / 两轴 / workflow」，目录结构里缺
    `zcode_dev_workflow.py`、`config/workflow.json`、`commands/`、`references/`。
    而 package.json 与 plugin.json 都在对外宣称 v3.1 的
    「two-axis routing / nine-stage workflow」——唯一面向用户的文档却完全没有。
    """
    src = read(readme)
    assert ("九阶段" in src or "nine-stage" in src.lower()), (
        "%s 未提及九阶段" % readme)
    assert ("两轴" in src or "two-axis" in src.lower()), (
        "%s 未提及两轴" % readme)


@pytest.mark.parametrize("readme", ["README.md", "README_CN.md"])
def test_readme_lists_core_files(readme):
    """README 的目录结构必须列出 v3.1 的核心文件。"""
    src = read(readme)
    for needle in ("zcode_dev_workflow.py", "workflow.json",
                   "skill_entry.py", "config/"):
        assert needle in src, "%s 的目录结构缺 %r" % (readme, needle)


@pytest.mark.parametrize("readme", ["README.md", "README_CN.md"])
def test_readme_version_is_current(readme):
    """README 不得停留在旧版本号。"""
    src = read(readme)
    pkg = load_json("package.json")["version"]
    assert pkg in src, "%s 未体现当前版本 %s" % (readme, pkg)


# ===========================================================================
# #24 decisions.md：要么有产出者，要么不再被引用
# ===========================================================================

def test_decisions_md_has_producer_or_no_reference():
    """`decisions.md` 要么真有产出方，要么所有引用都指向别处。

    修前实测：4 处引用它作为「P2 证据 / 恢复读序第 7 项」，
    但 S2 的 artifacts 里没有它、`workflow_check` 也不检查它——
    resume 流程会读一个永远不存在的文件，恢复者会误判「决策证据丢失」。

    R2 的裁决是**收回引用**（指向计划文档 `## Rulings`），不新增产出物：
    `## Rulings` 已有产出方与校验，再造一条账本与之职责重叠。
    """
    wf_data = load_json("config/workflow.json")
    has_producer = any(
        "decisions.md" in a["path"]
        for s in wf_data["stages"] for a in s.get("artifacts", []))

    refs = []
    for rel in ("SKILL.md", "config/workflow.json",
                "commands/wf/resume.md", "references/workflow-tree.md"):
        if "decisions.md" in read(rel):
            refs.append(rel)

    if has_producer:
        assert True     # 有产出方则引用正当
    else:
        assert not refs, (
            "`decisions.md` 没有任何阶段产出它，但仍被这些文件引用：%s" % refs)


def test_rulings_section_is_the_decision_record():
    """决策记录的权威位置是计划文档 `## Rulings`，且有机械校验。

    这是 R2 裁决的正面表达：不是「删掉某个文件」，而是「指向已有的、
    有产出方也有校验的那个位置」。
    """
    from scripts import workflow_check as wc
    assert hasattr(wc, "has_section")
    # workflow_check 里确实检查 Rulings 段
    src = (PROJECT_ROOT / "scripts" / "workflow_check.py").read_text(encoding="utf-8")
    assert '"Rulings"' in src, "workflow_check 未检查 Rulings 段"


# ===========================================================================
# 一致性族：零三方依赖 / CLI 契约 / 死代码 / 账本模板
# ===========================================================================

def test_no_unused_third_party_import():
    """核心模块不得引入未使用的三方依赖。

    修前实测：`scripts/embedding_client.py:9` 顶层 `import requests`，全文件无使用，
    且仓库无 requirements/setup.py/pyproject。环境缺 requests 时
    `zcode_expert_system.py` 的 import 会被 except 吞掉——功能正确降级，
    但故障完全不可见。删掉这一行即可让「零三方依赖」成为真事实。
    """
    files = ["scripts/embedding_client.py", "scripts/llm_client.py",
             "zcode_expert_system.py", "zcode_dev_workflow.py",
             "skill_entry.py", "scripts/workflow_check.py"]
    offenders = []
    for rel in files:
        src = read(rel)
        for mod in ("requests", "numpy", "pandas", "yaml", "aiohttp", "httpx"):
            if re.search(r"^\s*import\s+%s\b" % mod, src, re.M) or \
               re.search(r"^\s*from\s+%s\b" % mod, src, re.M):
                # 是否真的被使用（出现次数 > 1 才算用）
                body = re.sub(r"^\s*(?:import|from)\s+%s\b.*$" % mod, "", src, flags=re.M)
                if mod not in body:
                    offenders.append("%s: %s" % (rel, mod))
    assert not offenders, "未使用的三方依赖：%s" % offenders


def test_cli_has_help_alias():
    """`bin/cli.js` 必须支持 `--help`（修前 default 分支指向一个同样报错的分支）。

    修前实测：`node bin/cli.js --help` → 「未知命令，使用 --help 查看帮助」，rc=1。
    自指循环：出错提示把用户导向同样出错的分支。
    """
    src = read("bin/cli.js")
    assert re.search(r"case\s+['\"]--help['\"]", src), "bin/cli.js 缺 --help 分支"


def test_cli_has_uninstall():
    """`bin/cli.js` 必须有 uninstall（README 教的第一卸载命令）。

    修前实测：`node bin/cli.js uninstall` → 未知命令 rc=1。
    """
    assert re.search(r"case\s+['\"]uninstall['\"]", read("bin/cli.js")), \
        "bin/cli.js 缺 uninstall 分支"


def test_cli_no_unused_imports():
    """`bin/cli.js` 不得有引入后从未使用的模块（修前 execSync/path/fs 全未用）。"""
    src = read("bin/cli.js")
    offenders = []
    for name in ("execSync", "path", "fs"):
        if re.search(r"const\s+%s\s*=\s*require" % name, src):
            body = src.split("\n")
            uses = [ln for ln in body
                    if name in ln and "require(" not in ln]
            if not uses:
                offenders.append(name)
    assert not offenders, "bin/cli.js 未使用的引入：%s" % offenders


def test_validate_transition_is_reachable():
    """`validate_transition` 不得是纯死代码——状态机必须有一个执行入口。

    修前实测：全仓只有定义处一处，`_main` 的子命令只有
    triage/stages/plan/states，状态机在 CLI 面不可达。
    workflow.json 的 13 条 transitions 因此只能靠人肉遵守。
    """
    src = read("zcode_dev_workflow.py")
    assert "def validate_transition" in src
    # 必须有一个子命令能触达它
    assert re.search(r"cmd\s*==\s*['\"]transition", src), (
        "validate_transition 没有 CLI 入口（仍是死代码）")


def test_progress_template_has_all_seven_states():
    """账本模板的状态枚举必须是完整七态。

    修前实测：`templates/progress.md:15` 只写 4 个
    （PENDING / IN_PROGRESS / BLOCKED / DONE），缺 REVIEW / NEEDS_FIX / PARKED。
    PARKED 是「默认禁归档」的判定依据——模板不给这个值，
    主控改用 BLOCKED 表示就绕过了 workflow_check 的 PARKED 拦截。
    """
    wf_data = load_json("config/workflow.json")
    states = wf_data["states"]["list"]
    tpl = read("templates/progress.md")
    missing = [s for s in states if s not in tpl]
    assert not missing, "账本模板缺这些状态：%s" % missing


def test_progress_template_has_isolation_row():
    """账本模板的 Triage 表必须含「是否需隔离」。

    修前实测：S0 规格要求分诊 11 项（含「是否需隔离」），
    模板只有 10 行。该项是 W1「无 worktree 即无实施并行」的决策依据。
    """
    tpl = read("templates/progress.md")
    assert "隔离" in tpl, "账本模板缺「是否需隔离」行"


# ===========================================================================
# 交叉一致性：SKILL.md 阶段名 / check.md 计数
# ===========================================================================

def test_skill_md_stage_names_match_config():
    """SKILL.md 九阶段表的阶段名应与 workflow.json 一致（或明示为简称）。

    修前实测：9 个阶段名里 8 个不一致
    （SKILL「S4 环境与基线」vs 配置「环境准备与基线测试」）。
    按名称 join 的消费方（账本 Current Phase、报告引用）会错配。
    """
    wf_data = load_json("config/workflow.json")
    src = read("SKILL.md")
    mismatched = []
    for s in wf_data["stages"]:
        if s["name"] in src or (s.get("short") and "「%s」" % s["short"] in src):
            continue
        if ("| **%s**" % s["id"]) in src:
            mismatched.append((s["id"], s["name"]))
    assert not mismatched, (
        "SKILL.md 未出现这些阶段的配置名或标注简称：%s" % mismatched)


def test_check_md_gate_count_is_accurate():
    """`commands/wf/check.md` 自称的核对项数量必须与实际表格行数一致。

    修前实测：标题写「13 类」，表格实际 9 个门禁行，脚本 31 个检查点。
    三个数字互不相同。
    """
    src = read("commands/wf/check.md")
    m = re.search(r"核对项（(\d+)\s*类）", src)
    if not m:
        pytest.skip("check.md 未使用「核对项（N 类）」表述")
    claimed = int(m.group(1))
    # 数表格里的门禁行（形如 `| G0 |` 或以 G 开头的单元格）
    rows = re.findall(r"^\|\s*(G[0-9][^\s|]*)\s*\|", src, re.M)
    actual = len(set(rows))
    assert claimed == actual, (
        "check.md 自称 %d 类，实际表格 %d 行（%s）" % (claimed, actual, sorted(set(rows))))


# ===========================================================================
# P8 批次三 Task 7：package.json 改名与 files 白名单收窄
# ===========================================================================

def test_package_name_is_expert_system():
    """npm 包名必须是 zcode-expert-system（老板拍板的改名决策落地核对）。"""
    pkg = load_json("package.json")
    assert pkg["name"] == "zcode-expert-system", (
        "npm 包名仍是 %r——改名决策未落地（占名包已撤，新名需同步全链）" % pkg["name"])


def test_files_whitelist_has_no_directory_wildcard_for_scripts_and_docs():
    """files 白名单不得整目录打包 scripts/ 与 docs/（npm pack 实测混入）。"""
    pkg = load_json("package.json")
    files = pkg["files"]
    assert "scripts/" not in files, (
        "files 含 \"scripts/\"——npm pack 实测混入 scripts/__pycache__/*.pyc")
    assert "docs/" not in files, (
        "files 含 \"docs/\"——开发期修复计划 docs/superpowers/plans 会随包分发")
    for f in ("scripts/install.js", "scripts/workflow_check.py",
              "scripts/llm_client.py", "scripts/embedding_client.py",
              "docs/workflow-fusion-design.md"):
        assert f in files, "files 白名单缺 %s（收窄后必须逐文件列举）" % f


def test_main_points_to_cli():
    """npm main 指向 .py 文件无意义（require 必然失败），应为 bin/cli.js。"""
    pkg = load_json("package.json")
    assert pkg["main"] == "bin/cli.js", "main=%r 应为 bin/cli.js" % pkg.get("main")
    assert (PROJECT_ROOT / "bin" / "cli.js").is_file()


# ===========================================================================
# P8 批次三 Task 9：专家提示词零第三方供应链推广
# ===========================================================================

def test_agents_have_no_third_party_supply_chain_promo():
    """agents 提示词不得含第三方包安装推广（随部署注入人格 prompt 的供应链通道）。

    实测：expert-accounts-payable-agent.md 曾含 `npm install agenticbtc-mcp`
    与 `npx -y agenticbtc-mcp` 指引（主控亲核 :56-77），且配置推广段之外
    「可用支付通道」表与「核心工作流」示例持续引用该包。
    """
    agents_dir = PROJECT_ROOT / "agents"
    hits = [p.name for p in sorted(agents_dir.glob("*.md"))
            if "agenticbtc" in p.read_text(encoding="utf-8").lower()]
    assert not hits, "agents 提示词含第三方包推广：%s" % hits
    payable = agents_dir / "expert-accounts-payable-agent.md"
    text = payable.read_text(encoding="utf-8")
    assert "npm install" not in text and "npx -y" not in text, (
        "支付代理提示词仍含第三方包安装指引")
    # 正向锚（P9 复审 🟡 收口）：本轮是大段删除——「删干净」与「没删过头」
    # 两个方向都要锁。业务段（核心工作流/幂等语义/异常处理）必须仍在。
    assert "## 核心工作流" in text, "支付代理业务段被误删（删过头）"
    assert "幂等查重" in text, "幂等语义段被误删"
    assert "不自动批准" not in text or "异常" in text, "异常处理语义段被误删"


# ===========================================================================
# P2-1（2026-11-19）：总经理提示词专家数量与 categories.json 一致
#
# 抓的破坏：32 个 agents/manager-*.md 中 23 个存在「该大类包含 N 位专家」
# （与 config/categories.json 的 expert_count 一致）与「从管辖的 M 位专家
# 中选择」两处数字矛盾——职责节与执行流程节各写一次、且两处 M 值相同，
# 都是陈旧残留。派总经理（多专家协同复杂任务，SKILL.md 明示路径）时，
# 总经理按错误的 M 做专家选择，会漏派真实存在的专家。
#
# 根源是「声明源 categories.json」与「提示词正文」无机器校验联动：
# 只改数字不加门禁，下次改专家表必复发。此测试即那道门禁。
# ===========================================================================

def test_manager_prompt_expert_counts_match_categories():
    """manager 提示词正文里出现的「N 位专家」必须等于 categories.json 的 expert_count。

    遍历 config/categories.json 全部 32 类 → 读对应 agents/manager-<cat>.md →
    正则提取全部「(\\d+) 位专家」（排除 331 全局总数）→ 断言每个值 ==
    该类的 expert_count。修前实测 23 文件命中（职责节+执行流程节各一处），
    修后必须全绿。
    """
    cats = load_json("config/categories.json")
    mismatches = []
    for cat, meta in cats.items():
        declared = meta["expert_count"]
        mgr_path = PROJECT_ROOT / "agents" / ("%s.md" % meta["manager"])
        text = mgr_path.read_text(encoding="utf-8")
        # 提取所有「N 位专家」，排除 331（全局总数，出现在总述句里）
        found = [int(n) for n in re.findall(r"(\d+)\s*位专家", text)
                 if int(n) != 331]
        bad = [n for n in found if n != declared]
        if bad:
            mismatches.append((cat, declared, bad))
    assert not mismatches, (
        "以下 manager 提示词的「N 位专家」与 categories.json 的 expert_count 不符"
        "（cat, declared, 正文出现值）：%s" % mismatches)


def test_manager_scope_table_row_count_matches_expert_count():
    """「管辖范围」节表格行数必须等于 expert_count（防表格与数字各自漂移）。

    P2-1 的加固断言：数字修对后，表格本身也可能与 categories.json 脱节。
    只统计「## 管辖范围」到下一个「## 」之间的表格行（文件里执行流程节
    还有「子任务类型/关键词/典型任务/匹配专家」等其他表格，全文件统计会虚高）。
    表格行 = 该 section 内 `| ` 开头、非表头（首格「专家」）、非 |---| 分隔的行。
    """
    cats = load_json("config/categories.json")
    mismatches = []
    for cat, meta in cats.items():
        declared = meta["expert_count"]
        mgr_path = PROJECT_ROOT / "agents" / ("%s.md" % meta["manager"])
        text = mgr_path.read_text(encoding="utf-8")
        # 截取「## 管辖范围」到下一个「## 」之间的 section
        m = re.search(r"##\s*管辖范围\s*\n(.*?)(?=\n##\s)", text, re.DOTALL)
        if not m:
            mismatches.append((cat, declared, "no-管辖范围-section"))
            continue
        section = m.group(1)
        table_rows = [ln for ln in section.splitlines()
                      if ln.strip().startswith("|")
                      and "---" not in ln
                      and ln.split("|")[1].strip() != "专家"]  # 排除表头
        if len(table_rows) != declared:
            mismatches.append((cat, declared, len(table_rows)))
    assert not mismatches, (
        "以下 manager 管辖范围表格行数与 expert_count 不符"
        "（cat, declared, 表格行数）：%s" % mismatches)


# ===========================================================================
# P2-2 / P2-5（2026-11-19，方案 B：删死字段）：terminal 与 counts_as_complete
#
# 抓的破坏：config/workflow.json 的 states.terminal=[DONE,PARKED] 与
# counts_as_complete=[DONE] 两键**全仓零逻辑消费**（仅 states_summary 透传
# 展示），却与 13 条 transitions 的 T10/T11/T13 出边语义矛盾——terminal
# 声明 DONE/PARKED 是终态，transition CLI 却实测放行 DONE→NEEDS_FIX。
# 完成语义实际由 INV2（DONE↔tasks.md - [x]）与 workflow_check S8 承担。
#
# 老板决策（2026-11-19）：方案 B「删死字段」——transitions 是唯一真相，
# 删两个零消费字段，13 条 transitions 一条不动，CLI 行为零变化。
# ===========================================================================

def test_states_config_has_no_dead_fields():
    """P2-2/P2-5：states 不得含 terminal / counts_as_complete 死字段。

    修前实测：两键存在但零逻辑消费，且与 transitions 出边语义矛盾。
    修后必须删除；states.list（7 态）、transitions（13 条）、invariants 不动。
    """
    wf_data = load_json("config/workflow.json")
    states = wf_data["states"]
    assert "terminal" not in states, (
        "states 仍含 terminal 死字段（零消费且与 T10/T11/T13 出边矛盾）")
    assert "counts_as_complete" not in states, (
        "states 仍含 counts_as_complete 死字段（零消费）")
    # 正向锚：删死字段不能误删真实状态机
    assert states["list"] == ["PENDING", "IN_PROGRESS", "REVIEW",
                              "NEEDS_FIX", "BLOCKED", "DONE", "PARKED"], \
        "states.list 七态被破坏"
    assert len(states["transitions"]) == 13, \
        "transitions 13 条被破坏（删死字段不应动 transitions）"


def test_states_summary_output_has_no_dead_field_keys():
    """P2-2/P2-5：states_summary() 输出不得再含 terminal / counts_as_complete 键。

    zcode_dev_workflow.states_summary 透传了这两个死键，删除后输出键集
    应为 states/terminal?/counts_as_complete?/transitions/invariants/
    sdd_report_mapping——terminal 与 counts_as_complete 均消失。
    """
    summary = wf.states_summary()
    assert "terminal" not in summary, "states_summary 仍透传 terminal 死键"
    assert "counts_as_complete" not in summary, \
        "states_summary 仍透传 counts_as_complete 死键"
    # 正向锚：其余键必须仍在（states_summary 的键名是 states，值为七态列表）
    assert "transitions" in summary and "invariants" in summary, \
        "states_summary 误删了 transitions/invariants"
    assert "states" in summary and "sdd_report_mapping" in summary, \
        "states_summary 误删了 states/sdd_report_mapping"


# ===========================================================================
# I-1（2026-11-22）：zcode_dev_workflow.py 内部信号词表间一致性
#
# 抓的破坏：**同族动词在多张表登记、唯主表缺席**。「搭建/建设」在
# FEATURE_CONTEXT（新功能语境表）与 NEW_BUILD_VERBS（能力词守卫）都有
# 登记，唯 WRITE_SIGNALS 主表缺失——「搭建一个博客系统」误判只读，
# 合规跳过 S1-S8 全部门禁。这是 I-04「变更」缺陷的完全同构复发：
# 变更/改变当时同样只登记了语境表、主表缺席。
#
# 约束（架构师裁定）：规模轴与领域轴分表正交，本测试只做
# zcode_dev_workflow.py 内部三表（FEATURE_CONTEXT / NEW_BUILD_VERBS /
# WRITE_SIGNALS）的一致性，**不引入对 zcode_expert_system.GENERIC_TOKENS
# 的跨文件强耦合**（「搭建/建设/处理」在 GENERIC_TOKENS 是泛化降权词，
# 与写动作主表是两个正交关注点，字面同步没有语义意义）。
# ===========================================================================

# FEATURE_CONTEXT 尾部 7 个成员是**名词**（「设计一个机制」的名词尾巴），
# 作为「新功能语境」词正当存在——句子不含动词也应把 Bug 语境中和掉，
# 不要求进 WRITE_SIGNALS。豁免必须显式列举，防止静默漏网。
FEATURE_CONTEXT_NOUNS = ("机制", "策略", "规则", "流程", "页面", "模块", "功能")

# 显式豁免清单：字面不在 WRITE_SIGNALS 的实施类动词，逐个记录原因。
# 两个语义不同的桶，新词必须登记进其一，否则一致性测试报红。
VERB_SUBSTR_COVERED = {
    # 「增加/添加」含单字「加」、「写一个/写个」含单字「写」：
    # write_hits 按子串命中单字，行为正常（实测「增加日志功能」
    # 「写一个登录页面」→ light）。
    "增加": "单字「加」子串覆盖（write_hits 命中「加」）",
    "添加": "单字「加」子串覆盖",
    "写一个": "单字「写」子串覆盖（实测「写一个登录页面」→ light）",
    "写个": "单字「写」子串覆盖",
}
VERB_KNOWN_GAPS = {
    # 2026-11-22 实测发现的**同形态真缺陷**（与「搭建」缺主表完全同构）：
    # 零覆盖复合词（无单字子串可用），行为确有误判——
    #   「做一个登录页面」→ readonly；「新增日志功能」→ readonly
    # 修复（加入 WRITE_SIGNALS）待老板决策；决策后应转入 WRITE_SIGNALS
    # 并从本清单移除。此处豁免只是把已知缺口**显式留档**，不是宣称正当。
    "做一个": "已知缺口：零覆盖复合词（实测「做一个登录页面」误判只读），修复待决策",
    "做个": "已知缺口：同「做一个」",
    "新增": "已知缺口：零覆盖复合词（实测「新增日志功能」误判只读），修复待决策",
}


def test_new_build_verbs_registered_in_write_signals():
    """NEW_BUILD_VERBS 的实施类动词必须也在 WRITE_SIGNALS 主表登记。

    NEW_BUILD_VERBS 是「能力词 + 新建动词 → 不判 Bug」的守卫表；若守卫表
    认得这个词而主表不认，含该词的句子即使不判 Bug 也会因「无写动作」
    误判只读——守卫表的存在就失去了意义。

    重建缺陷验证：从 WRITE_SIGNALS 移除「搭建」本测试即红（「搭建」
    不在任何豁免清单）——正是 I-N-NEW 缺陷形态。
    """
    missing = [v for v in wf.NEW_BUILD_VERBS
               if v not in wf.WRITE_SIGNALS
               and v not in VERB_SUBSTR_COVERED
               and v not in VERB_KNOWN_GAPS]
    assert not missing, (
        "NEW_BUILD_VERBS 中这些实施动词未在 WRITE_SIGNALS 登记"
        "（同「搭建」缺陷形态，会误判只读）：\n  %s"
        % "\n  ".join(missing))


def test_feature_context_verbs_registered_in_write_signals():
    """FEATURE_CONTEXT 的动词成员（名词豁免外）必须也在 WRITE_SIGNALS 登记。

    FEATURE_CONTEXT 是「新功能语境」中和判定源；语境表登记了动词、
    主表却缺席，意味着「新功能语境」永远等不来对应的写动作命中——
    句子会被「未命中任何写动作信号」拦成只读，语境中和形同虚设。
    """
    verbs = [w for w in wf.FEATURE_CONTEXT if w not in FEATURE_CONTEXT_NOUNS]
    missing = [v for v in verbs
               if v not in wf.WRITE_SIGNALS
               and v not in VERB_SUBSTR_COVERED
               and v not in VERB_KNOWN_GAPS]
    assert not missing, (
        "FEATURE_CONTEXT 中这些实施动词未在 WRITE_SIGNALS 登记"
        "（名词豁免外，同「搭建」缺陷形态）：\n  %s"
        % "\n  ".join(missing))


def test_seed_defect_verbs_are_hard_registered():
    """种子清单：历次实证缺陷动词必须**字面**在 WRITE_SIGNALS（不得进豁免）。

    每个种子对应一次实证「误判只读、跳过全部门禁」的事故：
      - 变更 / 改变：I-04（「数据模型变更」误判只读）
      - 搭建 / 建设：I-N-NEW（「搭建一个博客系统」误判只读）
    种子成员永不进入 VERB_SUBSTR_COVERED / VERB_KNOWN_GAPS——
    豁免只允许给「行为已被单字覆盖」或「已留档待决策」的词。
    """
    seeds = ("变更", "改变", "搭建", "建设")
    missing = [v for v in seeds if v not in wf.WRITE_SIGNALS]
    assert not missing, "种子动词缺失（防复发锚被拔）：%s" % missing
