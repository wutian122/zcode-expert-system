/**
 * 安装目标选择菜单（共享模块）
 *
 * 被 install.js 与 install-claude-code.js 共用，避免两套重复实现。
 * 零依赖，手写 readline 按键处理：
 *   ↑/↓ 移动，Space 切换，Enter 确认，Ctrl+C 取消。
 * 非 TTY 环境（CI、管道、重定向）直接返回全选，绝不卡住。
 */

const fs = require('fs');
const path = require('path');

function log(msg) { console.log(msg); }

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
 * 交互式多选菜单。
 *
 * 返回 Promise<string[]>（选中的 target id 列表）。
 * 非 TTY 时回退为全选。
 */
function selectTargets(options) {
  if (!process.stdin.isTTY || !process.stdout.isTTY) {
    log('（非交互终端，默认全选）');
    return Promise.resolve(options.map((o) => o.id));
  }

  return new Promise((resolve) => {
    const checked = options.map((o) => o.detected); // 检测到的默认勾选
    let cursor = 0;

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

module.exports = { detectTargets, selectTargets, log };
