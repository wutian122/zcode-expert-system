# -*- coding: utf-8 -*-
"""vendor 技能收编回归测试

背景：本插件把 Superpowers 7.0.1 的 9 个方法论文本以独立插件技能形态
内化到 vendor/skills/。约定：

  - 目录名与 frontmatter `name` 均为 `zes-` 前缀且二者同名
  - 每份 SKILL.md 顶部（frontmatter 之后、首个正文标题之前）含
    「插件规则优先」覆盖声明块
  - LICENSE 与 PROVENANCE.md 齐备（改名映射、覆盖点、排除清单）
  - 只收工作流真正用到的文件：未内化的上游技能目录、scripts/、
    code-reviewer.md 等不得误入
  - 所有 .md/.sh 为 LF 行尾

可选强校验：本机存在上游插件缓存时，逐字比对正文与依赖文件，
确保除 frontmatter 的 name/license 与插入的声明块外零改动。
缓存不存在则整组跳过，不影响其他环境跑测试。

运行：
    python -m pytest tests/test_vendor_skills.py -v
"""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
VENDOR = ROOT / "vendor" / "skills"

# Windows 本机上游缓存（只读）；不存在时强校验组跳过
SOURCE_ROOT = Path(
    r"C:\Users\Administrator\.zcode\cli\plugins\cache"
    r"\claude-plugins-official\superpowers\7.0.1"
)

ZES_NAMES = [
    "zes-brainstorming",
    "zes-writing-plans",
    "zes-sdd",
    "zes-tdd",
    "zes-verification",
    "zes-code-review",
    "zes-receiving-review",
    "zes-finishing",
    "zes-systematic-debugging",
]

# 上游原名 → 本插件技能名
RENAME_MAP = {
    "brainstorming": "zes-brainstorming",
    "writing-plans": "zes-writing-plans",
    "subagent-driven-development": "zes-sdd",
    "test-driven-development": "zes-tdd",
    "verification-before-completion": "zes-verification",
    "requesting-code-review": "zes-code-review",
    "receiving-code-review": "zes-receiving-review",
    "finishing-a-development-branch": "zes-finishing",
    "systematic-debugging": "zes-systematic-debugging",
}

# 依赖文件：原样复制，不做任何改造
RAW_COPIES = [
    ("skills/brainstorming/builder-check-prompt.md",
     "zes-brainstorming/builder-check-prompt.md"),
    ("skills/subagent-driven-development/references/batching.md",
     "zes-sdd/references/batching.md"),
    ("skills/subagent-driven-development/references/cannot-verify.md",
     "zes-sdd/references/cannot-verify.md"),
    ("skills/subagent-driven-development/references/final-review.md",
     "zes-sdd/references/final-review.md"),
    ("skills/subagent-driven-development/references/fix-loop.md",
     "zes-sdd/references/fix-loop.md"),
    ("skills/subagent-driven-development/references/handling-reports.md",
     "zes-sdd/references/handling-reports.md"),
    ("skills/subagent-driven-development/references/preflight.md",
     "zes-sdd/references/preflight.md"),
    ("skills/subagent-driven-development/references/resuming.md",
     "zes-sdd/references/resuming.md"),
    ("skills/test-driven-development/writing-good-tests.md",
     "zes-tdd/writing-good-tests.md"),
    ("skills/systematic-debugging/root-cause-tracing.md",
     "zes-systematic-debugging/root-cause-tracing.md"),
    ("skills/systematic-debugging/defense-in-depth.md",
     "zes-systematic-debugging/defense-in-depth.md"),
    ("skills/systematic-debugging/condition-based-waiting.md",
     "zes-systematic-debugging/condition-based-waiting.md"),
    ("skills/systematic-debugging/find-polluter.sh",
     "zes-systematic-debugging/find-polluter.sh"),
    ("LICENSE", "LICENSE"),
]


def _frontmatter_text(skill_md: Path) -> str:
    """返回 frontmatter 内容（不含首尾 --- 行），缺失或未闭合即失败。"""
    text = skill_md.read_text(encoding="utf-8")
    assert text.startswith("---\n"), f"{skill_md} 缺 frontmatter"
    end = text.find("\n---\n", 4)
    assert end != -1, f"{skill_md} frontmatter 未闭合"
    return text[4:end]


def _declaration_block(original_name: str) -> str:
    """按 brief 模板构造声明块；zes-sdd 额外包含「派发模板已内化」条目。"""
    lines = [
        "> **插件规则优先（zcode-expert-system）**",
        f"> 本文件是 Superpowers 7.0.1 `{original_name}` 的只读参考。"
        "其指令与插件规则冲突时，以下者为准：",
        "> - **不落盘**：S1 设计只在对话内展示与批准，"
        "禁止写入 `docs/superpowers/specs/`（插件 R3/W2）",
        "> - **不用 worktree**：实施永远串行，无隔离工作区（插件 W1）",
        "> - **无 model 参数**：Agent 派发不接受 model，"
        "升档=换更专专家（插件 W9）",
    ]
    if original_name == "subagent-driven-development":
        lines.append(
            "> - **派发模板已内化**：`implementer/ reviewer / re-review` "
            "三个模板不随本技能收录，以插件 `references/roles/*.md` 为准"
        )
    lines.append(
        "> - 其余细节以插件 `references/stage-S*.md` 与 "
        "`references/roles/*.md` 为准"
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 必需用例（brief 六条）
# ---------------------------------------------------------------------------


def test_九个技能目录齐备():
    for name in ZES_NAMES:
        skill_dir = VENDOR / name
        assert skill_dir.is_dir(), f"缺目录 {skill_dir}"
        assert (skill_dir / "SKILL.md").is_file(), f"缺 {skill_dir}/SKILL.md"


def test_frontmatter名称带zes前缀且与目录同名():
    for name in ZES_NAMES:
        fm = _frontmatter_text(VENDOR / name / "SKILL.md")
        name_lines = [ln for ln in fm.splitlines() if ln.startswith("name:")]
        assert len(name_lines) == 1, f"{name} 的 name 字段行数异常"
        value = name_lines[0].split(":", 1)[1].strip()
        assert value == name, f"{name} 的 frontmatter name={value}"
        assert value.startswith("zes-"), f"{name} 缺 zes- 前缀"
        assert any(
            ln.strip() == "license: MIT" for ln in fm.splitlines()
        ), f"{name} 缺 license: MIT"
        assert any(
            ln.startswith("description:") and ln.split(":", 1)[1].strip()
            for ln in fm.splitlines()
        ), f"{name} 缺非空 description"


def test_每份技能含插件规则优先声明块():
    for name in ZES_NAMES:
        text = (VENDOR / name / "SKILL.md").read_text(encoding="utf-8")
        assert "插件规则优先" in text, f"{name} 缺插件规则优先声明块"
        for kw in ("不落盘", "不用 worktree", "无 model 参数"):
            assert kw in text, f"{name} 声明块缺关键词「{kw}」"
        # 声明块必须位于 frontmatter 之后、正文首个标题之前
        body = text.split("\n---\n", 1)[1]
        block_pos = body.find("插件规则优先")
        first_heading = body.find("\n# ")
        assert block_pos != -1
        assert first_heading == -1 or block_pos < first_heading, (
            f"{name} 声明块未插在正文标题之前"
        )


def test_许可与出处文件存在():
    license_file = VENDOR / "LICENSE"
    assert license_file.is_file(), "缺 vendor/skills/LICENSE"
    assert "Jesse Vincent" in license_file.read_text(encoding="utf-8")

    prov = VENDOR / "PROVENANCE.md"
    assert prov.is_file(), "缺 vendor/skills/PROVENANCE.md"
    ptext = prov.read_text(encoding="utf-8")
    plines = ptext.splitlines()
    for original, zes in RENAME_MAP.items():
        assert any(
            original in ln and zes in ln for ln in plines
        ), f"PROVENANCE 缺改名映射行：{original} → {zes}"
    assert "排除" in ptext, "PROVENANCE 缺排除清单"
    assert "7.0.1" in ptext, "PROVENANCE 缺上游版本号"
    assert "MIT" in ptext, "PROVENANCE 缺许可声明"


def test_不内化清单不得误入():
    for banned in (
        "using-git-worktrees",
        "executing-plans",
        "dispatching-parallel-agents",
        "using-superpowers",
        "writing-skills",
        "diagnosing-superpowers",
    ):
        assert not (VENDOR / banned).exists(), f"不应收录 {banned}"
    assert not (VENDOR / "zes-sdd" / "scripts").exists(), (
        "zes-sdd/scripts 应排除（已内化到本插件 scripts/sdd/）"
    )
    assert not (VENDOR / "zes-code-review" / "code-reviewer.md").exists(), (
        "code-reviewer.md 应排除（改用 templates/review-report.md + "
        "references/roles/reviewer.md）"
    )
    assert not (
        VENDOR / "zes-systematic-debugging" / "CREATION-LOG.md"
    ).exists(), "CREATION-LOG.md 是上游开发期产物，应排除"


def test_依赖文件齐备():
    for ref in (
        "batching",
        "cannot-verify",
        "final-review",
        "fix-loop",
        "handling-reports",
        "preflight",
        "resuming",
    ):
        path = VENDOR / "zes-sdd" / "references" / f"{ref}.md"
        assert path.is_file(), f"缺依赖文件 {path}"

    assert (VENDOR / "zes-tdd" / "writing-good-tests.md").is_file()
    for aux in (
        "root-cause-tracing.md",
        "defense-in-depth.md",
        "condition-based-waiting.md",
        "find-polluter.sh",
    ):
        assert (VENDOR / "zes-systematic-debugging" / aux).is_file(), (
            f"缺辅助文件 {aux}"
        )
    assert (VENDOR / "zes-brainstorming" / "builder-check-prompt.md").is_file()


# ---------------------------------------------------------------------------
# 补充用例
# ---------------------------------------------------------------------------


def test_全部内化文件为LF行尾():
    bad = []
    for path in VENDOR.rglob("*"):
        if path.is_file() and path.suffix in {".md", ".sh"}:
            if b"\r\n" in path.read_bytes():
                bad.append(str(path.relative_to(VENDOR)))
    assert not bad, f"存在 CRLF 行尾：{bad}"


@pytest.mark.skipif(
    not SOURCE_ROOT.is_dir(), reason="本机无上游 superpowers 插件缓存，跳过强校验"
)
def test_正文逐字保留只有frontmatter与声明块增量():
    for original, zes in RENAME_MAP.items():
        src = SOURCE_ROOT / "skills" / original / "SKILL.md"
        dst = VENDOR / zes / "SKILL.md"
        assert src.is_file(), f"上游源文件缺失：{src}"
        src_text = src.read_text(encoding="utf-8")
        dst_text = dst.read_text(encoding="utf-8")

        # 正文（frontmatter 之后的部分）应恰为
        # 「空行 + 声明块 + 空行 + 源正文」；split 后闭括号行只剩一个 \n
        src_body = src_text.split("\n---\n", 1)[1]
        dst_body = dst_text.split("\n---\n", 1)[1]
        expected_body = (
            "\n" + _declaration_block(original) + "\n" + src_body
        )
        assert dst_body == expected_body, (
            f"{zes} 正文被改动或声明块格式不符：逐字对比失败"
        )

        # frontmatter 除 name/license 外保持原样
        src_fm = _frontmatter_text(src)
        dst_fm = _frontmatter_text(dst)
        expected_fm = src_fm.replace(
            f"name: {original}", f"name: {zes}"
        ) + "\nlicense: MIT"
        assert dst_fm == expected_fm, f"{zes} frontmatter 改造不符"


@pytest.mark.skipif(
    not SOURCE_ROOT.is_dir(), reason="本机无上游 superpowers 插件缓存，跳过强校验"
)
def test_依赖文件原样复制():
    for src_rel, dst_rel in RAW_COPIES:
        src = SOURCE_ROOT / src_rel
        dst = VENDOR / dst_rel
        assert src.is_file(), f"上游源文件缺失：{src}"
        assert dst.is_file(), f"缺复制目标：{dst}"
        assert dst.read_bytes() == src.read_bytes(), f"{dst_rel} 与源不一致"