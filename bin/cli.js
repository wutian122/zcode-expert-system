#!/usr/bin/env node
/**
 * ZCode Expert System - CLI 入口
 *
 * 对外只保留两个命令：
 *   zcode-expert-system install
 *   zcode-expert-system uninstall
 *
 * 所有平台（ZCode / Claude Code / Qoder）均通过这两个命令的交互菜单选择。
 * 平台专用脚本是内部实现，不再暴露独立 CLI 子命令。
 */

const HELP = `
ZCode 专家体系 - CLI 工具

用法:
  zcode-expert-system install      选择 ZCode / Claude Code / Qoder 安装
  zcode-expert-system uninstall    选择 ZCode / Claude Code / Qoder 卸载

选项:
  --dry-run                        预演，不改动磁盘
  --targets <targets>              install 脚本化目标：zcode,claude-code,qoder
  --zcode / --claude-code / --qoder / --all
                                   uninstall 脚本化目标
`;

function runInstaller(uninstall) {
  // install 与 uninstall 共用 scripts/install.js；只改 argv，不复制实现。
  if (uninstall) {
    process.argv = [
      process.argv[0], 'install.js', '--uninstall', ...process.argv.slice(3),
    ];
  }
  require('../scripts/install.js');
}

const command = process.argv[2];

switch (command) {
  case 'install':
    console.log('安装 ZCode 专家体系...');
    runInstaller(false);
    break;

  case 'uninstall':
    console.log('卸载 ZCode 专家体系...');
    runInstaller(true);
    break;

  case '--help':
  case '-h':
    console.log(HELP);
    break;

  default:
    console.log(`未知命令：${command === undefined ? '(未提供)' : command}`);
    console.log(HELP);
    process.exitCode = 1;
}
