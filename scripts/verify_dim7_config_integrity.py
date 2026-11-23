#!/usr/bin/env python3
"""维度7：配置数据完整性（categories/experts/workflow）+ 路由覆盖 全量校验脚本。

输出只报告：真缺陷 / 行为异常，带 file:line，区分「真缺陷」与「设计如此/已知取舍」。
每条 finding 给出复现命令或缺口证据。
"""
import json
import os
import re
import sys
from collections import Counter

# Windows 控制台默认 GBK，强制 UTF-8 输出避免中文乱码
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = "E:/zcode-expert-system"
CONFIG = os.path.join(ROOT, "config")
AGENTS = os.path.join(ROOT, "agents")

failures = []   # 真缺陷 / 行为异常
notes = []      # 设计如此 / 已知取舍（供参考，不算缺陷）


def fail(title, file, line, detail, suggestion, severity="high"):
    failures.append({
        "title": title, "file": file, "line": line,
        "detail": detail, "suggestion": suggestion, "severity": severity,
    })


def note(title, detail):
    notes.append({"title": title, "detail": detail})


# ---------------------------------------------------------------------------
# 1. 载入 JSON（语法/编码检查）
# ---------------------------------------------------------------------------
json_files = {
    "categories": os.path.join(CONFIG, "categories.json"),
    "experts": os.path.join(CONFIG, "experts.json"),
    "workflow": os.path.join(CONFIG, "workflow.json"),
}
loaded = {}
for key, path in json_files.items():
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            loaded[key] = json.load(f)
    except UnicodeDecodeError as e:
        fail("JSON 编码问题（非 UTF-8/无 BOM 或含非法字符）", path, 0,
             f"{key}.json 编码读取失败：{e}", "将文件转码为 UTF-8（无 BOM）", "critical")
        sys.exit(1)
    except json.JSONDecodeError as e:
        fail("JSON 语法错误", path, getattr(e, "lineno", 0),
             f"{key}.json 第 {getattr(e, 'lineno', 0)} 行第 {getattr(e, 'colno', 0)} 列：{e.msg}",
             "修复 JSON 语法", "critical")
        sys.exit(1)

categories = loaded["categories"]
experts_data = loaded["experts"]
workflow = loaded["workflow"]

# ---------------------------------------------------------------------------
# 校验 1：categories 数 = 32？experts 总数 = 331？
# ---------------------------------------------------------------------------
# categories.json 顶层本身就是按类目 id 键的对象（无嵌套 "categories" 键）
cat_dict = categories if isinstance(categories, dict) else {}
if not cat_dict:
    fail("categories 不是对象或为空", os.path.join(CONFIG, "categories.json"), 0,
         "categories.json 顶层不是 dict，无法计数与索引", "检查 categories.json 结构", "critical")
else:
    cat_count = len(cat_dict)
    note(f"categories 实际数量 = {cat_count}（要求 32）",
         f"categories.json 中共 {cat_count} 个类目键")
    if cat_count != 32:
        fail("categories 数不等于 32", os.path.join(CONFIG, "categories.json"), 0,
             f"实际 {cat_count} 个，期望 32 个", "核对类目增删，补全或移除多余类目", "high")

experts = experts_data.get("experts", [])
if not isinstance(experts, list):
    fail("experts 不是数组", os.path.join(CONFIG, "experts.json"), 0,
         "experts 字段缺失或不是 list", "检查 experts.json 结构", "critical")
else:
    expert_total = len(experts)
    declared_total = experts_data.get("total_experts")
    note(f"experts 实际条目数 = {expert_total}，声明 total_experts = {declared_total}",
         f"experts.json experts 数组长度 {expert_total}")
    if expert_total != 331:
        fail("experts 总数不等于 331", os.path.join(CONFIG, "experts.json"), 0,
             f"实际 {expert_total} 个，期望 331 个", "核对专家增删，补全或移除多余专家", "high")
    if declared_total is not None and declared_total != expert_total:
        fail("total_experts 声明与实际条目数不一致", os.path.join(CONFIG, "experts.json"), 3,
             f"声明 {declared_total}，实际 {expert_total}", "同步 total_experts 字段", "high")

# ---------------------------------------------------------------------------
# 建立索引
# ---------------------------------------------------------------------------
cat_ids = set(cat_dict.keys()) if isinstance(cat_dict, dict) else set()
# 类目 id 是 dict 的 key，不是值内字段
cat_by_id = {cid: c for cid, c in cat_dict.items()}

# experts 索引：id -> 条目
expert_by_id = {}
dup_expert_ids = []
for i, e in enumerate(experts):
    eid = e.get("id")
    if eid in expert_by_id:
        dup_expert_ids.append((eid, i + 1, expert_by_id[eid][1] + 1))
    expert_by_id[eid] = (e, i)

# manager 索引：manager_id -> 条目（在 categories 里）
manager_ids = set()
for cid, c in cat_by_id.items():
    mgr = c.get("manager")
    if mgr:
        manager_ids.add(mgr)

# ---------------------------------------------------------------------------
# 校验 2：每个 expert 的 category/manager 引用是否都指向存在的 category；孤儿专家/空类目
# ---------------------------------------------------------------------------
orphan_experts = []      # expert.category 指向不存在的 category
empty_categories = []    # category 无专家
for eid, (e, idx) in expert_by_id.items():
    cat = e.get("category")
    if cat not in cat_by_id:
        orphan_experts.append((eid, cat, idx + 1))

if orphan_experts:
    for eid, cat, line in orphan_experts:
        fail("孤儿专家：category 引用不存在的类目", os.path.join(CONFIG, "experts.json"), line,
             f"expert {eid} 的 category='{cat}' 在 categories.json 中不存在",
             "补全该类目或修正 expert 的 category 引用", "high")

# 每个 category 的专家计数
cat_expert_count = {cid: 0 for cid in cat_ids}
for eid, (e, idx) in expert_by_id.items():
    cat = e.get("category")
    if cat in cat_expert_count:
        cat_expert_count[cat] += 1

for cid, c in cat_by_id.items():
    declared_count = c.get("expert_count")
    actual_count = cat_expert_count.get(cid, 0)
    if declared_count is not None and declared_count != actual_count:
        fail("类目 expert_count 声明与实际不符", os.path.join(CONFIG, "categories.json"), 0,
             f"类目 {cid} 声明 expert_count={declared_count}，实际引用该类目的 expert 有 {actual_count} 个",
             "同步 categories.json 中的 expert_count", "high")
    if actual_count == 0:
        empty_categories.append(cid)
        fail("空类目：无专家归属", os.path.join(CONFIG, "categories.json"), 0,
             f"类目 {cid}（{c.get('name')}）无任何 expert 引用",
             "添加专家归入该类目或移除空类目", "medium")

# ---------------------------------------------------------------------------
# 校验 3：manager_id / expert_id 唯一性、无重复
# ---------------------------------------------------------------------------
if dup_expert_ids:
    for eid, line1, line2 in dup_expert_ids:
        fail("重复 expert_id", os.path.join(CONFIG, "experts.json"), line1,
             f"expert_id '{eid}' 在第 {line1} 行与第 {line2} 行重复出现",
             "删除重复条目或重命名 id", "critical")

# manager_id 唯一性（categories 里）
dup_manager_ids = [m for m, c in Counter([c.get("manager") for c in cat_by_id.values() if c.get("manager")]).items() if c > 1]
for m in dup_manager_ids:
    fail("重复 manager_id", os.path.join(CONFIG, "categories.json"), 0,
         f"manager_id '{m}' 在多个类目中重复出现", "修正重复的 manager 引用", "critical")

# manager 引用是否指向存在的 manager agent 文件
missing_manager_agents = []
for mgr in manager_ids:
    mgr_file = os.path.join(AGENTS, f"{mgr}.md")
    if not os.path.exists(mgr_file):
        missing_manager_agents.append(mgr)
if missing_manager_agents:
    for mgr in missing_manager_agents:
        fail("manager 对应的 agent 文件缺失", os.path.join(CONFIG, "categories.json"), 0,
             f"类目声明 manager='{mgr}'，但 agents/{mgr}.md 不存在",
             "补充 manager agent 文件或修正 manager 引用", "high")

# ---------------------------------------------------------------------------
# 校验 4：每个 category 至少有一个 manager-* agent（对照 agents/ 目录）
# ---------------------------------------------------------------------------
agent_files = set(os.listdir(AGENTS)) if os.path.isdir(AGENTS) else set()
manager_agent_files = {f for f in agent_files if f.startswith("manager-") and f.endswith(".md")}
for cid, c in cat_by_id.items():
    mgr = c.get("manager")
    if not mgr:
        fail("类目缺少 manager 字段", os.path.join(CONFIG, "categories.json"), 0,
             f"类目 {cid} 未声明 manager，不符合「每个 category 至少一个 manager-* agent」",
             "为该类目补充 manager 字段", "high")
    elif f"{mgr}.md" not in manager_agent_files:
        fail("类目 manager 无对应 agent 文件", os.path.join(CONFIG, "categories.json"), 0,
             f"类目 {cid} 的 manager='{mgr}' 在 agents/ 目录下无对应 .md 文件",
             "补充 manager agent 文件或修正 manager 字段", "high")

# ---------------------------------------------------------------------------
# 校验 5：workflow.json 内部引用完整性
# ---------------------------------------------------------------------------
wf_components = workflow.get("component_registry", {})
wf_stages = workflow.get("stages", [])
wf_gates = workflow.get("gates", {})

# 5a：stages 引用的 gate 是否存在
for s in wf_stages:
    gate = s.get("gate")
    if gate and gate not in wf_gates:
        fail("stage 引用的 gate 不存在", os.path.join(CONFIG, "workflow.json"), 0,
             f"stage {s.get('id')} 的 gate='{gate}' 在 gates 中未定义",
             "补全 gate 定义或修正 stage 的 gate 引用", "high")

# 5b：gates 引用的 component 是否存在（检查 gates 里是否有 component 字段，以及 stages 的 components）
# gates 本身一般不直接引用 component，但 stages 的 components 引用 component_registry
registered_components = set(wf_components.keys())
for s in wf_stages:
    for comp in s.get("components", []):
        if comp not in registered_components:
            fail("stage 引用的 component 未在 component_registry 登记", os.path.join(CONFIG, "workflow.json"), 0,
                 f"stage {s.get('id')} 的 component='{comp}' 未在 component_registry 中登记",
                 "在 component_registry 中补登记或移除该引用", "high")

# 5c：trim_matrix 是否覆盖所有 scale × stage 组合
scale_list = [k for k in workflow.get("scale", {}).keys() if not k.startswith("$")]
stage_ids = [s.get("id") for s in wf_stages]
trim_matrix = workflow.get("trim_matrix", {})
missing_trim = []
for sc in scale_list:
    row = trim_matrix.get(sc)
    if not isinstance(row, dict):
        missing_trim.append(f"scale '{sc}' 完全缺失")
        continue
    for st in stage_ids:
        if st not in row:
            missing_trim.append(f"scale '{sc}' × stage '{st}'")
if missing_trim:
    for item in missing_trim:
        fail("trim_matrix 缺格", os.path.join(CONFIG, "workflow.json"), 0,
             f"trim_matrix 未覆盖 {item}", "补全 trim_matrix 中对应 scale×stage 的标记（必/简/条/-）", "high")

# ---------------------------------------------------------------------------
# 校验 6：agents/ 目录下 .md 的 name 与 experts.json 的 expert_name 是否对得上
# ---------------------------------------------------------------------------
# experts.json 里每个 expert 有 id、name、file。按 file 匹配 agents/ 目录下的 .md，比对 frontmatter name。
def extract_frontmatter_name(path):
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            first = f.readline()
            if not first.strip().startswith("---"):
                return None, "非 frontmatter 开头（无 ---）"
            lines = []
            for line in f:
                lines.append(line)
                if line.strip() == "---":
                    break
            else:
                return None, "未闭合的 frontmatter"
            block = "".join(lines)
            m = re.search(r"^name:\s*(.+)$", block, re.MULTILINE)
            if m:
                return m.group(1).strip().strip('"').strip("'"), None
            return None, "frontmatter 中无 name 字段"
    except Exception as e:
        return None, f"读取失败：{e}"

mismatch_name = []
missing_agent_file = []
expert_files_in_json = set()
for eid, (e, idx) in expert_by_id.items():
    ef = e.get("file")
    if not ef:
        continue
    expert_files_in_json.add(ef)
    agent_path = os.path.join(AGENTS, ef)
    if not os.path.exists(agent_path):
        missing_agent_file.append((ef, eid, idx + 1))
        continue
    fname, err = extract_frontmatter_name(agent_path)
    if err:
        mismatch_name.append((ef, eid, idx + 1, f"frontmatter 解析异常：{err}", None))
    elif fname != e.get("name"):
        mismatch_name.append((ef, eid, idx + 1,
                              f"agents 文件 frontmatter name='{fname}' 与 experts.json name='{e.get('name')}' 不一致",
                              f"agents/中 name='{fname}'"))

if missing_agent_file:
    for ef, eid, line in missing_agent_file:
        fail("expert 声明的 agent 文件缺失", os.path.join(CONFIG, "experts.json"), line,
             f"expert {eid} 的 file='{ef}' 在 agents/ 目录下不存在",
             "补充 agent 文件或修正 experts.json 的 file 字段", "high")

for ef, eid, line, detail, actual in mismatch_name:
    fail("agent 文件 name 与 experts.json expert_name 不一致", os.path.join(CONFIG, "experts.json"), line,
         f"{detail}（文件 {ef}）", f"将 agents/{ef} 的 name 统一为 '{eid}' 对应的 experts.json name，或反之", "medium")

# 反向：agents/ 目录下存在但 experts.json 未声明的 expert .md 文件
agent_expert_files = {f for f in agent_files if f.startswith("expert-") and f.endswith(".md")}
undeclared_agent_files = agent_expert_files - expert_files_in_json
for f in sorted(undeclared_agent_files):
    fail("agents/ 目录下存在未在 experts.json 声明的 expert 文件", os.path.join(AGENTS, f), 0,
         f"agents/{f} 存在但 experts.json 中无对应 file 条目",
         "在 experts.json 中补全该 expert 声明，或移除孤立文件", "medium")

# manager 文件 name 与 categories manager 字段对齐（补充检查，增值）
manager_name_mismatch = []
for cid, c in cat_by_id.items():
    mgr = c.get("manager")
    if not mgr:
        continue
    mgr_path = os.path.join(AGENTS, f"{mgr}.md")
    if not os.path.exists(mgr_path):
        continue
    fname, err = extract_frontmatter_name(mgr_path)
    if err:
        manager_name_mismatch.append((mgr, f"frontmatter 解析异常：{err}"))
    elif fname != mgr:
        manager_name_mismatch.append((mgr, f"agents/{mgr}.md frontmatter name='{fname}' 与 categories manager='{mgr}' 不一致"))
for mgr, detail in manager_name_mismatch:
    fail("manager agent 文件 name 与 categories manager 字段不一致", os.path.join(CONFIG, "categories.json"), 0,
         detail, "统一两边的 manager 名称", "medium")

# ---------------------------------------------------------------------------
# 输出结果
# ---------------------------------------------------------------------------
print("=" * 70)
print("维度7 配置数据完整性校验报告")
print("=" * 70)
print(f"\n[统计] categories 类目数：{len(cat_ids)}（要求 32）")
print(f"[统计] experts 条目数：{expert_total}（要求 331，声明 total_experts={declared_total}）")
print(f"[统计] agents/ .md 文件数：{len(agent_files)}（其中 manager-* {len(manager_agent_files)} 个，expert-* {len(agent_expert_files)} 个）")

print(f"\n------------------------------------------------------------")
print(f"真缺陷 / 行为异常：共 {len(failures)} 条")
print("------------------------------------------------------------")
if not failures:
    print("（无）")
for f in failures:
    print(f"\n[{f['severity'].upper()}] {f['title']}")
    print(f"  文件：{f['file']}:{f['line']}")
    print(f"  详情：{f['detail']}")
    print(f"  建议：{f['suggestion']}")

print(f"\n------------------------------------------------------------")
print(f"设计如此 / 已知取舍（非缺陷）：共 {len(notes)} 条")
print("------------------------------------------------------------")
if not notes:
    print("（无）")
for n in notes:
    print(f"\n- {n['title']}")
    print(f"  {n['detail']}")

print("\n" + "=" * 70)
if failures:
    print(f"结论：发现 {len(failures)} 个配置完整性缺陷/异常，需修复。")
    sys.exit(1)
else:
    print("结论：配置数据完整性校验全部通过，未发现缺陷。")
    sys.exit(0)
