#!/usr/bin/env node
/**
 * ZCode Expert System - CLI 入口
 *
 * 契约（缺陷 #20 族）：
 *   zcode-expert-system install     安装 / 升级
 *   zcode-expert-system uninstall   卸载（转调 scripts/install.js --uninstall）
 *   zcode-expert-system version     显示版本
 *   zcode-expert-system help        显示帮助
 *   zcode-expert-system --help      同 help（旧版缺此别名，出错提示会把用户
 *                                   导向一个同样报错的分支，形成自指循环）
 */

const HELP = `
ZCode 专家体系 - CLI 工具

用法:
  zcode-expert-system install      安装插件到 ZCode
  zcode-expert-system uninstall    从 ZCode 卸载插件
  zcode-expert-system version      显示版本信息
  zcode-expert-system help         显示本帮助

示例:
  zcode-expert-system install
  zcode-expert-system uninstall
`;

function runInstaller(uninstall) {
  // 安装与卸载共用 scripts/install.js，由它读取 process.argv[2] === '--uninstall'
  // 决定方向。这里显式设置 argv 再转调——若直接 require，脚本会读到
  // 'uninstall'（不带 --）而走安装分支，即「卸载命令装了一遍」。
  if (uninstall) {
    process.argv = [process.argv[0], 'install.js', '--uninstall', ...process.argv.slice(3)];
  }
  require('../scripts/install.js');
}

const command = process.argv[2];

switch (command) {
  case 'install':
    console.log('安装 ZCode 专家体系插件...');
    runInstaller(false);
    break;

  case 'uninstall':
    console.log('卸载 ZCode 专家体系插件...');
    runInstaller(true);
    break;

  case 'version': {
    const packageJson = require('../package.json');
    console.log(`版本: ${packageJson.version}`);
    break;
  }

  case 'help':
  case '--help':
  case '-h':
    console.log(HELP);
    break;

  default:
    console.log(`未知命令：${command === undefined ? '(未提供)' : command}`);
    console.log(HELP);
    process.exitCode = 1;
}
