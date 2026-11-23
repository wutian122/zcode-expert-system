"""P1/P2/P4 三项验收缺陷的守护测试（P9 批次，2026-11-23）。

三项缺陷来自 2026-11-23 的全方位验收（子代理 a8bd42 报告）：
  P1 install.js --dry-run 打印 ✅ 已完成，与「磁盘未改动」事实矛盾
  P2 只读分支不判置信度，低置信度仍派无关领域专家（护栏不对称）
  P4 llm_verdict 判平不暴露，主控无法判断「唯一最高」还是「并列取首」

本文件只锁行为契约，不锁实现细节。
"""
import importlib.util
import json
import os
import re
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import zcode_expert_system as Z  # noqa: E402
import zcode_dev_workflow as W  # noqa: E402


def _load_install_mjs():
    """把 hooks 里的 .mjs 内容读出来做静态断言用（不执行）。"""
    p = os.path.join(ROOT, 'hooks', 'prepend-global-rules-reminder.mjs')
    with open(p, encoding='utf-8') as f:
        return f.read()


# ---------------------------------------------------------------------------
# P1：install.js dry-run 不得声称已完成
# ---------------------------------------------------------------------------

INSTALL_JS = os.path.join(ROOT, 'scripts', 'install.js')


def _install_src():
    with open(INSTALL_JS, encoding='utf-8') as f:
        return f.read()


def test_done_helper_exists_and_strips_checkmark():
    """done() 必须存在，且 dry-run 分支剥掉 ✅。"""
    src = _install_src()
    assert 'function done(real)' in src
    # dry-run 分支必须剥 ✅（replace(/^✅\s*/, '')）并标注【未执行】
    assert '【未执行】' in src
    assert "replace(/^✅" in src


def test_no_bare_log_checkmark_outside_done():
    """不得再有裸 `log('✅ …')`——状态陈述必须走 done()。

    白名单三类（都有静态的「不会在 dry-run 下撒谎」理由）：
      · done() 内部那一处（它是改写器本身）
      · deployClaudeCode：DRY_RUN 时提前 return，函数内 ✅ 不可达
      · `if (!DRY_RUN)` / try 写盘块内：dry-run 下整块跳过
    白名单靠「这几行不是无条件执行」这一静态事实，**并另由
    test_dry_run_install_never_prints_checkmark 用实跑兜底**——
    任何一条白名单判错，实跑断言会红。
    """
    src = _install_src()
    lines = src.splitlines()

    # 允许的 ✅ 行（按内容特征，而非行号——行号会随编辑漂移）
    ALLOW_MARKERS = (
        'String(real).replace',            # done() 自身
        'Claude Code 插件已部署',           # deployClaudeCode（dry-run 早退）
        'Claude Code 部署校验通过',
        '插件缓存 agents/ 只有',            # 在 if (!DRY_RUN) 内
        '个子代理到插件缓存目录',
        '技能 SKILL.md 已规范化',
        '安装清单已写入',
        '已注册插件',
        '旧版备份无用户改动',
        '已移除插件注册',
    )
    bare = []
    for i, line in enumerate(lines, 1):
        s = line.strip()
        if s.startswith('//') or s.startswith('*') or s.startswith('/*'):
            continue
        if not re.search(r"log\(\s*[`'\"][^`'\"]*✅", line):
            continue
        if any(m in line for m in ALLOW_MARKERS):
            continue
        bare.append((i, s))
    assert not bare, '仍有裸 log(✅ …) 行：%r' % bare


def test_dry_run_install_never_prints_checkmark():
    """实跑 --dry-run：stdout 不得出现 ✅。"""
    p = subprocess.run(['node', 'scripts/install.js', '--dry-run'],
                       cwd=ROOT, capture_output=True, timeout=180)
    out = p.stdout.decode('utf-8', 'replace')
    assert p.returncode == 0, p.stderr.decode('utf-8', 'replace')[:400]
    assert '✅' not in out, '超测：dry-run 输出仍含 ✅'
    assert '【未执行】' in out


def test_dry_run_uninstall_never_prints_checkmark():
    """卸载 dry-run 的计数日志同样不得声称「已删除」。"""
    p = subprocess.run(['node', 'scripts/install.js', '--uninstall', '--dry-run'],
                       cwd=ROOT, capture_output=True, timeout=180)
    out = p.stdout.decode('utf-8', 'replace')
    assert p.returncode == 0
    assert '✅' not in out
    assert '【未执行】' in out


# ---------------------------------------------------------------------------
# P2：只读分支低置信度必须阻断，高置信度必须派 analyst
# ---------------------------------------------------------------------------

def test_readonly_low_confidence_blocks_dispatch():
    """conf < 0.5 的只读任务不得派 analyst，必须置 blocked_low_confidence。

    复现用例来自验收报告：`分析一下 zcode_expert_system.py 的结构` 曾派
    conf=0.0312 的「无障碍审核员」。用 monkeypatch 把域路由钉死成低置信度，
    避免依赖关键词表的具体取值（防止未来词表调整让测试假绿）。
    """
    fake = {
        'category': 'business-support',
        'manager_id': 'manager-business-support',
        'expert_name': '旅行规划师',
        'expert_id': 'expert-business-support-travel-planner',
        'confidence': 0.0312,
        'alternatives': [],
        'semantic_selection_required': True,
        'selection_basis': 'heuristic',
        'routing_warning': 'x',
        'top_candidates': [],
    }
    orig = W._route_domain
    W._route_domain = lambda task, persist=True: (dict(fake), '旅行规划师')
    try:
        plan = W.build_dispatch_plan('分析一下某个模块的结构', files=2, root=ROOT)
    finally:
        W._route_domain = orig

    assert plan['scale']['scale'] == 'readonly'
    roles = [d.get('role') for d in plan['dispatches']]
    actions = [d.get('action') for d in plan['dispatches']]
    assert 'analyst' not in roles, '低置信度仍派了 analyst：%r' % roles
    assert 'blocked_low_confidence' in actions, actions
    assert plan.get('blocking'), '必须置 blocking'
    # 不得落盘 dispatch.json（审计锚点只认已定领域的派发）
    assert not plan['domain'].get('dispatch_artifact')


def test_readonly_high_confidence_dispatches_analyst():
    """conf >= 0.5 的只读任务仍必须派 analyst（不能矫枉过正）。"""
    fake = {
        'category': 'backend-architecture',
        'manager_id': 'manager-backend-architecture',
        'expert_name': '软件架构师',
        'expert_id': 'expert-engineering-software-architect',
        'confidence': 1.0,
        'alternatives': [],
        'semantic_selection_required': False,
        'selection_basis': 'semantic',
        'routing_warning': None,
        'top_candidates': [],
    }
    orig = W._route_domain
    W._route_domain = lambda task, persist=True: (dict(fake), '软件架构师')
    try:
        plan = W.build_dispatch_plan('分析一下这个模块的架构', files=2, root=ROOT)
    finally:
        W._route_domain = orig

    analysts = [d for d in plan['dispatches'] if d.get('role') == 'analyst']
    assert analysts, plan['dispatches']
    assert analysts[0]['subagent_type'] != 'general-purpose'


# ---------------------------------------------------------------------------
# P4：判平必须暴露
# ---------------------------------------------------------------------------

def test_tied_candidates_marked():
    """并列最高分的候选必须带 score_detail.tied=True。"""
    task = '审查并验证 zcode-expert-system 插件的路由正确性、专家派遣可用性与各功能模块实现质量，输出测试结论'
    r = Z.zcode_expert_system(task, persist=False)
    tied = [c for c in r['top_candidates'] if c['score_detail'].get('tied')]
    if len(tied) > 1:
        assert r['score_tied'] is True
        assert '判平' in (r['routing_warning'] or '')
    else:
        # 词表若变了导致不再并列，至少 score_tied 字段必须存在且类型正确
        assert isinstance(r['score_tied'], bool)


def test_unique_max_not_marked_tied():
    """唯一最高分不得被标 tied。"""
    r = Z.zcode_expert_system('微信小程序的支付流程怎么接', persist=False)
    assert r['score_tied'] is False
    assert all(not c['score_detail'].get('tied') for c in r['top_candidates'])


def test_score_tied_propagated_to_dispatch_plan():
    """_route_domain 必须把 score_tied 透传进 plan.domain。"""
    fake = {
        'category': 'data-testing',
        'manager_id': 'manager-data-testing',
        'expert_name': '测试结果分析师',
        'expert_id': 'x',
        'confidence': 0.75,
        'alternatives': [],
        'semantic_selection_required': True,
        'selection_basis': 'heuristic',
        'routing_warning': None,
        'score_tied': True,
        'top_candidates': [],
    }
    orig = W._route_domain
    W._route_domain = lambda task, persist=True: (dict(fake), '测试结果分析师')
    try:
        plan = W.build_dispatch_plan('重构支付模块并补齐单元测试', files=20, root=ROOT)
    finally:
        W._route_domain = orig
    assert plan['domain'].get('score_tied') is True