#!/usr/bin/env python3
"""OpenSpec 引擎 —— 内置 CLI（前三个子命令：new-change / status / instructions）。

仅使用 Python 3 标准库（json/os/re/sys/argparse/datetime/pathlib），无第三方依赖。
.openspec.yaml 手写/手读简单键值对，不依赖第三方 YAML 库。
LF 行尾，pathlib 跨平台路径。
"""

import argparse
import json
import os
import re
import shutil
import sys
from datetime import date, datetime
from pathlib import Path

# 四件产物及其在 change 目录下的相对路径（按 OpenSpec/S2 规格）
PRODUCTS = {
    "proposal": "proposal.md",
    "design": "design.md",
    "tasks": "tasks.md",
    "specs": "specs",
}


def change_dir(root: Path, name: str) -> Path:
    # 库模式抛 ValueError（调用方自行处置）；6 个 CLI 入口捕获后转
    # 「error: ... + return 1」，进程退出码语义不变——勿在库函数里
    # sys.exit，那会以 SystemExit 炸宿主进程。
    if name == "archive":
        raise ValueError("'archive' is a reserved container name, not a change")
    return root / "openspec" / "changes" / name


def write_metadata(cdir: Path, name: str) -> None:
    """手写 .openspec.yaml，简单键值对，LF 行尾。"""
    lines = [
        "schema: spec-driven",
        f"name: {name}",
        f"created: {date.today().isoformat()}",
        "status: pending",
    ]
    (cdir / ".openspec.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_status(cdir: Path, status: dict) -> None:
    """手写 .status.json，简单 JSON，LF 行尾。"""
    (cdir / ".status.json").write_text(
        json.dumps(status, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def cmd_new_change(args) -> int:
    root = Path(args.root).resolve()
    try:
        cdir = change_dir(root, args.name)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if cdir.exists():
        print(f"error: change already exists: {cdir}", file=sys.stderr)
        return 1
    cdir.mkdir(parents=True, exist_ok=True)
    (cdir / "specs").mkdir(exist_ok=True)
    write_metadata(cdir, args.name)
    write_status(cdir, {
        "tasksCompleted": False,
        "specsConsistent": False,
        "testsPassed": False,
        "reviewPassed": False,
        "noBlockers": True,
        "gitStatusOk": True,
        "docsUpdated": True,
        "parked": False,
    })
    print(f"change created: {cdir}")
    return 0


def product_state(cdir: Path, product: str) -> str:
    """状态只判文件是否存在（OpenSpec：status 只判文件存在，别被 done 误导）。"""
    rel = PRODUCTS[product]
    target = cdir / rel
    if product == "specs":
        # 空的 specs/ 子目录不算产物就绪；只有包含具体 spec 时才为 done
        return "done" if (target.is_dir() and any(target.iterdir())) else "pending"
    return "done" if target.is_file() else "pending"


def cmd_status(args) -> int:
    root = Path(args.root).resolve()
    try:
        cdir = change_dir(root, args.change)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if not cdir.exists():
        print(f"error: change not found: {cdir}", file=sys.stderr)
        return 1
    products = {name: product_state(cdir, name) for name in PRODUCTS}
    result = {
        "change": args.change,
        "status": "pending",
        "products": products,
        "applyRequires": [],
        "requires": [],
        "artifactPaths": {},
    }
    # 从 .openspec.yaml 读取 requires 元数据（如果存在）
    meta_path = cdir / ".openspec.yaml"
    if meta_path.is_file():
        try:
            meta_text = meta_path.read_text(encoding="utf-8")
            meta = {}
            for line in meta_text.splitlines():
                line = line.strip()
                if ":" in line:
                    k, v = line.split(":", 1)
                    meta[k.strip()] = v.strip()
            requires_raw = meta.get("requires", "")
            if requires_raw:
                result["requires"] = [r.strip() for r in requires_raw.split(",") if r.strip()]
            apply_requires_raw = meta.get("applyRequires", "")
            if apply_requires_raw:
                result["applyRequires"] = [r.strip() for r in apply_requires_raw.split(",") if r.strip()]
        except OSError:
            pass
    # artifactPaths：从当前 change 的 artifacts 目录构造（如果存在）
    artifacts_dir = cdir / "artifacts"
    if artifacts_dir.is_dir():
        artifact_paths = {}
        for entry in sorted(artifacts_dir.iterdir()):
            if entry.is_file():
                artifact_paths[entry.name] = str(entry.resolve())
        result["artifactPaths"] = artifact_paths
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_instructions(args) -> int:
    root = Path(args.root).resolve()
    try:
        cdir = change_dir(root, args.change)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if not cdir.exists():
        print(f"error: change not found: {cdir}", file=sys.stderr)
        return 1
    # apply 不是四件产物，而是实施模式入口（AGENTS.md：「instructions apply 取
    # contextFiles/动态指令与 progress」）。返回实施上下文来源，不校验产物存在。
    if args.id == "apply":
        tasks_path = cdir / "tasks.md"
        specs_dir = cdir / "specs"
        result = {
            "template": "apply",
            "resolvedOutputPath": str(tasks_path),
            "required": False,
            "exists": tasks_path.is_file(),
            "contextFiles": [str(tasks_path)] if tasks_path.is_file() else [],
            "specsDir": str(specs_dir),
            "note": "实施模式：按 tasks.md 逐任务最小改动并立即勾选；无计划文档、"
                    "不建 progress.md、账本即 tasks.md 勾选",
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.id not in PRODUCTS:
        print(f"error: unknown product id: {args.id}", file=sys.stderr)
        return 1
    rel = PRODUCTS[args.id]
    target = cdir / rel
    exists = target.is_dir() if args.id == "specs" else target.is_file()
    result = {
        "template": args.id,
        "resolvedOutputPath": str(target),
        "required": True,
        "exists": exists,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def _split_sections(text: str):
    """按 ## 标题切分 Markdown，返回 [(header 或 None, [lines], ...)]。
    仅做行级/段落级判断，不依赖第三方 Markdown 库。"""
    sections = []
    cur_header = None
    cur_lines = []
    for line in text.split("\n"):
        if line.startswith("## "):
            sections.append((cur_header, cur_lines))
            cur_header = line[2:].strip()
            cur_lines = []
        else:
            cur_lines.append(line)
    sections.append((cur_header, cur_lines))
    return sections


def _section_lines(sections, header):
    for h, lines in sections:
        if h == header:
            return list(lines)
    return []


def _has_purpose(sections) -> bool:
    lines = _section_lines(sections, "Purpose")
    return any(l.strip() for l in lines)


def cmd_validate_change(args) -> int:
    """validate --change <name>：检查四件产物是否完整，输出 JSON，rc=0 无论 valid 与否。"""
    root = Path(args.root).resolve()
    try:
        cdir = change_dir(root, args.change)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if not cdir.exists():
        print(f"error: change not found: {cdir}", file=sys.stderr)
        return 1
    missing = []
    for fname in ("proposal.md", "design.md", "tasks.md"):
        if not (cdir / fname).is_file():
            missing.append(fname)
    specs_dir = cdir / "specs"
    spec_found = False
    if specs_dir.is_dir():
        for entry in specs_dir.iterdir():
            if entry.is_dir() and (entry / "spec.md").is_file():
                spec_found = True
                break
    if not spec_found:
        missing.append("specs/spec.md")
    valid = len(missing) == 0
    print(json.dumps({"change": args.change, "valid": valid, "missing": missing},
                     ensure_ascii=False, indent=2))
    return 0


def _find_change_spec(cdir: Path):
    """在 change 目录下找 specs 产物：返回 (capability, spec_path)。找不到返回 (None, None)。"""
    specs_dir = cdir / "specs"
    if not specs_dir.is_dir():
        return None, None
    for entry in sorted(specs_dir.iterdir()):
        if entry.is_dir() and (entry / "spec.md").is_file():
            return entry.name, entry / "spec.md"
    return None, None


def _merge_delta_into_main(main_text: str, delta_text: str) -> str:
    """把 delta spec 合并进主 spec（行级/段落级规则）。

    规则：
    - 主 spec 的 ## Purpose 权威不动（不被 delta 覆盖）。
    - ## Requirements：保留主 spec 既有场景，追加 delta 未提及的新场景（去重）。
    - ## ADDED / ## MODIFIED / ## REMOVED / ## RENAMED：按段落原文合并记录。
    - 其他未知段落：新增则追加，已存在则并入。
    """
    main_secs = _split_sections(main_text or "")
    delta_secs = _split_sections(delta_text)

    main_by_header = {}
    main_order = []
    leading = []
    for h, lines in main_secs:
        if h is None:
            leading = list(lines)
            continue
        if h not in main_by_header:
            main_by_header[h] = []
            main_order.append(h)
        main_by_header[h].extend(lines)

    result = {h: list(lines) for h, lines in main_by_header.items()}
    result_order = list(main_order)

    def _ensure(header):
        if header not in result:
            result[header] = []
            result_order.append(header)
        return result[header]

    for h, lines in delta_secs:
        if h is None:
            continue
        if h == "Purpose":
            # 主 spec Purpose 权威不动
            continue
        if h == "Requirements":
            dst = _ensure("Requirements")
            for line in lines:
                s = line.strip()
                if s and s not in dst:
                    dst.append(s)
        elif h.startswith("ADDED"):
            dst = _ensure(h)
            dst.extend(lines)
        elif h.startswith("MODIFIED"):
            dst = _ensure(h)
            dst.extend(lines)
        elif h.startswith("REMOVED"):
            # P2-1（老板批准 2026-11-18）：REMOVED 整块移除（stage-S8:29/125）。
            # delta 中 REMOVED 段落列出的条目从主 spec 的 Requirements 中移除；
            # REMOVED 段本身不写入主 spec（归档复验要求「REMOVED 消失」）。
            # 旧实现 dst.extend(lines) 把 REMOVED 连同条目一起追加——语义相反。
            dst = result.get("Requirements")
            if dst is not None:
                removed = {line.strip() for line in lines if line.strip()}
                dst[:] = [ln for ln in dst if ln.strip() not in removed]
        elif h.startswith("RENAMED"):
            dst = _ensure(h)
            dst.extend(lines)
        else:
            if h not in result:
                result[h] = list(lines)
                result_order.append(h)
            else:
                result[h].extend(lines)

    out = []
    if leading:
        out.extend(leading)
    for h in result_order:
        out.append(f"## {h}")
        out.extend(result[h])
    return "\n".join(out).rstrip("\n") + "\n"


def cmd_sync_specs_change(args) -> int:
    """sync-specs --change <name>：delta 合并进主 spec，输出 JSON，rc=0。

    P0-2 安全契约：--dry-run 只计算不写入；正常执行时对主 spec 做
    .bak-<ts> 备份后再覆盖，保证合并出错可回滚。
    """
    root = Path(args.root).resolve()
    try:
        cdir = change_dir(root, args.change)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if not cdir.exists():
        print(f"error: change not found: {cdir}", file=sys.stderr)
        return 1
    capability, delta_path = _find_change_spec(cdir)
    if capability is None or delta_path is None:
        print(f"error: specs product not found in change: {cdir}", file=sys.stderr)
        return 1
    main_dir = root / "openspec" / "specs" / capability
    main_dir.mkdir(parents=True, exist_ok=True)
    main_path = main_dir / "spec.md"
    main_text = main_path.read_text(encoding="utf-8") if main_path.is_file() else ""
    delta_text = delta_path.read_text(encoding="utf-8")
    merged = _merge_delta_into_main(main_text, delta_text)

    if args.dry_run:
        print(json.dumps({
            "change": args.change,
            "capability": capability,
            "dry_run": True,
            "target": str(main_path),
        }, ensure_ascii=False, indent=2))
        return 0

    # 备份主 spec（.bak-<ts>，同一目录下），覆盖写入前保留回滚点
    backup_path = None
    if main_path.is_file():
        ts = datetime.now().strftime("%Y%m%d-%H%M%S%f")
        backup_path = main_path.with_name(f"{main_path.name}.bak-{ts}")
        backup_path.write_text(main_text, encoding="utf-8")
    main_path.write_text(merged, encoding="utf-8")
    print(json.dumps({
        "change": args.change,
        "capability": capability,
        "merged": True,
        "target": str(main_path),
        "backup": str(backup_path) if backup_path else None,
    }, ensure_ascii=False, indent=2))
    return 0


def _status_flag(status: dict, *keys) -> bool:
    for k in keys:
        if k in status and status[k]:
            return True
    return False


def cmd_archive_change(args) -> int:
    """archive-change <name>：七条件逐条检查后归档到 archive/YYYY-MM-DD-<change>。

    P0-3 安全契约：--dry-run 只校验不移动；正常归档前对变更目录做
    .bak-<ts> 备份，移动成功后清理备份（成功才清，失败保留供回滚）。
    """
    root = Path(args.root).resolve()
    try:
        cdir = change_dir(root, args.name)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if not cdir.exists():
        print(f"error: change not found: {cdir}", file=sys.stderr)
        return 1
    status_path = cdir / ".status.json"
    if not status_path.is_file():
        print(f"error: .status.json not found, archive blocked: {cdir}", file=sys.stderr)
        return 1
    try:
        status = json.loads(status_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        print(f"error: .status.json invalid: {exc}", file=sys.stderr)
        return 1

    # W8：存在 PARKED 任务，默认禁止归档
    if _status_flag(status, "parked", "PARKED"):
        print(f"error: PARKED tasks present, archive prohibited (W8): {cdir}", file=sys.stderr)
        return 1

    required = [
        ("tasksCompleted", "tasks_completed", "所有必须完成的任务已完成"),
        ("specsConsistent", "specs_consistent", "规格与实现一致"),
        ("testsPassed", "tests_passed", "测试验证通过"),
        ("reviewPassed", "review_passed", "代码审查通过"),
        ("noBlockers", "no_blockers", "无未解决阻断问题"),
        ("gitStatusOk", "git_status_ok", "Git 状态符合要求"),
        ("docsUpdated", "docs_updated", "必要文档已更新"),
    ]
    failed = [label for camel, snake, label in required
              if not _status_flag(status, camel, snake)]
    if failed:
        print(f"error: archive conditions not met: {', '.join(failed)}", file=sys.stderr)
        return 1

    # 变更目录只允许标准产物（含引擎元数据与 artifacts）；插件运行时残留
    # （如 .mimosa）混入时拒绝归档——备份在归档成功后即删，无清理兜底
    allowed = {"proposal.md", "design.md", "tasks.md", "specs",
               ".openspec.yaml", ".status.json", "artifacts"}
    extras = sorted(e.name for e in cdir.iterdir() if e.name not in allowed)
    if extras:
        print(f"error: non-standard entries in change dir, archive blocked: "
              f"{', '.join(extras)}: {cdir}", file=sys.stderr)
        return 1

    archive_root = root / "openspec" / "changes" / "archive"
    archive_root.mkdir(parents=True, exist_ok=True)
    target = archive_root / f"{date.today().isoformat()}-{args.name}"
    if target.exists():
        print(f"error: archive target already exists: {target}", file=sys.stderr)
        return 1

    if args.dry_run:
        print(json.dumps({
            "change": args.name,
            "dry_run": True,
            "target": str(target),
        }, ensure_ascii=False, indent=2))
        return 0

    # 备份变更目录（.bak-<ts>），作为移动操作的回滚点
    ts = datetime.now().strftime("%Y%m%d-%H%M%S%f")
    backup_dir = cdir.with_name(f"{cdir.name}.bak-{ts}")
    shutil.copytree(str(cdir), str(backup_dir))

    # 归档前把元数据 status 更新为 archived（备份在前，替换失误可从 .bak 回滚）
    meta_path = cdir / ".openspec.yaml"
    if meta_path.is_file():
        text = meta_path.read_text(encoding="utf-8")
        updated = re.sub(r"^status:.*$", "status: archived",
                         text, count=1, flags=re.MULTILINE)
        if updated != text:
            meta_path.write_text(updated, encoding="utf-8")

    try:
        shutil.move(str(cdir), str(target))
    except OSError as exc:
        # 移动失败：保留备份，便于回滚（不静默失败）
        print(f"error: archive move failed: {exc}", file=sys.stderr)
        return 1

    # 移动成功：清理备份（成功才清）
    shutil.rmtree(str(backup_dir))

    print(json.dumps({
        "change": args.name,
        "archived": True,
        "target": str(target),
    }, ensure_ascii=False, indent=2))
    return 0


def cmd_validate_specs(args) -> int:
    """validate-specs：验证 openspec/specs/ 下所有 spec.md（Purpose 非空、退役不留空 Requirements）。"""
    root = Path(args.root).resolve()
    specs_root = root / "openspec" / "specs"
    issues = []
    if specs_root.is_dir():
        for cap_dir in sorted(specs_root.iterdir()):
            if not cap_dir.is_dir():
                continue
            spec_path = cap_dir / "spec.md"
            if not spec_path.is_file():
                continue
            capability = cap_dir.name
            text = spec_path.read_text(encoding="utf-8")
            sections = _split_sections(text)
            if not _has_purpose(sections):
                issues.append(f"{capability}: 缺少非空的 ## Purpose")
            # 能力退役：文中出现 退役/retired 时，## Requirements 不得为空
            is_retired = ("退役" in text) or ("retired" in text.lower())
            if is_retired:
                req_lines = _section_lines(sections, "Requirements")
                if not any(l.strip() for l in req_lines):
                    issues.append(f"{capability}: 已退役但 ## Requirements 为空")
    valid = len(issues) == 0
    print(json.dumps({"valid": valid, "issues": issues}, ensure_ascii=False, indent=2))
    return 0


def cmd_list_changes(args) -> int:
    """list --root <根>：列出所有 change 目录及其状态，输出 JSON，rc=0。
    
    输出：
    {
        "changes": [
            {"name": "add-user-auth", "path": "...", "status": "pending", "products": {...}},
            ...
        ],
        "root": "<根目录绝对路径>"
    }
    """
    # --root 缺省（None）时 fallback 到 cwd，与父 --root 语义一致。
    # 旧实现直接 Path(None).resolve() 崩溃（list 必崩）。
    root = Path(getattr(args, "root", os.getcwd()) or os.getcwd()).resolve()
    changes_dir = root / "openspec" / "changes"
    changes = []
    if changes_dir.is_dir():
        for entry in sorted(changes_dir.iterdir()):
            if not entry.is_dir():
                continue
            # P1-2：archive/ 是归档容器而非 pending 变更，跳过（对齐官方 openspec 口径）
            if entry.name == 'archive':
                continue
            cdir = entry
            # 读取元数据，兼容无 .openspec.yaml 的旧 change
            meta_path = cdir / ".openspec.yaml"
            name = entry.name
            status = "pending"
            if meta_path.is_file():
                try:
                    for line in meta_path.read_text(encoding="utf-8").splitlines():
                        line = line.strip()
                        if line.startswith("status:"):
                            status = line.split(":", 1)[1].strip()
                            break
                except OSError:
                    pass
            # products 状态
            products = {name_: product_state(cdir, name_) for name_ in PRODUCTS}
            changes.append({
                "name": name,
                "path": str(cdir),
                "status": status,
                "products": products,
            })
    print(json.dumps({
        "changes": changes,
        "root": str(root),
        "openspec": changes_dir.is_dir(),
    }, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="openspec_engine.py")
    parser.add_argument("--root", default=os.getcwd(), help="仓库根目录（默认 cwd）")
    sub = parser.add_subparsers(dest="command", required=True)

    p_new = sub.add_parser("new-change", help="创建 change 目录 + 元数据文件")
    p_new.add_argument("name", help="change 名（kebab-case）")
    p_new.set_defaults(func=cmd_new_change)

    p_status = sub.add_parser("status", help="读取变更状态")
    p_status.add_argument("--change", required=True, help="change 名")
    p_status.set_defaults(func=cmd_status)

    p_instr = sub.add_parser("instructions", help="读取产物模板 + resolvedOutputPath")
    p_instr.add_argument("id", help="产物 id（proposal/design/tasks/specs）")
    p_instr.add_argument("--change", required=True, help="change 名")
    p_instr.set_defaults(func=cmd_instructions)

    p_validate = sub.add_parser("validate", help="验证 change 四件产物完整")
    p_validate.add_argument("--change", required=True, help="change 名")
    p_validate.set_defaults(func=cmd_validate_change)

    p_sync = sub.add_parser("sync-specs", help="delta 合并进主 spec")
    p_sync.add_argument("--change", required=True, help="change 名")
    p_sync.add_argument("--dry-run", action="store_true",
                        help="只计算合并结果，不写主 spec、不产生备份")
    p_sync.set_defaults(func=cmd_sync_specs_change)

    p_archive = sub.add_parser("archive-change", help="归档 change")
    p_archive.add_argument("name", help="change 名")
    p_archive.add_argument("--dry-run", action="store_true",
                           help="只校验七条件、目录标准性与目标路径，不移动、不备份")
    p_archive.set_defaults(func=cmd_archive_change)

    p_validatespecs = sub.add_parser("validate-specs", help="验证主 spec")
    p_validatespecs.set_defaults(func=cmd_validate_specs)

    p_list = sub.add_parser("list", help="列出所有 change 及其状态")
    # P3-6：default=argparse.SUPPRESS，子命令未传 --root 时不覆盖顶层已设值
    # （旧 default=None 会把顶层 --root 静默覆盖为 None，回落 cwd）。
    # 显式传 `list --root X` 时仍生效；两者都不传时由 cmd_list_changes 用 getattr 兜底 cwd。
    p_list.add_argument("--root", default=argparse.SUPPRESS,
                        help="仓库根目录（优先于顶层 --root；缺省用顶层 --root 或 cwd）")
    p_list.set_defaults(func=cmd_list_changes)

    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
