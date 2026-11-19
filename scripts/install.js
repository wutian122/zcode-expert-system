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
 *        注意：插件 manifest 的 agents 字段是 recorded-but-not-executed，
 *              插件无法贡献子代理，只能靠本脚本写入 ~/.zcode/agents/
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

// --dry-run：只打印计划，不动磁盘。所有写/删操作都经 guard() 收口。
const DRY_RUN = process.argv.includes('--dry-run');

/** 执行一个破坏性动作；dry-run 时只打印不执行。 */
function act(label, fn) {
  if (DRY_RUN) {
    log(`  [dry-run] 将${label}`);
    return undefined;
  }
  return fn();
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
function copyDir(src, dest) {
  fs.mkdirSync(dest, { recursive: true });
  for (const entry of fs.readdirSync(src, { withFileTypes: true })) {
    if (SKIP_NAMES.has(entry.name)) continue;
    const srcPath = path.join(src, entry.name);
    const destPath = path.join(dest, entry.name);
    // 按相对路径排除运行时产物（如 context/store 下的结果 JSON）
    const rel = path.relative(PROJECT_ROOT, srcPath).split(path.sep).join('/');
    if (SKIP_REL_PATHS.has(rel)) continue;
    if (entry.isDirectory()) {
      copyDir(srcPath, destPath);
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
    // 显式声明可执行组件：不声明则 commands 不会被加载（skills/hooks 有约定发现，commands 没有）
    skills: 'skills',
    commands: 'commands',
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

function install() {
  const homeDir = os.homedir();
  const zcodeDir = path.join(homeDir, '.zcode');

  // ---------- 0. 预检（必须在任何删除之前） ----------
  const pkg = preflight();
  const version = pkg.version || '3.0.0';

  log(`开始部署 ${PLUGIN_NAME} v${version} ...`);
  log(`源目录: ${PROJECT_ROOT}`);
  log(`目标 HOME: ${homeDir}${DRY_RUN ? '   [dry-run：不改动磁盘]' : ''}`);

  // ---------- 1. 插件缓存目录 ----------
  const pluginRoot = path.join(
    zcodeDir, 'cli', 'plugins', 'cache', MARKETPLACE, PLUGIN_NAME, version
  );
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
  log('✅ 插件清单已写入: .zcode-plugin/plugin.json');

  // 1b. 技能本体 -> <pluginRoot>/skills/<skill>/
  const skillDest = path.join(pluginRoot, 'skills', SKILL_NAME);
  if (!DRY_RUN) copyDir(PROJECT_ROOT, skillDest);

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
    log(`✅ vendored 技能已部署: ${deployedSkills.length} 个`);
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
  log('✅ 插件级 hooks 已写入: hooks/');

  // 1f. 插件级 commands -> <pluginRoot>/commands/
  const commandsSrc = path.join(PROJECT_ROOT, 'commands');
  if (!DRY_RUN && fs.existsSync(commandsSrc)) {
    copyDir(commandsSrc, path.join(pluginRoot, 'commands'));
  }
  log('✅ 插件级 commands 已写入: commands/');

  // ---------- 2. 技能独立目录（兼容仅扫描 ~/.zcode/skills 的版本） ----------
  //
  // **删前备份**（缺陷 #17b）：这个目录是**用户目录**，不是缓存。
  // 用户可能在里面改过 SKILL.md 或加了自己的 references。旧实现直接
  // `rmSync` 无备份清空——而同一脚本对 installed_plugins.json 是有
  // `.bak-<ts>` 的，策略不一致。现在改为 rename 备份，部署成功后才清。
  const legacySkillDir = path.join(zcodeDir, 'skills', SKILL_NAME);
  const skillBackup = backupDir(legacySkillDir);
  if (!DRY_RUN) copyDir(skillDest, legacySkillDir);
  log(`✅ 技能已同步: ${legacySkillDir}`
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
    log(`✅ 命令已同步: ${userCmdRoot}（${deployedCommands.length} 个）`);

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
  const agentsSrc = path.join(PROJECT_ROOT, 'agents');
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
    log(`✅ 已清理 ${stale.length} 个陈旧子代理（源里已删）`);
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

  log(`✅ 已部署 ${managerCount} 个总经理子智能体 -> ${agentsDest}`);
  log(`✅ 已部署 ${expertCount} 位专家子智能体 -> ${agentsDest}`);

  // ---------- 4. 注册插件 ----------
  //
  // dry-run 时必须整段跳过：`writeInstalledPlugins` 内部会先 `copyFileSync`
  // 生成 `.bak-<ts>` 备份——那是写操作。初版漏了这一处保护，
  // 实测 dry-run 会在 `installed_plugins.json.bak-*` 留下一个文件（81 → 82）。
  const installedFile = path.join(zcodeDir, 'cli', 'plugins', 'installed_plugins.json');
  if (DRY_RUN) {
    log(`  [dry-run] 将在 ${installedFile} 注册插件 ${PLUGIN_NAME}@${MARKETPLACE}`);
  } else {
    const installed = readInstalledPlugins(installedFile);
    installed.plugins = (installed.plugins || []).filter((p) => p.name !== PLUGIN_NAME);

    const now = new Date().toISOString();
    installed.plugins.push({
      id: `${PLUGIN_NAME}@${MARKETPLACE}`,
      name: PLUGIN_NAME,
      marketplace: MARKETPLACE,
      version,
      installPath: pluginRoot,
      installedAt: now,
      updatedAt: now,
      scope: 'user',
      source: { source: 'local', type: 'directory', path: PLUGIN_NAME },
      cacheTransactionId: crypto.randomUUID(),
    });
    writeInstalledPlugins(installedFile, installed);
    log(`✅ 已注册插件: ${PLUGIN_NAME}@${MARKETPLACE}（共 ${installed.plugins.length} 个）`);
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

  // 1. 移除插件注册
  const installedFile = path.join(zcodeDir, 'cli', 'plugins', 'installed_plugins.json');
  if (!DRY_RUN && fs.existsSync(installedFile)) {
    const installed = readInstalledPlugins(installedFile);
    const before = (installed.plugins || []).length;
    installed.plugins = (installed.plugins || []).filter((p) => p.name !== PLUGIN_NAME);
    if (installed.plugins.length !== before) {
      writeInstalledPlugins(installedFile, installed);
      log(`✅ 已移除插件注册（剩余 ${installed.plugins.length} 个）`);
    } else {
      log('ℹ️  插件注册不存在，跳过');
    }
  } else if (DRY_RUN && fs.existsSync(installedFile)) {
    log(`  [dry-run] 将从 ${installedFile} 移除插件注册`);
  }

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
      log(`✅ 已按清单删除 ${skillsRemoved} 个 vendored 技能`);
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
      log(`✅ 已按清单删除 ${cmdRemoved} 个命令文件（未触碰其他插件）`);
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
  log(`✅ 已移除 ${removedMgr} 个总经理子智能体、${removedExp} 个专家子智能体`);

  log('');
  log('🎉 卸载完成，请重启 ZCode。');
}

const arg = process.argv[2];
try {
  if (arg === '--uninstall' || arg === '-u') {
    uninstall();
  } else {
    install();
  }
} catch (err) {
  console.error('❌ 执行失败:', err.message);
  process.exit(1);
}