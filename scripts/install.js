#!/usr/bin/env node
/**
 * ZCode Expert System v3.2 - NPM 一键部署脚本
 *
 * 固化手工验证过的完整部署流程（6 步）：
 *   1. 插件缓存目录：~/.zcode/cli/plugins/cache/zcode-plugins-official/<name>/<version>/
 *        .zcode-plugin/plugin.json        插件清单（显式声明 skills / commands / hooks）
 *        skills/<name>/...                技能本体（SKILL.md 规范化 + config + scripts + references + templates）
 *        hooks/hooks.json + *.mjs         插件级 hooks（必须放在插件根 hooks/，ZCode 只从那里加载）
 *        commands/wf/*.md                 插件级命令（manifest 声明了 commands 字段才会加载）
 *   2. 技能独立目录：~/.zcode/skills/<name>/（兼容仅扫描该目录的 ZCode 版本）
 *   2b. 命令兜底目录：~/.zcode/commands/wf/（user scope 优先于 plugin root，双保险）
 *   3. 子智能体：~/.zcode/agents/
 *        manager-<slug>.md                32 个领域总经理
 *        expert-<...>.md                  331 位领域专家
 *        frontmatter 只保留 name/description/color/injectAgentsMd
 *        （专家与总经理均注册为可派发子代理，共 363 个）
 *        注意：ZCode 运行时从 <installPath>/agents/ 加载插件前缀子代理
 *              （collectPluginAgentRoots 硬编码探测），另从 ~/.zcode/agents/
 *              加载用户级裸名子代理；本脚本两侧都写（步骤 1g 与步骤 3）。
 *   4. 插件注册：~/.zcode/cli/plugins/installed_plugins.json（不注册则界面不显示）
 *   5. 运行时数据：统一落在 ~/.zcode/expert-system/context/（不写安装目录）
 *
 * ## 安全契约（P5 修复，务必保持）
 *
 * 1. **先校验、后动手**：所有前置校验（源树完整性）必须在任何 `rmSync` 之前。
 *    旧实现先删插件缓存与用户技能目录，最后才校验 agents/ 是否存在——
 *    缺 agents/ 时用户得到「旧的已删、新的没装」且无回滚。
 * 2. **删前备份、成功才清**：覆盖 `~/.zcode/skills/<name>/`（用户目录，不是缓存）
 *    前先 rename 成 `.bak-<ts>`；部署成功且自检通过后才删备份，中途失败则回滚。
 * 3. **集合幂等**：重装时删除「旧清单有、本次源没有」的陈旧 agent。
 *    旧实现只写不删，源里删掉的专家会变成永久幽灵（清单也不记录，卸载删不掉）。
 * 4. **`--dry-run` 先看再删**：只打印将要删除的绝对路径与数量，零写入。
 * 5. **卸载清单缺失时宁可留残留**：不按 `manager-*`/`expert-*` 前缀扫，
 *    以免误删其他插件投放的同名前缀文件。
 *
 * 用法：
 *   node scripts/install.js              安装 / 升级
 *   node scripts/install.js --dry-run    只打印计划，零写入
 *   node scripts/install.js --uninstall  卸载（保留 ~/.zcode/expert-system 下的用户运行时数据）
 *   node scripts/install.js --uninstall --dry-run  只打印卸载计划
 */

const fs = require('fs');
const path = require('path');
const os = require('os');
const crypto = require('crypto');

const PLUGIN_NAME = 'zcode-expert-system';
const SKILL_NAME = 'zcode-expert-system';
const MARKETPLACE = 'zcode-plugins-official';

// ---- 图标修复（C2 注入，2026-11-23）----
//
// ZCode 桌面端插件图标的唯一来源是「插件所属 marketplace 清单条目的顶层
// icon 字段」（CLI 端 s8e 提取 → UI listing.icon），且渲染端只渲染
// `https://` 开头的完整 URL（app.asar 的 FD 校验，相对路径/file:// 一律
// 回落占位符）。官方远端清单 zcode-plugins-official（76 个插件）不含本
// 插件 → listing.icon 永远缺失 → 图标空白。
//
// 修复：本地注入一个 directory 型 marketplace（wutian122-expert-system，
// 清单条目携带 https icon），并把 installed_plugins.json 记录挂到该
// marketplace 命名空间下。插件缓存路径（installPath）不变，组件加载不受影响。
const ICON_MARKETPLACE_ID = 'wutian122-expert-system';
const ICON_MARKETPLACE_DESC =
  'Local marketplace providing the zcode-expert-system plugin listing with its icon (C2 icon fix).';
// enabledPlugins 的旧键（marketplace 切换前），部署时迁移、卸载时清理
const LEGACY_PLUGIN_ID = `${PLUGIN_NAME}@${MARKETPLACE}`;

// --dry-run：只打印计划，不动磁盘。所有写/删操作都经 guard() 收口。
const DRY_RUN = process.argv.includes('--dry-run');

// --purge：卸载时连用户运行时数据（context/）与备份目录一起清理，彻底删除。
// 不加此标志时保留 context/（属用户数据），仅清理部署残留（备份、空目录、空 expert-system）。
const PURGE = process.argv.includes('--purge');

/** 执行一个破坏性动作；dry-run 时只打印不执行。 */
function act(label, fn) {
  if (DRY_RUN) {
    log(`  [dry-run] 将${label}`);
    return undefined;
  }
  return fn();
}

/**
 * 状态日志：陈述「某动作已完成」时必须走这里（P1，2026-11-23）。
 *
 * 病灶：旧实现把 `log('✅ 插件清单已写入…')` 写在 `if (!DRY_RUN)` 守卫**外面**——
 * 写入动作被守卫住了，但日志无条件打印。`--dry-run` 下输出与真实执行一字不差，
 * 老板/CI 无法凭日志判断是否真的落了盘；卸载侧更糟：`✅ 已按清单删除 12 个命令文件`
 * 里那个 12 其实只是「磁盘上还剩 12 个」（removeFile 在 dry-run 下不删）。
 *
 * 约定：`real` 是真实执行时会打印的那句（含 ✅）；dry-run 下自动改写成
 * 同一事实的将来时，并标注未被改动。**只用于状态陈述，不用于计划陈述**——
 * 计划陈述（`将复制 N 个…`）继续直接 log，因为它本来就不声称已完成。
 */
function done(real) {
  if (!DRY_RUN) {
    log(real);
    return;
  }
  // 真实执行时会打印的那句含 ✅；dry-run 下必须去掉 ✅ 再陈述——
  // 保留 ✅ 会让输出仍读作「已完成」。去掉后即「已按清单删除 N 个」→
  // 「【未执行】按清单删除 N 个（磁盘未改动）」，语义为将来时。
  log(`  [dry-run] 【未执行】${String(real).replace(/^✅\s*/, '')}（磁盘未改动）`);
}

/** 递归统计文件数（用于 dry-run 输出与备份校验）。 */
function countFiles(p) {
  if (!fs.existsSync(p)) return 0;
  const st = fs.statSync(p);
  if (st.isFile()) return 1;
  let n = 0;
  for (const e of fs.readdirSync(p, { withFileTypes: true })) {
    const child = path.join(p, e.name);
    n += e.isDirectory() ? countFiles(child) : 1;
  }
  return n;
}

/**
 * 删除单个文件。dry-run 时只打印，真实执行时才 rmSync。
 * 分离出来是为了让卸载路径的每一处删除都经 dry-run 收口。
 */
function removeFile(target, label) {
  if (!fs.existsSync(target)) return;
  act(`${label || '删除文件'}：${target}`, () => fs.rmSync(target, { force: true }));
}


// 项目根目录（scripts 的上一级），用 dirname 避免 ".." 字面量
const PROJECT_ROOT = path.dirname(__dirname);

// 静态读取 package.json（不做动态 require）
const PKG = JSON.parse(fs.readFileSync(path.join(PROJECT_ROOT, 'package.json'), 'utf8'));

// 部署时跳过的无关目录/文件
const SKIP_NAMES = new Set([
  'node_modules', '.git', '__pycache__', '.mimosa', '.sync-tmp',
  'bs_doc.txt', '工作流.txt', 'package-lock.json',
  // 开发期产物，不随插件分发：
  // .pytest_cache 是跑测试留下的缓存，tests/ 是源码仓库的回归防线，
  // 插件运行时用不到，拷进去只会污染安装目录。
  '.pytest_cache', 'tests',
  // SDD 开发账本：实施过程的 ledger/brief/report，属开发期证据，不随插件分发
  '.superpowers',
  // vendor/skills/zes-* 由步骤 1c' 单独部署为兄弟目录，
  // 不得被 copyDir(PROJECT_ROOT, skillDest) 整树嵌进技能目录。
  'vendor',
]);

// 运行时产物目录：相对于项目根的 POSIX 风格路径，部署时整体跳过
const SKIP_REL_PATHS = new Set([
  'context/store',
]);

// 32 个总经理的颜色映射（键与 manager-<slug>.md 的 slug 一一对应）
const MANAGER_COLORS = {
  'frontend-client': 'cyan',
  'backend-architecture': 'blue',
  'data-database': 'blue',
  'devops-operations': 'green',
  'ai-llm': 'purple',
  'embedded-iot': 'orange',
  'network-engineering': 'blue',
  'engineering-quality': 'green',
  'security-compliance': 'red',
  'data-testing': 'yellow',
  'design-creative': 'magenta',
  'marketing-growth': 'yellow',
  'paid-media': 'yellow',
  'sales-customer': 'green',
  'business-strategy': 'blue',
  'healthcare': 'red',
  'supply-chain': 'orange',
  'legal-compliance': 'red',
  'hr': 'green',
  'finance-tax': 'green',
  'academic-research': 'cyan',
  'government-public': 'blue',
  'business-support': 'yellow',
  'data-knowledge': 'cyan',
  'game-dev': 'magenta',
  'spatial-computing': 'purple',
  'gis': 'green',
  'project-management': 'blue',
  'product-management': 'cyan',
  'customer-support': 'yellow',
  'language-translation': 'cyan',
  'agent-governance': 'purple',
};

function log(msg) { console.log(msg); }

// 32 个分类 -> 颜色（专家子代理按所属分类着色，与总经理同色系）
const CATEGORY_COLORS = MANAGER_COLORS;

// 专家 id -> 分类（从 experts.json 读取，用于给专家子代理着色）
const EXPERT_CATEGORY = (() => {
  const map = {};
  try {
    const cfgPath = path.join(PROJECT_ROOT, 'config', 'experts.json');
    const data = JSON.parse(fs.readFileSync(cfgPath, 'utf8'));
    for (const e of data.experts || []) {
      if (e.id && e.category) map[e.id] = e.category;
    }
  } catch (err) {
    log(`⚠️  读取 experts.json 失败，专家子代理将使用默认颜色: ${err.message}`);
  }
  return map;
})();

/** 递归复制目录，跳过无关文件与运行时产物 */
/**
 * 递归复制目录。
 *
 * @param {string} src   源目录
 * @param {string} dest  目标目录
 * @param {object} [opts]
 * @param {string[]} [opts.skip] 只按「文件名」排除的条目（作用于每一层）。
 *   用于 skills 镜像复制时排除 skills/ 自身，防止无限递归。
 */
function copyDir(src, dest, opts = {}) {
  const skip = new Set([...SKIP_NAMES, ...(opts.skip || [])]);
  fs.mkdirSync(dest, { recursive: true });
  for (const entry of fs.readdirSync(src, { withFileTypes: true })) {
    if (skip.has(entry.name)) continue;
    const srcPath = path.join(src, entry.name);
    const destPath = path.join(dest, entry.name);
    // 按相对路径排除运行时产物（如 context/store 下的结果 JSON）
    const rel = path.relative(PROJECT_ROOT, srcPath).split(path.sep).join('/');
    if (SKIP_REL_PATHS.has(rel)) continue;
    if (entry.isDirectory()) {
      copyDir(srcPath, destPath, opts);
    } else {
      fs.copyFileSync(srcPath, destPath);
    }
  }
}

/** 解析 markdown 的 frontmatter 与正文 */
function parseMarkdown(content) {
  const m = content.match(/^---\r?\n([\s\S]*?)\r?\n---\r?\n/);
  if (!m) return { frontmatter: {}, body: content };
  const frontmatter = {};
  for (const line of m[1].split(/\r?\n/)) {
    if (!line.includes(':')) continue;
    if (/^\s/.test(line) || line.startsWith('-')) continue;
    const idx = line.indexOf(':');
    const key = line.slice(0, idx).trim();
    const value = line.slice(idx + 1).trim().replace(/^["']|["']$/g, '');
    frontmatter[key] = value;
  }
  return { frontmatter, body: content.slice(m[0].length) };
}

/** 从正文提取第一个一级标题作为中文名 */
function extractChineseName(body, fallback) {
  const m = body.match(/^#\s+(.+)$/m);
  return m ? m[1].trim() : fallback;
}

/**
 * 把 manager-<slug>.md / expert-<id>.md 转换为 ZCode 子智能体格式。
 * ZCode 只认 name / description / color / injectAgentsMd / tools，
 * 多余的 metadata/input/output 字段会导致解析失败。
 *
 * @param {string} slugOrId   经理 slug 或专家 id（仅作兜底名称）
 * @param {string} rawContent 源 md 全文
 * @param {object} colorMap   名称/分类 -> 颜色的映射
 * @param {string} [category] 专家所属分类（决定颜色）
 */
function buildAgentFile(slugOrId, rawContent, colorMap, category) {
  const { frontmatter, body } = parseMarkdown(rawContent);
  const cnName = frontmatter.name || extractChineseName(body, slugOrId);
  const desc = (frontmatter.description || cnName).replace(/\r?\n/g, ' ').trim();
  const color =
    (category && CATEGORY_COLORS[category]) || colorMap[slugOrId] || 'blue';

  const front = [
    '---',
    `name: "${cnName}"`,
    `description: "${desc.replace(/"/g, "'")}"`,
    `color: ${color}`,
    'injectAgentsMd: true',
    '---',
    '',
  ].join('\n');

  return front + body.trim() + '\n';
}

/** 创建插件清单 */
function buildPluginManifest(version) {
  const enDesc =
    'ZCode Expert System v3.2 - 331 experts in 32 top-level categories with two-axis routing (scale -> nine-stage workflow, domain -> expert). Fuses OpenSpec + Superpowers + multi-agent + TDD.';
  return {
    name: PLUGIN_NAME,
    description: enDesc,
    description_i18n: {
      en: enDesc,
      'zh-CN':
        'ZCode 专家体系 v3.2 - 331 位专家 / 32 个一级大类，两轴正交路由（规模→九阶段工作流，领域→专家）。融合 OpenSpec 规格、Superpowers 纪律、多 Agent 协作与 TDD。',
    },
    version,
    author: { name: 'wutian122' },
    // 显式声明可执行组件：commands 没有约定发现，必须声明；
    // 子代理同样声明 agents，否则 ZCode 运行时探测不到插件内子代理。
    skills: 'skills',
    commands: 'commands',
    agents: 'agents',
    hooks: 'hooks/hooks.json',
    keywords: ['expert-system', 'routing', 'agents', 'workflow', 'openspec', 'superpowers', 'tdd', 'zcode'],
  };
}

/** 简化技能 SKILL.md 的 frontmatter（ZCode 只可靠识别 name / description / version） */
function normalizeSkillMd(content) {
  const { frontmatter, body } = parseMarkdown(content);
  const name = frontmatter.name || SKILL_NAME;
  const desc = frontmatter.description || '';
  const version = frontmatter.version || '3.0.0';
  const front = [
    '---',
    `name: ${name}`,
    `description: ${desc}`,
    `version: "${version}"`,
    '---',
    '',
  ].join('\n');
  return front + body.trim() + '\n';
}

function readInstalledPlugins(file) {
  if (!fs.existsSync(file)) return { version: 1, plugins: [] };
  return JSON.parse(fs.readFileSync(file, 'utf8'));
}

function writeInstalledPlugins(file, data) {
  if (fs.existsSync(file)) {
    fs.copyFileSync(file, `${file}.bak-${Date.now()}`);
  }
  fs.writeFileSync(file, JSON.stringify(data, null, 2), 'utf8');
}

// ---- 图标修复：本地 marketplace 注入 / 清理（C2，2026-11-23）----

/** 带时间戳备份后写 JSON（与 writeInstalledPlugins 同风格）。 */
function writeJsonWithBackup(file, data) {
  if (fs.existsSync(file)) {
    fs.copyFileSync(file, `${file}.bak-${Date.now()}`);
  }
  fs.writeFileSync(file, JSON.stringify(data, null, 2), 'utf8');
}

/**
 * 注入本地 icon marketplace（幂等）：
 *   1. 实体清单：<zcode>/cli/plugins/marketplaces/<id>/.claude-plugin/marketplace.json
 *      （directory 源刷新时 ZCode 从这里发现源清单并重写缓存）
 *   2. 根级缓存清单：<zcode>/cli/plugins/marketplaces/<id>/marketplace.json
 *      （ZCode pk 直读此文件构建 UI listing——重启即生效，无需等刷新）
 *   3. known_marketplaces.json upsert（对齐 addMarketplace 产物格式，
 *      按 id merge、保留首次 addedAt，重复部署不产生重复条目）
 *
 * 任何一步失败都只告警不中断：installed_plugins.json 注册（功能层）
 * 独立于 marketplace 注入（图标层），后者失败只损失图标。
 */
function injectIconMarketplace(zcodeDir) {
  const manifestSrc = path.join(PROJECT_ROOT, '.claude-plugin', 'marketplace.json');
  if (!fs.existsSync(manifestSrc)) {
    // 注意：这里**故意**保持告警+return——图标注入是装饰层（损失只是图标
    // 不显示），而 deployClaudeCode 的 manifest 缺失是部署链断裂，必须 exit 1。
    // 两者语义不同，勿统一。test_p12 只守 deployClaudeCode 那一处。
    log(`⚠️  缺 ${manifestSrc}，跳过图标 marketplace 注入（图标将不显示）`);
    return;
  }
  let manifestRaw;
  try {
    manifestRaw = fs.readFileSync(manifestSrc, 'utf8');
    const parsed = JSON.parse(manifestRaw);
    if (parsed.name !== ICON_MARKETPLACE_ID) {
      log(`⚠️  marketplace.json name=${parsed.name} 与 ICON_MARKETPLACE_ID 不符，跳过注入`);
      return;
    }
  } catch (err) {
    log(`⚠️  marketplace.json 不可解析（${err.message}），跳过注入`);
    return;
  }

  // 1+2. 实体清单 + 根级缓存清单（同内容，覆盖写 = 幂等）
  const mktDir = path.join(zcodeDir, 'cli', 'plugins', 'marketplaces', ICON_MARKETPLACE_ID);
  act(`创建本地 marketplace 目录 ${mktDir}`,
    () => fs.mkdirSync(path.join(mktDir, '.claude-plugin'), { recursive: true }));
  for (const rel of [['.claude-plugin', 'marketplace.json'], ['marketplace.json']]) {
    const dest = path.join(mktDir, ...rel);
    act(`写入 marketplace 清单 ${dest}`, () => fs.writeFileSync(dest, manifestRaw, 'utf8'));
  }

  // 3. known_marketplaces.json upsert
  const knownFile = path.join(zcodeDir, 'cli', 'plugins', 'known_marketplaces.json');
  let known = { version: 1, marketplaces: [] };
  try {
    if (fs.existsSync(knownFile)) {
      known = JSON.parse(fs.readFileSync(knownFile, 'utf8'));
    }
  } catch (err) {
    log(`⚠️  known_marketplaces.json 不可解析（${err.message}），跳过注册（图标将不显示）`);
    return;
  }
  if (!Array.isArray(known.marketplaces)) known.marketplaces = [];
  const now = new Date().toISOString();
  const entry = {
    id: ICON_MARKETPLACE_ID,
    source: { source: 'directory', path: mktDir },
    name: ICON_MARKETPLACE_ID,
    description: ICON_MARKETPLACE_DESC,
    addedAt: now,
    lastUpdated: now,
    pluginCount: 1,
  };
  const idx = known.marketplaces.findIndex((m) => m && m.id === ICON_MARKETPLACE_ID);
  if (idx >= 0) {
    const old = known.marketplaces[idx];
    known.marketplaces[idx] = { ...old, ...entry, addedAt: old.addedAt || now };
  } else {
    known.marketplaces.push(entry);
  }
  act(`更新 known_marketplaces.json（upsert ${ICON_MARKETPLACE_ID}）`,
    () => writeJsonWithBackup(knownFile, known));

  // 4. enabledPlugins 键迁移：旧官方命名空间键 → 新 marketplace 键。
  //    config.json 是 ZCode 主配置：不存在或损坏时只告警，绝不重建/覆盖。
  const configFile = path.join(zcodeDir, 'cli', 'config.json');
  try {
    if (fs.existsSync(configFile)) {
      const config = JSON.parse(fs.readFileSync(configFile, 'utf8'));
      const ep = config.plugins && config.plugins.enabledPlugins;
      if (ep && typeof ep === 'object') {
        const hadLegacy = LEGACY_PLUGIN_ID in ep;
        const hadNew = `${PLUGIN_NAME}@${ICON_MARKETPLACE_ID}` in ep;
        if (hadLegacy || hadNew) {
          // M3（2026-11-23）：尊重用户显式 false。旧实现
          // `hadLegacy ? ep[legacy] : ep[new]` 在新键已存在且为 false 时
          // 会被 hadNew 分支读出 false 又被 `=== false ? false : true`
          // 覆盖——看起来保留了 false，但若新键缺失而旧键为 false，
          // `ep[new]` 是 undefined，`undefined === false` 为 false → true，
          // 用户禁用被翻回启用。改为 `(ep[new] ?? true)`：新键缺失时
          // 默认 true（新装机默认启用），legacy=false 时保留 false。
          const value = hadLegacy ? ep[LEGACY_PLUGIN_ID] : (ep[`${PLUGIN_NAME}@${ICON_MARKETPLACE_ID}`] ?? true);
          delete ep[LEGACY_PLUGIN_ID];
          ep[`${PLUGIN_NAME}@${ICON_MARKETPLACE_ID}`] = value === false ? false : true;
          act(`迁移 enabledPlugins 键到 ${PLUGIN_NAME}@${ICON_MARKETPLACE_ID}`,
            () => writeJsonWithBackup(configFile, config));
        }
      }
    }
  } catch (err) {
    log(`⚠️  config.json 键迁移失败（${err.message}）；插件可能显示为禁用，`
      + `请在 ZCode 设置里手动启用`);
  }
  done(`✅ 图标 marketplace 已注入: ${ICON_MARKETPLACE_ID}（listing.icon → https CDN）`);
}

/** 卸载侧对称清理：known 条目、marketplace 目录、enabledPlugins 键。 */
function removeIconMarketplace(zcodeDir) {
  // known_marketplaces.json：按 id 移除
  const knownFile = path.join(zcodeDir, 'cli', 'plugins', 'known_marketplaces.json');
  try {
    if (fs.existsSync(knownFile)) {
      const known = JSON.parse(fs.readFileSync(knownFile, 'utf8'));
      if (Array.isArray(known.marketplaces)) {
        const before = known.marketplaces.length;
        known.marketplaces = known.marketplaces.filter((m) => !m || m.id !== ICON_MARKETPLACE_ID);
        if (known.marketplaces.length !== before) {
          act(`从 known_marketplaces.json 移除 ${ICON_MARKETPLACE_ID}`,
            () => writeJsonWithBackup(knownFile, known));
        }
      }
    }
  } catch (err) {
    log(`⚠️  known_marketplaces.json 清理失败（${err.message}），保留现场`);
  }

  // marketplace 目录整体删除（本脚本写入的专用目录，整删安全）
  const mktDir = path.join(zcodeDir, 'cli', 'plugins', 'marketplaces', ICON_MARKETPLACE_ID);
  removePath(mktDir, `删除本地 marketplace 目录 ${mktDir}`);

  // enabledPlugins：精确删除本插件两个命名空间键，不碰其他插件
  const configFile = path.join(zcodeDir, 'cli', 'config.json');
  try {
    if (fs.existsSync(configFile)) {
      const config = JSON.parse(fs.readFileSync(configFile, 'utf8'));
      const ep = config.plugins && config.plugins.enabledPlugins;
      if (ep && typeof ep === 'object') {
        const keys = [`${PLUGIN_NAME}@${ICON_MARKETPLACE_ID}`, LEGACY_PLUGIN_ID];
        const present = keys.filter((k) => k in ep);
        if (present.length > 0) {
          for (const k of present) delete ep[k];
          act(`从 enabledPlugins 移除 ${present.join(', ')}`,
            () => writeJsonWithBackup(configFile, config));
        }
      }
    }
  } catch (err) {
    log(`⚠️  config.json 清理失败（${err.message}），保留现场`);
  }
}

/**
 * 预检：在**任何** rmSync 之前确认源树完整。
 *
 * 缺陷 #17 的根因就是这一步缺失——旧实现先删再说，缺文件时才抛错，
 * 用户得到「旧的已删、新的没装」且无回滚。这里把所有前置条件集中检查，
 * 任一不满足即抛错，此时磁盘零改动。
 */
function preflight() {
  const problems = [];

  const pkgPath = path.join(PROJECT_ROOT, 'package.json');
  let pkg = null;
  try {
    pkg = JSON.parse(fs.readFileSync(pkgPath, 'utf8'));
  } catch (err) {
    problems.push(`package.json 不可读或不是合法 JSON：${err.message}`);
  }

  for (const rel of ['SKILL.md', 'config', 'agents', 'commands']) {
    const p = path.join(PROJECT_ROOT, rel);
    if (!fs.existsSync(p)) problems.push(`缺 ${rel}：${p}`);
  }

  for (const rel of [
    'scripts/sdd/sdd-workspace',
    'scripts/sdd/task-brief',
    'scripts/sdd/review-package',
  ]) {
    const p = path.join(PROJECT_ROOT, rel);
    if (!fs.existsSync(p)) problems.push(`缺 ${rel}：${p}`);
  }

  // vendored 技能资产：仅当源树含 vendor/ 时才强制校验其中的具体文件。
  // 1c' 步骤本身也是 if (fs.existsSync(vendoredSkillsRoot)) 保护的——
  // 没 vendored 就不部署，也不应强制要求这些文件（避免误杀不含 vendored 的源树）。
  const vendoredSkillsRoot = path.join(PROJECT_ROOT, 'vendor', 'skills');
  if (fs.existsSync(vendoredSkillsRoot)) {
    for (const rel of [
      'vendor/skills/LICENSE',
      'vendor/skills/PROVENANCE.md',
      'vendor/skills/zes-brainstorming/SKILL.md',
      'vendor/skills/zes-writing-plans/SKILL.md',
      'vendor/skills/zes-sdd/SKILL.md',
      'vendor/skills/zes-tdd/SKILL.md',
      'vendor/skills/zes-verification/SKILL.md',
      'vendor/skills/zes-code-review/SKILL.md',
      'vendor/skills/zes-receiving-review/SKILL.md',
      'vendor/skills/zes-finishing/SKILL.md',
      'vendor/skills/zes-systematic-debugging/SKILL.md',
    ]) {
      const p = path.join(PROJECT_ROOT, rel);
      if (!fs.existsSync(p)) problems.push(`缺 ${rel}：${p}`);
    }
  }

  const agentsDir = path.join(PROJECT_ROOT, 'agents');
  if (fs.existsSync(agentsDir)) {
    const mds = fs.readdirSync(agentsDir).filter((f) => f.endsWith('.md'));
    if (mds.length === 0) problems.push(`agents/ 下没有任何 .md 文件：${agentsDir}`);
  }

  const expertsPath = path.join(PROJECT_ROOT, 'config', 'experts.json');
  if (fs.existsSync(expertsPath)) {
    try {
      JSON.parse(fs.readFileSync(expertsPath, 'utf8'));
    } catch (err) {
      problems.push(`config/experts.json 不是合法 JSON：${err.message}`);
    }
  }

  if (problems.length) {
    const err = new Error('预检失败，未改动任何文件：\n  - ' + problems.join('\n  - '));
    err.isPreflight = true;
    throw err;
  }
  return pkg;
}

/** 删除一个目录/文件；dry-run 时只报告规模。 */
function removePath(target, label) {
  if (!fs.existsSync(target)) return;
  act(`${label}：${target}（${countFiles(target)} 个文件）`,
    () => fs.rmSync(target, { recursive: true, force: true }));
}

/**
 * 覆盖目录前先改名备份，返回 { path, hasUserFiles }。
 *
 * `hasUserFiles` 判定：备份目录里是否存在「本插件不会产出」的文件。
 * 插件产出的顶层条目是固定集合（见 PLUGIN_OUTPUTS）；集合外的文件说明
 * 用户自己加过东西，此时**备份不得自动删除**——自动清理等于换个方式
 * 销毁用户数据。
 */
const PLUGIN_OUTPUTS = new Set([
  'SKILL.md', 'README.md', 'README_CN.md', 'LICENSE', 'package.json',
  'zcode_expert_system.py', 'zcode_dev_workflow.py', 'skill_entry.py',
  'config', 'agents', 'references', 'templates', 'commands', 'context',
  'docs', 'hooks', 'scripts', 'bin', '.zcode-plugin',
  // 'tests' 已移除（P8 批次三 Task 8）：源树从不部署 tests/，把它算进
  // 「插件产物」会让用户自建的 tests/ 在备份时被判 hasUserFiles=false
  // 而连备份一起删——数据销毁方向。
]);

function backupDir(target) {
  if (!fs.existsSync(target)) return null;
  const bak = `${target}.bak-${Date.now()}`;
  act(`备份 ${target} → ${bak}`, () => fs.renameSync(target, bak));
  if (DRY_RUN) return { path: null, hasUserFiles: false };

  let hasUserFiles = false;
  try {
    hasUserFiles = fs.readdirSync(bak).some((name) => !PLUGIN_OUTPUTS.has(name));
  } catch {
    hasUserFiles = true;          // 读不到就当有，宁可不删
  }
  return { path: bak, hasUserFiles };
}

function writeAgentFile(dest, rendered) {
  // agents/ 覆盖前备份（P8 批次三 Task 8）：此前直接 writeFileSync 覆盖，
  // 用户自建/其他插件投放的同名 manager-*/expert-* 文件会静默丢失——
  // 技能目录有 backupDir，这里对齐「覆盖前备份」契约，并更进一步：
  // 内容未变化时整段跳过（幂等重装不产生 .bak 垃圾）。
  // 备份不进 deployedAgentNames 清单 → 卸载按清单删，不触碰 .bak-*。
  if (fs.existsSync(dest)) {
    const current = fs.readFileSync(dest, 'utf8');
    if (current === rendered) return;            // 幂等：内容一致不写不备
    const bak = `${dest}.bak-${Date.now()}`;
    // P3-2：覆盖前清理历史 .bak-*，仅保留最近 N=1 个备份（即删除全部旧 .bak，
    // 只留本次新生成的一个），避免重复部署累积 .bak-* 垃圾。
    const dir = path.dirname(dest);
    const base = path.basename(dest);
    const existingBaks = fs.readdirSync(dir).filter(n => n.startsWith(base + '.bak-')).sort();
    const N = 1;
    for (const old of existingBaks.slice(0, Math.max(0, existingBaks.length - (N - 1)))) {
      fs.rmSync(path.join(dir, old), { force: true });
    }
    fs.renameSync(dest, bak);                    // 备份失败即抛：不得无备份覆盖
    log(`  备份被改动的子代理 ${path.basename(dest)} → ${path.basename(bak)}`);
  }
  fs.writeFileSync(dest, rendered, 'utf8');
}

/**
 * 部署 Claude Code 插件副本。
 *
 * 部署目标：~/.claude/plugins/cache/claude-plugins-official/zcode-expert-system/<version>/
 *
 * 与 ZCode 部署的核心差异：**必须包含 agents/**。Claude Code 只从插件目录内
 * 加载子代理；ZCode 则是从全局 ~/.zcode/agents/ 加载（见 install.js 步骤 3）。
 */
function deployClaudeCode(homeDir, version) {
  const claudePluginRoot = path.join(
    homeDir, '.claude', 'plugins', 'cache', 'claude-plugins-official', PLUGIN_NAME, version
  );

  // I2（2026-11-23）：先校验、后动手——manifestSrc 缺失时直接返回，
  // 不得先 rmSync 用户已有的 Claude Code 插件缓存（旧实现先删后验，
  // manifest 缺失时用户得到「旧的已删、新的没装」）。
  // 2026-11-24 修正：缺失属源树完整性问题（npm 包 files 白名单漏了
  // .claude-plugin/ 导致），必须**报错退出 rc=1**，不得静默跳过后还
  // 打印「部署完成」误导用户——npm 3.2.2 的「装上了但 /plugin 没有」
  // 事故即由此出。
  const manifestSrc = path.join(PROJECT_ROOT, '.claude-plugin', 'plugin.json');
  if (!fs.existsSync(manifestSrc)) {
    log('❌ Claude Code 部署失败：源树缺少 .claude-plugin/plugin.json');
    log('   这是源树完整性问题（npm 包 files 白名单应含 .claude-plugin/）。');
    log('   ZCode 侧已部署；Claude Code 侧未部署，请修复源树后重装。');
    process.exit(1);
  }

  if (!DRY_RUN) {
    if (fs.existsSync(claudePluginRoot)) {
      fs.rmSync(claudePluginRoot, { recursive: true, force: true });
    }
    fs.mkdirSync(claudePluginRoot, { recursive: true });
  }

  if (DRY_RUN) {
    log(`  [dry-run] 将部署 Claude Code 插件到: ${claudePluginRoot}`);
    return;
  }

  // 1. 插件清单
  const manifestDest = path.join(claudePluginRoot, '.claude-plugin', 'plugin.json');
  fs.mkdirSync(path.dirname(manifestDest), { recursive: true });
  fs.copyFileSync(manifestSrc, manifestDest);

  // 2. 子代理（Claude Code 要求放在插件内）
  copyDir(path.join(PROJECT_ROOT, 'agents'),
          path.join(claudePluginRoot, 'agents'));

  // 3. 命令
  const commandsSrc = path.join(PROJECT_ROOT, 'commands');
  if (fs.existsSync(commandsSrc)) {
    copyDir(commandsSrc, path.join(claudePluginRoot, 'commands'));
  }

  // 4. 技能（源码仓库可能没有，靠自动发现；有则带上）
  const skillsSrc = path.join(PROJECT_ROOT, 'skills');
  if (fs.existsSync(skillsSrc)) {
    copyDir(skillsSrc, path.join(claudePluginRoot, 'skills'));
  }

  // 5. hooks —— **不复制 hooks.json**：那是 ZCode 格式（type: process），
  //    Claude Code 会自动扫描 hooks/ 下的 json 并对未知 hook type 报 warning。
  //    虽然只是忽略、不影响功能，但噪音会让用户以为装错了。
  const hooksSrc = path.join(PROJECT_ROOT, 'hooks');
  if (fs.existsSync(hooksSrc)) {
    const hooksDest = path.join(claudePluginRoot, 'hooks');
    fs.mkdirSync(hooksDest, { recursive: true });
    for (const file of fs.readdirSync(hooksSrc)) {
      if (file === 'hooks.json') continue; // ZCode 专用
      const src = path.join(hooksSrc, file);
      if (fs.statSync(src).isFile()) {
        fs.copyFileSync(src, path.join(hooksDest, file));
      }
    }
  }

  // 6. 运行时依赖
  for (const dir of ['scripts', 'config', 'references', 'templates', 'bin']) {
    const src = path.join(PROJECT_ROOT, dir);
    if (fs.existsSync(src)) {
      copyDir(src, path.join(claudePluginRoot, dir));
    }
  }

  // 6b. 主脚本（仓库根的三个 .py）：zcode_dev_workflow.py 与
  //    zcode_expert_system.py 是命令直接引用的路由/分诊引擎，
  //    skill_entry.py 是技能入口。它们不在任何子目录里，
  //    ZCode 侧靠 skills/<name>/ 整树复制带上，Claude Code 侧须显式复制。
  for (const f of ['zcode_dev_workflow.py', 'zcode_expert_system.py', 'skill_entry.py']) {
    const src = path.join(PROJECT_ROOT, f);
    if (fs.existsSync(src)) {
      fs.copyFileSync(src, path.join(claudePluginRoot, f));
    }
  }

  // 7. 命令路径对齐（布局契约）：
  //   commands/wf/*.md 里的脚本引用统一写成
  //   ${ZCODE_PLUGIN_ROOT}/skills/zcode-expert-system/scripts/xxx.py，
  //   这是 **ZCode 部署布局**（技能本体在 skills/<name>/ 子目录里）。
  //   Claude Code 部署是扁平的（脚本在插件根 scripts/、主脚本在根），
  //   直接跑 /wf:* 命令会因路径不存在而全部失败。
  //
  //   对齐方式：把插件根本体复制一份到 skills/zcode-expert-system/，
  //   让命令里的相对路径在两个布局下都成立。代价是一份冗余拷贝
  //   （~几 MB，Claude Code 插件无分发约束，可接受）。
  //   必须在步骤 6/6b 之后执行——镜像源是插件根，此时根内容才完整。
  //   skip 掉 skills/ 自身，防止无限递归。
  const skillMirror = path.join(claudePluginRoot, 'skills', SKILL_NAME);
  if (fs.existsSync(skillMirror)) {
    fs.rmSync(skillMirror, { recursive: true, force: true });
  }
  copyDir(claudePluginRoot, skillMirror, { skip: ['skills'] });

  log(`✅ Claude Code 插件已部署: ${claudePluginRoot}`);

  // 部署后校验：agent 数量必须是 363（32 manager + 331 expert）
  const agentDir = path.join(claudePluginRoot, 'agents');
  const agentFiles = fs.existsSync(agentDir)
    ? fs.readdirSync(agentDir).filter((f) => f.endsWith('.md')).length
    : 0;
  if (agentFiles !== 363) {
    log(`❌ Claude Code 部署失败：agents/ 只有 ${agentFiles} 个文件，应为 363`);
    process.exit(1);
  }
  log(`✅ Claude Code 部署校验通过：${agentFiles} 个 agent`);
}

/**
 * 目标探测：返回本机各平台的安装情况，用于菜单里标注。
 *
 * 只返回「是否检测到该平台目录」，不做任何写入。
 */
function detectTargets(homeDir) {
  return [
    {
      id: 'zcode',
      label: 'ZCode',
      hint: '~/.zcode',
      detected: fs.existsSync(path.join(homeDir, '.zcode')),
    },
    {
      id: 'claude-code',
      label: 'Claude Code',
      hint: '~/.claude',
      detected: fs.existsSync(path.join(homeDir, '.claude')),
    },
  ];
}

/**
 * 交互式多选菜单（零依赖，手写 readline 按键处理）。
 *
 * 操作：↑/↓ 移动，Space 切换，Enter 确认，Ctrl+C 取消。
 * 非 TTY 环境（CI、管道、重定向）直接返回全选，绝不卡住。
 */
function selectTargets(options) {
  if (!process.stdin.isTTY || !process.stdout.isTTY) {
    log('（非交互终端，默认全选）');
    return options.map((o) => o.id);
  }

  return new Promise((resolve) => {
    const checked = options.map((o) => o.detected); // 检测到的默认勾选
    let cursor = 0;
    let rendered = false;

    const render = (first) => {
      if (!first) {
        // 擦掉上一次渲染：光标上移 N 行，逐行清屏
        process.stdout.write(`\x1b[${options.length + 3}A`);
        for (let i = 0; i < options.length + 3; i += 1) {
          process.stdout.write('\x1b[2K\x1b[1B');
        }
        process.stdout.write(`\x1b[${options.length + 3}A`);
      }
      const selectedCount = checked.filter(Boolean).length;
      process.stdout.write(
        `? 选择要安装到哪些工具（共 ${options.length} 个，已选 ${selectedCount}）\n`
      );
      options.forEach((o, i) => {
        const box = checked[i] ? '\x1b[36m◉\x1b[0m' : '\x1b[90m◯\x1b[0m';
        const arrow = i === cursor ? '\x1b[36m❯\x1b[0m' : ' ';
        const tag = o.detected ? ' \x1b[32m(detected)\x1b[0m' : '';
        process.stdout.write(`${arrow} ${box} ${o.label}${tag}  \x1b[90m${o.hint}\x1b[0m\n`);
      });
      process.stdout.write(
        '\x1b[90m↑↓ 移动 · Space 切换 · Enter 确认 · Ctrl+C 取消\x1b[0m\n'
      );
      rendered = true;
    };

    render(true);

    const cleanup = () => {
      process.stdin.setRawMode(false);
      process.stdin.pause();
      process.stdin.removeListener('data', onData);
      process.stdout.removeListener('resize', onResize);
    };

    const onResize = () => render(false);

    const onData = (chunk) => {
      const key = chunk.toString();

      if (key === '\u0003') { // Ctrl+C
        cleanup();
        process.stdout.write('\n');
        log('已取消。');
        process.exit(0);
      } else if (key === '\r' || key === '\n') { // Enter
        cleanup();
        const chosen = options.filter((_, i) => checked[i]).map((o) => o.id);
        if (chosen.length === 0) {
          log('❌ 至少需要选择一个安装目标。');
          process.exit(1);
        }
        render(false);
        return resolve(chosen);
      } else if (key === ' ') { // Space
        checked[cursor] = !checked[cursor];
        render(false);
      } else if (key === '\u001b[A' || key === 'k') { // ↑
        cursor = (cursor - 1 + options.length) % options.length;
        render(false);
      } else if (key === '\u001b[B' || key === 'j') { // ↓
        cursor = (cursor + 1) % options.length;
        render(false);
      }
    };

    process.stdin.setRawMode(true);
    process.stdin.resume();
    process.stdin.setEncoding('utf8');
    process.stdin.on('data', onData);
    process.stdout.on('resize', onResize);
  });
}

/**
 * 部署插件。
 *
 * @param {string[]} targets 要部署的目标，取值 'zcode' / 'claude-code'。
 *                           为空数组时表示「只跑预检与提示，不部署」。
 */
function install(targets = ['zcode', 'claude-code']) {
  const wantZcode = targets.includes('zcode');
  const wantClaude = targets.includes('claude-code');
  const homeDir = os.homedir();
  const zcodeDir = path.join(homeDir, '.zcode');

  // ---------- 0. 预检（必须在任何删除之前） ----------
  const pkg = preflight();
  const version = pkg.version || '3.0.0';

  log(`开始部署 ${PLUGIN_NAME} v${version} ...`);
  log(`源目录: ${PROJECT_ROOT}`);
  log(`目标 HOME: ${homeDir}${DRY_RUN ? '   [dry-run：不改动磁盘]' : ''}`);
  log(`部署目标: ${targets.join(' + ') || '（无）'}`);

  // ---------- 0a. Claude Code 部署（独立于 ZCode，不影响 ZCode 行为） ----------
  // 部署目标：~/.claude/plugins/cache/claude-plugins-official/zcode-expert-system/<version>/
  // 必须包含 agents/（Claude Code 从插件目录加载子代理，ZCode 从全局 ~/.zcode/agents/ 加载）
  if (wantClaude) {
    deployClaudeCode(homeDir, version);
  } else {
    log('⏭️  跳过 Claude Code 部署（未选择）');
  }

  if (!wantZcode) {
    log('');
    log('🎉 部署完成！');
    log('');
    log('验证方式：');
    if (wantClaude) {
      log('  1. 在 Claude Code 中执行 /plugin，应出现 zcode-expert-system');
      log('  2. 派发专家时使用 zcode-expert-system:<专家中文名>');
    }
    return;
  }

  // ---------- 1. 插件缓存目录 ----------
  const pluginRoot = path.join(
    zcodeDir, 'cli', 'plugins', 'cache', MARKETPLACE, PLUGIN_NAME, version
  );
  // agents/ 源目录：步骤 1g（插件缓存副本）与步骤 3（用户级）共用
  const agentsSrc = path.join(PROJECT_ROOT, 'agents');
  removePath(pluginRoot, '清理旧版本缓存');
  if (!DRY_RUN) {
    fs.mkdirSync(path.join(pluginRoot, '.zcode-plugin'), { recursive: true });
  }

  // 1a. 插件清单
  if (!DRY_RUN) {
    fs.writeFileSync(
      path.join(pluginRoot, '.zcode-plugin', 'plugin.json'),
      JSON.stringify(buildPluginManifest(version), null, 2),
      'utf8'
    );
  }
  done('✅ 插件清单已写入: .zcode-plugin/plugin.json');

  // 1b. 技能本体 -> <pluginRoot>/skills/<skill>/
  const skillDest = path.join(pluginRoot, 'skills', SKILL_NAME);
  if (!DRY_RUN) copyDir(PROJECT_ROOT, skillDest);

  // 1g. 子代理 -> <pluginRoot>/agents/
  //
  // ZCode 运行时 collectPluginAgentRoots **硬编码探测 <installPath>/agents/**，
  // 插件前缀子代理（zcode-expert-system:XXX）只从这里加载。
  // 另从 ~/.zcode/agents/ 加载用户级裸名子代理（见步骤 3）——两侧都写。
  //
  // **数量校验**（与 Claude Code 分支同口径）：copyFileSync 在磁盘满/权限
  // 不足时静默失败，会产出空或半量缓存且无人知晓。这里复制后回读计数，
  // 与源文件数不符即 exit(1)，拒绝留下半毁产物。
  {
    const pluginAgentsDest = path.join(pluginRoot, 'agents');
    if (fs.existsSync(agentsSrc)) {
      if (!DRY_RUN) {
        fs.mkdirSync(pluginAgentsDest, { recursive: true });
        const mdFiles = fs.readdirSync(agentsSrc).filter((f) => f.endsWith('.md'));
        for (const file of mdFiles) {
          fs.copyFileSync(path.join(agentsSrc, file),
                          path.join(pluginAgentsDest, file));
        }
        // 回读校验：目标目录实际 .md 数必须与源一致
        const written = fs.readdirSync(pluginAgentsDest)
          .filter((f) => f.endsWith('.md')).length;
        if (written !== mdFiles.length) {
          log(`❌ ZCode 部署失败：插件缓存 agents/ 只有 ${written} 个，`
            + `源有 ${mdFiles.length} 个（复制不完整，可能磁盘满或权限不足）`);
          process.exit(1);
        }
        log(`✅ 已部署 ${written} 个子代理到插件缓存目录`);
      } else {
        const n = fs.readdirSync(agentsSrc).filter((f) => f.endsWith('.md')).length;
        log(`  [dry-run] 将复制 ${n} 个子代理到 ${pluginAgentsDest}`);
      }
    }
  }

  // 1c'. 技能本体之外：将 vendored 技能各自复制为兄弟目录
  const vendoredSkillsRoot = path.join(PROJECT_ROOT, 'vendor', 'skills');
  if (fs.existsSync(vendoredSkillsRoot)) {
    const deployedSkills = [];
    for (const entry of fs.readdirSync(vendoredSkillsRoot, { withFileTypes: true })) {
      if (!entry.isDirectory()) continue;
      const srcSkillDir = path.join(vendoredSkillsRoot, entry.name);
      const dstSkillDir = path.join(pluginRoot, 'skills', entry.name);
      if (!DRY_RUN) {
        act(`部署技能 ${entry.name} 到 ${dstSkillDir}`, () => {
          fs.rmSync(dstSkillDir, { recursive: true, force: true }); // 幂等重装
          copyDir(srcSkillDir, dstSkillDir);
        });
      }
      deployedSkills.push(entry.name);
    }
    // 写部署清单（卸载时据此精确删除，绝不按前缀扫）
    if (!DRY_RUN) {
      const manifestDir = path.join(zcodeDir, 'expert-system');
      act(`创建专家系统目录 ${manifestDir}`, () => {
        fs.mkdirSync(manifestDir, { recursive: true });
      });
      act(`写入技能部署清单 deployed-skills.json`, () => {
        fs.writeFileSync(
          path.join(manifestDir, 'deployed-skills.json'),
          JSON.stringify({ version, skills: deployedSkills }, null, 2),
          'utf8'
        );
      });
    }
    done(`✅ vendored 技能已部署: ${deployedSkills.length} 个`);
  }

  // 1c. 清除技能目录里属于插件级的文件（避免干扰技能识别）
  //
  // 缺陷 #21 的真实病灶是 `scripts/install.js` 副本：同一份拷贝里
  // `package.json` 已被删除，这个副本一运行就在 readFileSync(package.json)
  // 处抛错。P9 部署验证实测：整目录剔除 `scripts` 是**过度剔除**——
  // `/wf:*` 命令按 `${ZCODE_PLUGIN_ROOT}/skills/<skill>/scripts/*.py` 引用
  // workflow_check.py 等运行时脚本，整目录删让部署布局下命令引用落空。
  // 改为：目录级只剔 package.json / .zcode-plugin / bin，scripts 里逐文件
  // 只剔坏副本 install.js 与开发期残留。
  if (!DRY_RUN) {
    for (const rel of ['package.json', 'observability.py', '.zcode-plugin',
                       'bin']) {
      const target = path.join(skillDest, rel);
      if (fs.existsSync(target)) fs.rmSync(target, { recursive: true, force: true });
    }
    for (const junk of ['install.js', '_deploy_run_tmp.js']) {
      const target = path.join(skillDest, 'scripts', junk);
      if (fs.existsSync(target)) fs.rmSync(target, { force: true });
    }
  }

  // 1d. 规范化 SKILL.md frontmatter
  const skillMdPath = path.join(skillDest, 'SKILL.md');
  if (!DRY_RUN && fs.existsSync(skillMdPath)) {
    fs.writeFileSync(
      skillMdPath,
      normalizeSkillMd(fs.readFileSync(skillMdPath, 'utf8')),
      'utf8'
    );
    log('✅ 技能 SKILL.md 已规范化');
  }

  // 1e. 插件级 hooks -> <pluginRoot>/hooks/
  const hooksSrc = path.join(PROJECT_ROOT, 'hooks');
  if (!DRY_RUN && fs.existsSync(hooksSrc)) {
    const hooksDest = path.join(pluginRoot, 'hooks');
    fs.mkdirSync(hooksDest, { recursive: true });
    for (const file of fs.readdirSync(hooksSrc)) {
      const src = path.join(hooksSrc, file);
      if (fs.statSync(src).isFile()) {
        fs.copyFileSync(src, path.join(hooksDest, file));
      }
    }
  }
  done('✅ 插件级 hooks 已写入: hooks/');

  // 1f. 插件级 commands -> <pluginRoot>/commands/
  const commandsSrc = path.join(PROJECT_ROOT, 'commands');
  if (!DRY_RUN && fs.existsSync(commandsSrc)) {
    copyDir(commandsSrc, path.join(pluginRoot, 'commands'));
  }
  done('✅ 插件级 commands 已写入: commands/');

  // ---------- 2. 技能独立目录（兼容仅扫描 ~/.zcode/skills 的版本） ----------
  //
  // **删前备份**（缺陷 #17b）：这个目录是**用户目录**，不是缓存。
  // 用户可能在里面改过 SKILL.md 或加了自己的 references。旧实现直接
  // `rmSync` 无备份清空——而同一脚本对 installed_plugins.json 是有
  // `.bak-<ts>` 的，策略不一致。现在改为 rename 备份，部署成功后才清。
  const legacySkillDir = path.join(zcodeDir, 'skills', SKILL_NAME);
  const skillBackup = backupDir(legacySkillDir);
  if (!DRY_RUN) copyDir(skillDest, legacySkillDir);
  done(`✅ 技能已同步: ${legacySkillDir}`
    + (skillBackup && skillBackup.path
      ? `（旧版已备份至 ${path.basename(skillBackup.path)}）` : ''));

  // ---------- 2b. 命令兜底目录 -> ~/.zcode/commands/ ----------
  //     ZCode 的命令发现顺序里 user scope 优先于 plugin root；
  //     把命令同时放到用户目录，保证「插件 commands 未被发现」时仍可调用。
  //
  //     注意：命令按目录层级映射为命令名（commands/wf/triage.md -> /wf:triage），
  //     所以必须**递归**同步。此前只扫一层直接子文件，而实际命令都在 wf/ 子目录里，
  //     导致 ~/.zcode/commands/wf/ 建成空目录、命令全部丢失（实测踩到）。
  if (!DRY_RUN && fs.existsSync(commandsSrc)) {
    const userCmdRoot = path.join(zcodeDir, 'commands');
    const deployedCommands = [];
    const walkCommands = (fromDir, toDir, relPrefix) => {
      fs.mkdirSync(toDir, { recursive: true });
      for (const entry of fs.readdirSync(fromDir, { withFileTypes: true })) {
        const srcPath = path.join(fromDir, entry.name);
        const dstPath = path.join(toDir, entry.name);
        const rel = relPrefix ? `${relPrefix}/${entry.name}` : entry.name;
        if (entry.isDirectory()) {
          walkCommands(srcPath, dstPath, rel);
        } else if (entry.isFile() && entry.name.endsWith('.md')) {
          fs.copyFileSync(srcPath, dstPath);
          deployedCommands.push(rel);
        }
      }
    };
    walkCommands(commandsSrc, userCmdRoot, '');
    done(`✅ 命令已同步: ${userCmdRoot}（${deployedCommands.length} 个）`);

    // 写命令清单：卸载时据此精确删除，避免误删其他插件的同名命令
    try {
      const manifestDir = path.join(zcodeDir, 'expert-system');
      fs.mkdirSync(manifestDir, { recursive: true });
      fs.writeFileSync(
        path.join(manifestDir, 'deployed-commands.json'),
        JSON.stringify({ version, commands: deployedCommands }, null, 2),
        'utf8'
      );
    } catch (err) {
      log(`⚠️  命令清单写入失败（卸载将跳过命令清理）: ${err.message}`);
    }
  }

  // ---------- 3. 32 个总经理子智能体 ----------
  const agentsDest = path.join(zcodeDir, 'agents');
  if (!DRY_RUN) fs.mkdirSync(agentsDest, { recursive: true });

  // 读旧清单，用于「集合幂等」：本次源里没有、但上次装过的 agent 必须删掉。
  // 缺陷 #18：旧实现只写不删，随后用新清单整体覆盖 → 源里删掉的专家
  // 变成永久幽灵（仍在可派发列表里，而卸载按新清单永远删不掉）。
  const manifestDir = path.join(zcodeDir, 'expert-system');
  const manifestFile = path.join(manifestDir, 'deployed-agents.json');
  let previousAgents = [];
  try {
    if (fs.existsSync(manifestFile)) {
      const prev = JSON.parse(fs.readFileSync(manifestFile, 'utf8'));
      if (Array.isArray(prev.agents)) previousAgents = prev.agents;
    }
  } catch (err) {
    log(`⚠️  旧安装清单读取失败（跳过陈旧清理）: ${err.message}`);
  }

  let managerCount = 0;
  let expertCount = 0;
  const deployedAgentNames = [];
  for (const file of fs.readdirSync(agentsSrc)) {
    if (!file.endsWith('.md')) continue;

    if (file.startsWith('manager-')) {
      // 总经理：manager-<slug>.md -> agents/manager-<slug>.md
      const slug = file.slice('manager-'.length, -'.md'.length);
      const outName = `manager-${slug}.md`;
      if (!DRY_RUN) {
        const raw = fs.readFileSync(path.join(agentsSrc, file), 'utf8');
        writeAgentFile(path.join(agentsDest, outName),
          buildAgentFile(slug, raw, MANAGER_COLORS));
      }
      deployedAgentNames.push(outName);
      managerCount += 1;
    } else if (file.startsWith('expert-')) {
      // 331 位专家：expert-<...>.md -> agents/expert-<...>.md（同样注册为子代理）
      const eid = file.slice(0, -'.md'.length);
      if (!DRY_RUN) {
        const raw = fs.readFileSync(path.join(agentsSrc, file), 'utf8');
        const cat = EXPERT_CATEGORY[eid] || 'business-support';
        writeAgentFile(path.join(agentsDest, file),
          buildAgentFile(eid, raw, CATEGORY_COLORS, cat));
      }
      deployedAgentNames.push(file);
      expertCount += 1;
    }
  }

  // 清理陈旧代理：旧清单有、本次源没有 → 删除。
  // **先删陈旧、后写新清单**：顺序反了会在中途失败时留下「清单已更新
  // 但陈旧文件还在」的更坏状态（清单说没装，磁盘上有 → 卸载永远漏删）。
  const currentSet = new Set(deployedAgentNames);
  const stale = previousAgents.filter((n) => !currentSet.has(n));
  for (const name of stale) {
    removePath(path.join(agentsDest, name), `删除陈旧子代理 ${name}`);
  }
  if (stale.length) {
    done(`✅ 已清理 ${stale.length} 个陈旧子代理（源里已删）`);
  }

  // 写安装清单：卸载时据此精确删除，避免按前缀误删其他插件的产物
  if (!DRY_RUN) {
    try {
      fs.mkdirSync(manifestDir, { recursive: true });
      fs.writeFileSync(
        manifestFile,
        JSON.stringify({ version, agents: deployedAgentNames }, null, 2),
        'utf8'
      );
      log(`✅ 安装清单已写入: ${deployedAgentNames.length} 个子代理`);
    } catch (err) {
      log(`⚠️  安装清单写入失败（卸载将跳过，不按前缀扫）: ${err.message}`);
    }
  } else {
    log(`  [dry-run] 将写入安装清单：${deployedAgentNames.length} 个子代理`);
  }

  done(`✅ 已部署 ${managerCount} 个总经理子智能体 -> ${agentsDest}`);
  done(`✅ 已部署 ${expertCount} 位专家子智能体 -> ${agentsDest}`);

  // ---------- 4. 注册插件（幂等 upsert，C2 对齐 wutian122 命名空间） ----------
  //
  // C2（2026-11-23）：目标命名空间改为 ICON_MARKETPLACE_ID
  // （wutian122-expert-system），与 C2 现场的 installed_plugins.json 对齐。
  // 旧实现 `filter(p => p.name !== PLUGIN_NAME)` 按名全删会把现场的
  // wutian122 记录也删掉再写入 zcode-plugins-official 记录——命名空间
  // 回退，图标再次消失。改为按目标 id 过滤：只删「本次要写的那个 id」，
  // 其他命名空间的同名插件记录（历史遗留或用户自装）原样保留。
  //
  // dry-run 时必须整段跳过：`writeInstalledPlugins` 内部会先 `copyFileSync`
  // 生成 `.bak-<ts>` 备份——那是写操作。初版漏了这一处保护，
  // 实测 dry-run 会在 `installed_plugins.json.bak-*` 留下一个文件（81 → 82）。
  const installedFile = path.join(zcodeDir, 'cli', 'plugins', 'installed_plugins.json');
  const targetPluginId = `${PLUGIN_NAME}@${ICON_MARKETPLACE_ID}`;
  if (DRY_RUN) {
    log(`  [dry-run] 将在 ${installedFile} 注册插件 ${targetPluginId}`);
    log(`  [dry-run] 将注入图标 marketplace ${ICON_MARKETPLACE_ID}`);
  } else {
    const installed = readInstalledPlugins(installedFile);
    // 先取旧记录（upsert 语义：保留首装 installedAt 与 cacheTransactionId），
    // 再按目标 id 过滤后写回——只删「本次要写的那个 id」，
    // 其他命名空间的同名插件记录（历史遗留或用户自装）原样保留。
    const existing = (installed.plugins || [])
      .find((p) => p && p.id === targetPluginId);
    installed.plugins = (installed.plugins || []).filter((p) => !p || p.id !== targetPluginId);

    const now = new Date().toISOString();
    installed.plugins.push({
      id: targetPluginId,
      name: PLUGIN_NAME,
      marketplace: ICON_MARKETPLACE_ID,
      version,
      installPath: pluginRoot,
      installedAt: existing ? existing.installedAt : now,
      updatedAt: now,
      scope: 'user',
      source: { source: 'local', type: 'directory', path: PLUGIN_NAME },
      cacheTransactionId: existing ? existing.cacheTransactionId : crypto.randomUUID(),
    });
    writeInstalledPlugins(installedFile, installed);
    log(`✅ 已注册插件: ${targetPluginId}（共 ${installed.plugins.length} 个）`);

    // ---------- 4b. 图标 marketplace 注入（C1：接线，此前函数零调用） ----------
    //
    // 图标层独立于功能层：注入失败只损失图标（函数内部已 try-catch 告警
    // 不中断），installed_plugins 注册（功能层）不受影响。
    injectIconMarketplace(zcodeDir);
  }

  // ---------- 5. 部署成功 → 视情况清理旧版备份 ----------
  //
  // **只有确认备份里没有用户自己的文件时才删**。
  // 若用户在该目录里加过东西（PLUGIN_OUTPUTS 之外的条目），
  // 自动清理等于换个方式销毁用户数据——保留并明确告知路径，
  // 让用户自己决定什么时候删。
  if (skillBackup && skillBackup.path && !DRY_RUN) {
    if (skillBackup.hasUserFiles) {
      log(`⚠️  旧版备份含用户自己的文件，已保留：${skillBackup.path}`);
      log('   确认无需后可手工删除。');
    } else {
      try {
        fs.rmSync(skillBackup.path, { recursive: true, force: true });
        log('✅ 旧版备份无用户改动，已在部署成功后清理');
      } catch (err) {
        log(`⚠️  旧版备份清理失败（可手工删除）: ${skillBackup.path} — ${err.message}`);
      }
    }
  }

  // ---------- 6. 完成提示 ----------
  log('');
  if (DRY_RUN) {
    log('ℹ️  dry-run 结束：以上为计划执行的动作，磁盘未改动。');
    log('   去掉 --dry-run 即真正执行。');
    return;
  }
  log('🎉 部署完成！请重启 ZCode 使配置生效。');
  log('');
  log('验证方式：');
  log(`  1. 设置 → 插件：应出现 ${PLUGIN_NAME} v${version}`);
  log(`  2. 设置 → 子智能体：应出现 ${managerCount} 个新增总经理`);
  log('  3. 会话中直接下达专业任务（/wf:triage、/wf:plan、/wf:check 为显式入口）');
}

function uninstall() {
  const homeDir = os.homedir();
  const zcodeDir = path.join(homeDir, '.zcode');

  log(`开始卸载 ${PLUGIN_NAME} ...`);
  log(`目标 HOME: ${homeDir}${DRY_RUN ? '   [dry-run：不改动磁盘]' : ''}`);

  // 1. 移除插件注册（按 id 精确匹配，兼容 legacy 与 wutian122 两个命名空间）
  //
  // C2 现场对齐：安装侧已改为 upsert 到 `${PLUGIN_NAME}@${ICON_MARKETPLACE_ID}`
  // （wutian122-expert-system），历史版本装的
  // `${PLUGIN_NAME}@${MARKETPLACE}`（zcode-plugins-official）记录也要一并清掉，
  // 否则卸载后 installed_plugins.json 里残留官方命名空间条目。其他插件
  // 的同名记录不动（id 不同即不是本插件）。
  const installedFile = path.join(zcodeDir, 'cli', 'plugins', 'installed_plugins.json');
  const pluginIds = [LEGACY_PLUGIN_ID, `${PLUGIN_NAME}@${ICON_MARKETPLACE_ID}`];
  if (!DRY_RUN && fs.existsSync(installedFile)) {
    const installed = readInstalledPlugins(installedFile);
    const before = (installed.plugins || []).length;
    installed.plugins = (installed.plugins || [])
      .filter((p) => !p || !pluginIds.includes(p.id));
    if (installed.plugins.length !== before) {
      writeInstalledPlugins(installedFile, installed);
      log(`✅ 已移除插件注册（剩余 ${installed.plugins.length} 个）`);
    } else {
      log('ℹ️  插件注册不存在，跳过');
    }
  } else if (DRY_RUN && fs.existsSync(installedFile)) {
    log(`  [dry-run] 将从 ${installedFile} 移除插件注册`);
  }

  // 1b. 卸载图标 marketplace（C3：卸载对称，此前安装注入但从不清理）
  //
  // 清理三处：known_marketplaces.json 的 wutian122 条目、
  // marketplaces/wutian122-expert-system/ 目录、config.json 的
  // enabledPlugins 两个命名空间键。函数内部对不存在项自动跳过，
  // dry-run 由 act() 收口（只打印不写）。
  if (DRY_RUN) {
    log(`  [dry-run] 将清理图标 marketplace ${ICON_MARKETPLACE_ID}`);
  }
  removeIconMarketplace(zcodeDir);

  // 2. 移除插件缓存目录
  const pluginRoot = path.join(
    zcodeDir, 'cli', 'plugins', 'cache', MARKETPLACE, PLUGIN_NAME
  );
  removePath(pluginRoot, '删除插件缓存');

  // 3. 移除独立技能目录
  const legacySkillDir = path.join(zcodeDir, 'skills', SKILL_NAME);
  removePath(legacySkillDir, '删除技能目录');

  // 3c. 移除 vendored 技能（按部署清单精确删除，绝不按前缀扫）
  const skillsManifestFile = path.join(zcodeDir, 'expert-system', 'deployed-skills.json');
  let skillsRemoved = 0;
  if (fs.existsSync(skillsManifestFile)) {
    try {
      const skillsManifest = JSON.parse(fs.readFileSync(skillsManifestFile, 'utf8'));
      const skillNames = Array.isArray(skillsManifest.skills) ? skillsManifest.skills : [];
      for (const name of skillNames) {
        // P2-3（2026-11-19，方案 B 单写对齐）：vendored 技能只部署到插件缓存
        // （见步骤 1c' :475），卸载侧也只删插件缓存这一处——原 :798 预留的
        // `zcodeDir/skills/<name>` 删除路径是安装侧从未写入的死分支，删除使
        // 安装/卸载两侧对齐，不再单边缺口。
        const targets = [
          path.join(pluginRoot, 'skills', name),   // 插件缓存（唯一部署位置）
        ];
        for (const target of targets) {
          if (fs.existsSync(target)) {
            removeFile(target, `删除技能 ${target}`);
            skillsRemoved += 1;
          }
        }
      }
      act(`删除技能清单 ${skillsManifestFile}`, () => fs.rmSync(skillsManifestFile, { force: true }));
      // P1：卸载计数在 dry-run 下是「现存还剩多少个」，不是「已删除多少个」。
      // 旧措辞 `✅ 已按清单删除 N 个` 在 dry-run 下与事实相反（removeFile 未删）。
      done(`✅ 已按清单删除 ${skillsRemoved} 个 vendored 技能`);
    } catch (err) {
      log(`⚠️  技能清单读取失败，保留技能目录不删: ${err.message}`);
    }
  } else {
    log('ℹ️  未找到技能清单，跳过 vendored 技能清理');
  }

  // 3b. 移除命令兜底目录（按清单精确删除本插件投放的命令文件）
  const cmdManifestFile = path.join(zcodeDir, 'expert-system', 'deployed-commands.json');
  let cmdRemoved = 0;
  if (fs.existsSync(cmdManifestFile)) {
    try {
      const cmdManifest = JSON.parse(fs.readFileSync(cmdManifestFile, 'utf8'));
      const rels = Array.isArray(cmdManifest.commands) ? cmdManifest.commands : [];
      for (const rel of rels) {
        const target = path.join(zcodeDir, 'commands', rel);
        if (fs.existsSync(target)) {
          removeFile(target, `删除命令 ${target}`);
          cmdRemoved += 1;
        }
      }
      act(`删除命令清单 ${cmdManifestFile}`, () => fs.rmSync(cmdManifestFile, { force: true }));
      // 清理命令子目录（仅在已空时；非空说明有别处文件，保留）
      const wfDir = path.join(zcodeDir, 'commands', 'wf');
      if (fs.existsSync(wfDir) && fs.readdirSync(wfDir).length === 0) {
        act(`删除已空的命令目录 ${wfDir}`,
          () => fs.rmSync(wfDir, { recursive: true, force: true }));
      }
      // P1：同技能清单——dry-run 下 cmdRemoved 只是「清单里现存的文件数」，
      // 不是已删除数。措辞改由 done() 在 dry-run 下陈述真实事实。
      done(`✅ 已按清单删除 ${cmdRemoved} 个命令文件（未触碰其他插件）`);
    } catch (err) {
      log(`⚠️  命令清单读取失败，保留目录不删: ${err.message}`);
    }
  } else {
    log('ℹ️  未找到命令清单，跳过命令清理（避免误删其他插件的 wf 命名空间）');
  }

  // 4. 移除子智能体（按安装清单精确删除，绝不按前缀扫）
  //
  // 缺陷 #24 族：旧实现在「清单缺失」时**回退到前缀扫描**，会误删其他插件
  // 投放的 `manager-*` / `expert-*` 文件。现在的取舍是明确的：
  // **宁可留残留，不可误删**。清单缺失时只报告，不动手。
  const agentsDest = path.join(zcodeDir, 'agents');
  const manifestFile = path.join(zcodeDir, 'expert-system', 'deployed-agents.json');
  let removedMgr = 0;
  let removedExp = 0;

  let deployed = null;
  try {
    if (fs.existsSync(manifestFile)) {
      deployed = JSON.parse(fs.readFileSync(manifestFile, 'utf8'));
    }
  } catch (err) {
    log(`⚠️  安装清单读取失败，跳过子代理删除以免误删其他插件: ${err.message}`);
  }

  if (deployed && Array.isArray(deployed.agents)) {
    for (const name of deployed.agents) {
      const target = path.join(agentsDest, name);
      if (!fs.existsSync(target)) continue;
      removeFile(target, `删除子代理 ${target}`);
      if (name.startsWith('manager-')) removedMgr += 1;
      else if (name.startsWith('expert-')) removedExp += 1;
    }
    act(`删除安装清单 ${manifestFile}`, () => fs.rmSync(manifestFile, { force: true }));
    log('ℹ️  已按安装清单精确删除（未触碰其他插件的子代理）');
  } else if (fs.existsSync(agentsDest)) {
    log('⚠️  未找到安装清单：跳过子代理删除。');
    log('   若确需清理残留，请手工检查后逐个删除——脚本不按前缀扫，');
    log('   以免误删其他插件投放的 manager-* / expert-* 文件。');
  }
  done(`✅ 已移除 ${removedMgr} 个总经理子智能体、${removedExp} 个专家子智能体`);

  // 5. 清理部署残留
  //
  // 卸载主流程按清单精确删除，但会留下三类「无清单可循的残留」，
  // 这里统一兜底清理，避免用户反复重装后堆积：
  //   - 备份目录 skills/*.bak-*（本插件 install.js 每次覆盖技能目录前自动生成）
  //   - 已空的命令目录 commands/wf/（文件删完后若空则删目录）
  //   - 已空的 expert-system/ 目录（清单删完后若空则删目录）
  //
  // --purge 时额外清理用户运行时数据 expert-system/context/，
  // 实现彻底删除（默认保留，属用户数据）。

  // 5a. 备份目录（只删 .bak-<ts> 形式，不误删用户自建的其他目录）
  const skillsBase = path.join(zcodeDir, 'skills');
  if (fs.existsSync(skillsBase)) {
    for (const entry of fs.readdirSync(skillsBase, { withFileTypes: true })) {
      if (entry.isDirectory() && entry.name.startsWith(`${SKILL_NAME}.bak-`)) {
        removePath(path.join(skillsBase, entry.name), `删除备份目录 ${entry.name}`);
      }
    }
  }

  // 5b. 已空的命令目录
  const wfDir = path.join(zcodeDir, 'commands', 'wf');
  if (fs.existsSync(wfDir) && fs.readdirSync(wfDir).length === 0) {
    act(`删除已空的命令目录 ${wfDir}`,
      () => fs.rmSync(wfDir, { recursive: true, force: true }));
  }

  // 5c. 已空的 expert-system 目录（清单已删后）
  const esDir = path.join(zcodeDir, 'expert-system');
  if (fs.existsSync(esDir) && fs.readdirSync(esDir).length === 0) {
    act(`删除已空的 expert-system 目录 ${esDir}`,
      () => fs.rmSync(esDir, { recursive: true, force: true }));
  } else if (fs.existsSync(esDir) && !DRY_RUN) {
    log(`ℹ️  expert-system/ 仍有用户数据，保留（加 --purge 可连同运行时数据一起清除）`);
  }

  // 5d. --purge：连用户运行时数据一起清除
  if (PURGE) {
    const ctxDir = path.join(esDir, 'context');
    if (fs.existsSync(ctxDir)) {
      removePath(ctxDir, '删除运行时数据 context/');
    }
    if (fs.existsSync(esDir)) {
      act(`删除 expert-system 目录 ${esDir}`,
        () => fs.rmSync(esDir, { recursive: true, force: true }));
    }
    done(`✅ 已彻底清除（--purge）：运行时数据与残留目录全部删除`);
  }

  log('');
  log('🎉 卸载完成，请重启 ZCode。');
}

const arg = process.argv[2];

/** 解析 --targets 参数，如 --targets=zcode 或 --targets zcode,claude-code */
function parseTargetsArg() {
  const argv = process.argv;
  let raw = null;
  for (let i = 2; i < argv.length; i += 1) {
    if (argv[i].startsWith('--targets=')) {
      raw = argv[i].slice('--targets='.length);
    } else if (argv[i] === '--targets' && i + 1 < argv.length) {
      raw = argv[i + 1];
      i += 1;
    }
  }
  if (raw === null) return null;
  const valid = new Set(['zcode', 'claude-code']);
  const list = raw.split(',').map((s) => s.trim()).filter(Boolean);
  const bad = list.filter((s) => !valid.has(s));
  if (bad.length) {
    log(`❌ 未知目标：${bad.join(', ')}（可选：zcode, claude-code）`);
    process.exit(1);
  }
  if (list.length === 0) {
    log('❌ --targets 不能为空（可选：zcode, claude-code）');
    process.exit(1);
  }
  return list;
}

/**
 * 解析卸载目标标志 --zcode / --claude-code。
 * 返回 'zcode' | 'claude-code' | 'both'（未指定时为 'both'）。
 */
function parseUninstallTarget() {
  const argv = process.argv;
  let hasZcode = false;
  let hasClaude = false;
  for (const a of argv) {
    if (a === '--zcode') hasZcode = true;
    else if (a === '--claude-code') hasClaude = true;
  }
  if (hasZcode && hasClaude) return 'both';
  if (hasZcode) return 'zcode';
  if (hasClaude) return 'claude-code';
  return 'both';
}

async function main() {
  if (arg === '--uninstall' || arg === '-u') {
    const target = parseUninstallTarget();

    // 统一卸载入口：按 --zcode / --claude-code 标志分发
    if (target === 'claude-code') {
      const { uninstallClaudeCode } = require('./cc-uninstall');
      uninstallClaudeCode({ homeDir: os.homedir(), dryRun: DRY_RUN, logger: log });
      return;
    }
    if (target === 'zcode') {
      uninstall();
      return;
    }
    // both：先 Claude Code，再 ZCode
    const { uninstallClaudeCode } = require('./cc-uninstall');
    uninstallClaudeCode({ homeDir: os.homedir(), dryRun: DRY_RUN, logger: log });
    log('');
    uninstall();
    return;
  }

  if (arg === '--help' || arg === '-h') {
    log('用法：');
    log('  node scripts/install.js                    交互式选择安装目标');
    log('  node scripts/install.js --targets zcode    只装 ZCode');
    log('  node scripts/install.js --targets claude-code   只装 Claude Code');
    log('  node scripts/install.js --targets zcode,claude-code  两者都装');
    log('');
    log('  node scripts/install.js --dry-run          预演，不改动磁盘');
    log('  node scripts/install.js --uninstall                卸载 ZCode + Claude Code');
    log('  node scripts/install.js --uninstall --zcode        只卸载 ZCode');
    log('  node scripts/install.js --uninstall --claude-code  只卸载 Claude Code');
    log('  node scripts/install.js --uninstall --zcode --purge  卸载 ZCode 并清除所有残留');
    return;
  }

  // 显式 --targets 优先（脚本化/CI 场景，不弹菜单）
  const explicit = parseTargetsArg();
  const targets = explicit || await selectTargets(detectTargets(os.homedir()));

  install(targets);
}

main().catch((err) => {
  console.error('❌ 执行失败:', err.message);
  process.exit(1);
});