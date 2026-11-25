#!/usr/bin/env node
/**
 * 一键安装 zcode-expert-system 到 Claude Code
 *
 * 把「构建本地 marketplace → 注册市场 → 安装插件 → 验证」四步封装成一条命令，
 * 用户无需手工执行多步 CLI。
 *
 * 用法：
 *   node scripts/install-claude-code.js              一键安装
 *   node scripts/install-claude-code.js --dry-run    预演，不改动磁盘与配置
 *   node scripts/install-claude-code.js --force      已安装时强制重装
 *   node scripts/install-claude-code.js --uninstall  卸载（移除注册与市场目录）
 *
 * 说明：
 *   - 市场目录落在 ~/.claude/plugins/marketplaces/zcode-local/
 *   - 注册走官方 CLI（claude plugin marketplace add / install），保证格式正确
 *   - 不触碰 ZCode 侧任何文件，ZCode 部署逻辑不受影响
 */

const fs = require('fs');
const path = require('path');
const os = require('os');
const { spawnSync } = require('child_process');

const PLUGIN_NAME = 'zcode-expert-system';
const MARKETPLACE = 'zcode-local';
const PROJECT_ROOT = path.dirname(__dirname);
const DRY_RUN = process.argv.includes('--dry-run');
const FORCE = process.argv.includes('--force');
const UNINSTALL = process.argv.includes('--uninstall');

/** 解析 --targets 参数（M4 修复）：--targets=claude-code 或 --targets claude-code。
 *  非交互/CI 场景下显式指定目标，跳过 selectTargets 的全选回退。 */
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

const { detectTargets, selectTargets, log } = require('./target-menu');

/** 目录名级跳过项（与 install.js 保持一致的排除口径） */
const SKIP_NAMES = new Set([
  'node_modules', '.git', '__pycache__', '.mimosa', '.sync-tmp',
  'bs_doc.txt', '工作流.txt', 'package-lock.json',
  '.pytest_cache', 'tests', '.superpowers', 'vendor',
  '.zcode-plugin', '.zcode',
]);

/** 运行时产物路径级跳过项 */
const SKIP_REL_PATHS = new Set(['context/store']);

/** 市场目录里要复制的插件组件（相对源码根） */
const PLUGIN_COMPONENTS = [
  '.claude-plugin', 'agents', 'commands', 'hooks',
  'scripts', 'config', 'references', 'templates', 'bin',
];

/**
 * 未打包组件清单——显式声明，消除源码树与交付物不一致的模糊地带（R4）。
 * src/：openspec jwt-auth-system 在建模块，当前零生产消费方
 *（仅 tests/test_auth_login.py 经 sys.path 直接导入源码目录）。
 * 不随插件分发：打包会分发死代码并扩大密钥/JWT 实现的暴露面。
 * 如需使用，按 openspec/changes/jwt-auth-system 文档显式引入。
 */
const UNPACKED_COMPONENTS = ['src/'];

/** 插件根目录需单独复制的顶层主脚本 */
const PLUGIN_ROOT_FILES = [
  'zcode_dev_workflow.py', 'zcode_expert_system.py', 'skill_entry.py',
];

function copyDir(src, dest, opts = {}) {
  const skip = new Set([...SKIP_NAMES, ...(opts.skip || [])]);
  fs.mkdirSync(dest, { recursive: true });
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

/**
 * 调用 Claude Code CLI，返回是否成功。
 *
 * Windows 下 claude 是 .cmd shim，必须经 cmd.exe 启动；用
 * `cmd.exe /c <args>` 显式包装，参数按数组传递并正确转义，
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

/** 部署必需组件清单——缺一不可，缺失即中止（R5：对齐 install.js P5 契约「先校验、后动手」） */
const DEPLOY_REQUIRED = [
  'SKILL.md', 'config', 'agents', 'commands', '.claude-plugin',
  'hooks', 'scripts',
];

/**
 * 源树完整性预检：部署必需组件缺失时抛错中止。
 * 在删除任何现有目录之前执行，落实 P5 契约「先校验、后动手」。
 *
 * 同时校验 .claude-plugin/plugin.json 不得含 agents 字段：
 * 本机 Claude Code 的 manifest schema 规定 agents 必须是**单个 .md 文件**
 * （"Invalid string: must end with .md"），声明目录会令整个插件加载失败。
 * 363 个专家靠约定式扫描 agents/ 目录注册，无需该字段。
 */
function preflightCheck() {
  const missing = DEPLOY_REQUIRED.filter(
    rel => !fs.existsSync(path.join(PROJECT_ROOT, rel))
  );
  if (missing.length > 0) {
    throw new Error(
      `[preflight] 源树缺少部署必需组件，中止：${missing.join(', ')}`
    );
  }
  const manifest = readJson(path.join(PROJECT_ROOT, '.claude-plugin', 'plugin.json'));
  if (!manifest) {
    throw new Error('[preflight] .claude-plugin/plugin.json 不可读或不是合法 JSON，中止');
  }
  if (manifest.agents) {
    throw new Error(
      '[preflight] .claude-plugin/plugin.json 含 "agents" 字段——'
      + '本机 Claude Code 要求该字段必须是单个 .md 文件路径，目录声明会导致'
      + '整个插件 manifest 校验失败（插件不可用）。请移除该字段后重试'
      + '（agents/ 目录由约定式扫描自动注册）。'
    );
  }
}

/** 备份市场目录，返回备份根路径（R5：删前备份、成功才清） */
function backupMarketplace(marketRoot) {
  const ts = Date.now();
  const backupRoot = path.join(
    path.dirname(marketRoot), `.bak-marketplace-${ts}`
  );
  if (fs.existsSync(marketRoot)) {
    fs.cpSync(marketRoot, backupRoot, { recursive: true });
  }
  return backupRoot;
}

/** 回滚：删除新构建的目录，恢复备份（R5：失败可回滚） */
function rollback(marketRoot, backupRoot) {
  if (fs.existsSync(marketRoot)) {
    fs.rmSync(marketRoot, { recursive: true, force: true });
  }
  if (fs.existsSync(backupRoot)) {
    fs.cpSync(backupRoot, marketRoot, { recursive: true });
  }
}

/** 构建本地 marketplace 目录（写 marketplace.json + 复制插件组件 + skills 镜像） */
function buildMarketplaceDir(homeDir) {
  const marketRoot = path.join(homeDir, '.claude', 'plugins', 'marketplaces', MARKETPLACE);
  const pluginDir = path.join(marketRoot, PLUGIN_NAME);

  if (DRY_RUN) {
    log(`  [dry-run] 将构建市场目录: ${marketRoot}`);
    log(`  [dry-run]   - 写入 .claude-plugin/marketplace.json`);
    log(`  [dry-run]   - 复制插件组件到 ${PLUGIN_NAME}/`);
    log(`  [dry-run]   - 构建 skills/${PLUGIN_NAME}/ 镜像（命令路径对齐）`);
    return;
  }

  // R5：复制前做源树完整性预检，任何删除动作之前先校验。
  preflightCheck();

  let backupRoot = null;
  try {
    // R5：删前备份，旧市场目录先复制为 .bak-marketplace-<ts>，成功才清。
    if (fs.existsSync(marketRoot)) {
      backupRoot = backupMarketplace(marketRoot);
      fs.rmSync(marketRoot, { recursive: true, force: true });
    }
    fs.mkdirSync(path.join(marketRoot, '.claude-plugin'), { recursive: true });
    fs.mkdirSync(pluginDir, { recursive: true });

    // 1. marketplace.json
    const pkg = readJson(path.join(PROJECT_ROOT, 'package.json')) || {};
    const version = pkg.version || '3.0.0';
    const marketplace = {
      $schema: 'https://anthropic.com/claude-code/marketplace.schema.json',
      name: MARKETPLACE,
      description: 'Local marketplace for zcode-expert-system',
      owner: { name: 'local', email: 'local@localhost' },
      plugins: [{
        name: PLUGIN_NAME,
        description: pkg.description || 'ZCode Expert System',
        author: { name: (pkg.author || 'local').name || 'local' },
        source: `./${PLUGIN_NAME}`,
        category: 'development',
        version,
        homepage: pkg.repository && pkg.repository.url ? pkg.repository.url : undefined,
      }],
    };
    fs.writeFileSync(
      path.join(marketRoot, '.claude-plugin', 'marketplace.json'),
      JSON.stringify(marketplace, null, 2), 'utf8'
    );

    // 2. 复制插件组件到市场目录（R5：缺失组件报错，不再静默跳过）
    for (const comp of PLUGIN_COMPONENTS) {
      const src = path.join(PROJECT_ROOT, comp);
      if (!fs.existsSync(src)) {
        throw new Error(`[build] 缺少插件组件，中止：${comp}`);
      }
      // hooks 目录排除 hooks.json（ZCode 格式，Claude Code 扫描会报 warning）
      if (comp === 'hooks') {
        const hooksDest = path.join(pluginDir, 'hooks');
        fs.mkdirSync(hooksDest, { recursive: true });
        for (const file of fs.readdirSync(src)) {
          if (file === 'hooks.json') continue;
          fs.copyFileSync(path.join(src, file), path.join(hooksDest, file));
        }
      } else {
        copyDir(src, path.join(pluginDir, comp));
      }
    }

    // 3. 复制根目录主脚本
    for (const f of PLUGIN_ROOT_FILES) {
      const src = path.join(PROJECT_ROOT, f);
      if (fs.existsSync(src)) fs.copyFileSync(src, path.join(pluginDir, f));
    }

    // 4. 写 .claude-plugin/plugin.json
    const manifestSrc = path.join(PROJECT_ROOT, '.claude-plugin', 'plugin.json');
    if (fs.existsSync(manifestSrc)) {
      fs.copyFileSync(manifestSrc, path.join(pluginDir, '.claude-plugin', 'plugin.json'));
    }

    // 5. skills 镜像（命令里引用 ${PLUGIN_ROOT}/skills/zcode-expert-system/...，
    //    镜像让这个路径在 Claude Code 部署布局下也成立）
    const skillMirror = path.join(pluginDir, 'skills', PLUGIN_NAME);
    copyDir(pluginDir, skillMirror, { skip: ['skills'] });

    // R5：部署成功，清理备份。
    if (backupRoot) fs.rmSync(backupRoot, { recursive: true, force: true });
  } catch (err) {
    // R5：构建中途失败，回滚到备份（保留备份供人工恢复，仅在完全无法恢复时删除）。
    if (backupRoot) {
      try { rollback(marketRoot, backupRoot); } catch (rbErr) {
        log(`⚠️  回滚失败，备份保留在 ${backupRoot} 供人工恢复：${rbErr.message}`);
      }
    }
    throw err;
  }

  log(`✅ 市场目录已构建: ${marketRoot}`);
}

/** 注册市场 + 安装插件 + 验证 */
function registerAndInstall(homeDir) {
  const marketPath = path.join(homeDir, '.claude', 'plugins', 'marketplaces', MARKETPLACE);

  // 1. 注册市场（已注册则跳过）
  if (marketplaceRegistered(homeDir)) {
    log(`ℹ️  市场 ${MARKETPLACE} 已注册，跳过 marketplace add`);
  } else {
    if (DRY_RUN) {
      log(`  [dry-run] 将注册市场: claude plugin marketplace add ${marketPath}`);
    } else {
      log('注册本地 marketplace...');
      if (!runClaude(['plugin', 'marketplace', 'add', marketPath])) {
        log('❌ 市场注册失败');
        process.exit(1);
      }
      log(`✅ 市场已注册: ${MARKETPLACE}`);
    }
  }

  // 2. 安装插件
  const id = `${PLUGIN_NAME}@${MARKETPLACE}`;
  if (pluginInstalled(homeDir)) {
    if (!FORCE) {
      log(`ℹ️  插件 ${id} 已安装。如需重装加 --force。`);
      return;
    }
    log('强制重装插件...');
  } else if (!DRY_RUN) {
    log('安装插件...');
  }

  if (DRY_RUN) {
    log(`  [dry-run] 将安装插件: claude plugin install ${id}`);
    return;
  }

  if (!runClaude(['plugin', 'install', id])) {
    log('❌ 插件安装失败');
    process.exit(1);
  }
  log(`✅ 插件已安装: ${id}`);
}

/** 验证安装结果 */
function verify(homeDir) {
  if (DRY_RUN) return;
  const installed = readJson(path.join(homeDir, '.claude', 'plugins', 'installed_plugins.json'));
  const enabled = readJson(path.join(homeDir, '.claude', 'settings.json'));

  const regOk = Boolean(installed && installed.plugins && installed.plugins[`${PLUGIN_NAME}@${MARKETPLACE}`]);
  const enableOk = Boolean(enabled && enabled.enabledPlugins && enabled.enabledPlugins[`${PLUGIN_NAME}@${MARKETPLACE}`]);

  if (!regOk) {
    log('❌ 验证失败：installed_plugins.json 无插件条目');
    process.exit(1);
  }
  if (!enableOk) {
    log('⚠️  插件已注册但未启用（enabledPlugins 无条目），请在 /plugin 中手动启用');
  } else {
    log('✅ 验证通过：插件已注册并启用');
  }

  // 验证 agents 目录是否被正确部署（约定式扫描，plugin.json 不声明 agents 字段）
  const marketAgentsDir = path.join(
    homeDir, '.claude', 'plugins', 'marketplaces', MARKETPLACE,
    PLUGIN_NAME, 'agents'
  );
  const agentCount = fs.existsSync(marketAgentsDir)
    ? fs.readdirSync(marketAgentsDir).filter(f => f.endsWith('.md')).length
    : 0;
  if (agentCount === 0) {
    log('⚠️  市场目录中 agents/ 无 .md 文件——363 个专家无法派发');
    log('   请检查源树 agents/ 目录是否完整（约定式扫描，无需 manifest 声明）');
  } else {
    log(`✅ agents/ 已部署 ${agentCount} 个专家智能体`);
  }

  // 验证 plugin.json 不含 agents 字段（本机 schema：必须是单个 .md，目录声明会炸整个插件）
  const manifestPath = path.join(
    homeDir, '.claude', 'plugins', 'marketplaces', MARKETPLACE,
    PLUGIN_NAME, '.claude-plugin', 'plugin.json'
  );
  const manifest = readJson(manifestPath);
  if (manifest && !manifest.agents) {
    log('✅ plugin.json 无 agents 字段（正确——agents/ 走约定式扫描）');
  } else if (manifest && manifest.agents) {
    log('❌ plugin.json 含 agents 字段——manifest 校验会失败，整个插件不可用');
    log('   请移除该字段（agents/ 目录由 Claude Code 约定式扫描自动注册）');
  }
}

function install() {
  const homeDir = os.homedir();
  log(`开始一键安装 ${PLUGIN_NAME} 到 Claude Code ...`);
  log(`源目录: ${PROJECT_ROOT}`);
  log(`目标 HOME: ${homeDir}${DRY_RUN ? '   [dry-run：不改动磁盘]' : ''}`);
  log('');

  // 预检：claude CLI 可用
  if (!DRY_RUN) {
    const ver = process.platform === 'win32'
      ? spawnSync('cmd.exe', ['/c', 'claude', '--version'], { stdio: 'pipe' })
      : spawnSync('claude', ['--version'], { stdio: 'pipe' });
    if (ver.status !== 0) {
      log('❌ 未检测到 Claude Code CLI（claude）。请先安装 Claude Code 再运行本脚本。');
      process.exit(1);
    }
    log(`✅ 检测到 Claude Code CLI`);
  }

  // P6（2026-11-23）：源树与部署副本不同步是常态（改了源码忘了重装），
  // 而安装脚本自己不报这件事——用户拿到的是「装成功了」，跑的却是旧代码。
  // 实测踩到：P1/P2/P4 三项修复后部署副本仍是旧版，全靠人工 cmp 才发现。
  // 这里在写盘之前打一份关键文件的一致性清单：不同步的显式列出，
  // 让「这次安装确实把新代码带上」成为可见事实，而不是假设。
  {
    const deployedRoot = path.join(
      homeDir, '.claude', 'plugins', 'marketplaces', MARKETPLACE, PLUGIN_NAME
    );
    const KEY_FILES = [
      'zcode_expert_system.py', 'zcode_dev_workflow.py', 'skill_entry.py',
      'scripts/workflow_check.py', 'scripts/openspec_engine.py',
      'scripts/install.js', 'scripts/install-claude-code.js',
      'hooks/prepend-global-rules-reminder.mjs', 'config/workflow.json',
    ];
    const drift = [];
    for (const rel of KEY_FILES) {
      const src = path.join(PROJECT_ROOT, rel);
      const dst = path.join(deployedRoot, rel);
      if (!fs.existsSync(src)) continue;
      if (!fs.existsSync(dst)) { drift.push(`${rel}（新文件，部署后生效）`); continue; }
      if (fs.readFileSync(src).compare(fs.readFileSync(dst)) !== 0) {
        drift.push(rel);
      }
    }
    if (drift.length) {
      log(`ℹ️  本次安装将更新 ${drift.length} 个与现有部署不一致的文件：`);
      for (const d of drift) log(`     · ${d}`);
    } else if (fs.existsSync(deployedRoot)) {
      log('ℹ️  源树与现有部署一致（无需更新）');
    }
  }

  buildMarketplaceDir(homeDir);
  log('');
  registerAndInstall(homeDir);
  log('');
  verify(homeDir);
  log('');

  if (DRY_RUN) {
    log('ℹ️  dry-run 结束：以上为计划执行的动作。');
    return;
  }
  log('🎉 一键安装完成！');
  log('');
  log('下一步：');
  log('  1. 在 Claude Code 中执行 /plugin，应出现 zcode-expert-system');
  log('  2. 派发专家时使用 zcode-expert-system:<专家中文名>（如 zcode-expert-system:安全架构师）');
  log('  3. 可用 /wf:* 命令调用九阶段工作流');
}

function uninstall() {
  // 卸载逻辑已抽到共享模块，避免与统一入口 install.js 重复实现
  const { uninstallClaudeCode } = require('./cc-uninstall');
  uninstallClaudeCode({ homeDir: os.homedir(), dryRun: DRY_RUN, logger: log });
}

/**
 * 入口：弹出目标菜单，按选择分发。
 *   - 选了 claude-code → 本脚本的 install()（构建市场 + 注册 + 安装）
 *   - 选了 zcode        → 委托 install.js（传 --targets zcode，避免它再弹菜单）
 *   - 两者都选          → 先本脚本，再委托 install.js
 */
async function main() {
  if (UNINSTALL) {
    uninstall();
    return;
  }

  // M4 修复：显式 --targets 优先（脚本化/CI 场景，不弹菜单、不全选）
  const explicit = parseTargetsArg();
  const targets = explicit || await selectTargets(detectTargets(os.homedir()));
  log('');
  log(`已选择安装目标: ${targets.join(' + ')}`);
  log('');

  const wantClaude = targets.includes('claude-code');
  const wantZcode = targets.includes('zcode');

  if (wantClaude) {
    install();
  }

  if (wantZcode) {
    if (wantClaude) log('');
    log('开始部署 ZCode 侧（委托 install.js）...');
    const args = ['scripts/install.js', '--targets', 'zcode'];
    if (DRY_RUN) args.push('--dry-run');
    const res = spawnSync(process.execPath, args, { stdio: 'inherit', cwd: PROJECT_ROOT });
    if (res.status !== 0) {
      log('❌ ZCode 部署失败');
      process.exit(1);
    }
  }

  if (wantClaude && wantZcode) {
    log('');
    log('🎉 全部安装完成（Claude Code + ZCode）！');
  }
}

main().catch((err) => {
  console.error('❌ 执行失败:', err.message);
  process.exit(1);
});
