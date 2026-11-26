/**
 * Claude Code 侧卸载逻辑（共享模块）
 *
 * 被 install.js（统一卸载入口）与 install-claude-code.js（独立安装脚本）共用，
 * 避免两套重复实现。
 *
 * 卸载内容：
 *   1. claude plugin uninstall —— 移除插件注册与启用
 *   2. claude plugin marketplace remove —— 移除市场注册
 *   3. 文件级回退：CLI 不可用或命令失败时，直接删掉
 *      installed_plugins.json / settings.json.enabledPlugins /
 *      known_marketplaces.json 中**本插件**的条目（其他插件一字不动）
 *   4. 删除市场目录（~/.claude/plugins/marketplaces/<marketplace>/）
 *   5. 删除本插件缓存子目录（不触碰其他插件的缓存）
 *
 * 注册残留（I1）：老实现在 CLI 失败时只打警告，随后照删目录并打印
 * 「🎉 卸载完成」，用户机器上留下幽灵注册。现在删目录前先做回退清理，
 * 结束时再验一遍；仍有残留时 rc≠0 且不打印完成语。
 *
 * 不触碰 ZCode 侧任何文件。
 */

const fs = require('fs');
const path = require('path');
const { spawnSync } = require('child_process');

const PLUGIN_NAME = 'zcode-expert-system';
const MARKETPLACE = 'zcode-local';

function log(msg) { console.log(msg); }

/** 读 JSON 文件，失败返回 null */
function readJson(file) {
  try {
    if (!fs.existsSync(file)) return null;
    return JSON.parse(fs.readFileSync(file, 'utf8'));
  } catch { return null; }
}

/** 市场目录是否已注册 */
function marketplaceRegistered(homeDir) {
  const known = readJson(path.join(homeDir, '.claude', 'plugins', 'known_marketplaces.json'));
  return Boolean(known && known[MARKETPLACE]);
}

/** 插件是否已安装 */
function pluginInstalled(homeDir) {
  const installed = readJson(path.join(homeDir, '.claude', 'plugins', 'installed_plugins.json'));
  return Boolean(installed && installed.plugins && installed.plugins[`${PLUGIN_NAME}@${MARKETPLACE}`]);
}

/** 本插件可能留下的缓存目录；只到 <plugin> 子目录，不碰 marketplace 根。 */
function pluginCacheDirs(homeDir) {
  const cache = path.join(homeDir, '.claude', 'plugins', 'cache');
  return [
    path.join(cache, MARKETPLACE, PLUGIN_NAME),
    // v3.2.2 及以前 install.js 直拷的死目录，从未被 /plugin 加载
    path.join(cache, 'claude-plugins-official', PLUGIN_NAME),
  ];
}

/**
 * 调用 Claude Code CLI。
 * Windows 下 claude 是 .cmd shim，必须经 cmd.exe 启动；
 * 用 cmd.exe /c 显式包装，参数按数组传递并正确转义，
 * 避免 shell:true 的拼接（DEP0190）与注入风险。
 */
function runClaude(args) {
  if (process.platform === 'win32') {
    const res = spawnSync('cmd.exe', ['/c', 'claude', ...args], { stdio: 'inherit' });
    return res.status === 0;
  }
  const res = spawnSync('claude', args, { stdio: 'inherit' });
  return res.status === 0;
}

/**
 * 从 JSON 文件的某个对象容器里删掉一个键，保留其他键与原有缩进。
 *
 * 返回值：是否真的删掉了（文件不存在 / 解析失败 / 键不存在 → false）。
 * 只删指定的那一个键——同文件里其他插件的条目必须原样保留。
 */
function removeKey(file, section, key) {
  if (!fs.existsSync(file)) return false;
  let raw;
  try { raw = fs.readFileSync(file, 'utf8'); } catch { return false; }
  let data;
  try { data = JSON.parse(raw); } catch { return false; }
  if (!data || typeof data !== 'object' || Array.isArray(data)) return false;
  const bag = section ? data[section] : data;
  if (!bag || typeof bag !== 'object' || !Object.prototype.hasOwnProperty.call(bag, key)) {
    return false;
  }
  delete bag[key];
  const indentMatch = raw.match(/\n([ \t]+)"/);
  const indent = indentMatch ? indentMatch[1] : 2;
  try { fs.writeFileSync(file, JSON.stringify(data, null, indent), 'utf8'); } catch { return false; }
  return true;
}

/** settings.json 的 enabledPlugins 是否还有本插件键 */
function enabledInSettings(homeDir) {
  const settings = readJson(path.join(homeDir, '.claude', 'settings.json'));
  return Boolean(
    settings && settings.enabledPlugins
    && settings.enabledPlugins[`${PLUGIN_NAME}@${MARKETPLACE}`]);
}

/**
 * 文件级回退清理：CLI 不可用或 CLI 命令失败时，直接编辑注册文件。
 *
 * 只删本插件的三个键，其他插件条目一字不动：
 *   - installed_plugins.json  → plugins[`<id>`]
 *   - settings.json           → enabledPlugins[`<id>`]
 *   - known_marketplaces.json → [`<marketplace>`]
 *
 * 这是「幽灵注册」的正解：老实现只打一句 ⚠️ 警告就继续删目录，用户看到
 * 「🎉 卸载完成」，而 /plugin 里插件条目与启用键仍在——重装时还会撞上
 * 「已安装」状态。
 */
function unregisterEntries(homeDir, log2) {
  const id = `${PLUGIN_NAME}@${MARKETPLACE}`;
  let edited = 0;
  if (removeKey(
    path.join(homeDir, '.claude', 'plugins', 'installed_plugins.json'),
    'plugins', id)) {
    log2(`✅ 已从 installed_plugins.json 移除插件注册：${id}`);
    edited += 1;
  }
  if (removeKey(
    path.join(homeDir, '.claude', 'settings.json'),
    'enabledPlugins', id)) {
    log2(`✅ 已从 settings.json enabledPlugins 移除启用键：${id}`);
    edited += 1;
  }
  if (removeKey(
    path.join(homeDir, '.claude', 'plugins', 'known_marketplaces.json'),
    null, MARKETPLACE)) {
    log2(`✅ 已从 known_marketplaces.json 移除市场注册：${MARKETPLACE}`);
    edited += 1;
  }
  return edited;
}

/**
 * 卸载 Claude Code 侧插件。
 *
 * @param {object} opts
 * @param {string} opts.homeDir 用户 HOME
 * @param {boolean} [opts.dryRun] 预演模式，不执行真实删除
 * @param {function} [opts.logger] 日志函数（默认 console.log）
 * @returns {{ok: boolean}} ok=false 表示注册仍有残留（调用方据此 rc≠0）
 */
function uninstallClaudeCode(opts = {}) {
  const homeDir = opts.homeDir || require('os').homedir();
  const dryRun = Boolean(opts.dryRun);
  const log2 = opts.logger || log;
  const id = `${PLUGIN_NAME}@${MARKETPLACE}`;

  log2(`开始卸载 ${PLUGIN_NAME} 从 Claude Code ...`);
  log2(`目标 HOME: ${homeDir}${dryRun ? '   [dry-run：不改动磁盘]' : ''}`);
  log2('');

  if (dryRun) {
    log2(`  [dry-run] 将执行: claude plugin uninstall ${id}`);
    log2(`  [dry-run] 将执行: claude plugin marketplace remove ${MARKETPLACE}`);
    log2(`  [dry-run] 若 CLI 不可用/失败，将直接清理 installed_plugins.json`
      + ` / settings.json enabledPlugins / known_marketplaces.json 中的 ${id} 条目`);
    log2(`  [dry-run] 将删除目录: ${path.join(homeDir, '.claude', 'plugins', 'marketplaces', MARKETPLACE)}`);
    for (const dir of pluginCacheDirs(homeDir)) {
      log2(`  [dry-run] 将删除缓存: ${dir}`);
    }
    log2(`ℹ️  Claude Code 侧卸载不受 --purge 影响（purge 仅作用于 ZCode 侧的运行时数据）`);
    return { ok: true };
  }

  if (pluginInstalled(homeDir)) {
    if (!runClaude(['plugin', 'uninstall', id])) {
      log2(`⚠️  插件卸载命令未成功（CLI 不可用或命令失败）`);
    } else {
      log2(`✅ 插件已卸载: ${id}`);
    }
  } else {
    log2(`ℹ️  插件未安装，跳过卸载`);
  }

  if (marketplaceRegistered(homeDir)) {
    if (!runClaude(['plugin', 'marketplace', 'remove', MARKETPLACE])) {
      log2(`⚠️  市场移除命令未成功（CLI 不可用或命令失败）`);
    } else {
      log2(`✅ 市场已移除: ${MARKETPLACE}`);
    }
  } else {
    log2(`ℹ️  市场未注册，跳过移除`);
  }

  // 删目录之前先把注册清干净：CLI 没做成的事在这里用文件级编辑兜住。
  // 顺序很重要——先改注册再删目录，任何一步失败都还能从注册状态看出端倪。
  if (pluginInstalled(homeDir) || enabledInSettings(homeDir) || marketplaceRegistered(homeDir)) {
    log2('ℹ️  检测到注册残留，执行文件级回退清理（只删本插件条目）...');
    if (unregisterEntries(homeDir, log2) === 0) {
      log2('⚠️  回退清理未改动任何条目（文件不可读或格式异常）');
    }
  }

  const marketDir = path.join(homeDir, '.claude', 'plugins', 'marketplaces', MARKETPLACE);
  if (fs.existsSync(marketDir)) {
    fs.rmSync(marketDir, { recursive: true, force: true });
    log2(`✅ 已清理市场目录: ${marketDir}`);
  }

  for (const cacheDir of pluginCacheDirs(homeDir)) {
    if (fs.existsSync(cacheDir)) {
      fs.rmSync(cacheDir, { recursive: true, force: true });
      log2(`✅ 已清理插件缓存: ${cacheDir}`);
    }
  }

  // 终态自检：注册还在就不许说「卸载完成」。
  const residual = [];
  if (pluginInstalled(homeDir)) residual.push('installed_plugins.json');
  if (enabledInSettings(homeDir)) residual.push('settings.json 的 enabledPlugins');
  if (marketplaceRegistered(homeDir)) residual.push('known_marketplaces.json');

  log2('');
  if (residual.length > 0) {
    log2(`❌ 卸载未完成：注册残留仍在 ${residual.join('、')}`);
    log2(`   请修复 Claude Code CLI 后重试：claude plugin uninstall ${id}`);
    log2(`   或手工删除上述文件中 ${id} / ${MARKETPLACE} 条目。`);
    process.exitCode = 1;
    return { ok: false };
  }
  log2('🎉 卸载完成。ZCode 侧不受影响。');
  return { ok: true };
}

module.exports = {
  uninstallClaudeCode,
  unregisterEntries,
  PLUGIN_NAME,
  MARKETPLACE,
  pluginInstalled,
  marketplaceRegistered,
  runClaude,
  readJson,
};
