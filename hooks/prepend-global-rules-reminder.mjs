#!/usr/bin/env node
/**
 * UserPromptSubmit hook: puts a fixed global-rule reminder in front of every
 * user prompt before the turn reaches the model.
 *
 * ZCode parses hook stdout against a strict schema. For UserPromptSubmit the
 * only accepted payload key is `additionalContext` — there is no prompt-rewrite
 * key — so the reminder travels as additional context that sits ahead of the
 * user's text, not as edited prompt text.
 *
 * v3.1 新增：研发任务的两轴入口提示 + 当前工作流阶段的动态摘要。
 * 动态部分只做「读一个文件」的成本（有 active ledger 时才读），
 * 不扫仓库、不调外部命令，保证远低于 timeoutMs=3000。
 *
 * Manual smoke test:
 *   printf '%s\n' '{"hook_event_name":"UserPromptSubmit","prompt":"帮我写一个排序算法"}' \
 *     | node prepend-global-rules-reminder.mjs
 */

import { readdirSync, readFileSync, statSync, existsSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const HOOK_DIR = dirname(fileURLToPath(import.meta.url));

/**
 * 32 个一级大类的中文名，从唯一声明源读取。
 *
 * **为什么不再手写（缺陷 #4）**：此前这里内联了第 5 份手写副本，
 * 与 `config/categories.json` 的 `name` 有 24/32 不符
 * （hook「工程效能」vs 配置「工程效能与质量」）。
 * hook 的领域名是模型每轮都会读到的触发提示——名字与权威表不同步时，
 * 模型会按 hook 的名字去猜 `subagent_type`，而 `build_dispatch_for_expert`
 * 只接受 `experts.json` 的 `name`，派发会失败。
 *
 * 失败时返回空数组：调用方据此退化为「只写数量与出处」，
 * 绝不因为读配置失败而阻断用户输入（hook 的 fail-open 契约）。
 */
function loadDomainNames() {
  // 两种部署形态：源码仓库 <root>/config，插件缓存 <root>/skills/<name>/config
  const candidates = [
    join(HOOK_DIR, '..', 'config', 'categories.json'),
    join(HOOK_DIR, '..', 'skills', 'zcode-expert-system', 'config', 'categories.json'),
  ];
  for (const p of candidates) {
    try {
      const data = JSON.parse(readFileSync(p, 'utf8'));
      const names = Object.values(data)
        .map((v) => (v && typeof v === 'object' ? v.name : ''))
        .filter((n) => typeof n === 'string' && n);
      if (names.length) return names;
    } catch {
      // 换下一个候选路径
    }
  }
  return [];
}

const DOMAIN_LINE = (() => {
  const names = loadDomainNames();
  if (names.length) {
    return `32 领域（与 config/categories.json 同源）：${names.join('/')}。`;
  }
  // 读配置失败时的退路：不枚举名字，只指向权威出处——
  // 宁可少写，也不要写一份会漂移的副本。
  return '32 领域清单见 config/categories.json 的 name 字段（本次读取失败，不枚举以免与权威表漂移）。';
})();

const REMINDER = [
  '请你严格遵守全局规则。',
  '【专家体系路由】所有任务都必须先走 zcode-expert-system 两轴路由（先规模后域），由 triage 的分诊结论决定派谁——任务是否「看起来像领域任务」不是主控的自判项。不得跳过域路由（W10）。',
  '判定顺序（先规模后域，与全局规则 Step1→Step2 一致）：',
  '① 先跑 zcode_dev_workflow.py triage（已双轴合一：规模+领域路由一次产出）——所有任务（含只读与机械任务）都必须完成两轴分诊，不得跳过域路由；',
  `② 看路由结果的 score_detail 做语义精判（见下【语义精判】）；含领域判断的（分析/设计/评估/诊断/审查/规划/撰写专业方案）→ 按结论派对应专家，subagent_type 填专家${process.env.CLAUDE_PLUGIN_ROOT ? '（格式：zcode-expert-system:中文名）' : '中文名'}；`,
  '③ 只读任务派 analyst（领域专家）只读分析，不得由主控凭通识自行分析；只读任务仅允许查看/搜索/读取类工具，禁止新增、删除、修改文件，禁止安装依赖、git 写操作与 shell 重定向写盘；',
  '④ 「机械任务」仅限纯格式转换/批量执行类操作；一旦需要领域解释或决策 → 升级为派专家，不得凭通识自行作答。复核/审查任何产出（含主控自己的产出）属于领域判断，必须派独立专家（实施者≠审查者），不得以「机械核对」名义自审；',
  '⑤ 禁止跳过域路由自行处理领域判断；确无法派专家须说明原因（路由失败走降级三件套：degraded=true + blocking）。',
  '⑥ 每次派发专家前，主控必须在会话中显示一行「正在调用专家：<专家中文名>」；Agent/Task 的 description 使用「专家：<专家中文名>」，不得只显示 Agent/general-purpose。',
  '【语义精判】本插件不配外部 LLM/Embedding（依赖会话模型，刻意设计）。zcode_expert_system 返回 semantic_selection_required=true 时，其 selected_expert 只是词元计数结果，你（主控）必须自己看 top_candidates[].score_detail 按业务语义复核；要改判用 build_dispatch_for_expert(专家名, task)。',
  DOMAIN_LINE,
  '【研发工作流】中/大任务走九阶段（分诊→设计→规格→计划→基线→实施→审查→交付→归档），每阶段过门禁并落证据；轻量任务可裁剪但 TDD 与验证不可跳。详细规格见 references/stage-S*.md。',
  '豁免仅两级：纯闲聊/问候可直答；老板明示豁免专家体系时必须记 Ruling（W10）。',
].join('\n');

/**
 * 找当前工作区的活跃工作流账本，输出一行阶段摘要。
 *
 * 向上最多找 8 层（代码 depth < 8），只读 progress.md 前 60 行
 * （代码 slice(0, 60)）。失败静默返回空串——
 * hook 绝不能因为读文件失败而阻断用户输入。
 *
 * **层数上限（P2-6）**：原硬编码 4 层在深层 monorepo / worktree 里
 * 可能读不到活跃账本，静默丢失阶段摘要。放宽到 8 层，保留「到根即 break」
 * 兜底，不影响浅层场景。
 *
 * **上溯语义（缺陷 #16）**：本层「没找到可用账本」不等于「到此为止」。
 * 以下三种情况都必须**继续上溯**，而不是 return：
 *   1. 本层没有 .superpowers/sdd 目录
 *   2. sdd 目录存在但没有子目录（空壳）
 *   3. sdd 下有子目录但都没有 progress.md，或账本里没有阶段字段
 * 旧实现把 2/3 当成终止条件，于是 monorepo / worktree / 任何子目录里的
 * 空 sdd 残留都会让父层的活跃账本读不到，摘要静默消失。
 * 只有上溯到根（parent === dir）才放弃。
 */
function activeStageSummary(cwd) {
  try {
    let dir = cwd;
    for (let depth = 0; depth < 8; depth += 1) {
      const sddDir = join(dir, '.superpowers', 'sdd');
      const summary = summaryFromSddDir(sddDir, join(dir, 'openspec', 'changes', 'archive'));
      if (summary) return summary;

      const parent = join(dir, '..');
      if (parent === dir) break;      // 已到根，放弃
      dir = parent;
    }
    return '';
  } catch {
    return '';
  }
}

/**
 * 读 tasks.md 勾选统计（I-06：门禁自动可见）。
 *
 * 活跃账本对应的 openspec/changes/<slug>/tasks.md 若存在未勾选任务，
 * 返回 {done, todo}；读不到/不存在返回 null（fail-open，不阻断）。
 *
 * 口径与 openspec_engine.count_task_checkboxes / workflow_check.count_checkboxes
 * 一致：空框 [] 算未完成，仅 x/X 算完成。
 */
function taskCheckboxStats(ledger, rootDir) {
  try {
    // 账本目录名即 change slug（.superpowers/sdd/<slug>/progress.md）
    const slug = ledger.split(/[\\/]/).slice(-2, -1)[0];
    if (!slug) return null;
    // tasks.md 在仓库根的 openspec/changes/<slug>/tasks.md
    const tasksPath = join(rootDir, 'openspec', 'changes', slug, 'tasks.md');
    if (!existsSync(tasksPath)) return null;
    const text = readFileSync(tasksPath, 'utf8');
    let done = 0;
    let todo = 0;
    for (const line of text.split(/\r?\n/)) {
      const m = line.match(/^\s*(?:[-*+]|\d{1,9}[.)])\s*\[([^\]]*)\]/);
      if (!m) continue;
      const mark = (m[1] || '').trim().toLowerCase();
      if (mark === 'x') done += 1;
      else todo += 1;
    }
    return { done, todo };
  } catch {
    return null;                       // 读失败 fail-open
  }
}

/**
 * 尝试从单个 sdd 目录读出一行摘要。
 * 返回空串表示「本层没有可用账本」——调用方据此继续上溯。
 *
 * **已归档/终态跳过（P1-1）**：归档或终态的账本不再是「当前工作流」，
 * 但旧实现只按 mtime 选最新 progress.md，导致每轮恒注入已归档 DONE 账本。
 * 跳过两类：①openspec/changes/archive/<name> 已存在（已归档）；
 * ②progress.md 前 60 行 `Overall Status` 为 DONE/PARKED/COMPLETE（终态）。
 * 判定失败按未终态处理（fail-open，不阻断上溯）。
 *
 * **I-06 门禁可见**：若活跃账本对应的 tasks.md 存在未勾选任务，
 * 摘要追加明确告警——让「任务未完成却要交付/归档」在每轮都可见，
 * 而不必依赖主控主动调用 /wf:check。仍 fail-open，不阻断输入。
 */
function summaryFromSddDir(sddDir, archiveRoot) {
  let entries;
  try {
    entries = readdirSync(sddDir);
  } catch {
    return '';                        // 本层无 sdd 目录
  }

  const TERMINAL = new Set(['DONE', 'PARKED', 'COMPLETE']);
  const isTerminal = (name) => {
    // 终态判定：读 progress.md 前 60 行，正则提 `Overall Status`。
    // 读失败/无该字段 → 未终态（fail-open）。
    let head;
    try {
      head = readFileSync(join(sddDir, name, 'progress.md'), 'utf8')
        .split(/\r?\n/).slice(0, 60).join('\n');
    } catch {
      return false;
    }
    const m = head.match(/^#+\s*Overall Status\s*\n+\s*(\S+)/m);
    return !!(m && TERMINAL.has(m[1].trim()));
  };

  // 取 mtime 最新的 progress.md（跳过已归档与终态账本）
  let best = null;
  let bestMtime = 0;
  for (const name of entries) {
    // 已归档判定：openspec/changes/archive/<name> 存在即跳过
    if (archiveRoot && existsSync(join(archiveRoot, name))) continue;
    // 终态判定
    if (isTerminal(name)) continue;

    const ledger = join(sddDir, name, 'progress.md');
    try {
      const st = statSync(ledger);
      if (st.isFile() && st.mtimeMs > bestMtime) {
        bestMtime = st.mtimeMs;
        best = ledger;
      }
    } catch {
      // 无 progress.md 的目录跳过
    }
  }
  if (!best) return '';               // 本层账本都是空壳

  let head;
  try {
    head = readFileSync(best, 'utf8').split(/\r?\n/).slice(0, 60).join('\n');
  } catch {
    return '';                        // 读失败也继续上溯
  }
  // 白名单消毒（P8 批次五 Task 15）：账本是自由文本，捕获值注入前必须过闸。
  // 允许：字母/数字/下划线/短横线/点/加号 + 中文；剔除控制字符；
  // 超长（>40）或含白名单外字符 → 整个字段丢弃。
  // 捕获用 (\S+)，值天然不含空格，白名单亦不含空格，两处口径一致。
  // fail-open：消毒只丢字段，hook 永不 rc≠0。
  const phase = sanitizeField(pick(head, /^#+\s*Current Phase\s*\n+\s*(\S+)/m));
  const status = sanitizeField(pick(head, /^#+\s*Overall Status\s*\n+\s*(\S+)/m));
  const scale = sanitizeField(pick(head, /^#+\s*Scale\s*\n+\s*(\S+)/m));
  if (!phase && !status) return '';   // 账本有效但无阶段字段 → 继续上溯

  const slug = best.split(/[\\/]/).slice(-2, -1)[0];
  // I-06：账本根目录 = sddDir 上两级（.superpowers/sdd → 仓库根）
  const rootDir = join(sddDir, '..', '..');
  const stats = taskCheckboxStats(best, rootDir);
  let gateLine = '继续前先核证据与 tasks.md 勾选是否一致（不一致先修再派）。';
  if (stats && stats.todo > 0) {
    gateLine = `⚠️ tasks.md 尚有 ${stats.todo} 项未勾选（已完成 ${stats.done}）：`
      + '未完成不得交付/归档。交付或归档前必须先完成或显式 PARKED 未完成项。';
  }
  return [
    '【当前工作流】',
    `账本: ${slug}`,
    phase ? `阶段: ${phase}` : '',
    scale ? `规模: ${scale}` : '',
    status ? `状态: ${status}` : '',
    gateLine,
  ].filter(Boolean).join(' · ');
}

function sanitizeField(value) {
  // 账本字段白名单消毒（P8 批次五 Task 15）：允许字母/数字/下划线/短横线/
  // 点/加号 + 中文（值可为中文，如「S5实施」）。剔除控制字符；
  // 超长（>40）或含白名单外字符 → 整个字段丢弃。
  // fail-open：消毒只丢字段，hook 永不 rc≠0。
  if (!value) return '';
  const cleaned = value.replace(/[\u0000-\u001f\u007f]/g, '');
  if (!cleaned || cleaned.length > 40) return '';
  return /^[A-Za-z0-9_\-.+\u4e00-\u9fff]+$/.test(cleaned) ? cleaned : '';
}

function pick(text, re) {
  const m = text.match(re);
  return m ? m[1].trim() : '';
}

/** 主流程。任何异常都 fail-open（rc=0），绝不阻断用户输入。 */
function main() {
  let raw = '';
  process.stdin.setEncoding('utf8');
  return new Promise((resolve) => {
    process.stdin.on('data', (chunk) => { raw += chunk; });
    process.stdin.on('end', () => resolve(raw));
    process.stdin.on('error', () => resolve(raw));
  }).then((text) => {
    let input = {};
    try {
      input = text.trim() ? JSON.parse(text) : {};
    } catch (err) {
      safeWrite(process.stderr,
        `[global-rules-reminder] invalid UserPromptSubmit stdin: ${err}\n`);
      return;
    }

    // 类型守卫（缺陷 #15）：宿主可能传 `prompt: 123` / 数组 / 对象。
    // 旧实现直接 `(input.prompt ?? '').trim()` —— 非字符串会抛
    // `TypeError: ... .trim is not a function`，进程 rc=1。
    // UserPromptSubmit 的 rc≠0 可能被宿主当作失败并阻断该轮输入，
    // 这与「hook 绝不能阻断用户输入」的契约正相反。
    const promptValue = input && input.prompt;
    const original = typeof promptValue === 'string' ? promptValue.trim() : '';

    // Slash commands (e.g. /clear, /init) are single-token inputs; leave them
    // untouched so they keep working, while still reminding on normal text that
    // happens to start with "/" (e.g. "/etc/passwd 是什么？").
    if (!original || (original.startsWith('/') && !/\s/.test(original))) {
      return;
    }

    const cwd = typeof input.cwd === 'string' && input.cwd ? input.cwd : process.cwd();
    // activeStageSummary 内部已 try/catch，这里再包一层是兜底：
    // 任何未预料的异常都不该让 hook 以非零码退出。
    let stage = '';
    try {
      stage = activeStageSummary(cwd);
    } catch {
      stage = '';
    }

    safeWrite(process.stdout, JSON.stringify({
      hookSpecificOutput: {
        hookEventName: 'UserPromptSubmit',
        additionalContext: stage ? `${REMINDER}\n${stage}` : REMINDER,
      },
    }));
  });
}

/**
 * 写 stdout/stderr，吞掉 EPIPE 等流错误。
 *
 * **为什么需要它（P6 复核审查 A-6）**：
 * `process.stdout.write()` 的失败是 **stream 的 `'error'` 事件**，
 * 不是 Promise rejection —— `main().catch()` 兜不住。下游提前关闭管道时
 * （`node hook.mjs | head -c 0`、宿主进程提前退出），Node 抛未捕获异常
 * 并让进程 **rc=1**。而本文件的契约是「绝不能阻断用户输入」。
 *
 * 这是唯一一条仍能让 hook 返回非零码的路径，且触发条件不罕见。
 * 双保险：try/catch 捕同步异常 + 挂空 error handler 忽略异步事件。
 */
function safeWrite(stream, data) {
  try {
    stream.on('error', () => {});
    stream.write(data);
  } catch {
    // 流已关闭 / 已 detach：静默忽略（fail-open）
  }
}

main().catch((err) => {
  // 最后一道防线：fail-open，只留一行诊断到 stderr（不打完整栈）。
  safeWrite(process.stderr, `[global-rules-reminder] unexpected: ${err && err.message}\n`);
  process.exitCode = 0;
});
