# 全局规则（AGENTS.md）

本文件是本项目的全局规则单一出处。所有在本仓库工作的代理/助手在每次响应前必须先遵守以下规则。

## 0.1 语言与称呼
- 所有输出、计划、思考过程使用**中文**；未指定语言默认中文。
- 统一称呼用户为 **"老板"**。

## 0.2 工具调用
- 浏览器操作 **唯一入口 = ZCode 内置浏览器**（`browser-use:control-browser`），所有浏览器操作一律使用内置浏览器；
- CodeGraph 走 MCP：仓库有 `.codegraph` 时**先** `codegraph_explore`（符号源码+调用路径一次拿到）再 `rg`/读文件；无 `.codegraph` 则跳过；
- **外部情报检索（tavily × anysearch 双引擎互补）**：默认引擎 = `tavily:*` 插件技能（1.0.0，八技能）与 tvly CLI（0.1.6）；互补引擎 = 本地技能 `anysearch`（3.1.1）。**分工**：①通用 web 搜索/文档查证默认 tavily，重要结论用 anysearch 交叉复搜，tavily 故障时 anysearch 兜底；②**垂直领域**（金融行情/CVE/学术 DOI/专利/IP/法律/安全等结构化域）**优先 anysearch**（先 `get_sub_domains` 取 sub_domain 与必填参数再搜）；③**深度研究/站点爬取/站点地图**优先 tavily（research/crawl/map）；④**多意图并行查询**优先 anysearch `batch_search`；⑤URL 全文抽取两者皆可（anysearch `extract` 直出 Markdown，不支持 PDF/图片等二进制——PDF 走 tavily-extract 或 qwen-mm）。anysearch 查询出站至 `api.anysearch.com`：凭据/个人数据/商业秘密不得进查询串。**检索结论必须附出处 URL**，搜索印象不得当事实。
- **远程操作唯一入口 `remote-shell`**（v0.4.0：SSH/SFTP/Telnet/WinRM + 加密凭证库；登录执行脚本不接受 `-p`，密码只能来自凭证库；修改类命令被拦截，向老板确认后加 `--auto-confirm` 重试；命中 `SecurityInterceptedError` 停止重试并请求老板确认）。
- **容器镜像构建与推送**：**不得**为「上传镜像」在 Windows 本机安装容器运行时。构建一律在服务器侧：`linux/amd64` 在 B 机（192.168.238.132）build+push，`linux/arm64` 在 A 机（10.129.7.87:62222）本地 buildx 构建；本机 AMD64 交叉构建 arm64 需 qemu、慢且不稳，禁止。经 `remote-shell` 执行并先征老板同意。

## 【专家体系路由】
所有任务都必须先走 zcode-expert-system 两轴路由（先规模后域），由 triage 的分诊结论决定派谁——任务是否「看起来像领域任务」不是主控的自判项。**不得跳过域路由（W10）。**

判定顺序（先规模后域，与全局规则 Step1→Step2 一致）：
1. 先跑 `zcode_dev_workflow.py triage "<任务>"`（已双轴合一：规模+领域路由一次产出）——所有任务（含只读与机械任务）都必须完成两轴分诊，不得跳过域路由；
2. 看路由结果的 `score_detail` 做语义精判；含领域判断的（分析/设计/评估/诊断/审查/规划/撰写专业方案）→ 按结论派对应专家，`subagent_type` 填专家中文名；
3. 只读任务派 analyst（领域专家）只读分析，不得由主控凭通识自行分析；只读任务仅允许查看/搜索/读取类工具，禁止新增、删除、修改文件，禁止安装依赖、git 写操作与 shell 重定向写盘；
4. 「机械任务」仅限纯格式转换/批量执行类操作；一旦需要领域解释或决策 → 升级为派专家，不得凭通识自行作答。复核/审查任何产出（含主控自己的产出）属于领域判断，必须派独立专家（实施者≠审查者），不得以「机械核对」名义自审；
5. 禁止跳过域路由自行处理领域判断；确无法派专家须说明原因（路由失败走降级三件套：`degraded=true` + `blocking`）；
6. 每次派发专家前，主控必须在会话中显示一行「正在调用专家：<专家中文名>」；Agent/Task 的 description 使用「专家：<专家中文名>」，不得只显示 Agent/general-purpose。

## 【语义精判】
本插件不配外部 LLM/Embedding（依赖会话模型，刻意设计）。`zcode_expert_system` 返回 `semantic_selection_required=true` 时，其 `selected_expert` 只是词元计数结果，主控必须自己看 `top_candidates[].score_detail` 按业务语义复核；要改判用 `build_dispatch_for_expert(专家名, task)`。

32 领域（与 `config/categories.json` 同源）：前端与客户端/后端与架构/数据与数据库/DevOps 与运维/AI 与大模型/嵌入式与物联网/网络工程/工程效能与质量/安全与合规技术/数据与测试/设计与创意/营销与增长/付费媒体/销售与客户/商业经营与战略/医疗健康/供应链与物流/法务与合规/人力资源/财务与税务/学术与研究/政企与公共服务/商业支持与专业服务/学术与知识服务/游戏开发/空间计算与 XR/地理信息系统/项目管理/产品管理/客户支持/语言与跨文化/身份与智能体治理。

## 【研发工作流】
中/大任务走九阶段（分诊→设计→规格→计划→基线→实施→审查→交付→归档），每阶段过门禁并落证据；轻量任务可裁剪但 TDD 与验证不可跳。详细规格见 `references/stage-S*.md`。

**豁免仅两级**：纯闲聊/问候可直答；老板明示豁免专家体系时必须记 Ruling（W10）。
