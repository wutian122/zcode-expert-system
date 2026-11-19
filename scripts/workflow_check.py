#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
工作流阶段完整性核对（机械可验）

设计原则：**纯 Markdown 检查表一定会被跳过，必须机械可验。**
本脚本只做机器能判定的部分——文件存在性、计数对齐、占位符扫描、
账本身份、状态-勾选一致性、delta 来源。语义质量（评审是否到位、
根因是否真到位）不由脚本判定，交角色契约与主控。

唯一声明源：config/workflow.json（阶段/门禁/产物/证据级）。
本脚本不内嵌任何阶段常量，避免文档与实现漂移。

用法：
    python scripts/workflow_check.py --change <change> [--plan <plan.md>] [--scale medium]
    python scripts/workflow_check.py --change <change> --json

退出码：
    0  全部通过
    1  有 FAIL 项
    2  参数/环境错误
"""

import argparse
import io
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKFLOW_PATH = os.path.join(BASE_DIR, "config", "workflow.json")

OK = "OK"
WARN = "WARN"
FAIL = "FAIL"
SKIP = "SKIP"


def _force_utf8_stdout():
    """让 stdout/stderr 用 UTF-8 输出，避免非 UTF-8 控制台抛 UnicodeEncodeError。

    背景（缺陷 #3 同族，P8 批次二补齐）：中文 Windows 默认代码页 CP936 编不了
    emoji 与 ✅/❌，而本工具的输出会携带账本/计划/路径的内容片段
    （`项目根：%s` 打印、S4.LEDGER_ID 的首行摘要、--json 的
    `ensure_ascii=False`），在 CP936 终端会 UnicodeEncodeError →
    未捕获 traceback、rc=1——门禁工具自己先炸。四个 CLI 入口中本文件
    是最后一个补齐的（另三个见各自同名函数）。

    只挂 main()（CLI 入口），不挂 run()：库调用方不应被改变 stdio 行为。
    不改 ensure_ascii（会把中文与 emoji 全转成 \\uXXXX，破坏可读性与下游断言）；
    errors="replace" 仅作重配失败时的兜底，不得当主手段（emoji 变 ? 是数据损坏）。
    """
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


# ---------------------------------------------------------------------------
# 理由码字典（固定，供测试断言；替代中文字面匹配）
#
# 设计意图：SKIP 只剩一个合法含义——「按声明这项本来就不该查」。
# 其余一切「没查成」都是 FAIL。这条规则由 Report.enforce_reasons() 机械执行，
# 所以未来新增的检查项自动继承，不需要靠 review 抓。
#
# 理由码前缀决定状态是否合法：
#   inapplicable: → SKIP 唯一合法前缀（这项不该查）
#   soft:         → WARN 唯一合法前缀（此刻不必成立，将来才成立）
#   unverifiable: / malformed: / missing: → 必须配 FAIL（查不了 / 格式错 / 应存在而缺）
# ---------------------------------------------------------------------------

REASON_INAPPLICABLE = "inapplicable"
REASON_SOFT = "soft"
REASON_UNVERIFIABLE = "unverifiable"
REASON_MALFORMED = "malformed"
REASON_MISSING = "missing"

VALID_SKIP_PREFIXES = (REASON_INAPPLICABLE + ":",)
VALID_WARN_PREFIXES = (REASON_SOFT + ":",)


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------

def load_workflow():
    with io.open(WORKFLOW_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


class Report(object):
    def __init__(self):
        self.items = []

    def add(self, gate, check, status, detail="", id=None, reason=None):
        self.items.append({
            "gate": gate, "check": check, "status": status,
            "detail": detail, "id": id, "reason": reason})

    def count(self, status):
        return sum(1 for i in self.items if i["status"] == status)

    def has_fail(self):
        return self.count(FAIL) > 0

    def enforce_reasons(self):
        """INV-R2：状态与理由码必须匹配，否则机械改判 FAIL。

        两件事在这里自动完成，不依赖各检查器自觉：

        1. SKIP 而理由码不以 `inapplicable:` 开头 → 改判 FAIL。
           这是把「拿 SKIP 当放过」在架构上堵死：一处新的 `return SKIP`
           即使忘了写理由，也不会变成假绿。
        2. WARN 而理由码不以 `soft:` 开头 → 改判 FAIL。
           WARN 只允许表达「此刻不必成立」，不允许表达「查不了」。
        """
        for item in self.items:
            reason = item["reason"] or ""
            if item["status"] == SKIP and not reason.startswith(VALID_SKIP_PREFIXES):
                item["status"] = FAIL
                item["reason"] = "inapplicable:invalid"
                item["detail"] = ("[inapplicable:invalid] SKIP 缺少合法理由码"
                                  "（应写明「为何不该查」）；原 detail: " + (item["detail"] or ""))
            elif item["status"] == WARN and not reason.startswith(VALID_WARN_PREFIXES):
                item["status"] = FAIL
                item["reason"] = "malformed:soft_reason"
                item["detail"] = ("[malformed:soft_reason] WARN 只用于「此刻不必成立」，"
                                  "查不了/格式错必须判 FAIL；原 detail: "
                                  + (item["detail"] or ""))

    def render(self):
        lines = []
        cur = None
        for i in self.items:
            if i["gate"] != cur:
                cur = i["gate"]
                lines.append("")
                lines.append("【%s】" % cur)
            mark = {OK: "[ OK ]", WARN: "[WARN]", FAIL: "[FAIL]", SKIP: "[SKIP]"}[i["status"]]
            line = "  %s %s" % (mark, i["check"])
            if i["detail"]:
                line += " —— %s" % i["detail"]
            lines.append(line)
        lines.append("")
        lines.append("汇总：OK %d / WARN %d / FAIL %d / SKIP %d" % (
            self.count(OK), self.count(WARN), self.count(FAIL), self.count(SKIP)))
        return "\n".join(lines)


def read(path):
    """读取文本文件。

    **用 `utf-8-sig` 而非 `utf-8`**（P6 复核审查 A-1 的核心修复）：
    BOM（U+FEFF）在 `utf-8` 下会作为普通字符保留在字符串开头，而
    Python 的 `\\s` 不匹配 U+FEFF、JavaScript 的 `\\s` 匹配 —— 同一行
    在检查器里不算任务、在 OpenSpec 真相源里算任务。

    后果是**假绿**：带 BOM 的 tasks.md 若首行未完成，该行从分子分母
    同时消失（done==total），归档门禁通过；而 `openspec archive` 会按
    真实计数拒绝。Windows 记事本与多数编辑器默认存 UTF-8 with BOM。

    `utf-8-sig` 对不含 BOM 的文件行为与 `utf-8` 完全一致，
    含 BOM 时自动剥掉开头那一个。
    """
    try:
        with io.open(path, "r", encoding="utf-8-sig") as f:
            return f.read()
    except (OSError, UnicodeDecodeError):
        return None


# ---------------------------------------------------------------------------
# tasks.md 勾选解析
#
# 正则直接镜像 OpenSpec 自己的解析器（真相源）：
#   node_modules/@fission-ai/openspec/dist/utils/task-progress.js
# 其注释逐条记录了本类漏洞：只认 `-` 会漏掉 `*`/`+`/`1.` 的任务；
# 锚定列 0 会漏掉嵌套子任务；只认 `[ ]`/`[x]` 会让 `[~]` 缩小分母
# （即「写 [~] 反而让完成度看起来更高」）。这里逐条对齐，避免与真相源漂移。
#
# 关键细节：闭括号后不得紧跟 `(` 或 `[`——那是 Markdown 链接语法
#   （`- [Some doc](./d.md)`），否则每个链接列表都会变成一堆「未完成任务」。
#
# 两处与 JS 真相源的刻意对齐（P6 复核审查发现）：
#   1. `\ufeff?` 前置 —— 即使 read() 已用 utf-8-sig，这里再兜一层：
#      任何来源（含用户手工传入的字符串）带 BOM 都不该让首行任务消失。
#   2. `\d` 全部改成 `[0-9]` —— Python 的 `\d` 是 Unicode 感知的
#      （匹配全角 `１`），JS 的只认 ASCII。不换会导致中文文档里的
#      全角编号在检查器算任务、在真相源不算，分母虚增。
# ---------------------------------------------------------------------------

_TASK_LINE_PATTERN = re.compile(
    r"^\ufeff?\s*(?:[-*+]|[0-9]{1,9}[.)])\s*\[(?:\s*([^\]\s]?)\s*\](?![([])|\s+\])\s*(.*)")


def parse_task_lines(text):
    """逐行解析勾选框，返回 [(done_bool, description), ...]（文档序）。

    每一条匹配到的行都计入，不论它是否在代码围栏/HTML 注释里——
    这是 OpenSpec 的取舍：把示例误当任务是可纠正的假阳性（响），
    而丢掉真实任务是静默的假阴性（不响）。
    """
    out = []
    for line in (text or "").splitlines():
        m = _TASK_LINE_PATTERN.match(line)
        if m:
            mark = (m.group(1) or "").lower()
            out.append((mark == "x", (m.group(2) or "").strip()))
    return out


def count_checkboxes(text):
    """统计 tasks.md 的勾选。只有 x/X 算完成（OpenSpec 归档口径）。

    返回 done/todo/other 三项，且恒有 done + todo + other == 总任务行数。
    口径：空框 [] 算 todo；仅 x/X 算 done（[ x ] 带空格同样算 x，与官方
    task-progress.js 口径一致）；其余非空非 x（[~]/[1] 等）算 other。
    单独分出 other 只为诊断信息更具体（异形标记 vs 空框），不影响完成判定。
    """
    done = todo = other = 0
    for line in (text or "").splitlines():
        m = _TASK_LINE_PATTERN.match(line)
        if not m:
            continue
        mark = (m.group(1) or "").lower()
        if mark == "x":
            done += 1
        elif mark == "":
            todo += 1
        else:
            other += 1
    return {"done": done, "todo": todo, "other": other}


def detect_bullet_styles(text):
    """诊断用：报告 tasks.md 里实际出现过哪些列表符，供 malformed 时提示用户。"""
    styles = []
    for line in (text or "").splitlines():
        m = re.match(r"^\s*([-*+]|\d{1,9}[.)])\s*\[", line)
        if m and m.group(1) not in styles:
            styles.append(m.group(1))
    return styles


# ---------------------------------------------------------------------------
# 段名精确匹配
#
# 修的不是「正则写错」，而是「把前缀匹配当前缀匹配用」：
# `^#+\s*Review` 会命中 `## Review Focus`，于是 S3 的计划必备段
# `## Review Focus` 冒充了 S6 的审查结论段 `## Review`；
# `Spec` 会命中 `## Specification`，架构段会命中 `## Architecture Notes`。
# 必备段检查因此形同虚设——任何段只要「以必备段名开头」就算写了。
# ---------------------------------------------------------------------------

def _section_re(name):
    """精确段名：允许行尾括注（`## Review（审查结论）`），禁止前缀吞并。"""
    return re.compile(
        r"^#{1,6}[ \t]+%s[ \t]*(?:[（(:：][^\n]*)?$" % re.escape(name),
        re.M | re.I)


def strip_code_fences(text):
    """剥离 ``` 围栏块：模板里的示例段不得充当真实证据。"""
    if not text:
        return ""
    return re.sub(r"^[ \t]*```.*?^[ \t]*```[ \t]*$", "", text, flags=re.M | re.S)


def has_section(text, name):
    """计划/账本里是否存在名为 name 的段（精确匹配，忽略围栏块内的示例）。"""
    return _section_re(name).search(strip_code_fences(text)) is not None


def section_body(text, name, keep_fences=False):
    """取某段正文（到下一个同级或更高级标题为止）。找不到返回 None。

    keep_fences=False（默认）会剥离 ``` 围栏块——用于「段存在性」判断，
    防模板示例冒充真实段落。

    keep_fences=True 保留围栏内容——用于「段内结论载体」判断。
    理由：`templates/plan-sections.md` 规定 `## Review` 的内容就写在
    ```markdown 围栏里（那是填写位）；若这里也剥掉，模板照抄的文档
    永远被判「段存在但无结论」，而它其实填得好好的。
    实测症状：本计划文档正确写了 spec/quality，却被判 soft:review_section_empty。
    """
    clean = text if keep_fences else strip_code_fences(text)
    m = _section_re(name).search(clean)
    if not m:
        return None
    start = m.end()
    level = len(re.match(r"#+", clean[m.start():]).group(0))
    rest = clean[start:]
    stop = re.search(r"^#{1,%d}[ \t]+\S" % level, rest, re.M)
    return rest[:stop.start()] if stop else rest


def strip_quoted_markers(text):
    """剥离「文档里引用的示例」再找标记，避免把说明文字当成真实结论。

    真实场景（本计划文档自身就踩到）：计划文档会写
    「修前：`independence: L0 设想` + `independence: L2` → 判 L0」这类**引用**。
    取最坏值策略下，这些引用会被当成真实标记，
    于是「正确记录了修复内容」的文档反而被判 L2 禁止交付——
    这正是「过度收紧造成假红」的典型形态。

    **剥什么、留什么**（A-6 修复后）：

      剥掉：
        - 行内代码 `` `...` `` 的内容 —— 引用与模板示例都在其中
        - **无键名**的表格行 —— 纯数据对照表（如「| L0 | 独立审查 |」），
          那不是结论，只是级别说明

      保留：
        - **含键名**的表格行 —— 例如 `| independence | L0 |`
          表格是本项目模板的主推排版（Baseline、Integration Verification、
          Triage 全是表格）。整行丢弃会让「用表格填标记」被判缺标记（假红），
          而它对 L0 和 L2 的错法还不一致——L2 本该 FAIL 却变成「缺标记」。

    判据是「行内有没有出现被找的那个键名」。这里不硬编码键名列表，
    而是把整行保留、由调用方的正则去判断——表格行里的 `| independence | L0 |`
    与正文里的 `independence: L0` 会被同一个正则命中，因为 `\\s*[:：]\\s*`
    在表格里退化为 `\\s+|\\s*` 的宽松匹配。
    """
    # 表格行里常见的「键 | 值」分隔：`| key | value |`
    TABLE_KV = re.compile(
        r"\|\s*(?:independence|spec|quality|reviewer|implementer|round)\s*\|",
        re.I)
    out = []
    for line in (text or "").splitlines():
        stripped = line.lstrip()
        if stripped.startswith("|"):
            if TABLE_KV.search(line):
                # 含键名的表格行：把 `| key | value |` 改写成 `key: value`，
                # 让下游正则无需为表格做特殊处理
                cells = [c.strip() for c in line.strip().strip("|").split("|")]
                if len(cells) >= 2 and cells[0] and cells[1]:
                    out.append("%s: %s" % (cells[0], cells[1]))
                else:
                    out.append(line)
            # 无键名的表格行：纯数据对照表，丢弃
            continue
        out.append(re.sub(r"`[^`]*`", "", line))   # 去掉行内代码引用
    return "\n".join(out)


# ---------------------------------------------------------------------------
# 规模 / 裁剪
# ---------------------------------------------------------------------------

TRIM_MODES = ("必", "简", "条", "-")

# 「简」模式下每个阶段保留的机器承重项。定义依据只有一条：
# **该项是下游机械消费的输入，还是给人看的格式？**
#
#   下游消费 → 简也必须查：
#     S3 的计划文件存在（task-brief 要读）、`### Task N:`（task-brief 正则依赖）、
#        勾选框（openspec list --json 的 totalTasks 来源）
#   纯格式/给人看 → 简可省：
#     8 个必备段的「存在性」——脚本无法验证「Architecture 段的内容是否成立」，
#     查 `^## Architecture` 只能证明有人写了标题。
LIGHT_KEEP = {
    "S3": ("plan_exists", "task_titles", "placeholders", "align"),
    "S6": ("independence",),
}


def scale_keys(wf):
    """workflow.json 声明的合法规模键（按声明序）。"""
    return [k for k in wf.get("scale", {}) if not k.startswith("$")]


def normalize_scale(wf, scale):
    """规范化规模值。返回 (key, valid)。

    **严格相等，不做大小写/空白宽容**（有意为之）：
    `--scale` 直接决定哪些门禁执行，属于「判定输入」，不接受猜测。
    `Medium` / ` medium` / `LIGHT` 一律判非法并报错列出合法取值——
    这比「猜成 medium 然后悄悄放行」安全：后者会让一次笔误变成
    一次未经声明的门禁裁剪，而报告里看不出任何异常。
    """
    key = scale if isinstance(scale, str) else ""
    return key, key in scale_keys(wf)


def trim_of(wf, scale_key, sid):
    """该规模下该阶段的裁剪标记。合法规模下必然命中；非法返回 None。"""
    matrix = wf.get("trim_matrix", {})
    row = matrix.get(scale_key)
    if not isinstance(row, dict):
        return None
    return row.get(sid)


def gate_label(wf, sid):
    """门禁显示名从 workflow.json 派生，避免 39 处硬编码各自漂移。"""
    try:
        st = _stage(wf, sid)
    except KeyError:
        return sid
    short = st.get("short") or st.get("name") or sid
    return "%s · %s %s" % (st.get("gate", ""), st["id"], short)


def light_wants(ctx, sid, item):
    """「简」模式下是否检查某个可选项。非「简」时一律检查。"""
    if ctx.get("trim") != "简":
        return True
    keep = LIGHT_KEEP.get(sid)
    if keep is None:
        return True
    return item in keep


# ---------------------------------------------------------------------------
# 各阶段检查
# ---------------------------------------------------------------------------

def _triage_has_domain_rows(ltext):
    """账本 Triage 段是否含 S0 即产生的域路由两行（领域 / 专家）。

    只查 `## Triage` 段内的表格行——C3 约束：Dispatches 派发行 S5 才产生，
    禁查；限定段内也天然把派发行排除在外。行格式对齐 templates/progress.md
    Triage 表与真实账本：
      | 领域（category） | backend-architecture |
      | 专家（name/basis） | 软件架构师（semantic） |
    两行齐备才算「有行」——只补一行仍是域路由信息不完整，判缺。
    """
    body = section_body(ltext or "", "Triage")
    if not body:
        return False
    keys = []
    for line in body.splitlines():
        s = line.strip()
        if not s.startswith("|"):
            continue
        first = s.strip("|").split("|")[0].strip()
        if first:
            keys.append(first)
    return (any("领域" in k for k in keys)
            and any("专家" in k for k in keys))


def check_S0(ctx, rep, wf):
    """S0：环境探测必须真实发生，规模必须合法可裁剪。"""
    label = gate_label(wf, "S0")

    probed = ctx["env_probed"]
    rep.add(label, "环境已探测（git / openspec root）",
            OK if probed else FAIL,
            ctx["env_summary"] if probed
            else "[unverifiable:root] 项目根不可读：%s" % ctx["root"],
            id="S0.ENV",
            reason=None if probed else "unverifiable:root")

    scale = ctx["scale"]
    valid = ctx["scale_valid"]
    if not scale:
        rep.add(label, "规模已分类", FAIL,
                "[unverifiable:scale] 未提供 --scale；本工具不做推断",
                id="S0.SCALE", reason="unverifiable:scale")
    elif not valid:
        rep.add(label, "规模已分类", FAIL,
                "[unverifiable:scale] scale=%r 不在 %s 内——未知规模无法查裁剪矩阵，"
                "本次按最严（全部阶段按「必」）执行"
                % (scale, "|".join(scale_keys(wf))),
                id="S0.SCALE", reason="unverifiable:scale")
    else:
        row = wf.get("trim_matrix", {}).get(ctx["scale_key"], {})
        rep.add(label, "规模已分类", OK,
                "scale=%s（裁剪：%s）" % (
                    ctx["scale_key"],
                    " ".join("%s=%s" % (k, v) for k, v in row.items()
                             if not k.startswith("$"))),
                id="S0.SCALE")

    # --- S0.DOMAIN（enforce-domain-routing A 案六格判定表，design §3） ---
    #
    # 判定表（首列=账本 Scale，双语）：
    #   任何规模 + 无账本            → SKIP  inapplicable:no_ledger
    #   任何规模 + 账本不可读        → FAIL  malformed_ledger
    #   readonly   + 有账本          → SKIP  inapplicable:readonly_no_ledger_expected（D4）
    #   非只读     + 有账本 + 缺行   → FAIL  s0_domain_missing（A 案执法核心格）
    #   非只读     + 有账本 + 有行   → OK
    #
    # 账本关联（#11）：给了 --plan 时只查 plan 关联 workspace 的账本
    # （find_workspace），**不做 discover_ledger 全仓兜底**——本仓存在遗留
    # 账本（openspec-impl / vendor-skills，均无 Triage 域路由行），扫全仓
    # 会让遗留账本无限期 FAIL。未给 --plan 时沿用 ctx["ledger"]（现有发现
    # 机制，readonly 逃逸守卫依赖它）。
    # Scale 双语（#10）：账本 Scale 段实测写中文（「中任务」「只读」），
    # readonly 判定走 parse_scale_section 的双语解析；解析不出（段缺失/
    # 歧义）回退 --scale。执法偏向：两边都无法确定规模时按非只读执法。
    if ctx["plan"]:
        ws = find_workspace(ctx["root"], ctx["plan"])
        ledger = (os.path.join(ws, "progress.md")
                  if ws and os.path.exists(os.path.join(ws, "progress.md"))
                  else None)
    else:
        ledger = ctx["ledger"]

    if ledger is None:
        rep.add(label, "Triage 域路由行（S0.DOMAIN）", SKIP,
                "[inapplicable:no_ledger] 无关联账本——S0 账本锚不存在，无从执法",
                id="S0.DOMAIN", reason="inapplicable:no_ledger")
        return
    ltext = read(ledger)
    if ltext is None:
        rep.add(label, "Triage 域路由行（S0.DOMAIN）", FAIL,
                "[malformed_ledger] 账本存在但读不出（%s）——「查不了」不允许静默放行"
                % ledger,
                id="S0.DOMAIN", reason="malformed_ledger")
        return
    recorded = parse_scale_section(ltext)
    is_readonly = (recorded == "readonly") if recorded else (ctx["scale_key"] == "readonly")
    if is_readonly:
        rep.add(label, "Triage 域路由行（S0.DOMAIN）", SKIP,
                "[inapplicable:readonly_no_ledger_expected] readonly 按裁剪不产生账本"
                "（D4）——本格判 SKIP，不按账本执法、不造假绿",
                id="S0.DOMAIN", reason="inapplicable:readonly_no_ledger_expected")
        return
    if _triage_has_domain_rows(ltext):
        rep.add(label, "Triage 域路由行（S0.DOMAIN）", OK,
                "Triage 段含域路由两行（领域/专家）——非只读任务执法锚在位",
                id="S0.DOMAIN")
    else:
        rep.add(label, "Triage 域路由行（S0.DOMAIN）", FAIL,
                "[s0_domain_missing] 账本缺 Triage 域路由两行（「领域（category）」"
                "与「专家（name/basis）」）——A 案执法：有账本的非只读任务缺行即 FAIL",
                id="S0.DOMAIN", reason="s0_domain_missing")


def check_S1(ctx, rep, wf):
    """S1：阶段一不落盘是设计，这里只查有没有违规落盘。"""
    label = gate_label(wf, "S1")
    specs_dir = os.path.join(ctx["root"], "docs", "superpowers", "specs")
    if not os.path.isdir(specs_dir):
        rep.add(label, "设计未违规落盘（R3）", OK, "docs/superpowers/specs/ 不存在",
                id="S1.DESIGN_LEAK")
        return
    # 「本次」的机械判据只能是日期。旧实现还匹配文件名含 "design"，
    # 会把一年前的 old-redesign.md 判成本次违规（实测 WARN 误报）。
    files = [f for f in os.listdir(specs_dir) if f.endswith(".md")]
    stale = [f for f in files if ctx["today"] in f]
    if not stale:
        rep.add(label, "设计未违规落盘（R3）", OK, "无本次设计文件",
                id="S1.DESIGN_LEAK")
        return
    bad = []
    for f in stale:
        head = read(os.path.join(specs_dir, f))
        if head is None or "非权威" not in head[:200]:
            # 三态：不可读 ≠ 未标注。不可读文件显式标注，防「读不出」
            # 被压成「查过且未标注」（A-9）。
            bad.append(f if head is not None else f + "（不可读）")
    if bad:
        rep.add(label, "设计未违规落盘（R3）", WARN,
                "[soft:design_not_marked] 存在未标注『非权威』的设计文件：%s"
                % ", ".join(bad[:3]),
                id="S1.DESIGN_LEAK", reason="soft:design_not_marked")
    else:
        rep.add(label, "设计未违规落盘（R3）", OK, "已标注非权威",
                id="S1.DESIGN_LEAK")


def _archived_entry(ctx):
    """在 openspec/changes/archive/ 下找「日期前缀 + 精确变更名」的目录。

    精确匹配，不用子串：旧实现 `ctx["change"] in e` 会让 `my-change`
    命中 `archive/2026-01-01-my-change-v2/`。
    """
    if not ctx.get("change"):
        return None
    arch = os.path.join(ctx["root"], "openspec", "changes", "archive")
    if not os.path.isdir(arch):
        return None
    pat = re.compile(r"^\d{4}-\d{2}-\d{2}-%s$" % re.escape(ctx["change"]))
    for name in sorted(os.listdir(arch)):
        if pat.match(name) and os.path.isdir(os.path.join(arch, name)):
            return name
    return None


def check_S2(ctx, rep, wf):
    """规格产物存在性。路径来自 workflow.json 的 artifacts 声明。

    **三态分流**是这里的核心（缺陷 #1）：
      未初始化 OpenSpec 且调用方未显式 --change、且该规模下 S2 为条件触发
          （trim="条"）→ SKIP（非 OpenSpec 项目是合法形态）
      已显式 --change 却未初始化 OpenSpec → FAIL（调用方声明本阶段适用，
          目录却不存在，事实与声明不符）
      已初始化但变更目录不存在             → FAIL（拼错 / 未创建 / 已归档，
          都不是「不适用」）
    fail-closed：宁可错杀漏报也不放行无法核实的规格。
    """
    label = gate_label(wf, "S2")
    stage = _stage(wf, "S2")
    change_dir = ctx["change_dir"]

    # 变更名本身非法（含 `..` 等）：已在 run() 记过 S0.CHANGE_NAME，
    # 这里不再把它当「目录不存在」重复报，而是明确指向格式问题。
    if ctx.get("change_invalid"):
        rep.add(label, "变更目录存在", FAIL,
                "[malformed:change_name] %r 不是合法变更名，无法定位目录"
                % ctx["change"],
                id="S2.CHANGE_DIR", reason="malformed:change_name")
        return

    if not change_dir or not os.path.isdir(change_dir):
        if ctx.get("change"):
            archived = _archived_entry(ctx)
            if not ctx["openspec"]:
                rep.add(label, "变更目录存在", FAIL,
                        "[unverifiable:no_openspec_root] 未初始化 OpenSpec，"
                        "但已显式声明 --change=%r：无法核验（root:null 不是免责理由）"
                        % ctx["change"],
                        id="S2.CHANGE_DIR", reason="unverifiable:no_openspec_root")
            elif archived:
                rep.add(label, "变更目录存在", FAIL,
                        "[missing:change_dir] 变更 %r 已归档到 %s；"
                        "请核对进行中的变更，不要对已结束的变更做门禁核对"
                        % (ctx["change"], archived),
                        id="S2.CHANGE_DIR", reason="missing:change_dir")
            else:
                rep.add(label, "变更目录存在", FAIL,
                        "[missing:change_dir] openspec/changes/%s 不存在"
                        "（拼写错误？或该变更尚未创建？若尚未进入 S2，请先不要传 --change）"
                        % ctx["change"],
                        id="S2.CHANGE_DIR", reason="missing:change_dir")
        else:
            # 本阶段未被裁剪，但调用方没给 --change。
            # 必/简 → 无法核验（FAIL）；条 → 触发条件不成立（SKIP）。
            trim = ctx.get("trim") or "必"
            if trim in ("必", "简"):
                rep.add(label, "变更目录存在", FAIL,
                        "[unverifiable:change_required] 该规模下 S2 不被裁剪，"
                        "必须提供 --change（当前 scale=%s）" % ctx.get("scale_key"),
                        id="S2.CHANGE_DIR", reason="unverifiable:change_required")
            else:
                rep.add(label, "变更目录存在", SKIP,
                        "[inapplicable:trigger:openspec] scale=%s 下 S2 为条件触发；"
                        "openspec=%s 且未提供 --change，触发条件不成立"
                        % (ctx.get("scale_key"), "有" if ctx.get("openspec") else "无"),
                        id="S2.CHANGE_DIR", reason="inapplicable:trigger:openspec")
        return

    rep.add(label, "变更目录存在", OK, change_dir, id="S2.CHANGE_DIR")

    for art in stage["artifacts"]:
        name = os.path.basename(art["path"].rstrip("/"))
        required = art.get("required", False)
        if art.get("glob"):
            found = expand_artifact(ctx["root"], art["path"], ctx["change"])
            if found:
                rep.add(label, "%s（glob）" % name, OK, "%d 个匹配" % len(found),
                        id="S2.ARTIFACT:%s" % name)
            else:
                rep.add(label, "%s（glob）" % name, FAIL,
                        "[missing:%s] 未找到：%s%s" % (
                            name, art["path"],
                            "（required=true）" if required else ""),
                        id="S2.ARTIFACT:%s" % name, reason="missing:%s" % name)
            continue
        p = os.path.join(change_dir, name)
        exists = os.path.exists(p)
        if exists:
            rep.add(label, name, OK, "", id="S2.ARTIFACT:%s" % name)
        elif required:
            rep.add(label, name, FAIL,
                    "[missing:%s] 缺失：%s（required=true）" % (name, p),
                    id="S2.ARTIFACT:%s" % name, reason="missing:%s" % name)
        else:
            # 非必需产物缺失：**不扣分**。
            #
            # 旧实现 emit WARN 但 reason=None，被 enforce_reasons() 机械改判
            # FAIL（malformed:soft_reason）—— 「非必需缺失」变成了 FAIL，
            # 与声明语义完全相反。这里改为不入项：声明本身就是「可选项」，
            # 缺失就是它的预期状态之一，不该产生噪音。
            continue


def _declared_parent_dir(wf, sid, fallback):
    """从配置声明的 glob 产物路径里推出「父目录」，用于逐能力核对。

    A-14 修复的一部分：S8 需要知道「主 spec 放在哪个根目录下」，
    而这个根目录在 `workflow.json` 里已经声明了
    （`openspec/specs/<capability>/spec.md`）。
    旧实现写死 `openspec/specs`，于是改配置不生效。

    取法：找该阶段第一个 `glob: true` 且文件名是 `spec.md` 的产物，
    取它的倒数第二段（`<capability>` 的父级）。
    找不到就用 fallback —— 不因为配置形状意外而让整个检查崩溃。
    """
    try:
        stage = _stage(wf, sid)
    except KeyError:
        return os.path.join(os.getcwd(), fallback)
    for art in stage.get("artifacts", []):
        if not art.get("glob"):
            continue
        if os.path.basename(art["path"].rstrip("/")) != "spec.md":
            continue
        parts = [p for p in art["path"].replace("\\", "/").split("/") if p]
        # parts 形如 ["openspec", "specs", "<capability>", "spec.md"]
        # 父目录 = 去掉最后两段
        if len(parts) >= 3:
            return "/".join(parts[:-2])
    return fallback


def _ledger_completed_ids(ledger_text):
    """账本中标记为完成的任务号集合。

    三处收紧（缺陷 #6）：
      行锚定 `^\\s*`  —— 旧实现 `Task\\s+\\d+.*:\\s*complete` 的 `\\s*` 可跨行，
                         `Task 1:` ⏎ `complete` 会被算成完成。
      词尾 `\\b`      —— `complete_pending` / `complete-x` 不再算完成；
                         同时接受 `completed`（`complete(?:d)?`）这一既有合法写法。
      集合去重        —— 同一 Task 的重试追加行不重复计数。

    同一行可能写多个 complete（`Task 1: complete (a) | Task 2: complete (b)`），
    旧实现的贪婪 `.*` 会把它们合并成 1 条。这里用 `finditer` 而非 `match`，
    逐个提取，同一行多个也能全数计入。
    """
    ids = set()
    pat = re.compile(
        r"(?:^|\s)(?:[-*+]\s*)?Task\s+(\d+)\b[^\n:|]*:\s*complete(?:d)?\b", re.I)
    for line in (ledger_text or "").splitlines():
        clean = line.replace("**", "").replace("__", "").replace("`", "")
        for m in pat.finditer(clean):
            ids.add(m.group(1))
    return ids


def _tasks_done_ids(tasks_text):
    """tasks.md 中已勾选叶子所属的一级任务号。

    返回 (ids, n_done, n_no_id)：
      ids      —— 从 `- [x] 1.1 a` 的描述里提取的 `1`
      n_done   —— 已勾选叶子总数
      n_no_id  —— 没有数字编号的已勾选叶子数

    **`n_no_id` 的用途在 A-5 修复后变了**：它不再决定「是否退化到计数比较」，
    只用来产出「有无编号叶子」的提示。原因：

      `references/stage-S3-plan.md:46` 明文允许 `1 Task ≥ N 叶子`（covers 语法），
      所以「勾选叶子数」与「账本任务号数」本来就不是同一单位。
      原逻辑只要有**一个**叶子没写编号就切到计数比较，于是
          `- [x] 1.1 a` / `- [x] 1.2 b` / `- [x] 无编号 c`  → 3 != 1 → FAIL
      而把第三行改成 `1.3 c` 就 OK。**同一事实，只因一个编号就全红。**

    退化条件改为「**全部**叶子都无编号」——那种情况下确实没有任务号可比，
    计数比较是唯一可行的判据。混合情况一律走 id-set 比较（更精确），
    无编号叶子另出一条 WARN 提示补编号。
    """
    ids, n_done, n_no_id = set(), 0, 0
    for is_done, desc in parse_task_lines(tasks_text):
        if not is_done:
            continue
        n_done += 1
        m = re.match(r"\s*([0-9]+)", desc or "")
        if m:
            ids.add(m.group(1))
        else:
            n_no_id += 1
    return ids, n_done, n_no_id


def check_S3(ctx, rep, wf):
    """计划文档：存在 + 必备段 + 任务标题 + 占位符 + 与 tasks.md 对齐。"""
    label = gate_label(wf, "S3")
    stage = _stage(wf, "S3")

    text = read(ctx["plan"]) if ctx["plan"] else None
    if not ctx["plan"]:
        rep.add(label, "计划文档", FAIL,
                "[unverifiable:plan_required] 该规模下 S3 不被裁剪，必须提供 --plan",
                id="S3.PLAN", reason="unverifiable:plan_required")
        return
    if text is None:
        rep.add(label, "计划文档存在", FAIL,
                "[malformed:plan_unreadable] 无法读取 %s" % ctx["plan"],
                id="S3.PLAN", reason="malformed:plan_unreadable")
        return
    rep.add(label, "计划文档存在", OK, ctx["plan"], id="S3.PLAN")

    # 必备段：精确匹配（前缀匹配会让 `## Specification` 冒充 `## Spec`）
    for sec in stage["required_sections"]:
        if not light_wants(ctx, "S3", "sections"):
            continue  # 「简」模式不查段名——它只证明有人写了标题，不证明内容
        has = has_section(text, sec)
        if has:
            rep.add(label, "必备段：%s" % sec, OK, "", id="S3.SECTION:%s" % sec)
        else:
            rep.add(label, "必备段：%s" % sec, FAIL,
                    "[missing:section] 缺 `## %s` 段（精确段名，`## %sXxx` 不算）"
                    % (sec, sec),
                    id="S3.SECTION:%s" % sec, reason="missing:section")

    # 任务标题：无论「必」还是「简」都必须查——task-brief 脚本按它解析
    tasks = re.findall(r"^#+\s+Task\s+(\d+)\s*:", text, re.M)
    if tasks:
        rep.add(label, "任务标题格式 '### Task N:'", OK,
                "找到 %d 个 Task：%s" % (len(tasks), ",".join(tasks[:10])),
                id="S3.TASK_TITLES")
    else:
        rep.add(label, "任务标题格式 '### Task N:'", FAIL,
                "[missing:task_title] 一个都没匹配到——task-brief 脚本按 "
                "`### Task N:` 解析，缺了它无法派发",
                id="S3.TASK_TITLES", reason="missing:task_title")

    placeholders = re.findall(r"TBD|TODO|适当的错误处理|同 Task [0-9]", text)
    if placeholders:
        rep.add(label, "无占位符", FAIL,
                "[malformed:placeholder] 命中 %d 处：%s"
                % (len(placeholders), sorted(set(placeholders))),
                id="S3.PLACEHOLDERS", reason="malformed:placeholder")
    else:
        rep.add(label, "无占位符", OK, "", id="S3.PLACEHOLDERS")

    # 双账本对齐：计划 Task 数 ≥ 1 且 tasks.md 有叶子
    if ctx["change_dir"] and os.path.isdir(ctx["change_dir"]):
        ttext = read(os.path.join(ctx["change_dir"], "tasks.md"))
        if ttext is not None:
            leaves = count_checkboxes(ttext)
            total_leaves = leaves["done"] + leaves["todo"] + leaves["other"]
            ok = total_leaves > 0 and len(tasks) >= 1
            rep.add(label, "计划 Task 与 tasks.md 叶子对齐",
                    OK if ok else FAIL,
                    ("tasks.md 叶子 %d 条 / 计划 Task %d 个（1 Task ≥ 1 叶子）"
                     % (total_leaves, len(tasks))) if ok else
                    "[malformed:leaf_align] tasks.md 叶子 %d 条 / 计划 Task %d 个"
                    % (total_leaves, len(tasks)),
                    id="S3.ALIGN",
                    reason=None if ok else "malformed:leaf_align")


def check_S4(ctx, rep, wf):
    """基线与账本：防丢的两处重点。"""
    label = gate_label(wf, "S4")

    text = read(ctx["plan"]) if ctx["plan"] else None
    if not ctx["plan"]:
        rep.add(label, "基线记录", FAIL,
                "[unverifiable:plan_required] 该规模下 S4 不被裁剪，必须提供 --plan",
                id="S4.BASELINE", reason="unverifiable:plan_required")
        return
    if text is None:
        # 提供了但读不出 ≠ 没提供（A-9 同族）：前者是 Q2 失败（malformed），
        # 报错该指向文件编码/权限；混同的文案会教用户去补传 --plan。
        rep.add(label, "基线记录", FAIL,
                "[malformed:plan_unreadable] 无法读取 %s" % ctx["plan"],
                id="S4.BASELINE", reason="malformed:plan_unreadable")
        return

    has_baseline = has_section(text, "Baseline")
    if has_baseline:
        rep.add(label, "基线主副本在计划文档（防 workspace 删除丢失）", OK, "",
                id="S4.BASELINE")
    else:
        rep.add(label, "基线主副本在计划文档（防 workspace 删除丢失）", FAIL,
                "[missing:baseline] 计划文档缺 `## Baseline` 段——"
                "基线证据会在删 workspace 时消失",
                id="S4.BASELINE", reason="missing:baseline")

    ledger = ctx["ledger"]
    if not ledger:
        # 账本缺失的三态分流（A-4 修复）。
        #
        # 原实现一律判 `missing:ledger` FAIL —— 但「交付完成 + workspace 已按
        # 铁律 11 清理」是**正常终态**，按规范做完交付的项目回查门禁必然 rc=1。
        # 更糟的是原提示给的出路是「请用 --scale light」——教人用降级绕门禁。
        #
        # 正确做法照 check_S5 已有的范式：按 tasks.md 是否还有未完成项区分。
        #   全部完成 + 无账本 → WARN soft:workspace_cleaned（正常清理）
        #   仍有未完成 / tasks.md 不可读 → FAIL missing:ledger（证据缺失）
        ttext = None
        if ctx["change_dir"] and os.path.isdir(ctx["change_dir"]):
            ttext = read(os.path.join(ctx["change_dir"], "tasks.md"))
        leaves = count_checkboxes(ttext) if ttext is not None else None
        unfinished = (leaves["todo"] + leaves["other"]) if leaves else 0
        if leaves is not None and unfinished == 0:
            rep.add(label, "账本存在", WARN,
                    "[soft:workspace_cleaned] 无账本，但 tasks.md 已全部完成——"
                    "疑似交付后按铁律 11 清理（正常终态）；若为交付前核对请补 --plan",
                    id="S4.LEDGER", reason="soft:workspace_cleaned")
        else:
            why = ("tasks.md 不可读，无法判断是否已完成"
                   if leaves is None
                   else "tasks.md 仍有 %d 项未完成" % unfinished)
            rep.add(label, "账本存在", FAIL,
                    "[missing:ledger] 找不到 .superpowers/sdd/<plan>/progress.md，"
                    "且 %s——实施证据缺失" % why,
                    id="S4.LEDGER", reason="missing:ledger")
        return
    ltext = read(ledger)
    if ltext is None:
        # 账本存在但读不出 ≠ 空账本（A-9）：前者是 Q2 失败（malformed），
        # 后者才是格式问题。混同会把「读不出」印成「空账本」误导排查方向。
        rep.add(label, "账本首行为身份行（INV4）", FAIL,
                "[malformed:ledger_unreadable] 账本存在但读不出（无效 UTF-8 / 权限），"
                "身份行无从核验",
                id="S4.LEDGER_ID", reason="malformed:ledger_unreadable")
        return
    first = ltext.splitlines()[0] if ltext else ""
    if first.startswith("# SDD ledger — plan:"):
        rep.add(label, "账本首行为身份行（INV4）", OK, first[:80], id="S4.LEDGER_ID")
    else:
        rep.add(label, "账本首行为身份行（INV4）", FAIL,
                "[malformed:ledger_identity] 首行必须是 `# SDD ledger — plan: <计划路径>`；"
                "实际：%s" % (first[:80] or "空账本"),
                id="S4.LEDGER_ID", reason="malformed:ledger_identity")


def check_S5(ctx, rep, wf):
    """每任务产物 + 三元对齐。

    三元对齐的判据从「计数相等」改为「任务号集合相等」（缺陷 #6 的语义层）：
    `references/stage-S3-plan.md:46` 明文允许一个 Task 覆盖多个叶子
    （`1 Task ≥ 1 叶子`），计数相等在这个合法形态下必然假红；
    反过来说，计数相等也证明不了「是同一批任务」。
    只有叶子无数字编号时才退化回计数比较。
    """
    label = gate_label(wf, "S5")

    if not ctx["workspace"]:
        # 交付后 workspace 已按铁律 11 清理属正常态；但「变更未完成 + 无 workspace」
        # 是证据缺失，不能静默。
        ttext = (read(os.path.join(ctx["change_dir"], "tasks.md"))
                 if ctx["change_dir"] and os.path.isdir(ctx["change_dir"]) else None)
        leaves = count_checkboxes(ttext) if ttext is not None else None
        unfinished = leaves and (leaves["todo"] + leaves["other"]) > 0
        if unfinished:
            rep.add(label, "任务产物", FAIL,
                    "[missing:workspace] tasks.md 仍有 %d 项未完成，"
                    "但找不到 .superpowers/sdd/<plan>/；实施证据缺失"
                    % (leaves["todo"] + leaves["other"]),
                    id="S5.WORKSPACE", reason="missing:workspace")
        else:
            rep.add(label, "任务产物", SKIP,
                    "[inapplicable:no_workspace] 无 SDD workspace（可能已按铁律 11 清理）",
                    id="S5.WORKSPACE", reason="inapplicable:no_workspace")
        return

    files = os.listdir(ctx["workspace"]) if os.path.isdir(ctx["workspace"]) else []
    briefs = [f for f in files if re.match(r"task-\d+-brief\.md$", f)]
    reports = [f for f in files if re.match(r"task-\d+-report\.md$", f)]
    if briefs:
        rep.add(label, "任务 brief 已生成", OK, "%d 份" % len(briefs), id="S5.BRIEF")
    else:
        rep.add(label, "任务 brief 已生成", FAIL,
                "[missing:brief] workspace 存在但一份 task-N-brief.md 都没有",
                id="S5.BRIEF", reason="missing:brief")
    if reports:
        rep.add(label, "实施报告已生成", OK, "%d 份" % len(reports), id="S5.REPORT")
    else:
        rep.add(label, "实施报告已生成", FAIL,
                "[missing:report] workspace 存在但一份 task-N-report.md 都没有",
                id="S5.REPORT", reason="missing:report")

    if ctx["change_dir"] and os.path.isdir(ctx["change_dir"]):
        ttext = read(os.path.join(ctx["change_dir"], "tasks.md"))
        ltext = read(ctx["ledger"]) if ctx["ledger"] else None
        # 证据面显式化（A-9 同族）：tasks.md/账本「存在但读不出」不得静默蒸发——
        # 三元对齐是 S5 的机器承重项，读不出=查不了=FAIL（malformed:*）。
        # ctx["ledger"] 非空已由 run() 用 os.path.exists 保证文件存在，
        # 故 ltext None 即「读不出」；tasks.md 需 os.path.isfile 区分「缺失」与「读不出」。
        if ttext is None and os.path.isfile(os.path.join(ctx["change_dir"], "tasks.md")):
            rep.add(label, "三元对齐：tasks.md 勾选 == ledger complete（INV2/INV6）",
                    FAIL, "[malformed:tasks_unreadable] tasks.md 存在但读不出，"
                    "三元对齐无从核对",
                    id="S5.TRIAD", reason="malformed:tasks_unreadable")
        elif ltext is None and ctx["ledger"]:
            rep.add(label, "三元对齐：tasks.md 勾选 == ledger complete（INV2/INV6）",
                    FAIL, "[malformed:ledger_unreadable] 账本存在但读不出，"
                    "三元对齐无从核对",
                    id="S5.TRIAD", reason="malformed:ledger_unreadable")
        elif ttext is not None and ltext is not None:
            done_ids, n_done, n_no_id = _tasks_done_ids(ttext)
            ledger_ids = _ledger_completed_ids(ltext)

            # 退化条件：**全部**叶子都无编号（A-5 修复）。
            # 原条件是「有一个就退化」，导致文档允许的 `1 Task ≥ N 叶子`
            # 在混入任一无编号叶子时必然假红。
            all_unnumbered = n_done > 0 and n_no_id == n_done
            if all_unnumbered:
                ok = n_done == len(ledger_ids)
                basis = "count"
                detail = "勾选 %d / ledger complete %d（全部叶子无编号，按计数比较）" % (
                    n_done, len(ledger_ids))
            else:
                ok = done_ids == ledger_ids
                basis = "id-set"
                detail = "已完成任务号 %s / ledger complete %s" % (
                    sorted(done_ids), sorted(ledger_ids))
                if n_no_id:
                    detail += "；另有 %d 个无编号叶子未参与比较" % n_no_id

            # 无编号叶子单独出提示：不影响主判据，但留下可操作信息。
            # 这是「把不可判定项显式化」——不改判据，只提示补编号。
            if n_no_id and not all_unnumbered:
                rep.add(label, "叶子编号完整性", WARN,
                        "[soft:unnumbered_leaf] 有 %d 个已勾选叶子没写数字编号，"
                        "未参与任务号比较；建议补成 `- [x] N.M 描述` 以便精确核对"
                        % n_no_id,
                        id="S5.LEAF_NUMBERING", reason="soft:unnumbered_leaf")

            if ok:
                rep.add(label, "三元对齐：tasks.md 勾选 == ledger complete（INV2/INV6）",
                        OK, "%s（basis=%s）" % (detail, basis), id="S5.TRIAD")
            else:
                rep.add(label, "三元对齐：tasks.md 勾选 == ledger complete（INV2/INV6）",
                        FAIL, "[malformed:triad] %s（basis=%s）" % (detail, basis),
                        id="S5.TRIAD", reason="malformed:triad")


def check_S6(ctx, rep, wf):
    """审查独立性标记 + Rulings / Review 段。

    independence 是**全流程唯一硬性交付禁止项**（L2 = 禁止交付），
    所以取值策略必须偏保守：文本顺序不是契约，账本是「裁决 + 讨论 + 历史」
    混写的自由文本，无法机械判定哪句是最终结论。取**最坏值**——
    它单调且有界，只能造成假红（清掉一行即可），不可能造成假绿（禁止交付项失效）。

    旧实现用 `re.search` 取**首个**匹配，于是「independence: L0 设想」这几个字
    就能把末位的 L2 洗白——实测判 `[ OK ] 级别 L0`。
    """
    label = gate_label(wf, "S6")

    # review-<N>.md 的存在性（P9 复审收口：本项前置——后面的 INDEPENDENCE
    # FAIL/SKIP 早退路径不得吞掉它，报告完整性）：config/workflow.json S6
    # artifacts 声明 required:true，旧实现从不列 workspace 目录 → 声明无人
    # 消费（实测满绿假绿）。硬约束（A-14 裁决）：workspace 已删必须
    # inapplicable——交付后跨阶段核对不能因 workspace 清理而假红。
    workspace = ctx.get("workspace") or ""
    if not workspace or not os.path.isdir(workspace):
        rep.add(label, "审查报告 review-<N>.md", SKIP,
                "[inapplicable:no_workspace] workspace 不存在或已删，审查报告无从核对",
                id="S6.REVIEW_REPORT", reason="inapplicable:no_workspace")
    else:
        reviews = sorted(f for f in os.listdir(workspace)
                         if re.match(r"^review-[0-9]+\.md$", f))
        if reviews:
            rep.add(label, "审查报告 review-<N>.md", OK, ", ".join(reviews[:3]),
                    id="S6.REVIEW_REPORT")
        else:
            rep.add(label, "审查报告 review-<N>.md", FAIL,
                    "[missing:review_report] workspace 存在但零个 review-<N>.md"
                    "（config/workflow.json S6 声明 required:true）",
                    id="S6.REVIEW_REPORT", reason="missing:review_report")

    ltext = read(ctx["ledger"]) if ctx["ledger"] else None
    ptext = read(ctx["plan"]) if ctx["plan"] else None

    # 证据三态（A-9 同族）：「没有证据」才能 SKIP；「有证据但读不出」是
    # Q2 失败 → FAIL。混同会让独立性核验（L2 = 禁止交付的唯一硬项）
    # 被静默归为「不该查」。
    if ctx["ledger"] and ltext is None:
        rep.add(label, "审查独立性标记 L0/L1/L2", FAIL,
                "[malformed:ledger_unreadable] 账本存在但读不出，独立性标记无从核验",
                id="S6.INDEPENDENCE", reason="malformed:ledger_unreadable")
        return
    # SKIP 仅限「证据确实不存在」（计划 Task 6 第 3 条，P9 复审 🟡 收口）：
    # ctx 里声明了 plan 但读不出 ≠ 没有证据——「声明了却查不出」按
    # missing:independence 落 FAIL（fail-closed），不把「查不了」印成「不该查」。
    if not ctx["ledger"] and not ctx["plan"]:
        rep.add(label, "审查独立性标记 L0/L1/L2", SKIP,
                "[inapplicable:no_evidence] 无账本与计划，无从核验独立性",
                id="S6.INDEPENDENCE", reason="inapplicable:no_evidence")
        return

    order = {"L0": 0, "L1": 1, "L2": 2}
    marker = re.compile(r"independence\s*[:：]\s*(L[012])\b", re.I)

    hits = []  # [(来源, 级别)]
    for src, txt in (("ledger", ltext), ("plan", ptext)):
        if txt is None:
            continue
        # 标记取值：剥引用（行内代码 / 表格行），但**保留围栏内容**——
        # templates/plan-sections.md 规定 ## Review 的内容就写在 ```markdown 里。
        whole = marker.findall(strip_quoted_markers(txt))
        # 优先只认 ## Review 段内的标记；段内没有才回退到全文（遗留写法）
        body = section_body(txt, "Review", keep_fences=True)
        in_section = marker.findall(strip_quoted_markers(body)) if body is not None else []
        for lvl in (in_section or whole):
            hits.append((src, lvl.upper()))

    if not hits:
        rep.add(label, "审查独立性标记 L0/L1/L2", FAIL,
                "[missing:independence] 未找到 independence 标记——"
                "L2（无审查）禁止交付，缺标记等同未审查",
                id="S6.INDEPENDENCE", reason="missing:independence")
    else:
        worst_src, worst = max(hits, key=lambda h: order[h[1]])
        all_hits = ",".join("%s:%s" % (s, l) for s, l in hits)
        if worst == "L2":
            rep.add(label, "审查独立性标记 L0/L1/L2", FAIL,
                    "[forbidden:independence_l2] 级别 L2（无审查，禁止交付）；"
                    "全部标记：%s（取最坏值）" % all_hits,
                    id="S6.INDEPENDENCE", reason="forbidden:independence_l2")
        else:
            rep.add(label, "审查独立性标记 L0/L1/L2", OK,
                    "级别 %s（来源 %s；全部标记：%s）" % (worst, worst_src, all_hits),
                    id="S6.INDEPENDENCE")

    if ptext is not None:
        if light_wants(ctx, "S6", "rulings"):
            if has_section(ptext, "Rulings"):
                rep.add(label, "Rulings 已持久化到计划文档", OK, "", id="S6.RULINGS")
            else:
                rep.add(label, "Rulings 已持久化到计划文档", WARN,
                        "[soft:missing_rulings] 计划文档缺 `## Rulings` 段——"
                        "删 workspace 后决策永久丢失",
                        id="S6.RULINGS", reason="soft:missing_rulings")

        # 段存在 ≠ 结论已写：必须看到结论载体（spec/quality/三态/independence）
        #
        # 注意 section_body 只取「## Review」到下一个同级标题之间的正文。
        # 若结论写在 `## Review` 下的子标题（`### 批次 P0 审查结论`）里，
        # 那仍在同一段内，会被正常读取；但如果文档把结论写在别的二级段
        # （例如 `## Integration Verification`）里，就不该算「Review 段有结论」。
        body = section_body(ptext, "Review", keep_fences=True)
        if body is None:
            # 退一步：全文里是否有 Review 类承载段（`## Review（…）` 已被
            # _section_re 覆盖，这里只处理「结论段换了标题」的宽松情形）
            rep.add(label, "审查结论已持久化", WARN,
                    "[soft:missing_review_section] 计划文档缺 `## Review` 段"
                    "（注意 `## Review Focus` 不算）",
                    id="S6.REVIEW", reason="soft:missing_review_section")
        else:
            carriers = re.findall(
                r"spec\s*[:：]\s*(?:✅|❌)|quality\s*[:：]"
                r"|APPROVED|NEEDS_FIX|BLOCKED"
                r"|independence\s*[:：]\s*L[012]", body, re.I)
            if carriers:
                rep.add(label, "审查结论已持久化", OK,
                        "%d 处结论载体" % len(carriers), id="S6.REVIEW")
            else:
                rep.add(label, "审查结论已持久化", WARN,
                        "[soft:review_section_empty] `## Review` 段存在但无结论载体"
                        "（需 spec ✅/❌、quality、三态或 independence）",
                        id="S6.REVIEW", reason="soft:review_section_empty")


def check_S7(ctx, rep, wf):
    label = gate_label(wf, "S7")
    text = read(ctx["plan"]) if ctx["plan"] else None
    if not ctx["plan"]:
        rep.add(label, "集成后重测记录", FAIL,
                "[unverifiable:plan_required] 该规模下 S7 不被裁剪，必须提供 --plan",
                id="S7.INTEGRATION", reason="unverifiable:plan_required")
        return
    if text is None:
        # 提供了但读不出 ≠ 没提供（A-9 同族，对齐 check_S3 先例）。
        rep.add(label, "集成后重测记录", FAIL,
                "[malformed:plan_unreadable] 无法读取 %s" % ctx["plan"],
                id="S7.INTEGRATION", reason="malformed:plan_unreadable")
        return
    if has_section(text, "Integration Verification"):
        rep.add(label, "集成后重测已记录", OK, "", id="S7.INTEGRATION")
    else:
        rep.add(label, "集成后重测已记录", FAIL,
                "[missing:integration_verification] 计划文档缺 "
                "`## Integration Verification`——不得沿用集成前结果",
                id="S7.INTEGRATION", reason="missing:integration_verification")


def check_S8(ctx, rep, wf):
    """归档条件：只认 x/X，且不能有 PARKED 残留。

    这里的核心修复是**不再提前 `return`**：tasks.md 解析不出勾选框
    不等于「本阶段不适用」，而是格式非法——必须 FAIL，且
    PARKED / 主 spec / 归档目录三项检查仍要照常执行。
    旧实现在 total==0 时 `return`，一次格式问题就能让归档门禁整段消失。
    """
    label = gate_label(wf, "S8")
    if not ctx["change_dir"] or not os.path.isdir(ctx["change_dir"]):
        rep.add(label, "归档条件", SKIP,
                "[inapplicable:no_change] 无变更目录，归档条件无从核对",
                id="S8.ARCHIVE_GATE", reason="inapplicable:no_change")
        return

    tpath = os.path.join(ctx["change_dir"], "tasks.md")
    ttext = read(tpath)
    if ttext is None:
        rep.add(label, "completedTasks == totalTasks（只认 x/X）", FAIL,
                "[missing:tasks_md] 变更目录存在但读不到 tasks.md",
                id="S8.COUNT", reason="missing:tasks_md")
    else:
        c = count_checkboxes(ttext)
        total = c["done"] + c["todo"] + c["other"]
        if total == 0:
            styles = detect_bullet_styles(ttext)
            rep.add(label, "completedTasks == totalTasks（只认 x/X）", FAIL,
                    "[malformed:tasks_md] tasks.md 存在但解析不到任何勾选框；"
                    "识别到的列表符：%s（支持 -, *, +, 1./1)）"
                    % (",".join(styles) if styles else "无"),
                    id="S8.COUNT", reason="malformed:tasks_md")
        else:
            all_done = c["todo"] == 0 and c["other"] == 0
            detail = "%d/%d 完成；未完成 %d；异形标记 %d" % (
                c["done"], total, c["todo"], c["other"])
            if all_done:
                rep.add(label, "completedTasks == totalTasks（只认 x/X）", OK,
                        detail, id="S8.COUNT")
            else:
                rep.add(label, "completedTasks == totalTasks（只认 x/X）", FAIL,
                        "[malformed:incomplete] " + detail, id="S8.COUNT",
                        reason="malformed:incomplete")

    # PARKED：优先读 .status.json（与 openspec_engine.py archive-change 一致），
    # 退化到账本正则检查（保留对旧项目的兼容）。
    #
    # P1-4：两处口径统一——**任一**出现 PARKED 即判 FAIL。旧实现在
    # .status.json 存在且 parked=false 时直接 OK，不查账本，账本中真实
    # 存在的 PARKED 任务被漏判，违反 W8「PARKED 默认禁归档」。
    # openspec_engine.py archive-change 只读 .status.json（无账本上下文），
    # 本检查器有账本，故在 .status.json 未标记时仍以账本兜底，两工具
    # 对「已标记」的判定一致，对「账本残留」由本检查器补位。
    status_path = os.path.join(ctx["change_dir"], ".status.json")
    status_text = read(status_path)
    parked_from_status = False
    if status_text is not None:
        try:
            status = json.loads(status_text)
        except (json.JSONDecodeError, ValueError):
            status = {}
        parked_from_status = _status_flag(status, "parked", "PARKED")
    if parked_from_status:
        rep.add(label, "无 PARKED 残留（W8）", FAIL,
                "[forbidden:parked] .status.json 中 parked=true——默认禁归档，须迁出到新 change",
                id="S8.PARKED", reason="forbidden:parked")
    elif ctx["ledger"] is None:
        # .status.json 未标记 parked 且无账本：以 .status.json 为准（若无则
        # 无法确认，显式 WARN 而非静默 OK）
        if status_text is None:
            rep.add(label, "无 PARKED 残留（W8）", WARN,
                    "[soft:no_ledger] 无账本且无 .status.json，无法确认是否有 PARKED 残留",
                    id="S8.PARKED", reason="soft:no_ledger")
        else:
            rep.add(label, "无 PARKED 残留（W8）", OK, "", id="S8.PARKED")
    else:
        # .status.json 未标记 parked：查账本兜底
        ltext = read(ctx["ledger"])
        if ltext is None:
            rep.add(label, "无 PARKED 残留（W8）", FAIL,
                    "[malformed:ledger_unreadable] 账本存在但读不出，「无残留」无法证明",
                    id="S8.PARKED", reason="malformed:ledger_unreadable")
        elif ltext == "":
            rep.add(label, "无 PARKED 残留（W8）", WARN,
                    "[soft:ledger_empty] 账本存在但为空（无身份行），证明力不完整",
                    id="S8.PARKED", reason="soft:ledger_empty")
        else:
            parked = len(re.findall(r"\bPARKED\b|:\s*parked", ltext, re.I))
            if parked == 0:
                rep.add(label, "无 PARKED 残留（W8）", OK, "", id="S8.PARKED")
            else:
                rep.add(label, "无 PARKED 残留（W8）", FAIL,
                        "[forbidden:parked] %d 处 parked——默认禁归档，须迁出到新 change"
                        % parked, id="S8.PARKED", reason="forbidden:parked")

    # 主 spec：优先逐个能力核对，退化到目录存在性
    #
    # **路径从配置派生，不硬编码**（A-14 修复）：旧实现写死 `openspec/specs`，
    # 实测把声明改成 `specs2/<capability>/spec.md` 并把证据搬过去后，
    # S8 仍报 `openspec/specs` 缺失 —— 「读了文件但不按配置读」。
    # 这是任何字面量扫描都抓不到的形态，只能靠行为测试盯住。
    specs_dir = os.path.join(ctx["root"],
                             _declared_parent_dir(wf, "S8", fallback="openspec/specs"))
    caps = sorted({p.name for p in Path(ctx["change_dir"], "specs").glob("*")
                   if p.is_dir()}) if os.path.isdir(
                       os.path.join(ctx["change_dir"], "specs")) else []
    if caps:
        missing = [c for c in caps
                   if not os.path.isfile(os.path.join(specs_dir, c, "spec.md"))]
        if not missing:
            # P0-1：文件存在 ≠ 内容合法。与 openspec_engine.validate-specs 同口径
            # 做真实内容校验（## Purpose 非空），缺 Purpose 的主 spec 判 FAIL，
            # 否则「文件存在就 OK」的假绿会让污染的 spec 被归档。
            #
            # 复用 openspec_engine 的切分/校验逻辑，保持两工具口径一致，
            # 避免在检查器里重新手写一份规则导致再次漂移。
            purpose_bad = []
            try:
                from openspec_engine import _split_sections, _has_purpose
            except Exception:
                _split_sections = None
                _has_purpose = None
            if _split_sections is not None:
                for c in caps:
                    main_spec = os.path.join(specs_dir, c, "spec.md")
                    try:
                        text = read(main_spec)
                    except OSError:
                        text = None
                    if text is None:
                        continue
                    if not _has_purpose(_split_sections(text)):
                        purpose_bad.append(c)
            if purpose_bad:
                rep.add(label, "主 spec 已同步（逐能力）", FAIL,
                        "[missing:spec_sync] %d 个主 spec 缺非空 ## Purpose：%s（%s/<cap>/spec.md）"
                        % (len(purpose_bad), "、".join(purpose_bad), specs_dir),
                        id="S8.SPEC_SYNC", reason="missing:spec_sync")
            else:
                rep.add(label, "主 spec 已同步（逐能力）", OK,
                        "%d 个能力均已同步且含非空 ## Purpose" % len(caps), id="S8.SPEC_SYNC")
        else:
            rep.add(label, "主 spec 已同步（逐能力）", FAIL,
                    "[missing:spec_sync] 未同步的能力：%s（应在 %s/<cap>/spec.md）"
                    % (", ".join(missing), specs_dir), id="S8.SPEC_SYNC",
                    reason="missing:spec_sync")
    elif os.path.isdir(specs_dir):
        rep.add(label, "主 spec 目录存在（sync 后）", OK, specs_dir, id="S8.SPEC_SYNC")
    else:
        rep.add(label, "主 spec 目录存在（sync 后）", WARN,
                "[soft:no_specs_dir] %s 不存在，可能未 sync" % specs_dir,
                id="S8.SPEC_SYNC", reason="soft:no_specs_dir")

    # 归档目录：精确匹配 + 缺失也要产出检查项（旧实现整块消失）
    archived = _archived_entry(ctx)
    arch = os.path.join(ctx["root"], "openspec", "changes", "archive")
    if archived:
        rep.add(label, "归档目录已生成", OK, archived, id="S8.ARCHIVE")
    elif ctx.get("change"):
        rep.add(label, "归档目录已生成",
                FAIL if ctx.get("expect_archive") else WARN,
                ("[missing:archive_entry] archive/ 下无 `YYYY-MM-DD-%s` 目录"
                 % ctx["change"]) if ctx.get("expect_archive") else
                "[soft:future_event:archive] 变更尚未归档（若此刻正在归档，请加 --expect-archive）",
                id="S8.ARCHIVE",
                reason="missing:archive_entry" if ctx.get("expect_archive")
                else "soft:future_event:archive")
    else:
        rep.add(label, "归档目录已生成", SKIP,
                "[inapplicable:no_change] 无变更名，无从核对归档目录",
                id="S8.ARCHIVE", reason="inapplicable:no_change")


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------

def _status_flag(status: dict, *keys) -> bool:
    """与 openspec_engine.py 的 _status_flag 语义一致：任一键存在且为真即 true。"""
    for k in keys:
        if k in status and status[k]:
            return True
    return False


def _stage(wf, sid):
    for s in wf["stages"]:
        if s["id"] == sid:
            return s
    raise KeyError(sid)


def expand_artifact(root, pattern, change):
    """按占位符逐层枚举子目录展开 artifact 路径，返回实际存在的路径列表。

    相比旧的 `while "<" in seg: seg = dirname(seg)` + 全树 `os.walk`：
    旧实现在 `<capability>/spec.md` 这类形态下会把 seg 退化成空串，
    等于 walk 整个仓库根（无界）；且依赖「占位符嵌套深度」这个隐式前提。
    本实现逐层枚举，天然有界，且不会越出 artifact 声明的前缀。

    占位符（含 `<...>`）的段必须在目录位置——它表示「枚举这一层的子目录」。
    若占位符出现在文件名位置，无法枚举，返回空列表（由调用方报 malformed）。
    """
    rel = (pattern or "").replace("<change>", change or "")
    parts = [p for p in rel.replace("\\", "/").split("/") if p]
    if not parts:
        return []
    if "<" in parts[-1]:
        return []                      # 文件名位占位符 → 无法定位

    cur = [root]
    for idx, part in enumerate(parts):
        nxt = []
        last = (idx == len(parts) - 1)
        for base in cur:
            if "<" in part:
                if not os.path.isdir(base):
                    continue
                for name in sorted(os.listdir(base)):
                    sub = os.path.join(base, name)
                    if os.path.isdir(sub):
                        nxt.append(sub)
            else:
                p = os.path.join(base, part)
                if os.path.exists(p) or last:
                    nxt.append(p)
        cur = nxt
        if not cur:
            return []
    return [p for p in cur if os.path.exists(p)]


def _detect_git_repo(start=None):
    """判断是否在 git 仓库内（与 zcode_dev_workflow.detect_git 同口径）。

    空 `.git` 目录不算仓库（目录形态须含 HEAD）；文件形态须以 `gitdir:` 开头
    （worktree / submodule）。向上逐级查找，到根才放弃。
    """
    cur = os.path.abspath(start or os.getcwd())
    while True:
        candidate = os.path.join(cur, ".git")
        if os.path.isdir(candidate):
            if os.path.isfile(os.path.join(candidate, "HEAD")):
                return True
        elif os.path.isfile(candidate):
            try:
                with open(candidate, "r", encoding="utf-8", errors="replace") as f:
                    head = f.read(64)
                if head.lstrip().startswith("gitdir:"):
                    return True
            except OSError:
                pass
        parent = os.path.dirname(cur)
        if parent == cur:
            return False
        cur = parent


def detect_env(root):
    """探测环境：git / openspec root。只读，不产生任何副作用。

    git 判定与 zcode_dev_workflow.detect_git 同口径（_detect_git_repo），
    不再用裸 os.path.exists(.git)——空 `.git` 目录会假阳性。
    """
    has_git = _detect_git_repo(root)
    os_dir = os.path.join(root, "openspec")
    has_openspec = os.path.isdir(os_dir)
    parts = []
    parts.append("git=%s" % ("有" if has_git else "无"))
    parts.append("openspec=%s" % ("有" if has_openspec else "无"))
    return {
        "git": has_git,
        "openspec": has_openspec,
        "summary": ", ".join(parts),
    }


def find_workspace(root, plan_path):
    """定位 SDD workspace。优先按计划 basename，找不到再扫亲代目录名。"""
    base = os.path.join(root, ".superpowers", "sdd")
    if not os.path.isdir(base):
        return None
    slug = os.path.splitext(os.path.basename(plan_path))[0]
    cand = os.path.join(base, slug)
    if os.path.isdir(cand):
        return cand
    parent = os.path.basename(os.path.dirname(plan_path))
    for name in (slug, "%s-%s" % (parent, slug)):
        cand = os.path.join(base, name)
        if os.path.isdir(cand):
            return cand
    return None


def discover_ledger(root):
    """在没有 `--plan` 的情况下找账本。

    **为什么必须有它（P6 复核审查 A-2）**：
    `ctx["ledger"]` 原先只从 `find_workspace(plan)` 推导，于是不给 `--plan`
    时 `ctx["ledger"]` 恒为 None → 「规模与账本一致」交叉校验整体短路。
    实测后果是一条零门槛后门：
        有未完成任务 + `--scale readonly` + 不给 `--plan` → **rc=0**
        同一夹具给出 `--plan` → rc=1（账本 scale 冲突）
    即任何变更只要声称只读、不传计划，就能拿到「无 FAIL 项」。

    现在改为：`--plan` 缺失时在 `.superpowers/sdd/` 下枚举候选 workspace，
    取**唯一一个**带 progress.md 的用于交叉校验。
    - 命中 0 个 → 返回 (None, None)：确实没有账本，不做交叉校验
    - 命中 1 个 → 返回其账本路径
    - 命中多个 → 返回 (None, "多条候选")：歧义，交给调用方报 WARN
      （不猜，猜错会拿错误账本判冲突）
    """
    base = os.path.join(root, ".superpowers", "sdd")
    if not os.path.isdir(base):
        return None, None
    candidates = []
    for name in sorted(os.listdir(base)):
        ledger = os.path.join(base, name, "progress.md")
        if os.path.isfile(ledger):
            candidates.append(ledger)
    if len(candidates) == 1:
        return candidates[0], None
    if len(candidates) > 1:
        return None, "多条候选：%s" % ", ".join(
            os.path.basename(os.path.dirname(p)) for p in candidates[:4])
    return None, None


# ---------------------------------------------------------------------------
# 自检：配置 ↔ 代码一致性
#
# 回答「谁验证验证器」的第一层：这个脚本本身是用来验证修复质量的，
# 它自己坏掉时不能指望它自证。所以把「配置声明的形状」与「代码期望的形状」
# 做机械比对，任何一侧漂移都当场暴露（rc=2），而不是等到第 12 步炸。
#
# 注意：这里只校验**结构**（id 集合、门禁覆盖、裁剪矩阵完整性），
# 不校验语义（评审是否到位、根因是否真到位）——那交角色契约与主控。
# ---------------------------------------------------------------------------

CHECKER_IDS = ("S0", "S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8")


def self_check(wf):
    """返回 drift 列表；空列表表示配置与代码一致。"""
    errors = []
    stage_ids = [s["id"] for s in wf.get("stages", [])]

    # 1. 检查器注册表 ↔ 声明源双射
    if set(stage_ids) != set(CHECKER_IDS):
        errors.append("检查器注册表与 stages 不一致：声明 %s / 代码 %s"
                      % (sorted(stage_ids), sorted(CHECKER_IDS)))

    # 2. 每个 stage 引用的门禁必须存在
    gates = wf.get("gates", {})
    for s in wf.get("stages", []):
        for gid in str(s.get("gate", "")).split("+"):
            gid = gid.strip()
            if gid and gid not in gates:
                errors.append("%s 引用了未声明的门禁 %r" % (s["id"], gid))

    # 3. 裁剪矩阵：行与规模键一致、每格取值合法
    keys = scale_keys(wf)
    matrix = wf.get("trim_matrix", {})
    declared_rows = set(k for k in matrix if not k.startswith("$"))
    if declared_rows != set(keys):
        errors.append("trim_matrix 行与 scale 键不一致：矩阵 %s / 规模 %s"
                      % (sorted(declared_rows), sorted(keys)))
    for sc in keys:
        row = matrix.get(sc) or {}
        for sid in stage_ids:
            mark = row.get(sid)
            if mark not in TRIM_MODES:
                errors.append("trim_matrix[%s][%s] = %r 不是合法裁剪标记 %s"
                              % (sc, sid, mark, "/".join(TRIM_MODES)))

    # 4. 门禁标签派生依赖 short 字段
    for s in wf.get("stages", []):
        if not s.get("short"):
            errors.append("%s 缺 short 字段——gate_label() 会退化成全名" % s["id"])

    # 5. glob 产物的路径必须可定界
    #
    # 只对 `glob: true` 的产物要求「文件名位置不得是占位符」——因为 glob 产物
    # 由 expand_artifact() 逐层枚举目录来定位，文件名位若放占位符则无从枚举。
    # 非 glob 产物的文件名占位符是合法的：`task-<N>-brief.md`、
    # `review-<N>.md` 这类由 check_S5/check_S6 用正则匹配，不经过 expand_artifact。
    # `review-<N>.md` 的存在性由 check_S6 的 S6.REVIEW_REPORT 项核对；
    # 其余检查读的是账本与计划文本。
    # （初版把规则套到全部产物，实测误报 9 处，全部是合法写法。）
    for s in wf.get("stages", []):
        for a in s.get("artifacts", []):
            if not a.get("glob"):
                continue
            base = os.path.basename(a["path"].rstrip("/"))
            if "<" in base:
                errors.append("%s 的 glob 产物路径不可定界（文件名位含占位符，"
                              "expand_artifact 无法枚举）：%s" % (s["id"], a["path"]))

    # 6. L2 必须仍被标注为禁止交付（check_S6 的输出文案依赖此事实）
    levels = wf.get("reviewer_independence", {}).get("levels", {}) or {}
    l2 = levels.get("L2")
    hint = l2 if isinstance(l2, str) else str(
        (l2 or {}).get("deliverable") or (l2 or {}).get("note")
        or (l2 or {}).get("meaning") or "")
    if "禁止" not in hint:
        errors.append("reviewer_independence.levels.L2 未标注禁止交付——"
                      "S6 的 L2 拦截语义失去依据（当前值：%r）" % (l2,))

    # 7. 「简」模式保留项必须引用真实存在的阶段
    for sid in LIGHT_KEEP:
        if sid not in stage_ids:
            errors.append("LIGHT_KEEP 声明了不存在的阶段 %r" % sid)

    # 8. component_registry 必须覆盖所有 stages[].components；internal 路径必须存在；
    #    required: true 的资产缺失即配置漂移。
    registry = wf.get("component_registry", {}) or {}
    reg_keys = set(registry.keys())
    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for s in wf.get("stages", []):
        for comp in s.get("components", []):
            if comp not in reg_keys:
                errors.append("stage %s 的组件 %r 未在 component_registry 登记" % (s["id"], comp))
            else:
                entry = registry[comp]
                internal = entry.get("internal")
                if internal and not os.path.exists(os.path.join(_root, internal)):
                    # P2-1：部署布局备用候选。部署下 _root = <技能根>/skills/zcode-expert-system/，
                    # 技能文件在 <技能根>/skills/zes-*/<文件>；取父目录 + internal
                    # 倒数第二段目录名 + 文件名作为备用候选，存在则不报 DRIFT。
                    parts = internal.split("/")
                    backup = os.path.join(os.path.dirname(_root), parts[-2], parts[-1])
                    if not os.path.exists(backup):
                        errors.append("组件 %r 声明的 internal 路径不存在：%s" % (comp, internal))
                if entry.get("required") is True:
                    scripts = entry.get("scripts") or {}
                    for script_name, script_rel in scripts.items():
                        if not os.path.exists(os.path.join(_root, script_rel)):
                            errors.append("组件 %r 的必需脚本 %s 路径不存在：%s"
                                          % (comp, script_name, script_rel))

    return errors


def explain(ctx):
    """解析明细：FAIL 时让用户 30 秒自查是不是格式问题，而不是怀疑工具。"""
    lines = ["", "解析明细"]
    if ctx.get("change_dir"):
        tp = os.path.join(ctx["change_dir"], "tasks.md")
        ttext = read(tp)
        if ttext is None:
            lines.append("  tasks.md: 读不到 %s" % tp)
        else:
            c = count_checkboxes(ttext)
            lines.append("  tasks.md: done=%d todo=%d other=%d，列表符=%s"
                         % (c["done"], c["todo"], c["other"],
                            ",".join(detect_bullet_styles(ttext)) or "无"))
    if ctx.get("ledger"):
        ltext = read(ctx["ledger"])
        lines.append("  ledger complete 行：%s"
                     % ((",".join(sorted(_ledger_completed_ids(ltext))) or "无")
                        if ltext is not None else "读不出"))
    if ctx.get("plan"):
        ptext = read(ctx["plan"])
        secs = (re.findall(r"^#{1,6}[ \t]+(.+?)[ \t]*$", ptext, re.M)
                if ptext is not None else [])
        lines.append("  计划段名：%s"
                     % ((", ".join(secs[:14]) or "无")
                        if ptext is not None else "读不出"))
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def run(change=None, plan=None, scale=None, root=None, expect_archive=False):
    wf = load_workflow()
    root = os.path.abspath(root or os.getcwd())
    env = detect_env(root)

    # 相对路径按 --root 解析，不按进程 cwd——否则跨目录核对会静默指向错误文件
    if plan and not os.path.isabs(plan):
        plan = os.path.join(root, plan)

    scale_key, scale_valid = normalize_scale(wf, scale)

    # --change 只允许单段名字：`../../docs` 会让 change_dir 逃出 openspec/changes/
    change_ok = bool(change) and re.match(r"^[A-Za-z0-9][A-Za-z0-9._-]*$", change or "")
    change_invalid = bool(change) and not change_ok

    ctx = {
        "root": root,
        "change": change,
        "change_dir": (os.path.join(root, "openspec", "changes", change)
                       if change and change_ok else None),
        "change_invalid": change_invalid,
        "plan": os.path.abspath(plan) if plan else None,
        "scale": scale,
        "scale_key": scale_key,
        "scale_valid": scale_valid,
        "today": datetime.now().strftime("%Y-%m-%d"),
        # 环境探测必须真实发生：旧实现写死 True，导致 --root 指向不存在目录
        # 也报 `[ OK ] 环境已探测`（实测 rc=0）。
        "env_probed": os.path.isdir(root),
        "env_summary": env["summary"],
        "git": env["git"],
        "openspec": env["openspec"],
        "expect_archive": expect_archive,
        "trim": None,
    }
    ctx["workspace"] = find_workspace(root, ctx["plan"]) if ctx["plan"] else None
    ctx["ledger"] = (os.path.join(ctx["workspace"], "progress.md")
                     if ctx["workspace"] and os.path.exists(
                         os.path.join(ctx["workspace"], "progress.md")) else None)
    # 不给 --plan 时也要能找到账本，否则「规模与账本一致」交叉校验会短路，
    # 形成「声称 readonly + 不传计划 ⇒ rc=0」的后门（P6 A-2）。
    ctx["ledger_ambiguous"] = None
    if ctx["ledger"] is None:
        discovered, ambiguity = discover_ledger(root)
        if discovered:
            ctx["ledger"] = discovered
        elif ambiguity:
            ctx["ledger_ambiguous"] = ambiguity

    rep = Report()

    # P3-3：消费 ctx["ledger_ambiguous"]（旧实现只写不读，歧义静默）。
    # 多账本并存导致 discover_ledger 无法唯一确定账本时，以 WARN 告知，
    # 不致 rc≠0（WARN 不触发失败），保持 fail-closed 粒度仅补通知。
    if ctx.get("ledger_ambiguous"):
        rep.add(gate_label(wf, "S0"), "账本唯一性", WARN,
                "[warn:ledger_ambiguous] %s —— 多个 progress.md 候选，未做规模与账本交叉校验"
                % ctx["ledger_ambiguous"],
                id="S0.LEDGER_AMBIGUOUS", reason="soft:ledger_ambiguous")

    # --change 名非法：先记一条，后续 S2 据此 FAIL
    if change_invalid:
        rep.add(gate_label(wf, "S0"), "变更名格式合法", FAIL,
                "[malformed:change_name] %r 不是合法的变更名（只允许字母数字与 ._-），"
                "且 `..` 会逃出 openspec/changes/" % change,
                id="S0.CHANGE_NAME", reason="malformed:change_name")

    # 只读误标防护（R-A）：声明 readonly 却给了 change/plan —— 自相矛盾。
    #
    # 为什么是 **FAIL** 而不是 WARN（P6 复核审查 A-2）：
    # 只读任务按 trim_matrix 不产生 change 也不产生 plan，所以「声明只读
    # 却指名变更/计划」不是「将来才成立的可宽限项」，而是**当下的矛盾**。
    # 判 WARN 时它不足以让 rc≠0——实测「有未完成任务 + readonly + 不给 --plan」
    # 得到 rc=0，唯一信号就是这条 WARN。那就是一道后门。
    if scale_valid and scale_key == "readonly" and (change or plan):
        rep.add(gate_label(wf, "S0"), "规模标注自洽", FAIL,
                "[malformed:readonly_mismatch] 声明 --scale readonly 却提供了 "
                "%s——只读任务按 trim_matrix 不产生 change 也不产生 plan；"
                "这是自相矛盾的声明，且 readonly 会跳过 S1-S8 全部门禁"
                % "/".join(x for x in (("--change" if change else None),
                                       ("--plan" if plan else None)) if x),
                id="S0.SCALE_MISMATCH", reason="malformed:readonly_mismatch")

    _BY_ID = {"S0": check_S0, "S1": check_S1, "S2": check_S2, "S3": check_S3,
              "S4": check_S4, "S5": check_S5, "S6": check_S6, "S7": check_S7,
              "S8": check_S8}
    # 检查器注册表与声明源必须一致（--self-check 也查这条，这里防运行时缺项）
    stage_ids = [s["id"] for s in wf["stages"]]
    checkers = [(_BY_ID[sid], sid) for sid in stage_ids if sid in _BY_ID]

    for fn, sid in checkers:
        trim = "必" if not scale_valid else trim_of(wf, scale_key, sid)
        if trim == "-":
            rep.add(gate_label(wf, sid), "阶段已裁剪（trim_matrix）", SKIP,
                    "[inapplicable:trim] %s 在 scale=%s 下为 '-'"
                    % (sid, scale_key or "-"),
                    id="%s.TRIM" % sid, reason="inapplicable:trim")
            continue
        ctx["trim"] = trim or "必"
        before = len(rep.items)
        try:
            fn(ctx, rep, wf)
        except Exception as exc:                     # 单阶段异常不拖垮整体
            rep.add(gate_label(wf, sid), "执行异常", FAIL,
                    "[unverifiable:exception] %s: %s" % (type(exc).__name__, exc),
                    id="%s.EXCEPTION" % sid, reason="unverifiable:exception")
        # INV-R1 无静默：未被裁剪的阶段必须至少产出一条检查项。
        # 这一条独立于各检查器实现——即使未来某人又写了一处提前 return 也不会静默。
        if len(rep.items) == before:
            rep.add(gate_label(wf, sid), "阶段未产出检查项", FAIL,
                    "[unverifiable:no_items] 该阶段在被裁剪之外却没有任何检查项——"
                    "疑似检查器提前返回",
                    id="%s.STAGE_EMPTY" % sid, reason="unverifiable:no_items")

    # 账本规模与 --scale 交叉校验（R-B）：只靠调用方自报挡不住「标 readonly 逃门禁」
    if scale_valid and ctx["ledger"]:
        _apply_ledger_scale_conflict(ctx, rep, wf, scale_key)

    rep.enforce_reasons()
    return rep, ctx


# 规模标签 ↔ 英文键的映射。
#
# 为什么需要它（P6 复核审查 A-3）：
#   `templates/progress.md` 规定 `## Scale` 填**中文**
#   （`<只读 | 轻量 | 中任务 | 大任务 | Bug>`），而旧实现只认英文键。
#   双向都错：填空模板会被正则命中 `Bug` 判成 scale=bug（假红）；
#   如实填「轻量」则正则不命中、检测静默 return（假绿）。
SCALE_LABEL = {
    "只读": "readonly",
    "轻量": "light",
    "中任务": "medium",
    "大任务": "large",
    "bug": "bug",
}


def parse_scale_section(text):
    """从 `## Scale` 段解析规模键。无法确定时返回 None。

    三条规则：
      1. **先剥模板占位符**：`<只读 | 轻量 | ... | Bug>` 是待填格式，
         不是真实取值。不剥会让「照抄模板」被判 scale=bug 冲突。
      2. 同时接受中文标签与英文键（见 SCALE_LABEL）。
      3. **出现多个不同规模 → 返回 None**（视为无法确定，不猜）。
         猜错的代价是「降级检测」失效或误报冲突，两个方向都坏。

    段缺失或只有占位符时返回 None——调用方据此跳过检查（不是判冲突）。
    """
    body = section_body(text or "", "Scale")
    if not body:
        return None

    # 1. 剥模板占位符：`<...>` 内的内容是待填说明，不是取值
    clean = re.sub(r"<[^>\n]*>", " ", body)

    found = set()
    # 中文标签（先匹配长的，避免「大任务」被「任务」之类吃掉）
    for label in sorted(SCALE_LABEL, key=len, reverse=True):
        if label in clean.lower():
            found.add(SCALE_LABEL[label])
    # 英文键（整词，避免 `bug` 命中 `debug`）
    for key in ("readonly", "light", "medium", "large", "bug"):
        if re.search(r"\b%s\b" % key, clean, re.I):
            found.add(key)

    if len(found) != 1:
        return None          # 0 个 = 未填；多个 = 歧义，都不猜
    return found.pop()


def _apply_ledger_scale_conflict(ctx, rep, wf, scale_key):
    """账本记录的 ## Scale 与 --scale 不一致 → FAIL。

    账本是 S0 的产出，留了当时的分类结论；与最终 --scale 冲突说明中途改了口径，
    而规格明确「规模只能升级不能降级」（workflow.json scale.ratchet）。
    """
    ltext = read(ctx["ledger"])
    if ltext is None:
        # 账本存在但读不出：交叉校验「查不了」→ FAIL（A-9）。
        # 旧实现压成空串后静默 return，而 readonly 下账本是唯一检查对象，
        # 整次核对就此空转还 rc=0（实测后门）。
        rep.add(gate_label(wf, "S0"), "规模与账本一致", FAIL,
                "[malformed:ledger_unreadable] 账本存在但读不出，规模交叉校验无从进行",
                id="S0.SCALE_CONFLICT", reason="malformed:ledger_unreadable")
        return
    recorded = parse_scale_section(ltext)
    if recorded is None:
        # 未填或歧义：不判冲突（无法确定就不猜），但要留痕。
        # 三态再分（A-9）：缺段与「有段但查不出」是两种失败——
        #   缺段：readonly 下账本是唯一检查对象，缺段=整次核对空转 → FAIL；
        #         其他规模下账本缺段属历史格式包袱，维持静默（防大面积假红，
        #         proj 夹具的常规账本就没有 Scale 段）。
        #   有段但未填/歧义/只有占位符：查了但查不出结论 → WARN（A-15 裁决范围，不升级）。
        if not section_body(ltext, "Scale"):
            if scale_key == "readonly":
                rep.add(gate_label(wf, "S0"), "规模与账本一致", FAIL,
                        "[missing:scale_section] 账本缺 `## Scale` 段——S0 产出缺失"
                        "（readonly 下账本唯一，缺段即整次核对空转）",
                        id="S0.SCALE_CONFLICT", reason="missing:scale_section")
        else:
            rep.add(gate_label(wf, "S0"), "规模与账本一致", WARN,
                    "[soft:scale_unparsable] 账本 `## Scale` 段无法确定规模"
                    "（未填 / 填了多个 / 只有模板占位符）",
                    id="S0.SCALE_CONFLICT", reason="soft:scale_unparsable")
        return
    if recorded == scale_key:
        return
    order = {k: i for i, k in enumerate(scale_keys(wf))}
    downgrade = order.get(scale_key, 99) < order.get(recorded, -1)
    rep.add(gate_label(wf, "S0"), "规模与账本一致", FAIL,
            "[malformed:scale_conflict] 账本记录 scale=%s，而 --scale=%s%s；"
            "规模只能升级不能降级——请修正 --scale 或更新账本"
            % (recorded, scale_key, "（疑似降级）" if downgrade else ""),
            id="S0.SCALE_CONFLICT", reason="malformed:scale_conflict")


def main(argv=None):
    _force_utf8_stdout()
    wf = load_workflow()
    ap = argparse.ArgumentParser(description="工作流阶段完整性核对")
    ap.add_argument("--change", help="OpenSpec change 名")
    ap.add_argument("--plan", help="实施计划文档路径")
    ap.add_argument("--scale", help="规模：%s" % "|".join(scale_keys(wf)))
    ap.add_argument("--root", help="项目根（默认当前目录）")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    ap.add_argument("--expect-archive", action="store_true",
                    help="此刻正在归档：归档目录缺失判 FAIL 而非 WARN")
    ap.add_argument("--self-check", action="store_true",
                    help="只校验配置与代码的一致性（不核项目内容），rc=2 表示有 drift")
    ap.add_argument("--explain", action="store_true",
                    help="打印 tasks.md / 账本 / 计划的解析明细，便于自查格式问题")
    args = ap.parse_args(argv)

    # 非法 --scale 走参数错误（rc=2），与「内容不合格」（rc=1）区分开。
    # 不做宽容匹配：`Medium`/` medium` 一律拒绝——门禁参数不接受猜测，
    # 否则一次笔误会变成一次未声明的门禁裁剪，而报告里看不出异常。
    # 这里显式 print + return 2 而非 argparse.error()（后者抛 SystemExit），
    # 使 main() 保持「返回码函数」契约，便于被测试与库调用方直接消费。
    if args.scale is not None:
        _, valid = normalize_scale(wf, args.scale)
        if not valid:
            print("参数错误：--scale 取值非法：%r（可选：%s）"
                  % (args.scale, "|".join(scale_keys(wf))), file=sys.stderr)
            return 2

    if args.self_check:
        errors = self_check(wf)
        print("配置自检")
        if errors:
            for e in errors:
                print("  [DRIFT] %s" % e)
            print("\n结论：发现 %d 处配置与代码漂移。" % len(errors))
            return 2
        print("  [ OK ] 配置与代码一致")
        print("\n结论：无漂移。")
        return 0

    rep, ctx = run(change=args.change, plan=args.plan,
                   scale=args.scale, root=args.root,
                   expect_archive=args.expect_archive)

    if args.json:
        print(json.dumps({
            "root": ctx["root"],
            "change": ctx["change"],
            "plan": ctx["plan"],
            "scale": ctx["scale_key"],
            "env": {"git": ctx["git"], "openspec": ctx["openspec"]},
            "workspace": ctx["workspace"],
            "summary": {s: rep.count(s) for s in (OK, WARN, FAIL, SKIP)},
            "items": rep.items,
        }, ensure_ascii=False, indent=2))
    else:
        print("工作流完整性核对")
        print("项目根：%s" % ctx["root"])
        print("变更：%s | 计划：%s | 规模：%s" % (
            ctx["change"] or "-", ctx["plan"] or "-", ctx["scale_key"] or "-"))
        print("环境：%s" % ctx["env_summary"])
        if args.explain:
            print(explain(ctx))
        print(rep.render())
        if rep.has_fail():
            print("\n结论：存在 FAIL 项，不得进入下一阶段。")
        else:
            print("\n结论：无 FAIL 项（WARN 项需人工确认）。")

    return 1 if rep.has_fail() else 0


if __name__ == "__main__":
    sys.exit(main())
