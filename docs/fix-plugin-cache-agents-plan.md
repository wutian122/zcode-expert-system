# 修复方案：ZCode 插件缓存顶层 agents/ 缺失 → 前缀派发 not found

- 文档版本：v1.0（2026-11-20，呈老板批准，未实施）
- 状态：**待批准**。本文档仅方案，未改任何代码。
- 目标：让 `Agent(subagent_type='zcode-expert-system:<专家中文名>')` 在 ZCode 会话中可用。
- 改动面：`scripts/install.js`（部署器）+ `tests/test_p5_install_safety.py`（防回归）。**运行时组件（*.py / commands / hooks / skills 内容）零改动**。

---

## 0. 结论速览

| 项 | 结论 |
|---|---|
| 根因 | install.js ZCode 分支从未向插件缓存 `<pluginRoot>/agents/` 复制子代理；ZCode 运行时 `collectPluginAgentRoots` **硬编码探测 `<installPath>/agents/`** → 前缀派发自插件发布以来不可用 |
| 定性 | **长期缺陷首次暴露，非 2026-11-20 13:22Z 部署回归**（缓存顶层 agents 此前 6 次部署均不存在） |
| 止血源 | 缓存内现成的 `skills/zcode-expert-system/agents/`（363 个 .md，21:22 部署随技能镜像带入） |
| 根治 | 步骤 1 新增 1g 复制 agents → 缓存顶层 + manifest 补 `agents:'agents'` 双保险 + 缓存数量校验对齐 claude 分支 + 修正过时注释 |
| 版本策略 | 建议**不 bump**（见 §8） |
| 老板裁决点 | 3 个（见 §10）：版本策略、SKIP 扩充是否纳入、claude 分支硬编码 363 是否动态化 |

---

## 1. 背景与根因（复核结论摘要）

1. **根因定位**：`scripts/install.js` install() ZCode 分支步骤 1「插件缓存目录」（当前工作树 720-828 行）只写 `.zcode-plugin/plugin.json`（723-737）、`skills/<name>/` 整仓镜像（739-742）、vendored zes-*（743-777）、`hooks/`（808-820）、`commands/`（822-828）。**无任何一步写 `<pluginRoot>/agents/`**。
2. **运行时机制实证**（`D:\Programs\ZCode\resources\app.asar` 只读字符串取证，2026-11-20）：
   - `collectPluginAgentMarkdownPaths → readPluginManifest → collectPluginAgentRoots`：
     `s("agents")` **硬编码**将 `<installPath>/agents/` 加入探测集；manifest `agents` 字段（字符串/数组）作为**追加**探测目录；`Set` 去重；`d.startsWith("..")` 路径逃逸防护。
   - 即：**manifest 不声明 agents，运行时也会探测缓存顶层 agents/**；声明了则叠加（去重）。
3. **同机官方先例**：documents 0.2.9（官方已装）manifest 带 `"agents":"agents"`、缓存顶层 `agents/visual-judge.md`；document-skills 0.1.4/0.1.5、documents 0.1.7-0.2.9 缓存均有顶层 agents/。
4. **定性证据**：install.js git 历史仅 1 提交（d1bb003）；注册表 6 个 `.bak-<ts>`（2026-11-18 v3.2.0 → 11-20 04:20Z）全为 local/directory 同一部署形态 → 缓存布局历次一致、顶层 agents 从未存在。2026-11-20 13:22:22Z 部署（本地 21:22，`bak-1795180942691` 文件名时间戳实证）**不是回归制造者**。
5. **过时文档**：install.js 头部 18-19 行注释「插件 manifest 的 agents 字段是 recorded-but-not-executed，插件无法贡献子代理」与现行运行时行为相反，是此前诊断方向的误导源，本方案一并修正。

---

## 2. 补充取证结论（老板指定 5 项）

### 2.1 deployed-agents.json：路径、结构、消费方、双源一致性

- **路径**：`C:/Users/Administrator/.zcode/expert-system/deployed-agents.json`（**用户级** expert-system 目录，非缓存）。
- **结构**（实测）：`{"version":"3.2.1","agents":[363 个文件名]}`，mtime 2026-11-20 21:22:22（与部署同刻）。
- **写方**：install.js:892（路径定义）、905/918/929（部署循环收集 `deployedAgentNames`）、952（写入）。**写的是用户级部署清单，供卸载精确删除**。
- **读方**：install.js:1129（uninstall 步骤 3，按清单删 `~/.zcode/agents/` 下文件，绝不前缀扫）。
- **ZCode 运行时不读它**（运行时直接扫 `~/.zcode/agents/` 目录与 `<installPath>/agents/` 目录）。
- **双源一致性结论**：**不会冲突，无需新增同步逻辑**。缓存 agents（新增）由「removePath 整层删（install.js:724）+ 1g 重建」自洽管理；deployed-agents.json 只管用户级。卸载侧（install.js:1057 removePath 整个 pluginRoot，**天然包含新 agents/**；1129 按清单删用户级）两侧同步清除，口径闭合。
- **数量口径分开**：缓存/源=363（工作树 `agents/` 实测 363 .md、无子目录、无非 .md 文件）；用户级磁盘 365 .md = 清单 363 + **2 个清单外幽灵残留**（`secops.md`、`visual-judge-qx.md`，实测比对得出）——属缺陷 #18 历史形态，本方案不修（见 §9），不影响 363 口径。

### 2.2 manifest 现状与 agents 字段兼容风险

- **缓存 `.zcode-plugin/plugin.json` 实测字段清单**：`name` / `description` / `description_i18n{en,zh-CN}` / `version` / `author` / `skills:'skills'` / `commands:'commands'` / `hooks:'hooks/hooks.json'` / `keywords[8]`。**无 agents**。
- **生成逻辑**：`buildPluginManifest(version)`（install.js:254-268），由 1a 写入（733-737）。
- **兼容风险结论：加 `agents:'agents'` 是纯双保险，无引入风险。** 依据（全部实证）：
  1. 运行时对未声明也硬编码探测 `'agents'` → 字段与硬编码同路径，`Set` 去重不双载；
  2. 值 `'agents'` 通过路径逃逸防护（`d.startsWith("..")` 拒绝）；
  3. manifest 解析为宽松 JSON + `isRecord` 校验，未知字段被忽略；官方 documents 0.1.7→0.2.9 多版本持续带此字段跨版本运行；
  4. 若未来运行时收紧为「未声明不加载」，显式声明即兜底；且 manifest 自描述性提升。

### 2.3 removePath/清理链与 1g 插入点交互

- install() 流程中**唯一**删除 pluginRoot 的点：install.js:724 `removePath(pluginRoot, '清理旧版本缓存')`（步骤 1 开头，1a 之前）。此后 1a→1g 期间无任何删除动作。
- 1c 剔除（798-806 附近）只作用于 `skillDest`（skills/zcode-expert-system/ 内部：package.json / .zcode-plugin / bin / scripts/install.js / _deploy_run_tmp.js），**不碰 `<pluginRoot>/agents/`**。
- 步骤 5 备份清理只动 `~/.zcode/skills/*.bak-*`；其余 removePath（1057/1061/1175/1200）全部在 uninstall()。
- **插入点定论：1g 插在 1f 的 log（828 行）之后、步骤 2 注释（829 行）之前。** 此时 pluginRoot 已建，1g 产物此后无人删除；下次部署由 724 整层重建（幂等）。claude 分支（0a 先跑）使用独立 claudePluginRoot，与 zcode pluginRoot 无共享路径，无交叉删除。
- dry-run 口径：1g 与校验必须在 `!DRY_RUN` 分支内（对齐 1e/1f 形态）；deployClaudeCode 的既有先例是 dry-run 提前 return，不会触发校验 exit。

### 2.4 SKIP 清单与缓存污染（裁决素材，详见 §9）

- `SKIP_NAMES`（install.js:98-110）：node_modules、.git、__pycache__、.mimosa、.sync-tmp、bs_doc.txt、工作流.txt、package-lock.json、.pytest_cache、tests、.superpowers、vendor；`SKIP_REL_PATHS`（113-115）：context/store。
- 缓存技能镜像 `skills/zcode-expert-system/` 内**实测部署带入的垃圾**：`1b5ac8ba-52d8-47b2-b57b-04260820d364.png`（457KB）、`.claude-plugin/`、`.zcode/`（.gitignore 忽略所以 git status 不可见，但磁盘存在被 copyDir 拷走）、`src/`、`openspec/`、`docs/`、`sandbox_home/`、`context/`（除 store）、`.gitignore`。
- 修正一项此前判断：缓存内 `__pycache__`（mtime 23:26 > 部署 21:22）是**运行时 import 生成的 .pyc**，非部署带入。
- 与本缺陷面关系：同属「部署产物卫生」，但修复手段（SKIP 扩充）与 1g **相互独立**；1g 复制源 `agents/` 目录纯净（363 .md），垃圾不会借 1g 进入缓存顶层。

### 2.5 claude 分支 363 校验模板（对齐基准）

install.js:556-565 原文（当前工作树）：

```js
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
```

- 模板口径：非递归一层 readdir、只数 .md、缺失算 0、失败 `exit(1)`、成功打印数量。
- 模板缺陷：**硬编码 363**——专家增减时必然误报。ZCode 分支对齐时改为「与源目录动态比对」（见 A-b-3）；claude 分支是否同步动态化 → 裁决点 3。
- **self-check rc 口径**：install 流程无独立 selfcheck 函数（`grep verify|selfcheck|自检` 仅命中第 29 行注释）；部署失败口径 = 非零退出码 + 输出含 `❌`/`agents` 字样，测试断言 `returncode != 0`（test_p5 既有惯例，run_installer 已带 `encoding='utf-8', errors='replace'`）。
- pytest 基数：**实测 606 collected**（`python -m pytest --collect-only -q -p no:cacheprovider`，31 个测试文件、423 个 def test_，含参数化）。老板口径「597+」以 606 为准。

---

## 3. 方案 A：三档

### A-a 止血（零重启恢复前缀派发）

**动作**（Windows 命令，零重启、零鉴权、零代码改动）：

```bash
# 源 = 缓存内技能镜像的 agents（363 个 .md，21:22 部署随镜像带入，实测完好）
cp -r "C:/Users/Administrator/.zcode/cli/plugins/cache/zcode-plugins-official/zcode-expert-system/3.2.1/skills/zcode-expert-system/agents" \
      "C:/Users/Administrator/.zcode/cli/plugins/cache/zcode-plugins-official/zcode-expert-system/3.2.1/agents"
```

等价源：工作树 `E:/zcode-expert-system/agents/`（363 .md 实测一致）。

**验证方式**：
1. `ls ".../3.2.1/agents" | wc -l` → 363；
2. 重开 ZCode 会话（插件组件清单会话启动时扫描），派发 `Agent(subagent_type='zcode-expert-system:研究证据综合专家')` 成功；
3. 对照组：`documents:visual-judge` 同机制官方插件（可选）。

**⚠️ 显式标注：下次部署再丢**——`<pluginRoot>/agents/` 位于 install.js:724 `removePath('清理旧版本缓存')` 管辖内，任何一次 `npm run deploy` 都会整层重建并再次丢失。止血仅应急，必须配合 A-b 根治。应急替代：裸名派发「研究证据综合专家」（用户级 389 文件完好）。

### A-b 根治（install.js 精确改动点，共 4 处）

**改动 1：步骤 1 新增 1g —— 复制 agents 到缓存顶层**

位置：828 行（`log('✅ 插件级 commands 已写入: commands/')`）之后、829 行（步骤 2 注释）之前。代码形态对齐 1f（`!DRY_RUN` 守卫 + 无条件 log，与既有口径一致）：

```js
  // 1g. 插件级 agents -> <pluginRoot>/agents/
  //     ZCode 运行时 collectPluginAgentRoots 硬编码探测 <installPath>/agents/
  //     （app.asar 取证 2026-11-20）；前缀派发 zcode-expert-system:<名> 依赖此目录。
  //     此前从未复制 → 前缀派发自插件发布以来不可用（长期缺陷，非回归）。
  const agentsSrcForCache = path.join(PROJECT_ROOT, 'agents');
  if (!DRY_RUN && fs.existsSync(agentsSrcForCache)) {
    copyDir(agentsSrcForCache, path.join(pluginRoot, 'agents'));
  }
  log('✅ 插件级 agents 已写入: agents/');
```

说明：copyDir 不传 skip——源目录纯净（363 .md 无子目录，实测），与 copyDir skip 口径无冲突。

**改动 2：manifest 补 agents 字段（双保险）**

位置：`buildPluginManifest`（254-268 行）内，`commands` 与 `hooks` 之间：

```js
    skills: 'skills',
    commands: 'commands',
    // 显式声明子代理目录：运行时硬编码探测 <installPath>/agents/（兜底），
    // 此字段使 manifest 自描述（对齐 documents 0.2.9 官方惯例；Set 去重不双载）。
    agents: 'agents',
    hooks: 'hooks/hooks.json',
```

**改动 3：缓存 agents 数量校验（对齐 claude 分支 556-565 形态，363 改为动态源比对）**

位置：1g 之后紧接着（仍在步骤 1 内，校验刚复制的产物，失败即停）：

```js
  // 部署后校验：缓存 agents 必须与源 agents/ 一致（形态对齐 Claude 分支，
  // 数量动态比对源目录，避免硬编码 363 随专家增减漂移）
  if (!DRY_RUN && fs.existsSync(agentsSrcForCache)) {
    const srcAgentCount = fs.readdirSync(agentsSrcForCache)
      .filter((f) => f.endsWith('.md')).length;
    const cacheAgentDir = path.join(pluginRoot, 'agents');
    const cacheAgentCount = fs.existsSync(cacheAgentDir)
      ? fs.readdirSync(cacheAgentDir).filter((f) => f.endsWith('.md')).length
      : 0;
    if (srcAgentCount === 0 || cacheAgentCount !== srcAgentCount) {
      log(`❌ ZCode 缓存 agents 校验失败：缓存 ${cacheAgentCount} 个，源 ${srcAgentCount} 个（${path.join(pluginRoot, 'agents')}）`);
      process.exit(1);
    }
    log(`✅ ZCode 缓存校验通过：${cacheAgentCount} 个 agent（=源）`);
  }
```

位置权衡（如实说明）：校验放 1g 后，若失败则缓存停在「1a-1g 已写、步骤 2/3/4 未做」的半成品态（注册表未刷新、用户级未动）。风险接受依据：①源 agents 空缺失已在既有 preflight（install.js 345-348 对应段：`agents/` 不存在或空 → 抛错先行，零残留）拦截；②1g 校验仅防 copyDir 静默失败，概率极低；③失败后重跑 install 即整层重建，秒级自愈。

**改动 4：修正头部过时注释（18-19 行）**

原：「注意：插件 manifest 的 agents 字段是 recorded-but-not-executed，插件无法贡献子代理，只能靠本脚本写入 ~/.zcode/agents/」
改为：「注意：ZCode 运行时从 <installPath>/agents/ 加载插件前缀子代理（collectPluginAgentRoots 硬编码探测），另从 ~/.zcode/agents/ 加载用户级裸名子代理；本脚本两侧都写（步骤 1g 与步骤 3）」（以实测为准，措辞可在实施时精炼）。

**不改动**：removePath 链、步骤 2/3/4、uninstall（1057 已天然覆盖缓存 agents 整层删除）、deployClaudeCode（其 363 校验是否动态化见裁决点 3）。

### A-c 防回归测试（4 个用例，全部挂进 tests/test_p5_install_safety.py）

夹具：复用现有 `sandbox`（HOME/USERPROFILE 双闸重定向 tmp_path）+ `make_source`（已含 3 个 agent 样本：1 manager + 2 expert）+ `run_installer`（非 TTY → selectTargets 全选，zcode+claude 双部署）。**零新增夹具**。

| 用例名 | 断言口径 |
|---|---|
| `test_deployed_plugin_cache_has_agents` | 安装后 `<home>/.zcode/cli/plugins/cache/zcode-plugins-official/zcode-expert-system/<version>/agents/*.md` 数量 === `(src/'agents').glob('*.md')` 数量且 ≥1（动态口径，不硬编码 3） |
| `test_deployed_manifest_declares_agents` | 沙箱内 `.zcode-plugin/plugin.json` 解析后 `agents == 'agents'`，且 skills/commands/hooks 三字段仍在（防顺手删） |
| `test_cache_agents_shape_manager_and_expert` | 缓存 agents/ 下 `manager-*.md` ≥1 且 `expert-*.md` ≥1（对齐运行时「一层扫描 .md」口径的形态检查） |
| `test_dry_run_writes_no_cache_agents` | `run_installer(src, env, '--dry-run')` 后缓存顶层无 `agents/` 目录（dry-run 零写口径延伸；与既有 `test_dry_run_deletes_nothing` 并列） |

---

## 4. TDD 顺序

1. **RED**：先写 A-c 的 4 个用例（不改 install.js）。预期：前 3 个失败（缓存无 agents/、manifest 无字段），第 4 个通过（dry-run 本来不写）。留存 pytest 输出作 RED 证据。
2. **GREEN**：按 A-b 实施 4 处改动 → 重跑 test_p5 全部 17+4=21 用例全绿 → 再跑全量。
3. **全量**：`python -m pytest -q -p no:cacheprovider`，基线 **606 collected** 零回归（GREEN 前可先跑一次全量取基线，确认 606 全绿后再动 RED，避免把既有红误判为本次引入）。

---

## 5. 风险矩阵（复用漏洞修复红线精神：可回退、业务无感、超范围不动作）

| 改动 | 失败模式 | 可探测性 | 回退方式 |
|---|---|---|---|
| 1g 复制 agents | 磁盘满/权限拒绝 → copyFileSync 抛错 → main().catch exit 1 | rc≠0 + `❌ 执行失败` stderr | 重跑 install（724 整层重建，幂等自愈）；无业务影响（部署器动作，非运行时） |
| 1g 后数量校验 exit(1) | copyDir 静默失败被拦（设计目的）；误报=源计数口径漂移 | rc≠0 + `❌ ZCode 缓存 agents 校验失败` 带双侧数量 | 修正后重跑；半成品缓存由下次部署整层重建 |
| manifest 补 agents | 旧版运行时不识别未知字段 → 忽略（宽松解析 + documents 官方先例实证）；同路径 Set 去重不双载 | 重开会话前缀派发实测（§6-5） | 删字段重部署，秒级 |
| 头部注释修正 | 无（纯注释） | — | — |
| （裁决项）SKIP 扩充 | 误排运行时引用文件（如某命令引用 skills/.../docs/） | pytest 全量 + 命令族抽测 | 还原 SKIP 列表重部署 |
| 不修用户级 2 个幽灵残留 | 无新增风险（现状即残留） | 已实测列名 | 不适用（超范围不动作） |

**业务无感性论证**：全部改动位于部署器与测试；已部署用户级 agents（363）、deployed-agents.json（363）、skills/commands/hooks 内容、运行时 py 均不被触碰。止血动作只**新增**缓存目录，不删不改任何现有文件。

---

## 6. 验证电池（全绿才可声明完成）

1. `node scripts/install.js --dry-run`：计划输出含「插件级 agents 已写入」行（计划可见）。
2. 真部署 `npm run deploy`：退出码 0。
3. 缓存校验：`ls ".../3.2.1/agents" | wc -l` === 363；python 断言 manifest 含 `agents:'agents'` 且四字段齐。
4. 双源无扰动：用户级仍 389 文件（365 .md + 24 .bak）；`deployed-agents.json` 仍 363 条；`expert-system/context/` 未被触碰。
5. **前缀派发实测**：重开 ZCode 会话，`Agent(subagent_type='zcode-expert-system:研究证据综合专家')` 成功（本修复的验收金标准）；对照裸名派发持续可用。
6. pytest 全量 606 collected 全绿（-p no:cacheprovider）。
7. 卸载闭合：`node scripts/install.js --uninstall` 后缓存整层（含 agents）消失（install.js:1057 removePath 覆盖）+ 用户级按清单删净 → 再重装恢复。

## 7. 实施顺序与门禁（九阶段裁剪：S1 → S5 → S6 → S7）

| 阶段 | 动作 | 产物/证据 |
|---|---|---|
| S1 本方案 | 呈老板批准，裁决点 §10 三项 | 本文档 + 批准记录 |
| S2/S3/S4 | 免（无新架构/无接口变更，复用既有部署器设计） | — |
| S5 实施 | TDD：RED 用例+输出 → GREEN 4 处改动 → 全量 606 | diff + pytest 全绿输出 + RED 截存 |
| S6 审查 | 验证电池 §6 全项 + zes-code-review | 电池逐项勾稽表、审查结论 |
| S7 交付 | 真机部署 + 前缀派发实测 + 经验沉淀（修正 install.js 头部文档即交付物之一） | 派发成功记录、复测提示词 |

## 8. 版本策略：建议不 bump（3.2.1 维持）

- 依据 1：本修复对已部署组件内容零变化，仅部署器把既有组件放到运行时会读的位置——version 语义（用户可感知组件变化）未触发。
- 依据 2：bump 会创建 `.../3.2.2/` 新缓存目录，而 `removePath`（724）只删**同版本**路径 → **3.2.1 旧目录连同污染镜像一并残留**（含 457KB PNG 等），需额外手动清理；不 bump 则 3.2.1 整层重建、注册表 installPath 不变、updatedAt 刷新，路径闭合。
- 若老板裁决 bump：唯一改动点 package.json version → 3.2.2，install.js 全部按 version 变量自适应，无第二处。

## 9. 本方案不修的事（超范围清单，仅报告待决策）

1. **缓存技能镜像垃圾**（§2.4 实测清单：PNG 457KB、.claude-plugin/、.zcode/、src/、openspec/、docs/、sandbox_home/、.gitignore）——修复手段为 SKIP_NAMES/SKIP_REL_PATHS 扩充，与 1g 独立。**裁决点 2**。若裁决纳入：前置核对项=grep 全部 `skills/zcode-expert-system/docs|src|openspec` 引用确认零运行时依赖后再排（当前证据：/wf:* 命令仅引用 `scripts/` 与 `config/`，P9 测试 `test_deployed_skill_has_runtime_scripts` 守护的也是 scripts/ 三件）。
2. **claude 分支硬编码 363**（install.js:560）随专家增减必误报 → 裁决点 3（动态化，一行改动，属本次 adapter 改动面的完善）。
3. **用户级 2 个幽灵残留**（`~/.zcode/agents/secops.md`、`visual-judge-qx.md`，deployed-agents.json 清单外）——缺陷 #18 历史形态，卸载永远删不掉；本方案不动用户级口径。
4. **installed_plugins.json 6 个 .bak 未清理**（install.js 仅清理 skills 的 .bak）——存储卫生小事。
5. **~/.claude 侧缓存 2026-11-20 19:14 被打 `.orphaned_at`**（Claude 侧注册未认可 12:59 的部署）——属 claude-code-plugin-adapter 改动的遗留问题，另行排查。
6. 21:22 部署为何未含 claude 目标（install.js 工作树 mtime 23:43 晚于运行时刻，中间版本内容不可考）——不影响本方案。

## 10. 老板裁决点清单

1. **版本策略**：不 bump（建议）vs bump 3.2.2（§8）。
2. **SKIP 扩充是否随本次纳入**：建议纳入（同部署器改动面、一行清单），但按红线单列由老板定；纳入则先做 §9-1 前置核对。
3. **claude 分支 363 校验是否同步动态化**：建议同步（与改动 3 同形态，消除未来误报）。

## 附：证据清单（关键件）

- `E:\zcode-expert-system\scripts\install.js`：18-19（过时注释）、98-115（SKIP）、254-268（buildPluginManifest）、556-565（claude 363 校验）、720-828（ZCode 步骤 1 全量复制清单）、829（1g 插入点）、885/892/952/1129（deployed-agents.json 写/读）、724/1057（removePath 缓存两处）
- `C:/Users/Administrator/.zcode/cli/plugins/installed_plugins.json` 及 6 个 `.bak-<ts>`：zcode-expert-system 六次部署链（v3.2.0→3.2.1，全 local/directory；13:22:22.690Z 实证）
- `C:/Users/Administrator/.zcode/expert-system/deployed-agents.json`：363 条；用户级磁盘 365 .md 差集={secops.md, visual-judge-qx.md}
- `C:/Users/Administrator/.zcode/cli/plugins/cache/zcode-plugins-official/documents/0.2.9/`：manifest `agents:"agents"` + `agents/visual-judge.md`（官方机制先例）
- `D:\Programs\ZCode\resources\app.asar`（385MB，只读 rg -a）：`collectPluginAgentRoots` `s("agents")` 硬编码 + manifest.agents 字符串/数组 + Set 去重 + `startsWith("..")` 防逃逸
- 工作树 `E:\zcode-expert-system\agents\`：363 .md / 0 子目录 / 0 非 .md
- pytest：`python -m pytest --collect-only -q -p no:cacheprovider` → **606 collected**（2026-11-20 实测）
