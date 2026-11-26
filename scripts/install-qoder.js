#!/usr/bin/env node
/**
 * ZCode Expert System - Qoder Desktop adapter
 *
 * Qoder Desktop shares the same user-level extension conventions as Qoder CLI:
 *   ~/.qoder/skills/<name>/          Skills
 *   ~/.qoder/commands/<dir>/*.md     Commands (subdirs map to /dir:command)
 *   ~/.qoder/agents/*.md             User-level subagents
 *   ~/.qoder/settings.json           User-level Hooks
 *
 * This installer is deliberately additive. It never reads or writes
 * ~/.zcode, ~/.claude, .zcode-plugin, or .claude-plugin, so the existing
 * ZCode and Claude Code deployment chains remain untouched.
 *
 * Design choice: deploy user-level components instead of a Plugin ZIP.
 * Qoder may prefix plugin-provided command names with the plugin id. Keeping
 * commands in ~/.qoder/commands/wf/ preserves the existing `/wf:triage`
 * invocation names exactly.
 *
 * Usage:
 *   node scripts/install-qoder.js                 install / upgrade
 *   node scripts/install-qoder.js --dry-run       preview, no writes
 *   node scripts/install-qoder.js --status        inspect installation
 *   node scripts/install-qoder.js --uninstall     remove only our files
 *   node scripts/install-qoder.js --uninstall --purge
 */

const fs = require('fs');
const path = require('path');
const os = require('os');
const crypto = require('crypto');

const PROJECT_ROOT = path.dirname(__dirname);
const PLUGIN_NAME = 'zcode-expert-system';
const HOOK_NAME = `${PLUGIN_NAME}-routing`;
const DRY_RUN = process.argv.includes('--dry-run');
const UNINSTALL = process.argv.includes('--uninstall');
const PURGE = process.argv.includes('--purge');
const STATUS = process.argv.includes('--status');
const JSON_OUT = process.argv.includes('--json');

function isInside(child, parent) {
  const c = path.resolve(child);
  const p = path.resolve(parent);
  const rel = path.relative(p, c);
  return rel === '' || (!rel.startsWith('..') && !path.isAbsolute(rel));
}

function resolveQoderDir(homeDir) {
  let dir;
  if (process.env.QODER_HOME) {
    dir = path.resolve(process.env.QODER_HOME);
  } else {
    const standard = path.join(homeDir, '.qoder');
    const cn = path.join(homeDir, '.qoder-cn');
    dir = fs.existsSync(standard) ? standard : (fs.existsSync(cn) ? cn : standard);
  }

  // QODER_HOME 是宿主注入值，但安装器不能无条件信任它：一旦误指向
  // ~/.zcode 或 ~/.claude，就会把 Qoder 形状的 Hook/agents 写进另一套宿主。
  const forbidden = [
    path.join(homeDir, '.zcode'),
    path.join(homeDir, '.claude'),
  ];
  for (const bad of forbidden) {
    if (isInside(dir, bad) || isInside(bad, dir)) {
      throw new Error(
        `QODER_HOME 指向了受保护的宿主目录：${dir}（禁止落在 ${bad} 内）。` +
        ' 请修正 QODER_HOME 或改用 ~/.qoder / ~/.qoder-cn。'
      );
    }
  }
  const base = path.basename(dir).toLowerCase();
  if (base !== '.qoder' && base !== '.qoder-cn') {
    throw new Error(
      `QODER_HOME 的目录名必须是 .qoder 或 .qoder-cn，实际为：${dir}。` +
      ' 为防止误写其他宿主，安装器已中止。'
    );
  }
  return dir;
}

const HOME_DIR = os.homedir();
let QODER_DIR;
try {
  QODER_DIR = resolveQoderDir(HOME_DIR);
} catch (err) {
  console.error(`❌ Qoder 适配中止：${err.message}`);
  process.exit(1);
}
const SKILL_DIR = path.join(QODER_DIR, 'skills', PLUGIN_NAME);
const COMMANDS_DIR = path.join(QODER_DIR, 'commands', 'wf');
const AGENTS_DIR = path.join(QODER_DIR, 'agents');
const SETTINGS_FILE = path.join(QODER_DIR, 'settings.json');
const MANIFEST_DIR = path.join(QODER_DIR, 'expert-system');
const MANIFEST_FILE = path.join(MANIFEST_DIR, 'qoder-deployed.json');
const BACKUP_DIR = path.join(MANIFEST_DIR, 'backups');
const BUILD_MARKER = '.zcode-qoder-build.json';
const ADAPTER_MARKER = '<!-- zcode-expert-system:qoder-adapter -->';

const SKIP_NAMES = new Set([
  'node_modules', '.git', '.github', '.claude', '.claude-plugin',
  '.zcode', '.zcode-plugin', '.qoder', '.qoder-plugin',
  '.mimosa', '.superpowers', '.pytest_cache', '__pycache__',
  'tests', 'dist', 'vendor', 'package-lock.json',
]);

const SKIP_REL_PATHS = new Set(['context/store']);
const VALID_COLORS = new Set([
  'red', 'blue', 'green', 'yellow', 'purple', 'orange', 'pink', 'cyan',
]);

function log(msg) {
  console.log(msg);
}

function act(label, fn) {
  if (DRY_RUN) {
    log(`  [dry-run] ${label}`);
    return;
  }
  log(`  ${label}`);
  fn();
}

function ensureDir(dir) {
  if (!DRY_RUN) fs.mkdirSync(dir, { recursive: true });
}

function removePath(target, label) {
  act(label || `删除 ${target}`, () => {
    fs.rmSync(target, { recursive: true, force: true });
  });
}

function copyDir(src, dest, opts = {}) {
  const skip = new Set([...(opts.skip || []), ...SKIP_NAMES]);
  ensureDir(dest);
  for (const entry of fs.readdirSync(src, { withFileTypes: true })) {
    if (skip.has(entry.name)) continue;
    const srcPath = path.join(src, entry.name);
    const destPath = path.join(dest, entry.name);
    const rel = path.relative(PROJECT_ROOT, srcPath).split(path.sep).join('/');
    if (SKIP_REL_PATHS.has(rel)) continue;
    if (entry.isDirectory()) {
      copyDir(srcPath, destPath, opts);
    } else {
      fs.copyFileSync(srcPath, destPath);
    }
  }
}

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

function qoderColor(value) {
  return VALID_COLORS.has(value) ? value : 'blue';
}

/**
 * Convert our manager/expert Markdown into Qoder Subagent frontmatter.
 * Keep only documented fields; manager metadata/input/output are intentionally
 * dropped (Qoder ignores unknown fields, but a clean file is easier to audit).
 */
function buildQoderAgent(slugOrId, rawContent) {
  const { frontmatter, body } = parseMarkdown(rawContent);
  const heading = body.match(/^#\s+(.+)$/m);
  const name = frontmatter.name || (heading ? heading[1].trim() : slugOrId);
  const description = (frontmatter.description || name)
    .replace(/\r?\n/g, ' ').trim().replace(/"/g, "'");
  return {
    name,
    content: [
      '---',
      `name: "${name.replace(/"/g, "'")}"`,
      `description: "${description}"`,
      `color: ${qoderColor(frontmatter.color)}`,
      '---',
      '',
      ADAPTER_MARKER,
      '',
      body.trim(),
      '',
    ].join('\n'),
  };
}

function ensureTrailingSlashFree(p) {
  return p.replace(/\\/g, '/').replace(/\/+$/, '');
}

/**
 * Commands and SKILL.md are shared with ZCode/Claude. Rewrite host placeholders
 * only in the deployed Qoder copy; the source files stay host-neutral.
 */
function rewriteHostPaths(text, skillDir) {
  const sd = ensureTrailingSlashFree(skillDir);
  const replacements = [
    '${CLAUDE_PLUGIN_ROOT:-${ZCODE_PLUGIN_ROOT:-$QODER_PLUGIN_ROOT}}/skills/zcode-expert-system',
    '${CLAUDE_PLUGIN_ROOT:-$ZCODE_PLUGIN_ROOT}/skills/zcode-expert-system',
    '${QODER_PLUGIN_ROOT}/skills/zcode-expert-system',
    '${ZCODE_PLUGIN_ROOT}/skills/zcode-expert-system',
    '$ZCODE_PLUGIN_ROOT/skills/zcode-expert-system',
    '$CLAUDE_PLUGIN_ROOT/skills/zcode-expert-system',
    '${CLAUDE_PLUGIN_ROOT:-${ZCODE_PLUGIN_ROOT:-$QODER_PLUGIN_ROOT}}',
    '${CLAUDE_PLUGIN_ROOT:-$ZCODE_PLUGIN_ROOT}',
    '${QODER_PLUGIN_ROOT}',
    '${ZCODE_PLUGIN_ROOT}',
    '${CLAUDE_PLUGIN_ROOT}',
    '$ZCODE_PLUGIN_ROOT',
    '$CLAUDE_PLUGIN_ROOT',
  ];
  let out = text;
  for (const needle of replacements) {
    out = out.split(needle).join(sd);
  }
  return out;
}

/**
 * Add an ownership marker after frontmatter. It is an HTML comment, so Qoder
 * ignores it visually, but uninstall can recover our files if the manifest is lost.
 */
function markQoderMarkdown(content) {
  if (content.includes(ADAPTER_MARKER)) return content;
  const m = content.match(/^---\r?\n[\s\S]*?\r?\n---\r?\n/);
  if (m) {
    return m[0] + '\n' + ADAPTER_MARKER + '\n' + content.slice(m[0].length);
  }
  return ADAPTER_MARKER + '\n' + content;
}

function rewriteMarkdownTree(root, skillDir) {
  if (DRY_RUN || !fs.existsSync(root)) return 0;
  let changed = 0;
  const walk = (dir) => {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const p = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        walk(p);
      } else if (entry.isFile() && entry.name.endsWith('.md')) {
        const raw = fs.readFileSync(p, 'utf8');
        const next = rewriteHostPaths(raw, skillDir);
        if (next !== raw) {
          fs.writeFileSync(p, next, 'utf8');
          changed += 1;
        }
      }
    }
  };
  walk(root);
  return changed;
}

function hashSourceTree(root) {
  const h = crypto.createHash('sha256');
  const walk = (dir) => {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true }).sort(
      (a, b) => a.name.localeCompare(b.name))) {
      if (SKIP_NAMES.has(entry.name)) continue;
      const p = path.join(dir, entry.name);
      const rel = path.relative(root, p).split(path.sep).join('/');
      if (SKIP_REL_PATHS.has(rel)) continue;
      if (entry.isDirectory()) {
        h.update('D:' + rel + '\n');
        walk(p);
      } else {
        h.update('F:' + rel + '\n');
        h.update(fs.readFileSync(p));
      }
    }
  };
  walk(root);
  return h.digest('hex');
}

function readJson(file, fallback = null) {
  try {
    if (!fs.existsSync(file)) return fallback;
    return JSON.parse(fs.readFileSync(file, 'utf8'));
  } catch {
    return fallback;
  }
}

function writeJson(file, data) {
  if (DRY_RUN) return;
  const text = JSON.stringify(data, null, 2) + '\n';
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const tmp = `${file}.tmp-${process.pid}-${Date.now()}`;
  fs.writeFileSync(tmp, text, 'utf8');
  fs.renameSync(tmp, file);
}

function backupFile(file, backupRoot) {
  if (DRY_RUN || !fs.existsSync(file)) return null;
  fs.mkdirSync(backupRoot, { recursive: true });
  const stamp = new Date().toISOString().replace(/[:.]/g, '-');
  const dest = path.join(backupRoot, `${path.basename(file)}.bak-${stamp}`);
  fs.copyFileSync(file, dest);
  return dest;
}

/** 技能目录必须存在的运行时组件（相对技能根）。
 *
 * v3.2.5：`scripts/workflow_check.py` 是 `/wf:*` 命令的机械核对入口
 * （含 dispatch 派发证据门禁），`config/categories.json` 的 32 类
 * description 是域路由画像，`templates` / `references` 是账本模板与
 * 阶段说明。缺一项，装出来的就是残件。
 */
const RUNTIME_COMPONENTS = [
  'scripts/workflow_check.py',
  'config/categories.json',
  'config/experts.json',
  'config/workflow.json',
  'templates',
  'references',
  'agents',
  'commands',
  'hooks',
  'SKILL.md',
  'zcode_dev_workflow.py',
  'zcode_expert_system.py',
  'skill_entry.py',
];

/** 不得出现在技能目录里的开发期内容（源树回归防线不属于运行时）。 */
const FORBIDDEN_IN_SKILL = ['tests', 'vendor', '.pytest_cache', '.superpowers'];

/** 校验 `<root>/config/categories.json`：32 类且每类 description 可读。 */
function checkCategoriesProfile(root) {
  const file = path.join(root, 'config', 'categories.json');
  if (!fs.existsSync(file)) return [`缺 config/categories.json：${file}`];
  let data;
  try {
    data = JSON.parse(fs.readFileSync(file, 'utf8'));
  } catch (err) {
    return [`config/categories.json 不是合法 JSON：${err.message}`];
  }
  if (!data || typeof data !== 'object' || Array.isArray(data)) {
    return ['config/categories.json 顶层必须是对象（分类名 → 分类定义）'];
  }
  const problems = [];
  const keys = Object.keys(data);
  if (keys.length !== 32) {
    problems.push(`config/categories.json 分类数 ${keys.length}（应为 32）`);
  }
  const noDesc = keys.filter(
    (k) => !data[k] || !String(data[k].description || '').trim());
  if (noDesc.length) {
    problems.push(
      `config/categories.json 有 ${noDesc.length} 个分类缺 description：`
      + noDesc.slice(0, 6).join(', '));
  }
  return problems;
}

/**
 * 部署后校验（v3.2.5）：技能目录缺运行时组件、或夹带 tests/vendor 即失败。
 * 校验失败抛错 → main 捕获 → rc=1，不写部署清单（不留「已安装」假象）。
 */
function verifyDeployment() {
  if (DRY_RUN) return;
  const problems = RUNTIME_COMPONENTS
    .filter(rel => !fs.existsSync(path.join(SKILL_DIR, rel)))
    .map(rel => `缺 ${rel}`);
  problems.push(...checkCategoriesProfile(SKILL_DIR));
  for (const name of FORBIDDEN_IN_SKILL) {
    if (fs.existsSync(path.join(SKILL_DIR, name))) {
      problems.push(`技能目录混入开发期内容：${name}/`);
    }
  }
  if (problems.length) {
    throw new Error(
      '部署校验失败（技能目录不完整）：' + problems.join('；') +
      '；请检查源树后重装（未写入部署清单）');
  }
  log(`  ✅ 部署校验通过：workflow_check / categories(32 类) / templates / references 均在位`);
}

function preflight() {
  const required = [
    'SKILL.md', 'config', 'agents', 'commands', 'hooks',
    'scripts', 'references', 'templates',
    'scripts/workflow_check.py', 'config/categories.json',
    'zcode_dev_workflow.py', 'zcode_expert_system.py',
    'hooks/prepend-global-rules-reminder.mjs',
  ];
  const missing = required.filter(rel => !fs.existsSync(path.join(PROJECT_ROOT, rel)));
  if (missing.length) {
    throw new Error(`[preflight] 源树缺少 Qoder 部署必需组件：${missing.join(', ')}`);
  }

  const profileProblems = checkCategoriesProfile(PROJECT_ROOT);
  if (profileProblems.length) {
    throw new Error(`[preflight] 源树类目画像不完整：${profileProblems.join('；')}`);
  }

  const agents = fs.readdirSync(path.join(PROJECT_ROOT, 'agents'))
    .filter(f => f.endsWith('.md'));
  const managers = agents.filter(f => f.startsWith('manager-'));
  const experts = agents.filter(f => f.startsWith('expert-'));
  if (managers.length !== 32 || experts.length !== 331) {
    throw new Error(
      `[preflight] agents 数量异常：manager=${managers.length}（应为 32），` +
      `expert=${experts.length}（应为 331）`
    );
  }

  if (fs.existsSync(SETTINGS_FILE)) {
    let parsed;
    try {
      parsed = JSON.parse(fs.readFileSync(SETTINGS_FILE, 'utf8'));
    } catch (err) {
      throw new Error(`[preflight] ~/.qoder/settings.json 不是合法 JSON，拒绝合并 Hook：${err.message}`);
    }
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      throw new Error('[preflight] ~/.qoder/settings.json 顶层必须是对象，拒绝合并 Hook');
    }
    if (parsed.hooks !== undefined && (
      !parsed.hooks || typeof parsed.hooks !== 'object' || Array.isArray(parsed.hooks)
    )) {
      throw new Error('[preflight] settings.json 的 hooks 字段不是对象，拒绝覆盖');
    }
    if (parsed.hooks && parsed.hooks.UserPromptSubmit !== undefined
        && !Array.isArray(parsed.hooks.UserPromptSubmit)) {
      throw new Error(
        '[preflight] settings.json 的 hooks.UserPromptSubmit 必须是数组，' +
        '当前形状无法安全合并，已中止（未修改任何文件）'
      );
    }
  }

  return { managers: managers.length, experts: experts.length };
}

function loadSourceHash() {
  return hashSourceTree(PROJECT_ROOT);
}

function installSkill(sourceHash) {
  const existingMarker = readJson(path.join(SKILL_DIR, BUILD_MARKER), null);
  if (existingMarker && existingMarker.sourceHash === sourceHash
      && fs.existsSync(path.join(SKILL_DIR, 'SKILL.md'))) {
    log(`  = Qoder 技能已是当前版本，跳过复制：${SKILL_DIR}`);
    return null;
  }

  let backup = null;
  if (fs.existsSync(SKILL_DIR)) {
    if (!isQoderOwnedDir(SKILL_DIR)) {
      throw new Error(
        `拒绝覆盖非本插件创建的技能目录：${SKILL_DIR}` +
        '（未找到 .zcode-qoder-build.json；请先移走该目录）');
    }
    const stamp = new Date().toISOString().replace(/[:.]/g, '-');
    backup = path.join(BACKUP_DIR, `${PLUGIN_NAME}-skill-${stamp}`);
    act(`备份旧 Qoder 技能 → ${backup}`, () => {
      fs.mkdirSync(BACKUP_DIR, { recursive: true });
      fs.cpSync(SKILL_DIR, backup, { recursive: true });
      fs.rmSync(SKILL_DIR, { recursive: true, force: true });
    });
  }

  try {
    act(`复制技能到 ${SKILL_DIR}`, () => {
      fs.mkdirSync(SKILL_DIR, { recursive: true });
      copyDir(PROJECT_ROOT, SKILL_DIR);
    });
    if (!DRY_RUN) {
      const rewritten = rewriteMarkdownTree(SKILL_DIR, SKILL_DIR);
      writeJson(path.join(SKILL_DIR, BUILD_MARKER), {
        host: 'qoder',
        adapterMarker: ADAPTER_MARKER,
        version: readJson(path.join(PROJECT_ROOT, 'package.json'), {}).version,
        sourceHash,
        rewrittenMarkdownFiles: rewritten,
      });
    }
  } catch (err) {
    if (!DRY_RUN && backup && fs.existsSync(backup)) {
      try {
        fs.rmSync(SKILL_DIR, { recursive: true, force: true });
        fs.cpSync(backup, SKILL_DIR, { recursive: true });
        log(`⚠️  技能复制失败，已从备份恢复：${backup}`);
      } catch (restoreErr) {
        log(`⚠️  技能回滚失败，请手工恢复：${backup}（${restoreErr.message}）`);
      }
    }
    throw err;
  }
  return backup;
}

function installVendorSkills(sourceHash) {
  const srcRoot = path.join(PROJECT_ROOT, 'vendor', 'skills');
  // null 表示源缺失：调用方必须保留上版清单，不能静默删除已部署技能。
  if (!fs.existsSync(srcRoot)) return null;
  const names = [];
  const conflicts = [];
  for (const entry of fs.readdirSync(srcRoot, { withFileTypes: true })) {
    if (!entry.isDirectory()) continue;
    const name = entry.name;
    const src = path.join(srcRoot, name);
    const dest = path.join(QODER_DIR, 'skills', name);
    if (fs.existsSync(dest) && !isQoderOwnedDir(dest)) {
      log(`  ⚠️  技能 ${name} 已存在且不属于本插件，保留用户版本并跳过`);
      conflicts.push(`skills/${name}`);
      continue;
    }
    const marker = readJson(path.join(dest, BUILD_MARKER), null);
    if (marker && marker.sourceHash === hashSourceTree(src)) {
      log(`  = Qoder 技能 ${name} 已是最新，跳过`);
      names.push(name);
      continue;
    }
    if (fs.existsSync(dest)) {
      const stamp = new Date().toISOString().replace(/[:.]/g, '-');
      act(`备份旧技能 ${name}`, () => {
        const backup = path.join(BACKUP_DIR, `${name}-${stamp}`);
        fs.mkdirSync(BACKUP_DIR, { recursive: true });
        fs.cpSync(dest, backup, { recursive: true });
        fs.rmSync(dest, { recursive: true, force: true });
      });
    }
    act(`部署 Qoder 技能 ${name}`, () => {
      fs.mkdirSync(dest, { recursive: true });
      copyDir(src, dest);
    });
    if (!DRY_RUN) {
      writeJson(path.join(dest, BUILD_MARKER), {
        host: 'qoder',
        adapterMarker: ADAPTER_MARKER,
        version: readJson(path.join(PROJECT_ROOT, 'package.json'), {}).version,
        sourceHash: hashSourceTree(src),
      });
    }
    names.push(name);
  }
  return { names, conflicts };
}

function isOwnedCommand(text) {
  if (text.includes(ADAPTER_MARKER)) return true;
  return text.includes(ensureTrailingSlashFree(SKILL_DIR));
}

function installCommands() {
  const srcDir = path.join(PROJECT_ROOT, 'commands', 'wf');
  const deployed = [];
  const conflicts = [];
  if (!fs.existsSync(srcDir)) return { commands: deployed, conflicts };

  if (!DRY_RUN) fs.mkdirSync(COMMANDS_DIR, { recursive: true });
  for (const file of fs.readdirSync(srcDir)) {
    if (!file.endsWith('.md')) continue;
    const src = path.join(srcDir, file);
    const dest = path.join(COMMANDS_DIR, file);
    const content = markQoderMarkdown(
      rewriteHostPaths(fs.readFileSync(src, 'utf8'), SKILL_DIR));
    if (fs.existsSync(dest)) {
      const old = fs.readFileSync(dest, 'utf8');
      if (!isOwnedCommand(old)) {
        log(`  ⚠️  命令 wf:${file.replace(/\.md$/, '')} 已存在且不属于本插件，保留用户版本`);
        conflicts.push(`wf/${file}`);
        continue;
      }
      if (old === content) {
        deployed.push(`wf/${file}`);
        continue;
      }
      if (!DRY_RUN) backupFile(dest, path.join(MANIFEST_DIR, 'backups', 'commands'));
    }
    act(`部署 Qoder 命令 wf:${file.replace(/\.md$/, '')}`, () => {
      fs.writeFileSync(dest, content, 'utf8');
    });
    deployed.push(`wf/${file}`);
  }
  return { commands: deployed, conflicts };
}

function installAgents() {
  const srcDir = path.join(PROJECT_ROOT, 'agents');
  const deployed = [];
  const conflicts = [];
  if (!DRY_RUN) fs.mkdirSync(AGENTS_DIR, { recursive: true });

  let updated = 0;
  let skipped = 0;
  for (const file of fs.readdirSync(srcDir)) {
    if (!file.endsWith('.md')) continue;
    if (!file.startsWith('manager-') && !file.startsWith('expert-')) continue;
    const src = path.join(srcDir, file);
    const dest = path.join(AGENTS_DIR, file);
    const built = buildQoderAgent(file.replace(/\.md$/, ''), fs.readFileSync(src, 'utf8'));
    if (fs.existsSync(dest)) {
      const old = fs.readFileSync(dest, 'utf8');
      if (!old.includes(ADAPTER_MARKER)) {
        log(`  ⚠️  子代理 ${file} 已存在且不属于本插件，保留用户版本`);
        conflicts.push(file);
        continue;
      }
      if (old === built.content) {
        deployed.push(file);
        skipped += 1;
        continue;
      }
      if (!DRY_RUN) backupFile(dest, path.join(MANIFEST_DIR, 'backups', 'agents'));
    }
    if (!DRY_RUN) fs.writeFileSync(dest, built.content, 'utf8');
    deployed.push(file);
    updated += 1;
  }
  log(`  子代理：${deployed.length} 个（更新 ${updated} / 已最新 ${skipped} / 冲突 ${conflicts.length}）`);
  return { agents: deployed, conflicts };
}

function removeStaleVendorSkills(previous, current) {
  const keep = new Set(current);
  let removed = 0;
  for (const name of previous) {
    if (keep.has(name)) continue;
    const target = path.join(QODER_DIR, 'skills', name);
    if (!fs.existsSync(target)) continue;
    if (!isQoderOwnedDir(target)) {
      log(`  ⚠️  陈旧技能 ${name} 已不属于本插件，保留用户版本`);
      continue;
    }
    const stamp = new Date().toISOString().replace(/[:.]/g, '-');
    act(`备份并移除陈旧技能 ${name}`, () => {
      const backup = path.join(BACKUP_DIR, `stale-${name}-${stamp}`);
      fs.mkdirSync(BACKUP_DIR, { recursive: true });
      fs.cpSync(target, backup, { recursive: true });
      fs.rmSync(target, { recursive: true, force: true });
    });
    removed += 1;
  }
  return removed;
}

function removeStaleAgents(previous, current) {
  const keep = new Set(current);
  let removed = 0;
  for (const name of previous) {
    if (keep.has(name)) continue;
    const p = path.join(AGENTS_DIR, name);
    if (!fs.existsSync(p)) continue;
    try {
      if (!fs.readFileSync(p, 'utf8').includes(ADAPTER_MARKER)) {
        log(`  ⚠️  陈旧子代理 ${name} 已不属于本插件，保留用户版本`);
        continue;
      }
    } catch {
      continue;
    }
    removePath(p, `移除陈旧 Qoder 子代理 ${name}`);
    removed += 1;
  }
  return removed;
}

function removeStaleCommands(previous, current) {
  const keep = new Set(current);
  let removed = 0;
  for (const rel of previous) {
    if (keep.has(rel)) continue;
    const p = path.join(QODER_DIR, 'commands', rel);
    if (!fs.existsSync(p)) continue;
    try {
      if (!isOwnedCommand(fs.readFileSync(p, 'utf8'))) {
        log(`  ⚠️  陈旧命令 ${rel} 已不属于本插件，保留用户版本`);
        continue;
      }
    } catch {
      continue;
    }
    removePath(p, `移除陈旧 Qoder 命令 ${rel}`);
    removed += 1;
  }
  return removed;
}

function hookEntry() {
  const hookFile = path.join(SKILL_DIR, 'hooks', 'prepend-global-rules-reminder.mjs');
  return {
    type: 'command',
    command: `node "${ensureTrailingSlashFree(hookFile)}"`,
    name: HOOK_NAME,
    timeout: 3,
    statusMessage: 'zcode-expert-system: 注入专家体系触发规则…',
  };
}

function isOwnHook(hook) {
  if (!hook || typeof hook !== 'object') return false;
  if (hook.name === HOOK_NAME) return true;
  if (typeof hook.command !== 'string') return false;
  const ownPath = ensureTrailingSlashFree(path.join(
    SKILL_DIR, 'hooks', 'prepend-global-rules-reminder.mjs'));
  return hook.command.includes(ownPath);
}

function mergeHook() {
  const settings = fs.existsSync(SETTINGS_FILE)
    ? JSON.parse(fs.readFileSync(SETTINGS_FILE, 'utf8'))
    : {};
  const hooks = (settings.hooks && typeof settings.hooks === 'object') ? settings.hooks : {};
  const groups = Array.isArray(hooks.UserPromptSubmit) ? hooks.UserPromptSubmit : [];

  const cleaned = groups
    .map(group => {
      if (!group || typeof group !== 'object' || !Array.isArray(group.hooks)) return group;
      return { ...group, hooks: group.hooks.filter(h => !isOwnHook(h)) };
    })
    .filter(group => !group || typeof group !== 'object'
      || !Array.isArray(group.hooks) || group.hooks.length > 0);

  const nextList = [...cleaned, { hooks: [hookEntry()] }];
  const next = { ...settings, hooks: { ...hooks, UserPromptSubmit: nextList } };
  const before = fs.existsSync(SETTINGS_FILE) ? fs.readFileSync(SETTINGS_FILE, 'utf8') : '';
  const after = JSON.stringify(next, null, 2) + '\n';
  if (before === after) {
    log('  = Qoder Hook 已存在且内容一致');
    return { changed: false, settings: next };
  }

  if (fs.existsSync(SETTINGS_FILE)) {
    const backup = backupFile(SETTINGS_FILE, path.join(MANIFEST_DIR, 'backups', 'settings'));
    if (backup) log(`  备份 Qoder settings → ${backup}`);
  }
  act(`合并 UserPromptSubmit Hook → ${SETTINGS_FILE}`, () => {
    // 与 writeJson 一致：tmp + rename，避免中断/磁盘满截断用户全局配置。
    writeJson(SETTINGS_FILE, next);
  });
  return { changed: true, settings: next };
}

function writeManifest(data) {
  if (DRY_RUN) {
    log(`  [dry-run] 写入部署清单 ${MANIFEST_FILE}`);
    return;
  }
  fs.mkdirSync(MANIFEST_DIR, { recursive: true });
  writeJson(MANIFEST_FILE, data);
}

function install() {
  const pkg = readJson(path.join(PROJECT_ROOT, 'package.json'), {});
  log(`开始部署 ${PLUGIN_NAME} 到 Qoder ...`);
  log(`源目录: ${PROJECT_ROOT}`);
  log(`Qoder 目录: ${QODER_DIR}${DRY_RUN ? '   [dry-run：不改动磁盘]' : ''}`);
  log('');

  const counts = preflight();
  const previous = readJson(MANIFEST_FILE, {});
  const sourceHash = loadSourceHash();

  log(`[1/5] 技能 → ${SKILL_DIR}`);
  const skillBackup = installSkill(sourceHash);

  log(`[2/5] vendored 技能`);
  const vendorResult = installVendorSkills(sourceHash);
  const vendorSourcePresent = vendorResult !== null;
  const vendorSkills = vendorSourcePresent
    ? vendorResult.names
    : (Array.isArray(previous.vendorSkills) ? previous.vendorSkills : []);
  if (!vendorSourcePresent) {
    log('  ⚠️  源树未包含 vendor/skills，保留上版已部署技能，跳过 stale 清理');
  }
  const removedVendorSkills = vendorSourcePresent
    ? removeStaleVendorSkills(
      Array.isArray(previous.vendorSkills) ? previous.vendorSkills : [],
      vendorSkills)
    : 0;

  log(`[3/5] 命令 → ${COMMANDS_DIR}`);
  const commandResult = installCommands();
  const commands = commandResult.commands;

  log(`[4/5] 子代理 → ${AGENTS_DIR}`);
  const agentResult = installAgents();
  const agents = agentResult.agents;
  const removedAgents = removeStaleAgents(
    Array.isArray(previous.agents) ? previous.agents : [], agents);
  const removedCommands = removeStaleCommands(
    Array.isArray(previous.commands) ? previous.commands : [], commands);
  const conflicts = [
    ...(vendorResult ? vendorResult.conflicts : []),
    ...commandResult.conflicts,
    ...agentResult.conflicts,
  ];

  log(`[5/5] UserPromptSubmit Hook → ${SETTINGS_FILE}`);
  const hook = mergeHook();

  // 部署后校验：技能目录不完整即抛错，不写部署清单（不留「已安装」假象）。
  verifyDeployment();

  writeManifest({
    host: 'qoder',
    version: pkg.version || '0.0.0',
    deployedAt: new Date().toISOString(),
    skillDir: SKILL_DIR,
    commandsDir: COMMANDS_DIR,
    agentsDir: AGENTS_DIR,
    settingsFile: SETTINGS_FILE,
    hookName: HOOK_NAME,
    commands,
    agents,
    vendorSkills,
    conflicts,
    skillBackup,
  });

  if (DRY_RUN) {
    log('');
    log('ℹ️  dry-run 结束：以上为计划动作，磁盘未改动。');
    return 0;
  }

  log('');
  log(`✅ Qoder 部署完成：${counts.managers} 个总经理 + ${counts.experts} 位专家`);
  log(`   技能：${SKILL_DIR}`);
  log(`   命令：${COMMANDS_DIR}（/wf:triage、/wf:plan、/wf:check …）`);
  log(`   子代理：${AGENTS_DIR}`);
  log(`   Hook：${SETTINGS_FILE} → UserPromptSubmit`);
  if (removedAgents || removedCommands || removedVendorSkills) {
    log(`   清理陈旧：${removedAgents} 个子代理 / ${removedCommands} 个命令 / ` +
        `${removedVendorSkills} 个技能`);
  }
  if (conflicts.length) {
    log(`   ⚠️  保留用户同名资产 ${conflicts.length} 个（未覆盖）：`);
    for (const c of conflicts.slice(0, 8)) log(`      · ${c}`);
  }
  log('');
  log('下一步：');
  log('  1. 重启 Qoder 或新建任务（Agent/Skill 清单是启动时加载的）');
  log('  2. 输入 /wf:triage <任务> 验证命令可见');
  log('  3. 直接下达专业任务，Hook 会自动注入两轴路由规则');
  log('  ZCode / Claude Code 侧未发生任何改动。');
  return 0;
}

function removeOwnHookFromSettings() {
  if (!fs.existsSync(SETTINGS_FILE)) return { changed: false };
  let settings;
  try {
    settings = JSON.parse(fs.readFileSync(SETTINGS_FILE, 'utf8'));
  } catch (err) {
    const backup = backupFile(
      SETTINGS_FILE, path.join(MANIFEST_DIR, 'backups', 'settings'));
    log(`  ⚠️  settings.json 无法解析，跳过 Hook 清理，继续卸载文件：${err.message}`);
    if (backup) log(`  损坏配置已备份：${backup}`);
    return { changed: false, error: err.message };
  }
  if (!settings.hooks || !Array.isArray(settings.hooks.UserPromptSubmit)) {
    return { changed: false };
  }
  const before = settings.hooks.UserPromptSubmit;
  const cleaned = before
    .map(group => {
      if (!group || typeof group !== 'object' || !Array.isArray(group.hooks)) return group;
      return { ...group, hooks: group.hooks.filter(h => !isOwnHook(h)) };
    })
    .filter(group => !group || typeof group !== 'object'
      || !Array.isArray(group.hooks) || group.hooks.length > 0);
  if (cleaned.length === before.length
      && JSON.stringify(cleaned) === JSON.stringify(before)) {
    return { changed: false, settings };
  }
  const next = { ...settings, hooks: { ...settings.hooks, UserPromptSubmit: cleaned } };
  if (cleaned.length === 0) delete next.hooks.UserPromptSubmit;
  const backup = backupFile(SETTINGS_FILE, path.join(MANIFEST_DIR, 'backups', 'settings'));
  if (backup) log(`  备份 Qoder settings → ${backup}`);
  act(`移除 Qoder UserPromptSubmit Hook → ${SETTINGS_FILE}`, () => {
    writeJson(SETTINGS_FILE, next);
  });
  return { changed: true, settings: next };
}

function readBuildMarker(dir) {
  return readJson(path.join(dir, BUILD_MARKER), null);
}

function isQoderOwnedDir(dir) {
  const marker = readBuildMarker(dir);
  return Boolean(marker && (marker.host === 'qoder'
    || marker.adapterMarker === ADAPTER_MARKER || marker.sourceHash));
}

function fallbackOwnedCommands() {
  // Manifest lost: only remove command files that still carry our marker.
  const out = [];
  if (!fs.existsSync(COMMANDS_DIR)) return out;
  for (const file of fs.readdirSync(COMMANDS_DIR)) {
    if (!file.endsWith('.md')) continue;
    const p = path.join(COMMANDS_DIR, file);
    try {
      const text = fs.readFileSync(p, 'utf8');
      if (text.includes(ADAPTER_MARKER)) out.push(`wf/${file}`);
    } catch {
      // unreadable -> leave it
    }
  }
  return out;
}

function fallbackOwnedAgents() {
  const out = [];
  if (!fs.existsSync(AGENTS_DIR)) return out;
  for (const file of fs.readdirSync(AGENTS_DIR)) {
    if (!file.endsWith('.md')) continue;
    const p = path.join(AGENTS_DIR, file);
    try {
      const head = fs.readFileSync(p, 'utf8').slice(0, 4096);
      if (head.includes(ADAPTER_MARKER)) out.push(file);
    } catch {
      // unreadable -> leave it
    }
  }
  return out;
}

function fallbackOwnedSkills() {
  const out = [];
  const root = path.join(QODER_DIR, 'skills');
  if (!fs.existsSync(root)) return out;
  for (const name of fs.readdirSync(root)) {
    if (name === PLUGIN_NAME) continue;
    const dir = path.join(root, name);
    try {
      if (fs.statSync(dir).isDirectory() && isQoderOwnedDir(dir)) out.push(name);
    } catch {
      // broken symlink / permission -> leave it
    }
  }
  return out;
}

function uninstall() {
  log(`开始从 Qoder 卸载 ${PLUGIN_NAME} ...`);
  log(`Qoder 目录: ${QODER_DIR}${DRY_RUN ? '   [dry-run：不改动磁盘]' : ''}`);
  const manifest = readJson(MANIFEST_FILE, {});
  const hasManifest = Boolean(manifest && manifest.version);
  if (!hasManifest) {
    log('  ⚠️  未找到部署清单，将按本插件写入的 ownership marker 精确回退清理');
  }

  log('[1/4] 移除 Hook');
  const hookResult = removeOwnHookFromSettings();
  const settingsBroken = Boolean(hookResult && hookResult.error);

  log('[2/4] 移除命令');
  const commands = hasManifest && Array.isArray(manifest.commands)
    ? manifest.commands : fallbackOwnedCommands();
  for (const rel of commands) {
    const target = path.join(QODER_DIR, 'commands', rel);
    if (!fs.existsSync(target)) continue;
    try {
      if (!isOwnedCommand(fs.readFileSync(target, 'utf8'))) {
        log(`  ⚠️  命令 ${rel} 已不属于本插件，保留用户版本`);
        continue;
      }
    } catch {
      continue;
    }
    removePath(target, `删除 Qoder 命令 ${rel}`);
  }
  if (fs.existsSync(COMMANDS_DIR)
      && fs.readdirSync(COMMANDS_DIR).length === 0) {
    removePath(COMMANDS_DIR, `删除已空命令目录 ${COMMANDS_DIR}`);
  }

  log('[3/4] 移除子代理');
  const agents = hasManifest && Array.isArray(manifest.agents)
    ? manifest.agents : fallbackOwnedAgents();
  for (const name of agents) {
    const target = path.join(AGENTS_DIR, name);
    if (!fs.existsSync(target)) continue;
    try {
      if (!fs.readFileSync(target, 'utf8').includes(ADAPTER_MARKER)) {
        log(`  ⚠️  子代理 ${name} 已不属于本插件，保留用户版本`);
        continue;
      }
    } catch {
      continue;
    }
    removePath(target, `删除 Qoder 子代理 ${name}`);
  }

  log('[4/4] 移除技能');
  const mainSkill = path.join(QODER_DIR, 'skills', PLUGIN_NAME);
  const vendor = hasManifest && Array.isArray(manifest.vendorSkills)
    ? manifest.vendorSkills : fallbackOwnedSkills();
  if (settingsBroken && fs.existsSync(mainSkill)) {
    // Hook 仍指向该技能；settings 修好前不能删，否则每轮 Hook 都会执行不存在的文件。
    log(`  ⚠️  settings.json 损坏：保留主技能目录 ${mainSkill}，修好配置后再卸载`);
  } else if (fs.existsSync(mainSkill) && isQoderOwnedDir(mainSkill)) {
    removePath(mainSkill, `删除 Qoder 技能 ${PLUGIN_NAME}`);
  } else if (fs.existsSync(mainSkill)) {
    log(`  ⚠️  保留非本插件创建的技能目录：${mainSkill}`);
  }
  for (const name of vendor) {
    const target = path.join(QODER_DIR, 'skills', name);
    if (!fs.existsSync(target)) continue;
    if (!isQoderOwnedDir(target)) {
      log(`  ⚠️  技能 ${name} 已不属于本插件，保留用户版本`);
      continue;
    }
    removePath(target, `删除 Qoder 技能 ${name}`);
  }

  if (fs.existsSync(MANIFEST_FILE)) removePath(MANIFEST_FILE, '删除 Qoder 部署清单');
  if (PURGE) {
    // 运行时上下文（QODER_HOME/expert-system/context）属用户数据，
    // 默认保留；--purge 才彻底删除，与 ZCode 侧语义对齐。
    const contextDir = path.join(MANIFEST_DIR, 'context');
    if (fs.existsSync(contextDir)) {
      removePath(contextDir, '删除 Qoder 运行时 context（--purge）');
    }
    removePath(BACKUP_DIR, '删除 Qoder 安装备份');
    if (fs.existsSync(MANIFEST_DIR) && fs.readdirSync(MANIFEST_DIR).length === 0) {
      removePath(MANIFEST_DIR, '删除已空 expert-system 目录');
    }
  }

  log('');
  log('✅ Qoder 侧卸载完成。ZCode / Claude Code 不受影响。');
  if (!PURGE) {
    log(`   安装备份保留在 ${BACKUP_DIR}（加 --purge 一并删除）`);
  }
  log('   重启 Qoder 或新建任务使清单更新。');
  return 0;
}

function status() {
  const manifest = readJson(MANIFEST_FILE, {});
  const settings = readJson(SETTINGS_FILE, {});
  const groups = settings && settings.hooks && Array.isArray(settings.hooks.UserPromptSubmit)
    ? settings.hooks.UserPromptSubmit : [];
  const hooks = groups.flatMap(g => (g && Array.isArray(g.hooks)) ? g.hooks : []);
  const ownHooks = hooks.filter(isOwnHook);
  const agentCount = Array.isArray(manifest.agents)
    ? manifest.agents.filter(name => fs.existsSync(path.join(AGENTS_DIR, name))).length
    : (fs.existsSync(AGENTS_DIR)
      ? fs.readdirSync(AGENTS_DIR).filter(f => f.endsWith('.md')).length : 0);
  const commandCount = Array.isArray(manifest.commands)
    ? manifest.commands.filter(rel => fs.existsSync(path.join(QODER_DIR, 'commands', rel))).length
    : (fs.existsSync(COMMANDS_DIR)
      ? fs.readdirSync(COMMANDS_DIR).filter(f => f.endsWith('.md')).length : 0);
  const skillOk = fs.existsSync(path.join(SKILL_DIR, 'SKILL.md'));

  const result = {
    host: 'qoder',
    qoderDir: QODER_DIR,
    installed: Boolean(manifest.version && skillOk && ownHooks.length > 0),
    version: manifest.version || null,
    skill: { path: SKILL_DIR, present: skillOk },
    commands: { path: COMMANDS_DIR, count: commandCount },
    agents: { path: AGENTS_DIR, count: agentCount },
    hook: { file: SETTINGS_FILE, present: ownHooks.length > 0, count: ownHooks.length },
    manifest: manifest.version ? MANIFEST_FILE : null,
  };

  if (JSON_OUT) {
    console.log(JSON.stringify(result, null, 2));
  } else {
    log('Qoder 专家体系状态');
    log(`  Qoder 目录：${QODER_DIR}`);
    log(`  已安装：${result.installed ? '是' : '否'}${result.version ? `（v${result.version}）` : ''}`);
    log(`  技能：${skillOk ? '存在' : '缺失'} — ${SKILL_DIR}`);
    log(`  命令：${commandCount} 个 — ${COMMANDS_DIR}`);
    log(`  子代理：${agentCount} 个 — ${AGENTS_DIR}`);
    log(`  路由 Hook：${ownHooks.length > 0 ? '已启用' : '未启用'} — ${SETTINGS_FILE}`);
  }
  return result.installed ? 0 : 1;
}

function main() {
  if (process.argv.includes('--help') || process.argv.includes('-h')) {
    log('用法：');
    log('  node scripts/install-qoder.js                 部署到 Qoder 用户目录');
    log('  node scripts/install-qoder.js --dry-run       预演，不改动磁盘');
    log('  node scripts/install-qoder.js --status        查看安装状态（--json 可选）');
    log('  node scripts/install-qoder.js --uninstall     仅移除本插件安装的 Qoder 内容');
    log('  node scripts/install-qoder.js --uninstall --purge  同时删除安装备份');
    return 0;
  }
  if (STATUS) return status();
  if (UNINSTALL) return uninstall();
  return install();
}

try {
  process.exitCode = main();
} catch (err) {
  console.error(`❌ Qoder 适配失败：${err.message}`);
  process.exitCode = 1;
}
