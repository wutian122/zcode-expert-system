/**
 * Claude Code 侧卸载逻辑（共享模块）
 *
 * 被 install.js（统一卸载入口）与 install-claude-code.js（独立安装脚本）共用，
 * 避免两套重复实现。
 *
 * 卸载内容：
 *   1. claude plugin uninstall —— 移除插件注册与启用
 *   2. claude plugin marketplace remove —— 移除市场注册
 *   3. 删除市场目录（~/.claude/plugins/marketplaces/<marketplace>/）
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
 * 卸载 Claude Code 侧插件。
 *
 * @param {object} opts
 * @param {string} opts.homeDir 用户 HOME
 * @param {boolean} [opts.dryRun] 预演模式，不执行真实删除
 * @param {function} [opts.logger] 日志函数（默认 console.log）
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
    log2(`  [dry-run] 将删除目录: ${path.join(homeDir, '.claude', 'plugins', 'marketplaces', MARKETPLACE)}`);
    log2(`ℹ️  Claude Code 侧卸载不受 --purge 影响（purge 仅作用于 ZCode 侧的运行时数据）`);
    return;
  }

  if (pluginInstalled(homeDir)) {
    if (!runClaude(['plugin', 'uninstall', id])) {
      log2(`⚠️  插件卸载命令未成功，可能已不存在`);
    } else {
      log2(`✅ 插件已卸载: ${id}`);
    }
  } else {
    log2(`ℹ️  插件未安装，跳过卸载`);
  }

  if (marketplaceRegistered(homeDir)) {
    if (!runClaude(['plugin', 'marketplace', 'remove', MARKETPLACE])) {
      log2(`⚠️  市场移除命令未成功`);
    } else {
      log2(`✅ 市场已移除: ${MARKETPLACE}`);
    }
  } else {
    log2(`ℹ️  市场未注册，跳过移除`);
  }

  const marketDir = path.join(homeDir, '.claude', 'plugins', 'marketplaces', MARKETPLACE);
  if (fs.existsSync(marketDir)) {
    fs.rmSync(marketDir, { recursive: true, force: true });
    log2(`✅ 已清理市场目录: ${marketDir}`);
  }

  log2('');
  log2('🎉 卸载完成。ZCode 侧不受影响。');
}

module.exports = {
  uninstallClaudeCode,
  PLUGIN_NAME,
  MARKETPLACE,
  pluginInstalled,
  marketplaceRegistered,
  runClaude,
  readJson,
};
