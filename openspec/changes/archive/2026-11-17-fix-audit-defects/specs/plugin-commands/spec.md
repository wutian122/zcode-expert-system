## ADDED Requirements

### Requirement: 文档命令不依赖外部 openspec CLI

所有面向用户的命令文档（commands/wf/*.md 与 references/stage-S*.md）中的 `openspec xxx` 调用 MUST 使用内置引擎 `python "$ZCODE_PLUGIN_ROOT/skills/zcode-expert-system/scripts/openspec_engine.py" xxx` 形式，使插件在未安装外部 openspec CLI 的环境下仍可完整使用。

#### Scenario: 未安装 openspec CLI 的电脑执行 /wf:spec
- WHEN 用户在未安装外部 openspec CLI 的电脑上执行 `/wf:spec`
- THEN 系统通过 `python "$ZCODE_PLUGIN_ROOT/.../openspec_engine.py" new-change` 成功创建 change
- AND 不出现 command not found 错误

#### Scenario: 未安装 jq 的电脑执行 /wf:archive
- WHEN 用户在未安装 jq 的电脑上执行 `/wf:archive`
- THEN 系统通过 `python .../openspec_engine.py status` + python 内联解析成功获取 delta 来源
- AND 不依赖 jq

### Requirement: git 判定口径统一

`scripts/workflow_check.py` 与 `zcode_dev_workflow.py` 对同一项目的 git 仓库判定 MUST 一致，均要求 `.git` 为有效仓库（目录含 HEAD 或文件以 `gitdir:` 开头），不得仅凭 `os.path.exists(.git)` 判定。

#### Scenario: 空 .git 目录不被误判为仓库
- WHEN 项目根存在一个空的 `.git` 目录（非有效仓库）
- THEN workflow_check.py 与 zcode_dev_workflow.py 均判定 git=无
- AND 走快照证据路径而非 diff 路径

### Requirement: stage-S2-spec.md 段落结构完整

`references/stage-S2-spec.md` 的 `## 关键约束：Planning boundary` 标题下 MUST 有正文内容，不得为空标题紧跟其他章节。

#### Scenario: workflow_check --self-check 通过
- WHEN 运行 `python scripts/workflow_check.py --self-check`
- THEN 返回 rc=0，无漂移
- AND stage-S2-spec.md 结构完整

### Requirement: install.js 不打包开发账本

`scripts/install.js` 的 `SKIP_NAMES` MUST 包含 `.superpowers`，使开发期 SDD 账本不随插件分发到目标电脑。

#### Scenario: dry-run 不包含 .superpowers
- WHEN 运行 `node scripts/install.js --dry-run`
- THEN 输出不包含任何 `.superpowers` 路径
- AND 部署后的技能目录不含开发账本