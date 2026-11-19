"""commands/wf/*.md 命令文件 frontmatter 规范测试（F2）。

12 个 /wf:* 命令的 YAML frontmatter 必须含 name 字段（值 = wf-<文件名主干>），
对照 opsx 命令规范（name + description）。ZCode 以文件名派生命令名，缺 name
不影响调用，但属规范对齐。
"""

import re
from pathlib import Path

import pytest

COMMANDS_DIR = Path(__file__).resolve().parent.parent / "commands" / "wf"


def _command_files():
    files = sorted(COMMANDS_DIR.glob("*.md"))
    assert files, f"未找到命令文件：{COMMANDS_DIR}"
    return files


@pytest.mark.parametrize("path", _command_files(), ids=lambda p: p.stem)
def test_wf命令frontmatter含name(path):
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), f"{path.name} 未以 YAML frontmatter 开头"
    end = text.find("\n---", 4)
    assert end > 0, f"{path.name} frontmatter 未闭合"
    frontmatter = text[4:end]
    m = re.search(r"^name:\s*(.+)$", frontmatter, re.MULTILINE)
    assert m, f"{path.name} frontmatter 缺 name 字段"
    assert m.group(1).strip() == f"wf-{path.stem}", (
        f"{path.name} name 应为 wf-{path.stem}，实际 {m.group(1).strip()}"
    )


@pytest.mark.parametrize("path", _command_files(), ids=lambda p: p.stem)
def test_wf命令frontmatter含description(path):
    text = path.read_text(encoding="utf-8")
    end = text.find("\n---", 4)
    frontmatter = text[4:end]
    assert re.search(r"^description:\s*\S", frontmatter, re.MULTILINE), (
        f"{path.name} frontmatter 缺 description"
    )