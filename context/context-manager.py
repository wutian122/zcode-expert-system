#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import json
import os
import sys
from datetime import datetime
from pathlib import Path

# 上下文压缩阈值：当累积摘要长度超过此值时，触发 LLM 摘要压缩
CONTEXT_SUMMARY_THRESHOLD = 1000  # 字符数
MAX_SUMMARY_LENGTH = 500  # 压缩后摘要最大长度

# 结果文件保留上限：超出后按修改时间删除最旧的，避免无限增长
MAX_RESULT_FILES = 200


def _default_store_dir():
    """按宿主隔离运行时上下文，避免三平台共用同一个 200 文件 LRU。

    优先级：
      1. ZCODE_EXPERT_CONTEXT_DIR（显式覆盖；测试与自定义部署使用）
      2. Qoder Desktop：QODER_HOME/expert-system/context
      3. Claude Code：~/.claude/expert-system/context
      4. ZCode / 默认：~/.zcode/expert-system/context（保持历史行为）

    仍然放在用户目录，避免写入可能只读的插件安装目录。
    """
    override = os.environ.get("ZCODE_EXPERT_CONTEXT_DIR")
    if override:
        return os.path.abspath(os.path.expanduser(override))

    home = os.path.expanduser("~")
    qoder_home = os.environ.get("QODER_HOME")
    if qoder_home:
        base = os.path.abspath(os.path.expanduser(qoder_home))
    elif os.environ.get("CLAUDE_PLUGIN_ROOT"):
        base = os.path.join(home, ".claude")
    else:
        base = os.path.join(home, ".zcode")
    return os.path.join(base, "expert-system", "context")


def _sanitize_component(value):
    """把调用方传入的标识符收敛为安全的文件名片段。

    task_id / expert_id 是外部输入，直接拼进文件名时若含目录分隔符或
    上级目录记号，会让结果文件落到存储目录之外。此处只保留字母、数字、
    下划线与短横线，其余字符统一替换为下划线；空值回退为下划线。
    """
    if not value:
        return "_"
    keep = []
    for ch in str(value):
        if ch.isalnum() or ch in ("_", "-"):
            keep.append(ch)
        else:
            keep.append("_")
    out = "".join(keep).strip("_")
    return out or "_"


def _warn(msg):
    """诊断输出走 stderr。

    zcode_expert_system.py 以 json.dumps 输出结果，若本模块向 stdout
    打印，会让下游 json.loads 直接失败。
    """
    sys.stderr.write(str(msg).rstrip() + "\n")


# scripts/ 目录一次性入 sys.path（P8 批次四 Task 13 精度项②）：
# 旧实现把 insert 放进 _llm_summarize，每次调用都插一条——本模块会被
# exec_module 反复加载，长会话内路径表持续膨胀。
# 带 not-in 守卫：exec_module 每次加载都会执行模块顶部。
_SCRIPTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)


class ExpertContext:
    def __init__(self, context_dir=None):
        if context_dir is None:
            context_dir = _default_store_dir()
        self.context_dir = context_dir
        os.makedirs(self.context_dir, exist_ok=True)
        self.context_store = {}

    def _prune_result_files(self):
        """结果文件超过 MAX_RESULT_FILES 时，按修改时间删除最旧的一批。

        实现要点：全程用 os.scandir 的 DirEntry（entry.path / entry.stat），
        不对目录列举结果做路径拼接，避免任何「由目录内容构造路径」的写法。
        """
        try:
            files = []
            with os.scandir(self.context_dir) as it:
                for entry in it:
                    name = entry.name
                    if not (name.startswith("result-") and name.endswith(".json")):
                        continue
                    try:
                        if not entry.is_file(follow_symlinks=False):
                            continue
                        files.append((entry.stat(follow_symlinks=False).st_mtime, entry.path))
                    except OSError:
                        continue
            if len(files) <= MAX_RESULT_FILES:
                return
            files.sort()
            overflow = len(files) - MAX_RESULT_FILES
            for _mtime, path in files[:overflow]:
                try:
                    os.remove(path)
                except OSError:
                    continue
        except OSError:
            return

    def _get_result_file_path(self, task_id, expert_id):
        """构造结果文件路径。

        task_id / expert_id 先经白名单清洗（只留字母数字与 -_），
        再逐段校验不含目录分隔符，最后才组合——使穿越在结构上不可能。
        """
        # 微秒精度（P8 批次四 Task 13 精度项①）：秒级时间戳下同 task+expert
        # 同一秒两次 save 会互相覆盖。文件名变长无副作用。
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S%f")
        safe_task = _sanitize_component(task_id)
        safe_expert = _sanitize_component(expert_id)
        filename = "result-" + safe_task + "-" + safe_expert + "-" + timestamp + ".json"

        # 三重守卫：清洗结果必须是纯文件名，不得含任何分隔符或上级记号
        for bad in (os.sep, os.altsep, "/", "\\"):
            if bad and bad in filename:
                raise ValueError("结果文件名含非法分隔符：%r" % filename)
        if filename.startswith(".") or ".." in filename:
            raise ValueError("结果文件名含非法上级记号：%r" % filename)

        return os.path.join(self.context_dir, filename)

    def save_context(self, task_id, expert_id, result):
        result_file = self._get_result_file_path(task_id, expert_id)
        # _get_result_file_path 已保证 filename 只含 [A-Za-z0-9_.-] 且不含 ".."；
        # 经 basename 后再拼接，确保写入目标恒为 context_dir 下的纯文件名。
        safe_name = os.path.basename(result_file)
        if not safe_name or safe_name in (".", "..") or ".." in safe_name:
            raise ValueError("结果文件路径非法：%r" % result_file)
        target = Path(self.context_dir) / safe_name
        target.write_text(json.dumps(result, ensure_ascii=False, indent=2),
                          encoding="utf-8")

        if task_id not in self.context_store:
            self.context_store[task_id] = {
                "task_id": task_id,
                "steps": [],
                "shared_data": {}
            }

        summary = self._generate_summary(result)
        self.context_store[task_id]["steps"].append({
            "expert": expert_id,
            "summary": summary,
            "result_file": result_file,
            "timestamp": datetime.now().isoformat()
        })

        # 容量上限清理（此前 _prune_result_files 定义了却零调用）
        self._prune_result_files()

        # 检查上下文长度，超出阈值时触发压缩
        self._maybe_compress(task_id)

        return result_file

    def _generate_summary(self, result):
        """生成路由结果的语义摘要（L2 修复）。

        旧实现：json.dumps(result) 后硬截 200 字符 —— 产出断头 JSON 片段，
        既不可解析也不含关键信息，摘要名不副实。
        新实现：提取 category/selected_expert/created_at 等关键字段生成短句摘要，
        可被主控/模型快速理解；若 result 非 dict 则退化为 json.dumps 截断。
        """
        if not isinstance(result, dict):
            result_str = json.dumps(result, ensure_ascii=False)
            return result_str[:200] + "..." if len(result_str) > 200 else result_str
        parts = []
        if result.get("category"):
            parts.append("分类=%s" % result["category"])
        if result.get("selected_expert"):
            exp = result["selected_expert"]
            name = exp.get("name") if isinstance(exp, dict) else str(exp)
            parts.append("专家=%s" % name)
        elif result.get("no_expert") or (result.get("confidence") == 0.0 and result.get("selected_expert") is None):
            parts.append("专家=无")
        if result.get("created_at"):
            parts.append("时间=%s" % result["created_at"])
        if not parts:
            # 无可提取字段时退化为短 JSON
            result_str = json.dumps(result, ensure_ascii=False)
            return result_str[:200] + "..." if len(result_str) > 200 else result_str
        return "；".join(parts)

    def _maybe_compress(self, task_id):
        """当上下文摘要长度超过阈值时，对早期步骤进行 LLM 摘要压缩。"""
        context = self.context_store.get(task_id)
        if not context:
            return

        steps = context.get("steps", [])
        if len(steps) <= 2:
            # 步骤太少，无需压缩
            return

        # 计算当前摘要总长度
        total_length = sum(len(s.get("summary", "")) for s in steps)
        if total_length <= CONTEXT_SUMMARY_THRESHOLD:
            return

        # 压缩：保留最后 2 个步骤的完整摘要，将之前的步骤合并为一个压缩摘要
        keep_count = 2
        recent_steps = steps[-keep_count:]
        old_steps = steps[:-keep_count]

        if not old_steps:
            return

        # 生成压缩摘要
        old_summaries = [f"步骤{i}: {s['summary']}" for i, s in enumerate(old_steps)]
        combined = "\n".join(old_summaries)

        try:
            compressed = self._llm_summarize(combined)
        except Exception:
            # LLM 不可用时，截断压缩
            compressed = combined[:MAX_SUMMARY_LENGTH] + "..."

        # 重建步骤列表
        new_steps = [
            {
                "expert": "compressed",
                "summary": f"[历史摘要] {compressed}",
                "result_file": "compressed",
                "timestamp": datetime.now().isoformat()
            }
        ] + recent_steps

        context["steps"] = new_steps
        # 走 stderr：stdout 属于调用方的 JSON 输出通道
        _warn("[context-manager] 任务 %s 上下文已压缩：%d 个步骤合并为 1 个摘要"
              % (task_id, len(old_steps)))

    def _llm_summarize(self, text):
        """使用 LLM 生成摘要。如果 LLM 不可用，返回截断文本。"""
        try:
            # scripts 路径由模块顶部一次性注入（见 _SCRIPTS_DIR），不再逐调用 insert
            from llm_client import _call_llm
            content = _call_llm(
                [
                    {"role": "system", "content": "你是一个上下文摘要专家。请将以下多个步骤的执行摘要压缩为一段不超过 200 字的中文摘要，保留关键信息和结果。"},
                    {"role": "user", "content": text},
                ],
                temperature=0.1,
                max_tokens=300,
            )
            if content:
                return content.strip()
        except Exception:
            pass
        # 降级：截断
        return text[:MAX_SUMMARY_LENGTH] + "..."

    def get_context(self, task_id):
        return self.context_store.get(task_id, {})

    def get_context_summary(self, task_id):
        """取任务历史摘要。

        内存 miss 时扫盘回填（P8 批次四 Task 13 接线）：本模块每次都被
        exec_module 全新加载（zcode_expert_system.py :806-812/:832-834），
        内存 store 必空——旧实现只读内存，摘要恒空串，宣称的
        「前序上下文注入」是死特性。磁盘 result-*.json 是第二证据源，
        load_result 从此有真实调用方。
        """
        context = self.get_context(task_id)
        if not context:
            context = self._load_task_from_disk(task_id)
            if not context:
                return ""

        steps = context.get("steps", [])
        summaries = ["[" + step['expert'] + "] " + step['summary'] for step in steps]
        return "\n".join(summaries)

    def _load_task_from_disk(self, task_id):
        """内存 miss 时按 task_id 扫 result-*.json 回填 store（跨进程接线的另一半）。

        文件名中的 task 段经 _sanitize_component 清洗（:26-42），按同一函数
        清洗后做前缀预筛；命中是否真属本任务以存盘 result 的 task_id 字段
        为准（防 `t1` 前缀误中 `t1-extra`），无 task_id 字段的旧文件按前缀
        放行。坏文件跳过，不让单个损坏 result 毁掉整个摘要。
        回填按 mtime 旧→新排列，与 save_context 的 append 顺序一致；
        容量沿用 MAX_RESULT_FILES 上限。
        """
        safe_task = _sanitize_component(task_id)
        prefix = "result-" + safe_task + "-"
        hits = []
        try:
            with os.scandir(self.context_dir) as it:
                for entry in it:
                    name = entry.name
                    if not (name.startswith(prefix) and name.endswith(".json")):
                        continue
                    try:
                        if not entry.is_file(follow_symlinks=False):
                            continue
                        hits.append((entry.stat(follow_symlinks=False).st_mtime,
                                     entry.path))
                    except OSError:
                        continue
        except OSError:
            return {}
        hits.sort()
        steps = []
        for _mtime, path in hits[-MAX_RESULT_FILES:]:
            try:
                result = self.load_result(path)
            except (OSError, ValueError):
                continue
            stored_id = result.get("task_id")
            if stored_id is not None and stored_id != task_id:
                continue          # 前缀误中（如 t1 vs t1-extra）：以存盘字段为准
            sel = result.get("selected_expert")
            expert = _sanitize_component(
                sel.get("id", "none") if isinstance(sel, dict)
                else str(sel or "none"))
            steps.append({
                "expert": expert,
                "summary": self._generate_summary(result),
                "result_file": path,
                "timestamp": datetime.fromtimestamp(_mtime).isoformat(),
            })
        if not steps:
            return {}
        self.context_store[task_id] = {
            "task_id": task_id, "steps": steps, "shared_data": {}}
        return self.context_store[task_id]

    def load_result(self, result_file):
        with open(result_file, 'r', encoding='utf-8') as f:
            return json.load(f)

    def clear_task(self, task_id):
        if task_id in self.context_store:
            del self.context_store[task_id]
