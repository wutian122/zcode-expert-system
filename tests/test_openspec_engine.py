"""Task 1 TDD tests for scripts/openspec_engine.py.

TDD 铁律：先写失败测试（RED），再实现（GREEN），最后重构。
测试通过 subprocess 调用 python scripts/openspec_engine.py，使用 tmp_path 临时目录。
"""

import json
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

ENGINE = Path(__file__).resolve().parent.parent / "scripts" / "openspec_engine.py"


def run(*args, root=None):
    """在给定根目录下运行 engine，返回 CompletedProcess。

    --root 必须放在子命令之前（argparse 全局选项位置）。

    安全说明：cmd 为参数列表形式，所有元素均来自测试代码硬编码字符串
    或 pytest tmp_path 生成的绝对路径，不含外部用户输入；subprocess.run
    使用 shell=False（默认），不会经过 shell 解释，不存在命令注入风险。
    """
    cmd = [sys.executable, str(ENGINE)]
    if root is not None:
        cmd += ["--root", str(root)]
    cmd += list(args)
    return subprocess.run(cmd, capture_output=True, text=True, shell=False,
                          cwd=str(root) if root else None,
                          encoding='utf-8', errors='replace')


def test_new_change_创建目录和元数据(tmp_path):
    r = run("new-change", "my-change", root=tmp_path)
    assert r.returncode == 0, r.stderr
    cdir = tmp_path / "openspec" / "changes" / "my-change"
    assert cdir.is_dir(), f"change dir not created: {cdir}"
    meta = cdir / ".openspec.yaml"
    assert meta.is_file(), f"metadata not created: {meta}"
    content = meta.read_text(encoding="utf-8")
    assert "schema: spec-driven" in content
    assert "name: my-change" in content
    assert "status: pending" in content
    assert "created:" in content
    assert (cdir / "specs").is_dir(), "specs subdir not created"


def test_new_change_已存在报错(tmp_path):
    run("new-change", "my-change", root=tmp_path)
    r = run("new-change", "my-change", root=tmp_path)
    assert r.returncode != 0, "duplicate new-change should exit non-zero"


def test_status_读取完成度(tmp_path):
    run("new-change", "my-change", root=tmp_path)
    r = run("status", "--change", "my-change", root=tmp_path)
    assert r.returncode == 0, r.stderr
    data = json.loads(r.stdout)
    assert data["change"] == "my-change"
    assert "products" in data
    products = data["products"]
    for key in ("proposal", "design", "tasks", "specs"):
        assert key in products, f"missing product: {key}"
        assert products[key] == "pending", f"{key} should be pending, got {products[key]}"


def test_status_不存在报错(tmp_path):
    r = run("status", "--change", "no-such-change", root=tmp_path)
    assert r.returncode != 0, "status for missing change should exit non-zero"


def test_instructions_读取模板(tmp_path):
    run("new-change", "my-change", root=tmp_path)
    # 先手动创建一个产物文件（模拟产物已就绪）
    prod = tmp_path / "openspec" / "changes" / "my-change" / "proposal.md"
    prod.write_text("# proposal\n", encoding="utf-8")
    r = run("instructions", "proposal", "--change", "my-change", root=tmp_path)
    assert r.returncode == 0, r.stderr
    data = json.loads(r.stdout)
    assert "template" in data
    assert "resolvedOutputPath" in data
    assert "required" in data
    assert "my-change" in data["resolvedOutputPath"]
    assert "proposal" in data["resolvedOutputPath"]
    assert data["exists"] is True


# ---------- Task 2: validate --change ----------

def test_validate_四件产物完整(tmp_path):
    run("new-change", "my-change", root=tmp_path)
    cdir = tmp_path / "openspec" / "changes" / "my-change"
    # 手动创建四件产物（proposal/design/tasks/specs）
    (cdir / "proposal.md").write_text("# proposal\n", encoding="utf-8")
    (cdir / "design.md").write_text("# design\n", encoding="utf-8")
    (cdir / "tasks.md").write_text("# tasks\n", encoding="utf-8")
    spec_dir = cdir / "specs" / "auth"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("## Purpose\n认证能力\n", encoding="utf-8")
    r = run("validate", "--change", "my-change", root=tmp_path)
    assert r.returncode == 0, r.stderr
    data = json.loads(r.stdout)
    assert data["change"] == "my-change"
    assert data["valid"] is True
    assert data["missing"] == []


def test_validate_缺失产物(tmp_path):
    run("new-change", "my-change", root=tmp_path)
    cdir = tmp_path / "openspec" / "changes" / "my-change"
    # 只创建 design、tasks、specs，缺 proposal.md
    (cdir / "design.md").write_text("# design\n", encoding="utf-8")
    (cdir / "tasks.md").write_text("# tasks\n", encoding="utf-8")
    spec_dir = cdir / "specs" / "auth"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("## Purpose\n认证能力\n", encoding="utf-8")
    r = run("validate", "--change", "my-change", root=tmp_path)
    assert r.returncode == 0, r.stderr
    data = json.loads(r.stdout)
    assert data["change"] == "my-change"
    assert data["valid"] is False
    assert "proposal.md" in data["missing"]


def test_validate_变更不存在报错(tmp_path):
    r = run("validate", "--change", "no-such-change", root=tmp_path)
    assert r.returncode != 0, "validate for missing change should exit non-zero"


# ---------- Task 2: sync-specs --change ----------

def _write_spec(tmp_path, capability, content):
    spec_dir = tmp_path / "openspec" / "specs" / capability
    spec_dir.mkdir(parents=True, exist_ok=True)
    (spec_dir / "spec.md").write_text(content, encoding="utf-8")
    return spec_dir / "spec.md"


def test_sync_specs_合并(tmp_path):
    run("new-change", "my-change", root=tmp_path)
    cdir = tmp_path / "openspec" / "changes" / "my-change"
    # 主 spec 已存在
    main_spec = _write_spec(tmp_path, "auth",
        "## Purpose\n认证主规格\n\n## Requirements\n登录场景\n")
    # change 下的 specs 产物（delta 来源）
    spec_dir = cdir / "specs" / "auth"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("## Purpose\n认证主规格\n\n## Requirements\n登录场景\n- 新增字段\n", encoding="utf-8")
    r = run("sync-specs", "--change", "my-change", root=tmp_path)
    assert r.returncode == 0, r.stderr
    data = json.loads(r.stdout)
    assert "change" in data
    assert data["capability"] == "auth"
    merged = main_spec.read_text(encoding="utf-8")
    assert "登录场景" in merged
    assert "新增字段" in merged


def test_sync_specs_缺少delta报错(tmp_path):
    run("new-change", "my-change", root=tmp_path)
    # 不创建 specs 产物，直接 sync 应报错非零
    r = run("sync-specs", "--change", "my-change", root=tmp_path)
    assert r.returncode != 0, "sync with missing specs product should exit non-zero"


def test_sync_specs_ADDED段落合并(tmp_path):
    """P2-1：delta 含 ## ADDED 段落时，合并进主 spec（追加到同名段）。

    锁定 _merge_delta_into_main 对 ADDED 段落的处理（openspec_engine.py:264-266）。
    """
    run("new-change", "my-change", root=tmp_path)
    cdir = tmp_path / "openspec" / "changes" / "my-change"
    _write_spec(tmp_path, "auth",
        "## Purpose\n认证主规格\n\n## Requirements\n登录场景\n")
    spec_dir = cdir / "specs" / "auth"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text(
        "## Purpose\n认证主规格\n\n## ADDED\n新增登录审计\n", encoding="utf-8")
    r = run("sync-specs", "--change", "my-change", root=tmp_path)
    assert r.returncode == 0, r.stderr
    merged = (tmp_path / "openspec" / "specs" / "auth" / "spec.md").read_text(encoding="utf-8")
    assert "## ADDED" in merged and "新增登录审计" in merged, (
        f"ADDED 段落未合并进主 spec：{merged}"
    )


def test_sync_specs_新能力无Purpose时补TBD并可通过validate(tmp_path):
    """F-3：新能力第一次 sync 必须生成非空 Purpose，validate-specs 立即通过。"""
    run("new-change", "new-cap", root=tmp_path)
    cdir = tmp_path / "openspec" / "changes" / "new-cap"
    spec_dir = cdir / "specs" / "billing"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text(
        "## ADDED Requirements\n- 支持账单导出\n", encoding="utf-8")

    r = run("sync-specs", "--change", "new-cap", root=tmp_path)
    assert r.returncode == 0, r.stderr
    data = json.loads(r.stdout)
    assert data["purpose"] == "placeholder"
    assert data["purpose_placeholder"] is True
    merged = (tmp_path / "openspec" / "specs" / "billing" / "spec.md").read_text(
        encoding="utf-8")
    assert "## Purpose" in merged
    assert "TBD" in merged

    v = run("validate-specs", root=tmp_path)
    assert v.returncode == 0, v.stdout + v.stderr
    assert json.loads(v.stdout)["valid"] is True


def test_sync_specs_新能力复制deltaPurpose(tmp_path):
    """F-3：delta 自带 Purpose 时必须原样复制到新主 spec。"""
    run("new-change", "new-cap", root=tmp_path)
    cdir = tmp_path / "openspec" / "changes" / "new-cap"
    spec_dir = cdir / "specs" / "billing"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text(
        "## Purpose\n账单与发票能力\n\n## ADDED Requirements\n- 支持账单导出\n",
        encoding="utf-8")

    r = run("sync-specs", "--change", "new-cap", root=tmp_path)
    assert r.returncode == 0, r.stderr
    data = json.loads(r.stdout)
    assert data["purpose"] == "delta"
    merged = (tmp_path / "openspec" / "specs" / "billing" / "spec.md").read_text(
        encoding="utf-8")
    assert "## Purpose\n账单与发票能力" in merged
    assert "TBD" not in merged


def test_sync_specs_REMOVED整块移除(tmp_path):
    """P2-1（老板批准 2026-11-18）：REMOVED 段落按设计文档改为「整块移除」。

    设计依据：stage-S8-sync-archive.md:29/125「REMOVED | 整块移除」；
    归档复验要求「REMOVED 消失」（line 58）。
    旧实现为「记录追加」（把 REMOVED 段落追加进主 spec）——与本期望相反。
    修复前本用例因 REMOVED 条目仍留在主 spec、且 REMOVED 段进入主 spec 而 RED。
    """
    run("new-change", "my-change", root=tmp_path)
    cdir = tmp_path / "openspec" / "changes" / "my-change"
    _write_spec(tmp_path, "auth",
        "## Purpose\n认证主规格\n\n## Requirements\n登录场景\n- 旧 token 会话\n")
    spec_dir = cdir / "specs" / "auth"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text(
        "## Purpose\n认证主规格\n\n## REMOVED\n- 旧 token 会话\n", encoding="utf-8")
    r = run("sync-specs", "--change", "my-change", root=tmp_path)
    assert r.returncode == 0, r.stderr
    merged = (tmp_path / "openspec" / "specs" / "auth" / "spec.md").read_text(encoding="utf-8")
    # REMOVED 条目从主 spec 整块移除
    assert "旧 token 会话" not in merged, (
        f"REMOVED 条目应从主 spec 整块移除，实际仍在：{merged}"
    )
    # REMOVED 段落本身不进入主 spec（归档复验要求 REMOVED 消失）
    assert "## REMOVED" not in merged, (
        f"REMOVED 段落不应进入主 spec：{merged}"
    )
    # 未提及的既有场景保留（MODIFIED 语义）
    assert "登录场景" in merged, f"未提及的既有场景应保留：{merged}"


def test_sync_specs_RENAMED段落记录(tmp_path):
    """P2-1：delta 含 ## RENAMED 段落时，合并保留 FROM/TO 记录。"""
    run("new-change", "my-change", root=tmp_path)
    cdir = tmp_path / "openspec" / "changes" / "my-change"
    _write_spec(tmp_path, "auth",
        "## Purpose\n认证主规格\n\n## Requirements\n登录场景\n")
    spec_dir = cdir / "specs" / "auth"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text(
        "## Purpose\n认证主规格\n\n## RENAMED\nFROM: 登录\nTO: 身份认证\n", encoding="utf-8")
    r = run("sync-specs", "--change", "my-change", root=tmp_path)
    assert r.returncode == 0, r.stderr
    merged = (tmp_path / "openspec" / "specs" / "auth" / "spec.md").read_text(encoding="utf-8")
    assert "## RENAMED" in merged and "FROM: 登录" in merged and "TO: 身份认证" in merged, (
        f"RENAMED 段落未按当前实现记录：{merged}"
    )


def test_sync_specs_dry_run不写主spec(tmp_path):
    """P0-2：--dry-run 时不得写主 spec，也不产生备份。

    旧实现无 --dry-run，任何 sync 都直接覆盖写主 spec，无法回滚。
    本用例在修复前因缺少 --dry-run 参数而报错（argparse 未知参数 rc=2），即 RED。
    """
    run("new-change", "my-change", root=tmp_path)
    cdir = tmp_path / "openspec" / "changes" / "my-change"
    main_spec = _write_spec(tmp_path, "auth",
        "## Purpose\n认证主规格\n\n## Requirements\n登录场景\n")
    before = main_spec.read_text(encoding="utf-8")
    spec_dir = cdir / "specs" / "auth"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("## Purpose\n认证主规格\n\n## Requirements\n- 新增字段\n", encoding="utf-8")

    r = run("sync-specs", "--dry-run", "--change", "my-change", root=tmp_path)
    assert r.returncode == 0, f"dry-run sync should exit 0: {r.stderr}"
    # 主 spec 未被改动
    assert main_spec.read_text(encoding="utf-8") == before, (
        "--dry-run 不得写入主 spec"
    )
    # 主 spec 目录无备份文件
    backups = [p for p in main_spec.parent.iterdir()
               if p.name.startswith("spec.md.bak-")]
    assert not backups, f"--dry-run 不得产生备份：{[p.name for p in backups]}"


def test_sync_specs_正常执行创建备份(tmp_path):
    """P0-2：正常 sync 前对主 spec 做 .bak-<ts> 备份。

    旧实现直接覆盖写，无备份；本用例在修复前因无备份而 RED。
    """
    run("new-change", "my-change", root=tmp_path)
    cdir = tmp_path / "openspec" / "changes" / "my-change"
    main_spec = _write_spec(tmp_path, "auth",
        "## Purpose\n认证主规格\n\n## Requirements\n登录场景\n")
    before = main_spec.read_text(encoding="utf-8")
    spec_dir = cdir / "specs" / "auth"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("## Purpose\n认证主规格\n\n## Requirements\n- 新增字段\n", encoding="utf-8")

    r = run("sync-specs", "--change", "my-change", root=tmp_path)
    assert r.returncode == 0, r.stderr
    # 主 spec 被更新
    merged = main_spec.read_text(encoding="utf-8")
    assert "新增字段" in merged
    # 产生备份，且备份内容等于合并前主 spec
    backups = [p for p in main_spec.parent.iterdir()
               if p.name.startswith("spec.md.bak-")]
    assert len(backups) == 1, (
        f"应产生 1 个主 spec 备份，实际 {len(backups)} 个：{[p.name for p in backups]}"
    )
    assert backups[0].read_text(encoding="utf-8") == before, (
        "备份内容应等于合并前主 spec"
    )


# ---------- Task 2: archive-change ----------

def test_archive_change_归档(tmp_path):
    today = date.today().isoformat()
    run("new-change", "my-change", root=tmp_path)
    cdir = tmp_path / "openspec" / "changes" / "my-change"
    # 满足归档条件：写入 .status.json 标记全部通过
    status = {
        "tasksCompleted": True,
        "specsConsistent": True,
        "testsPassed": True,
        "reviewPassed": True,
        "noBlockers": True,
        "gitStatusOk": True,
        "docsUpdated": True,
    }
    (cdir / ".status.json").write_text(json.dumps(status, ensure_ascii=False), encoding="utf-8")
    r = run("archive-change", "my-change", root=tmp_path)
    assert r.returncode == 0, r.stderr
    archive_dir = tmp_path / "openspec" / "changes" / "archive" / f"{today}-my-change"
    assert archive_dir.is_dir(), f"archive dir not created: {archive_dir}"
    assert not cdir.exists(), f"source change dir should be removed: {cdir}"


def test_archive_change_目标已存在报错(tmp_path):
    today = date.today().isoformat()
    run("new-change", "my-change", root=tmp_path)
    cdir = tmp_path / "openspec" / "changes" / "my-change"
    (cdir / ".status.json").write_text(json.dumps({"tasksCompleted": True}, ensure_ascii=False), encoding="utf-8")
    archive_dir = tmp_path / "openspec" / "changes" / "archive" / f"{today}-my-change"
    archive_dir.mkdir(parents=True, exist_ok=True)
    r = run("archive-change", "my-change", root=tmp_path)
    assert r.returncode != 0, "archive when target exists should exit non-zero"


def test_archive_change_PARKED禁止归档(tmp_path):
    run("new-change", "my-change", root=tmp_path)
    cdir = tmp_path / "openspec" / "changes" / "my-change"
    # 标记 PARKED 任务存在，满足其他条件
    status = {
        "tasksCompleted": True,
        "specsConsistent": True,
        "testsPassed": True,
        "reviewPassed": True,
        "noBlockers": True,
        "gitStatusOk": True,
        "docsUpdated": True,
        "parked": True,
    }
    (cdir / ".status.json").write_text(json.dumps(status, ensure_ascii=False), encoding="utf-8")
    r = run("archive-change", "my-change", root=tmp_path)
    assert r.returncode != 0, "archive with PARKED tasks should exit non-zero (W8)"


# ---------- I-05：归档必须校验 tasks.md 实际勾选状态 ----------

_ALL_TRUE_STATUS = {
    "tasksCompleted": True,
    "specsConsistent": True,
    "testsPassed": True,
    "reviewPassed": True,
    "noBlockers": True,
    "gitStatusOk": True,
    "docsUpdated": True,
}


def _setup_archivable_change(tmp_path, name="my-change", tasks_md=None):
    """建一个七标志全 true 的变更，可选写入 tasks.md。"""
    run("new-change", name, root=tmp_path)
    cdir = tmp_path / "openspec" / "changes" / name
    (cdir / ".status.json").write_text(
        json.dumps(_ALL_TRUE_STATUS, ensure_ascii=False), encoding="utf-8")
    if tasks_md is not None:
        (cdir / "tasks.md").write_text(tasks_md, encoding="utf-8")
    return cdir


def test_archive_change_tasks未勾选拒绝归档(tmp_path):
    """I-05：tasks.md 存在未勾任务，即使七标志全 true 也必须拒绝归档。"""
    _setup_archivable_change(
        tmp_path, tasks_md="- [ ] 任务一\n- [ ] 任务二\n")
    r = run("archive-change", "my-change", root=tmp_path)
    assert r.returncode != 0, "tasks.md 有未勾任务时不得归档"
    assert "未完成" in r.stderr or "tasks" in r.stderr.lower(), \
        "错误信息应说明未完成的任务"


def test_archive_change_tasks已勾选放行(tmp_path):
    """I-05：tasks.md 全部勾选，七标志全 true，放行归档。"""
    today = date.today().isoformat()
    _setup_archivable_change(
        tmp_path, tasks_md="- [x] 任务一\n- [x] 任务二\n")
    r = run("archive-change", "my-change", root=tmp_path)
    assert r.returncode == 0, r.stderr
    archive_dir = tmp_path / "openspec" / "changes" / "archive" / f"{today}-my-change"
    assert archive_dir.is_dir(), f"archive dir not created: {archive_dir}"


def test_archive_change_tasks不存在沿用状态放行(tmp_path):
    """I-05：tasks.md 不存在时不校验勾选（无账本可查），沿用 status 标志放行。"""
    today = date.today().isoformat()
    _setup_archivable_change(tmp_path)  # 不写 tasks.md
    r = run("archive-change", "my-change", root=tmp_path)
    assert r.returncode == 0, "无 tasks.md 时不增加校验，应放行"
    archive_dir = tmp_path / "openspec" / "changes" / "archive" / f"{today}-my-change"
    assert archive_dir.is_dir(), f"archive dir not created: {archive_dir}"


def test_archive_change_dry_run不移动(tmp_path):
    """P0-3：--dry-run 时不得移动变更目录，也不产生备份。

    旧实现无 --dry-run，任何 archive 都直接 shutil.move，不可逆。
    本用例在修复前因缺少 --dry-run 参数而报错（argparse 未知参数 rc=2），即 RED。
    """
    today = date.today().isoformat()
    run("new-change", "my-change", root=tmp_path)
    cdir = tmp_path / "openspec" / "changes" / "my-change"
    (cdir / ".status.json").write_text(json.dumps({
        "tasksCompleted": True, "specsConsistent": True, "testsPassed": True,
        "reviewPassed": True, "noBlockers": True, "gitStatusOk": True,
        "docsUpdated": True,
    }, ensure_ascii=False), encoding="utf-8")

    r = run("archive-change", "--dry-run", "my-change", root=tmp_path)
    assert r.returncode == 0, f"dry-run archive should exit 0: {r.stderr}"
    # 源目录未被移动
    assert cdir.is_dir(), "--dry-run 不得移动变更目录"
    # 无归档目录生成
    archive_dir = tmp_path / "openspec" / "changes" / "archive" / f"{today}-my-change"
    assert not archive_dir.exists(), "--dry-run 不得生成归档目录"
    # 无备份残留
    backups = [p for p in (tmp_path / "openspec" / "changes").iterdir()
               if p.name.startswith("my-change.bak-")]
    assert not backups, f"--dry-run 不得产生备份：{[p.name for p in backups]}"


def test_archive_change_归档成功后清理备份(tmp_path):
    """P0-3：正常归档成功后，备份目录被清理（成功才清），不留残留。

    旧实现直接 shutil.move，无备份无残留，此用例在修复前也通过；
    本用例作为回归守卫，锁定「备份存在→归档成功→清理备份」的行为。
    """
    today = date.today().isoformat()
    run("new-change", "my-change", root=tmp_path)
    cdir = tmp_path / "openspec" / "changes" / "my-change"
    (cdir / ".status.json").write_text(json.dumps({
        "tasksCompleted": True, "specsConsistent": True, "testsPassed": True,
        "reviewPassed": True, "noBlockers": True, "gitStatusOk": True,
        "docsUpdated": True,
    }, ensure_ascii=False), encoding="utf-8")

    r = run("archive-change", "my-change", root=tmp_path)
    assert r.returncode == 0, r.stderr
    archive_dir = tmp_path / "openspec" / "changes" / "archive" / f"{today}-my-change"
    assert archive_dir.is_dir(), "归档目录应存在"
    assert not cdir.exists(), "源目录应被移走"
    # 备份已被清理，无残留
    backups = [p for p in (tmp_path / "openspec" / "changes").iterdir()
               if p.name.startswith("my-change.bak-")]
    assert not backups, f"归档成功后备份应被清理，实际残留：{[p.name for p in backups]}"


@pytest.mark.parametrize("field,label", [
    ("tasksCompleted", "所有必须完成的任务已完成"),
    ("specsConsistent", "规格与实现一致"),
    ("testsPassed", "测试验证通过"),
    ("reviewPassed", "代码审查通过"),
    ("noBlockers", "无未解决阻断问题"),
    ("gitStatusOk", "Git 状态符合要求"),
    ("docsUpdated", "必要文档已更新"),
])
def test_archive_change_七条件逐条不满足报错(tmp_path, field, label):
    """P2-2：archive-change 七条件逐条——任一条件为 false 必须报错。

    旧测试只覆盖全部通过/目标已存在/PARKED，未覆盖逐条条件失效。
    本用例参数化逐条置 false，锁定七条件门禁的每一条。
    """
    run("new-change", "my-change", root=tmp_path)
    cdir = tmp_path / "openspec" / "changes" / "my-change"
    status = {
        "tasksCompleted": True, "specsConsistent": True, "testsPassed": True,
        "reviewPassed": True, "noBlockers": True, "gitStatusOk": True,
        "docsUpdated": True,
    }
    status[field] = False
    (cdir / ".status.json").write_text(json.dumps(status, ensure_ascii=False), encoding="utf-8")

    r = run("archive-change", "my-change", root=tmp_path)
    assert r.returncode != 0, (
        f"七条件中 {field}=false 时 archive-change 必须报错，实际 rc=0"
    )
    assert label in r.stderr, (
        f"archive 报错应提示缺失条件 {label}，实际 stderr：{r.stderr}"
    )


# ---------- Task 2: validate-specs ----------

def test_validate_specs_Purpose缺失(tmp_path):
    # spec.md 无 ## Purpose
    spec_path = _write_spec(tmp_path, "auth", "## Requirements\n登录场景\n")
    r = run("validate-specs", root=tmp_path)
    assert r.returncode == 0, r.stderr
    data = json.loads(r.stdout)
    assert data["valid"] is False
    assert any("auth" in issue and "Purpose" in issue for issue in data["issues"])


def test_validate_specs_全部通过(tmp_path):
    spec_path = _write_spec(tmp_path, "auth",
        "## Purpose\n认证主规格\n\n## Requirements\n登录场景\n")
    r = run("validate-specs", root=tmp_path)
    assert r.returncode == 0, r.stderr
    data = json.loads(r.stdout)
    assert data["valid"] is True
    assert data["issues"] == []


def test_validate_specs_退役能力空Requirements(tmp_path):
    """P2-3：已退役能力若 ## Requirements 为空，validate-specs 应判 invalid。

    旧测试只覆盖 ## Purpose 缺失，未覆盖退役能力留空 Requirements 的
    违规形态（openspec_engine.py:396-400）。本用例锁定该规则。
    """
    spec_path = _write_spec(tmp_path, "legacy",
        "## Purpose\n已退役的旧能力\n退役\n\n## Requirements\n")
    r = run("validate-specs", root=tmp_path)
    assert r.returncode == 0, r.stderr
    data = json.loads(r.stdout)
    assert data["valid"] is False, "退役能力 ## Requirements 为空应判 invalid"
    assert any("legacy" in issue and "Requirements" in issue for issue in data["issues"]), (
        f"issues 未指向 legacy 的 Requirements：{data['issues']}"
    )


# ---------- list 子命令 ----------

def test_list_读取_root_无_openspec(tmp_path):
    """无 openspec 目录时，root 应为 tmp_path，openspec 为 false，changes 为空。"""
    r = run("list", "--root", str(tmp_path))
    assert r.returncode == 0, r.stderr
    data = json.loads(r.stdout)
    assert data["root"] == str(tmp_path.resolve())
    assert data["openspec"] is False
    assert data["changes"] == []


def test_list_有_openspec_列出变更(tmp_path):
    run("new-change", "change-a", root=tmp_path)
    run("new-change", "change-b", root=tmp_path)
    r = run("list", "--root", str(tmp_path))
    assert r.returncode == 0, r.stderr
    data = json.loads(r.stdout)
    assert data["root"] == str(tmp_path.resolve())
    assert data["openspec"] is True
    names = sorted(c["name"] for c in data["changes"])
    assert names == ["change-a", "change-b"]
    for c in data["changes"]:
        assert "path" in c
        assert "products" in c


# ---------- round4 遗留缺陷修复：F1 / Q-1 / Q-2 / Q-3 ----------

def test_instructions_产物未创建时返回可写路径(tmp_path):
    """F1：new-change 后产物不存在时，instructions 返回可写路径（exists:false, rc=0），
    不得报 product not found——消除 new-change 与 instructions 的鸡生蛋空档。"""
    run("new-change", "my-change", root=tmp_path)
    # 不创建任何产物文件
    r = run("instructions", "proposal", "--change", "my-change", root=tmp_path)
    assert r.returncode == 0, r.stderr
    data = json.loads(r.stdout)
    assert data["template"] == "proposal"
    assert data["resolvedOutputPath"].endswith("proposal.md")
    assert data["required"] is True
    assert data["exists"] is False


@pytest.mark.parametrize("argv", [
    ["validate", "--change", "archive"],
    ["status", "--change", "archive"],
    ["instructions", "proposal", "--change", "archive"],
    ["sync-specs", "--change", "archive"],
    ["new-change", "archive"],
])
def test_保留名archive被统一拒绝(tmp_path, argv):
    """Q-1：archive 是归档容器保留名，6 个入口（经 change_dir）统一拒绝。"""
    r = run(*argv, root=tmp_path)
    assert r.returncode != 0, f"{argv} 应被拒绝（archive 保留名）"
    assert "archive" in r.stderr.lower()


def _make_archivable_change(tmp_path, name="my-change"):
    """round4 测试共用：建标准可归档 change（七字段全 true 的 .status.json）。"""
    run("new-change", name, root=tmp_path)
    cdir = tmp_path / "openspec" / "changes" / name
    status = {
        "tasksCompleted": True,
        "specsConsistent": True,
        "testsPassed": True,
        "reviewPassed": True,
        "noBlockers": True,
        "gitStatusOk": True,
        "docsUpdated": True,
    }
    (cdir / ".status.json").write_text(json.dumps(status, ensure_ascii=False), encoding="utf-8")
    return cdir


def test_archive_change_非标准条目拒绝归档(tmp_path):
    """Q-2：变更目录混入非标准条目（如 .mimosa）时拒绝归档——备份在归档
    成功后即删，清理删除会致用户文件永久丢失，故选校验拒绝而非删除。"""
    cdir = _make_archivable_change(tmp_path)
    (cdir / ".mimosa" / "hook-state").mkdir(parents=True)
    r = run("archive-change", "my-change", root=tmp_path)
    assert r.returncode != 0, "混入 .mimosa 应拒绝归档"
    assert ".mimosa" in r.stderr
    # 源目录与归档目录均未动（拒绝发生在移动之前）
    assert cdir.exists()
    today = date.today().isoformat()
    assert not (tmp_path / "openspec" / "changes" / "archive" / f"{today}-my-change").exists()


def test_archive_change_清理杂项后可归档且白名单产物不误伤(tmp_path):
    """Q-2 正向：清掉 .mimosa 后正常归档；artifacts/ 是引擎合法产物（cmd_status
    消费），不得因白名单误伤。"""
    today = date.today().isoformat()
    cdir = _make_archivable_change(tmp_path)
    (cdir / ".mimosa" / "hook-state").mkdir(parents=True)
    r = run("archive-change", "my-change", root=tmp_path)
    assert r.returncode != 0
    import shutil as _shutil
    _shutil.rmtree(cdir / ".mimosa")
    (cdir / "artifacts").mkdir()
    (cdir / "artifacts" / "a.json").write_text("{}", encoding="utf-8")
    r = run("archive-change", "my-change", root=tmp_path)
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "openspec" / "changes" / "archive" / f"{today}-my-change").is_dir()


def test_archive_change_归档后元数据status为archived(tmp_path):
    """Q-3：归档时 .openspec.yaml 的 status 同步更新为 archived。"""
    _make_archivable_change(tmp_path)
    r = run("archive-change", "my-change", root=tmp_path)
    assert r.returncode == 0, r.stderr
    today = date.today().isoformat()
    meta = tmp_path / "openspec" / "changes" / "archive" / f"{today}-my-change" / ".openspec.yaml"
    assert "status: archived" in meta.read_text(encoding="utf-8")


# ---------- resume.md 修复：instructions apply 可用 ----------

def test_instructions_apply_返回实施上下文(tmp_path):
    """resume.md 引用的 instructions apply 不再是 unknown product id：
    返回实施上下文（tasks.md 路径 + contextFiles + specsDir），产物不存在时
    exists:false 不报错。"""
    run("new-change", "my-change", root=tmp_path)
    cdir = tmp_path / "openspec" / "changes" / "my-change"
    (cdir / "tasks.md").write_text("# tasks\n- [ ] 1. 任务\n", encoding="utf-8")
    r = run("instructions", "apply", "--change", "my-change", root=tmp_path)
    assert r.returncode == 0, r.stderr
    data = json.loads(r.stdout)
    assert data["template"] == "apply"
    assert data["resolvedOutputPath"].endswith("tasks.md")
    assert data["exists"] is True
    assert data["contextFiles"] and data["contextFiles"][0].endswith("tasks.md")
    assert "specsDir" in data


def test_instructions_apply_无tasks不报错(tmp_path):
    """apply 是实施入口而非产物校验：tasks.md 不存在时也返回 rc=0（exists:false）。"""
    run("new-change", "my-change", root=tmp_path)
    r = run("instructions", "apply", "--change", "my-change", root=tmp_path)
    assert r.returncode == 0, r.stderr
    data = json.loads(r.stdout)
    assert data["exists"] is False
    assert data["contextFiles"] == []


# ---------- P1 技术债清偿：change_dir 库模式抛 ValueError ----------

def test_change_dir_库模式archive抛ValueError(tmp_path):
    """P1 方案 A：change_dir 以库模式调用时抛 ValueError（而非 sys.exit 炸宿主进程），
    由 CLI 入口负责转错误码。"""
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    try:
        import openspec_engine as _oe
        import importlib
        importlib.reload(_oe)
        with pytest.raises(ValueError, match="archive"):
            _oe.change_dir(tmp_path, "archive")
        # 正常名称仍返回 Path
        p = _oe.change_dir(tmp_path, "normal-change")
        assert p == tmp_path / "openspec" / "changes" / "normal-change"
    finally:
        sys.path.pop(0)


# ---------- vendored openspec 技能（zes-openspec-*） ----------

def test_vendored_openspec_技能存在():
    """B 方案：6 个 openspec 技能已 vendored 为 zes-openspec-*，
    目录与 SKILL.md 齐备且 frontmatter name 已 zes- 化。"""
    root = Path(__file__).resolve().parent.parent / "vendor" / "skills"
    expected = ["zes-openspec-propose", "zes-openspec-update-change",
                "zes-openspec-apply-change", "zes-openspec-sync-specs",
                "zes-openspec-archive-change", "zes-openspec-explore"]
    for name in expected:
        d = root / name
        assert d.is_dir(), f"vendored 技能目录缺失：{name}"
        skill = d / "SKILL.md"
        assert skill.is_file(), f"SKILL.md 缺失：{name}"
        text = skill.read_text(encoding="utf-8")
        assert f"name: {name}" in text, f"{name} frontmatter name 未 zes- 化"


def test_vendored_openspec_无裸CLI命令():
    """vendored 技能的 SKILL.md 不再含裸 `openspec <子命令>`，
    全部改写为内置 openspec_engine.py 调用。只判定代码块内的裸命令，
    散文中的反引号引用（如"match what `openspec archive` does"）不算。"""
    root = Path(__file__).resolve().parent.parent / "vendor" / "skills"
    import re
    bare_cmd_re = re.compile(r'^openspec\s+\w+')
    for d in sorted(root.glob("zes-openspec-*")):
        text = (d / "SKILL.md").read_text(encoding="utf-8")
        assert "openspec_engine.py" in text, f"{d.name} 未适配内置引擎"
        in_fence = False
        for line in text.splitlines():
            s = line.strip()
            # 围栏代码块状态跟踪
            if s.startswith("```"):
                in_fence = not in_fence
                continue
            if not in_fence:
                continue
            # 代码块内：裸命令行（行首 openspec <子命令>）才判定
            s2 = s.lstrip("`>-* ")
            if re.match(r'^openspec\s+\w+', s2) and "[引擎无此命令]" not in s2:
                assert False, f"{d.name} 残留裸 CLI 命令：{s2}"


def test_workflow_json_引用zes_openspec():
    """config/workflow.json 的技能声明已 zes- 化，无旧 openspec-* 悬空引用。"""
    import json, re
    wf = json.loads((Path(__file__).resolve().parent.parent / "config" / "workflow.json").read_text(encoding="utf-8"))
    text = json.dumps(wf, ensure_ascii=False)
    stale = re.findall(r'"(openspec-(?:propose|update-change|apply-change|sync-specs|archive-change))"', text)
    assert not stale, f"workflow.json 残留旧技能声明：{stale}"
    for name in ["zes-openspec-propose", "zes-openspec-update-change",
                 "zes-openspec-apply-change", "zes-openspec-sync-specs",
                 "zes-openspec-archive-change"]:
        assert name in text, f"workflow.json 缺声明：{name}"
