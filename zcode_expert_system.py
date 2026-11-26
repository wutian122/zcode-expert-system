#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ZCode Expert System v3 — 主入口：双层路由编排

架构：
  第一层：LLM 分类（32 个一级大类之一）
  第二层：总经理（32 个，负责任务分解与专家派发）
  第三层：专家（331 位，来自上游 dsh-agency-agents 的完整人格提示词）

入口：zcode_expert_system(task_description) -> result (dict)
"""

import json
import math
import os
import re
import sys
from collections import Counter
from functools import lru_cache

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_DIR = os.path.join(SCRIPT_DIR, "config")
AGENTS_DIR = os.path.join(SCRIPT_DIR, "agents")
SCRIPTS_DIR = os.path.join(SCRIPT_DIR, "scripts")
CONTEXT_DIR = os.path.join(SCRIPT_DIR, "context")

if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)
if CONTEXT_DIR not in sys.path:
    sys.path.insert(0, CONTEXT_DIR)

from llm_client import classify_task_with_llm, select_expert_with_llm, load_experts


def _force_utf8_stdout():
    """让 stdout/stderr 用 UTF-8 输出，避免非 UTF-8 控制台抛 UnicodeEncodeError。

    背景（缺陷 #3）：中文 Windows 默认代码页 CP936 无法编码 emoji，
    而 config/experts.json 每个专家都带 emoji 字段（⚙️ U+2699 等），
    它会经 top_candidates 透出到 `json.dumps(..., ensure_ascii=False)`，
    导致 `python zcode_expert_system.py "<任务>"` 在 CP936 终端 rc=1、stdout 全空。

    不改 ensure_ascii：它会把中文与 emoji 全转成 \\uXXXX，破坏可读性与下游断言。
    errors="replace" 仅作重配失败时的兜底；正常情况下 UTF-8 完整保留。
    与 zcode_dev_workflow.py / skill_entry.py 的同名函数保持一致。
    """
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass

# 32 个一级大类
CATEGORIES = [
    "frontend-client",
    "backend-architecture",
    "data-database",
    "devops-operations",
    "ai-llm",
    "embedded-iot",
    "network-engineering",
    "engineering-quality",
    "security-compliance",
    "data-testing",
    "design-creative",
    "marketing-growth",
    "paid-media",
    "sales-customer",
    "business-strategy",
    "healthcare",
    "supply-chain",
    "legal-compliance",
    "hr",
    "finance-tax",
    "academic-research",
    "government-public",
    "business-support",
    "data-knowledge",
    "game-dev",
    "spatial-computing",
    "gis",
    "project-management",
    "product-management",
    "customer-support",
    "language-translation",
    "agent-governance",
]

DEFAULT_CATEGORY = "business-support"

# 关键词映射（LLM 不可用时的兜底）
# 顺序即优先级：越具体的领域越靠前，通用工程词靠后，避免被宽泛词抢先命中。
KEYWORD_MAP = {
    # ---- 高优先级：边界清晰的专业领域 ----
    "security-compliance": [
        "渗透", "漏洞", "安全审计", "威胁检测", "威胁情报", "加密", "防火墙策略",
        "安全架构", "secops", "密钥", "凭据", "安全评估", "红队", "合规审计",
        "soc2", "iso27001", "等保", "身份与访问", "越权", "csp",
        # R6：认证授权安全词元。jwt/oauth/token 同时声明在 backend-architecture（功能视角），
        # 此处补入安全视角，靠声明序（security 在前）让安全事件胜出。
        # 裸 jwt/oauth/token 与 backend 同长 → 触发同分决胜（security 在 :97 靠前），
        # 安全事件（如"JWT token 泄漏应急"）由此拉回 security-compliance。
        # 注意：裸 token 会让"实现 token 刷新"这类功能任务同分落 security，
        # 与裸 jwt 的边界取舍一致（方案预期内，业务边界模糊可接受）。
        # 另补 token泄漏/泄露 复合词，覆盖中文连写场景。
        "jwt", "oauth", "token", "应急响应", "安全事件", "安全事故",
        "token泄漏", "token泄露", "jwt泄漏", "jwt泄露",
        # R7：补入「安全审查」「代码审计」——带安全意图的审查正确路由到 security。
        "安全审查", "代码审计",
        # H1 修复：补入「sql注入」「注入漏洞」「渗透测试」等复合词（长度≥4），
        # 压过 data-database 的裸 sql（长度3）。否则「渗透测试发现 SQL 注入漏洞」
        # 会被 data-database 的 sql 劫持（短词被误当强证据），误路由到数据库领域。
        # 裸「渗透」「漏洞」保留（长度2），用于无 sql 语境的安全任务。
        "sql注入", "注入漏洞", "渗透测试", "注入攻击", "sql注入漏洞",
    ],
    "legal-compliance": [
        "合同审查", "合同起草", "合同条款", "法律", "合规", "诉讼", "知识产权",
        "专利", "商标", "法务", "法规", "制度文件", "隐私政策", "用户协议", "律所",
        # R7：「合规检查」从 engineering-quality 迁入——合规语义归法律合规。
        "合规检查",
    ],
    "finance-tax": [
        "财务", "会计", "预算", "发票", "报销", "账单", "理财", "税务", "纳税",
        "审计", "对账", "现金流", "融资", "投资", "cfo", "成本核算", "簿记",
    ],
    "hr": [
        "招聘", "人力资源", "简历", "入职", "离职", "薪酬", "绩效", "员工关系",
        "培训开发", "面试", "人才", "组织发展", "考勤",
        # 口语招聘表达：中国职场口语说「招一个」「招人」「招个」，不说「招聘」。
        # 只用完整词组，不用单字「招」——避免「招标」「招呼」「招牌」误落 hr。
        "招人", "招一个", "招个", "招一名", "招两位", "招几个",
    ],
    "healthcare": [
        "医疗", "健康", "护理", "医院", "医生", "临床", "患者", "药品", "诊疗",
        "循证", "病历", "手术", "康复", "养老", "照护",
        "医疗账单", "icd", "cpt", "病历编码", "医保结算",
    ],
    "game-dev": [
        "游戏", "unity", "unreal", "godot", "关卡设计", "游戏设计", "游戏引擎",
        "cocos", "roblox", "shader graph", "gameplay",
    ],
    "design-creative": [
        "ui设计", "ux", "视觉设计", "品牌设计", "品牌视觉", "logo", "图标设计",
        "配色", "用户体验", "界面设计", "视觉识别", "vi设计", "设计规范",
        "交互设计", "原型设计", "figma",
        "可用性测试", "用户研究", "ux研究", "用户访谈",
    ],
    "marketing-growth": [
        "营销", "seo", "推广", "品牌营销", "社交媒体", "增长黑客", "电商运营",
        "直播电商", "内容创作", "小红书", "抖音", "快手", "微博", "知乎", "b站",
        "bilibili", "公众号", "视频号", "私域", "种草", "带货", "kol", "内容运营",
        "选题", "aso", "品牌传播", "公关", "投放策略",
    ],
    "paid-media": [
        "付费广告", "facebook广告", "google广告", "google ads", "meta广告",
        "ppc", "sem", "广告投放", "投放优化", "程序化广告", "信息流广告", "rtb",
    ],
    "sales-customer": [
        "销售", "客户拓展", "商机", "报价", "crm", "销售线索", "成交", "外联",
        "赢单", "标书应答", "售前", "渠道管理", "客户成功", "续约",
    ],
    "supply-chain": [
        "供应链", "物流", "库存", "运输", "仓储", "采购", "配送", "供应商",
        "补货", "需求预测", "清关", "跨境电商物流",
    ],
    "project-management": [
        "项目管理", "项目计划", "项目进度", "进度管理", "里程碑", "甘特", "敏捷",
        "scrum", "看板", "项目跟进", "风险登记", "会议纪要", "jira",
    ],
    "customer-support": [
        "客服", "客户服务", "技术支持", "faq", "帮助文档", "售后", "工单",
        "客户支持", "客户咨询", "投诉处理", "客诉", "满意度",
        "客户成功", "客户成功流程", "客户健康度",
    ],
    "data-testing": [
        "测试", "qa", "自动化测试", "性能测试", "单元测试", "集成测试", "回归测试",
        "用户行为", "数据分析", "统计分析", "压测", "基准测试", "覆盖率",
        "用例",
        "断言",
        "缺陷",
        "埋点",
    ],
    "spatial-computing": [
        "ar开发", "vr开发", "xr", "spatial", "增强现实", "虚拟现实", "元宇宙",
        "visionos", "空间计算", "空间应用", "webxr", "头显",
    ],
    "gis": [
        "gis", "地图", "地理", "无人机", "bim", "gps", "遥感", "测绘",
        "地理信息", "空间数据", "制图", "点云",
    ],
    "academic-research": [
        "学术", "论文", "文献", "期刊", "学位", "导师", "研究方法", "研究方法论",
        "历史学", "历史研究", "人类学", "社会学", "心理学研究", "文献综述",
        "考据", "史料",
    ],
    "business-strategy": [
        "公司战略", "企业战略", "经营策略", "商业模式", "企业文化", "变革管理",
        "运营优化", "组织架构", "高管", "决策支持", "m&a", "并购",
    ],
    "government-public": [
        "政务", "政府", "tog", "标书", "投标", "高考", "志愿填报", "留学",
        "签证", "公共政策", "事业单位",
        "政务标书", "等保标书", "信创标书", "政务数字化", "等保合规标书", "等保合规",
    ],
    "product-management": [
        "产品规划", "产品设计", "产品经理", "需求分析", "需求优先级", "用户研究",
        "用户调研", "路线图", "产品路线", "prd", "竞品分析",
    ],
    "data-knowledge": [
        "知识库", "知识管理", "zk", "卡片盒", "笔记法", "模型qa", "模型审计",
        "文档生成", "研究综合", "证据综合",
    ],
    "agent-governance": [
        "智能体", "agent", "mcp", "工具调用", "编排", "身份图谱",
        "ai治理", "ai agent",
    ],
    "language-translation": [
        "翻译", "本地化", "多语言", "i18n", "技术翻译", "l10n", "术语",
    ],
    # ---- 中优先级：技术实现类 ----
    "data-database": [
        "数据库", "db", "sql", "数据仓库", "数据湖", "etl", "elt", "spark", "dbt",
        "索引优化", "慢查询", "主从", "分库分表", "数据建模", "gaussdb",
        # 检索/排序质量：这些是“搜索相关性工程师”的正向证据。
        # 只收复合词，不收裸“搜索/相关性/排序”，避免劫持普通检索需求。
        "搜索相关性", "检索相关性", "相关性评估", "召回率", "排序质量",
        "分词器", "评测集", "标注集", "误判率", "专家路由",
    ],
    "frontend-client": [
        "前端", "react", "vue", "angular", "svelte", "css", "html", "微信小程序",
        "wxml", "wxss", "electron", "tauri", "桌面应用", "移动应用", "ios",
        "android", "app开发", "响应式", "组件库",
        "页面",
        "登录页",
        "表单",
        "组件",
        # 「路由」不在此声明——它同时属 network-engineering（网络路由），
        # 声明序会让前端恒胜，导致「路由器怎么配置」被劫持。
        # 前端语境由「前端」「vue」「react」「vue-router」等覆盖。
        "渲染",
        "浏览器",
        "移动端",
        "小程序",
        "白屏",
        "首屏",
        # I-4：「博客」此前不在任何分类词表，「搭建一个博客系统」在退化二
        # 打分里仅靠泛化词「一个」（STOP_TOKEN）与 hr「招一个」词元重叠，
        # 以 0.0357×0.75=0.0268 的噪声分误路由 hr。补词后走精确关键词命中。
        # 子串碰撞裁决：「博客园」等站点名会连带命中——爬取类任务从
        # conf=0 兜底变为 frontend-client，属可接受轻度偏航（有测试守护
        # 不得落入 hr/healthcare/finance 等明显无关域）。
        "博客",
    ],
    "backend-architecture": [
        "后端", "api", "restful", "graphql", "grpc", "微服务", "服务端", "cms",
        "drupal", "wordpress", "接口设计", "网关", "限流", "分布式",
        "登录",
        "认证",
        "鉴权",
        "授权",
        "会话",
        "注册",
        "权限",
        "jwt",
        "oauth",
        "token",
        "接口",
        "模块",
        "中间件",
        "校验",
        "消费者",
        "定时任务",
        "消息队列",
        "kafka",
        "rabbitmq",
        "redis",
        "缓存",
        "架构",
        "飞书", "钉钉", "飞书审批流", "钉钉审批流", "webhook", "低代码",
    ],
    "ai-llm": [
        "ai", "llm", "rag", "大模型", "大语言模型", "语言模型", "人工智能",
        "机器学习", "深度学习", "神经网络", "transformer", "embedding", "微调",
        "prompt", "提示词", "文生图", "文生视频", "sora", "midjourney",
        "stable diffusion", "语音识别", "asr", "tts", "聊天机器人", "chatbot",
        "智能助手", "对话系统", "sft", "rlhf",
        "向量库",
        "向量检索",
        "训练数据",
        "多智能体",
    ],
    "devops-operations": [
        "devops", "ci/cd", "jenkins", "github actions", "gitlab ci", "docker",
        "kubernetes", "k8s", "terraform", "ansible", "sre", "监控", "告警",
        "可观测性", "发布部署", "灰度", "容器化",
        "日志",
        "报错",
        "异常",
        "崩溃",
        "故障",
        "线上",
        "排查",
        "调试",
        "上线",
        "发布",
        "部署",
        "回滚",
        "502",
        "超时",
        "nginx",
        # dockerfile 是独立词：加了 ASCII 词边界后 `docker` 不再命中它的前缀，
        # 必须显式声明，否则「写一个 Dockerfile」会落到兜底分类
        "dockerfile",
        "docker",
    ],
    "embedded-iot": [
        "嵌入式", "固件", "rtos", "freertos", "zephyr", "stm32", "esp32",
        "arduino", "raspberry pi", "fpga", "verilog", "vhdl", "vivado",
        "quartus", "iot", "mqtt", "lorawan", "ble", "zigbee", "单片机",
    ],
    "network-engineering": [
        "网络工程", "路由", "交换", "防火墙", "cisco", "juniper", "palo alto",
        "华为", "华三", "锐捷", "bgp", "ospf", "mpls", "vxlan", "sdn",
        "vlan", "acl",
    ],
    # ---- 低优先级：通用工程词（放最后，避免抢具体领域）----
    "engineering-quality": [
        "代码审查", "代码质量", "重构", "技术债务", "git工作流", "code review",
        "refactor", "编码规范", "静态分析",
        "代码异味",
        "异步",
        "技术债",
        # 元评估/诊断类关键词（P0 修复）：避免「梳理插件是否有冲突」「审查工作流」
        # 这类任务误落 business-support 兜底导致无专家可派。
        # 注意：不单独加「评估」——security-compliance 的「安全评估」已含词元
        # "评估"，单独加会制造跨类并列并破坏同分决胜的声明序契约；改用更具体的短语。
        "审查", "诊断", "梳理", "检查", "冲突", "问题排查", "代码检查",
        # 插件/CLI/工作流修复：安装注册与工作流修复的正向证据。
        # 只收复合词，避免裸“插件/安装/注册”劫持普通后端任务。
        "插件安装", "插件注册", "安装注册", "命令行工具", "cli工具",
        "工作流修复", "路由准确率", "分类准确率",
        # R7：移除「合规检查」——合规属 legal-compliance/security-compliance，
        # 放在通用工程词里是错位。合规语义由 legal-compliance 的「合规」承接。
    ],
    # ---- 兜底：极通用词 ----
    "business-support": [
        # 「客户服务」只归 customer-support——本类是兜底类，不该持有抢具体类的词
        # R8：移除「翻译服务」——它属 language-translation 的具体业务词，
        # 4 字最长命中会压过 language-translation 的「翻译」(2字)，导致
        # "提供翻译服务"被兜底类抢走。移除后「翻译」自然命中 language-translation。
        "酒店", "零售", "退货", "房地产", "旅行", "会议效率",
        "个人成长", "养殖",
    ],
}


def _keyword_weight(keyword):
    """分类精确关键词的证据权重：长度越长，证据越强。

    2 字 1.0 / 3 字 1.5 / 4 字 2.0 / 5+ 字按 0.2 递增（上限 3.0）。
    这样「客户成功流程」(6) 才能压过「客户成功」(4)，
    「等保合规标书」(6) 才能压过「等保」(2)。
    """
    n = len(keyword or "")
    if n <= 2:
        return 1.0
    if n == 3:
        return 1.5
    if n == 4:
        return 2.0
    return min(3.0, 2.0 + 0.2 * (n - 4))


DOMAIN_INTENT_WORDS = (
    "说明", "解释", "分析", "评估", "审查", "审计", "对比", "是什么",
    "区别", "只读", "讲解", "怎么理解",
)
# 讨论“路由/分类/专家选择”本身时，测试/评估/审计是宾语，不是领域证据。
ROUTER_META_TERMS = ("路由", "分类", "准确率", "误判", "专家", "词面", "词元")
META_DOMAIN_WORDS = ("测试", "评估", "审计", "审查", "分析", "操作")


def _domain_intent(text):
    return any(w in (text or "") for w in DOMAIN_INTENT_WORDS)


def _router_meta_task(text):
    return any(w in (text or "") for w in ROUTER_META_TERMS)


def _confidence_from_scores(top, second, evidence, tied):
    """把 top1/top2 变成可解释置信度：绝对分 × margin。"""
    if top <= 0:
        return 0.0, 0.0, 0.0
    margin = max(0.0, (top - second) / float(top))
    abs_score = min(1.0, top / 2.0)
    conf = abs_score * (0.5 + 0.5 * margin)
    # 并列或间隔过小：胜者只靠声明序/微小分差，不能给高置信。
    if tied or margin < 0.15:
        conf = min(conf, 0.45)
    return round(conf, 4), round(margin, 4), round(abs_score, 4)


def classify_task_with_evidence(task_description):
    """分类并返回 (category, confidence, alternatives, confidence_detail)。

    confidence 不再只表示“词面强度”，而是 **绝对证据 × top1-top2 margin**：
      - 单 2 字关键词：最高 0.5；
      - 真并列：最高 0.45；
      - 4 字以上复合词/多关键词：可到 1.0。
    调用方据此决定是否必须语义复核/阻断派发。
    """
    if not task_description:
        return DEFAULT_CATEGORY, 0.0, [], {"evidence": "none", "top_score": 0.0,
                                          "second_score": 0.0, "margin": 0.0}

    # 尝试 LLM 分类（生产环境 _call_llm 恒返回 None，此层为将来留下接口）
    category = classify_task_with_llm(task_description)
    if category and category in CATEGORIES:
        return category, 1.0, [], {"evidence": "semantic", "top_score": 2.0,
                                   "second_score": 0.0, "margin": 1.0}

    text = task_description.lower()
    domain_intent = _domain_intent(text)
    router_meta = _router_meta_task(text)

    # 退化一：精确关键词命中，按关键词长度加权，取最高证据分类。
    # ASCII 关键词必须整词匹配：中文用子串包含是对的（中文无词边界），
    # 但英文/数字关键词用裸 `in` 会被别的单词碎片劫持——
    # `ai` 命中 em[ai]l / det[ai]l / m[ai]n，`db` 命中 g[db]。
    cat_scores = {}
    cat_keywords = {}
    for cat, keywords in KEYWORD_MAP.items():
        for kw in keywords:
            k = kw.lower()
            if not k:
                continue
            if _keyword_hits(k, text):
                w = _keyword_weight(k)
                if w > cat_scores.get(cat, 0.0):
                    cat_scores[cat] = w
                cat_keywords.setdefault(cat, []).append(k)
    if cat_scores:
        declared_order = list(KEYWORD_MAP)
        top_score = max(cat_scores.values())
        winners = sorted(
            (cat for cat, score in cat_scores.items() if score == top_score),
            key=declared_order.index,
        )
        winner = winners[0]
        alternatives = winners[1:]
        second_score = max(
            (score for cat, score in cat_scores.items() if cat != winner),
            default=0.0,
        )
        tied = bool(alternatives)
        confidence, margin, abs_score = _confidence_from_scores(
            top_score, second_score, "exact_keyword", tied)
        # 单弱词（只有一个 2 字关键词）不得冒充高置信。
        weak_single = (
            not tied and top_score <= 1.0
            and len(cat_keywords.get(winner, [])) == 1
        )
        if weak_single:
            confidence = min(confidence, 0.5)
        # 讨论“路由/分类/专家选择”本身时，测试/评估/审计只是宾语。
        # 不改变分类（缺少复合词时硬改会错到别的域），只把置信度压到阻断区，
        # 让主控澄清，而不是自信地派错专家。
        meta_only = bool(
            domain_intent and router_meta
            and cat_keywords.get(winner)
            and all(k in META_DOMAIN_WORDS for k in cat_keywords[winner])
        )
        if meta_only:
            confidence = min(confidence, 0.45)
        detail = {
            "evidence": "exact_keyword",
            "top_score": round(top_score, 4),
            "second_score": round(second_score, 4),
            "margin": margin,
            "abs_score": abs_score,
            "matched_keywords": sorted(cat_keywords.get(winner, [])),
            "weak_single": weak_single,
            "tied": tied,
            "intent": "explain" if domain_intent else "other",
            "intent_downgraded": meta_only,
        }
        return winner, confidence, alternatives, detail

    # 退化二：词元加权重叠打分，取最高分分类
    task_tokens = _tokenize(task_description)
    if task_tokens:
        scored = []
        descriptions = _category_descriptions()
        for cat, keywords in KEYWORD_MAP.items():
            score = _category_affinity_score(
                task_tokens, keywords, description=descriptions.get(cat, ""))
            if score > 0:
                scored.append((score, cat))

        if scored:
            top_score = max(s for s, _ in scored)
            declared_order = list(KEYWORD_MAP)
            winners = sorted(
                (cat for s, cat in scored if s == top_score),
                key=declared_order.index,
            )
            alternatives = winners[1:]
            second_score = max(
                (s for s, cat in scored if cat != winners[0]),
                default=0.0,
            )
            confidence, margin, abs_score = _confidence_from_scores(
                top_score, second_score, "token_overlap", bool(alternatives))
            detail = {
                "evidence": "token_overlap",
                "top_score": round(top_score, 4),
                "second_score": round(second_score, 4),
                "margin": margin,
                "abs_score": abs_score,
                "matched_keywords": [],
                "weak_single": False,
                "tied": bool(alternatives),
                "intent": "explain" if domain_intent else "other",
                "intent_downgraded": False,
            }
            return winners[0], confidence, alternatives, detail

    # 完全无信号：显式标记 0 置信度，不伪装成正常分类
    return DEFAULT_CATEGORY, 0.0, [], {"evidence": "none", "top_score": 0.0,
                                      "second_score": 0.0, "margin": 0.0}


def classify_task_detailed(task_description):
    """兼容入口：返回 (category, confidence, alternatives)。

    confidence 语义见 classify_task_with_evidence：绝对证据 × margin，
    不再是“最长关键词唯一命中即 1.0”。
    """
    category, confidence, alternatives, _detail = classify_task_with_evidence(
        task_description)
    return category, confidence, alternatives


def classify_task(task_description):
    """
    第一层：LLM 分类
    返回：category (str)，32 个一级大类之一

    这是 `classify_task_detailed` 的简化包装，保持既有调用方的 str 契约。
    需要置信度或备选分类时请直接用 `classify_task_detailed`。

    降级链：LLM 分类 → 关键词加权命中 → 词元加权重叠打分 → 默认分类。
    「关键词加权命中」用长度权重避免短词（如 "api"）抢先命中宽泛分类；
    同分一律按 KEYWORD_MAP 的声明优先级决胜（声明序即优先级）。
    """
    category, _confidence, _alternatives = classify_task_detailed(task_description)
    return category


def get_manager(category):
    """
    根据分类获取对应的领域总经理
    返回：manager_id (str)
    """
    return f"manager-{category}"


def get_experts_by_category(category):
    """
    获取指定分类的所有专家
    返回：experts (list[dict])
    """
    all_experts = load_experts()
    return [e for e in all_experts if e.get("category") == category]


def _keyword_hits(keyword, text):
    """判断一个关键词是否命中文本，按字符类型区别对待。

    中文：子串包含即可（中文没有空格词边界，二元组本来就是子串）。
    ASCII：必须整词匹配。判定标准是前后字符不能是「标识符字符」
           （a-z0-9_），否则 `ai` 会命中 `em[ai]l`、`det[ai]l`、`m[ai]n`，
           `db` 会命中 `g[db]`，`ui` 会命中 `b[ui]ld`。

    注意：允许 `-` `.` `+` `#` 作为边界——`vue-router` 里 `router` 是独立词，
    `c++`/`c#` 这类关键词自身就含符号，交由关键词侧决定含不含。
    """
    kw = (keyword or "").lower()
    if not kw:
        return False
    # 纯 ASCII 关键词走整词匹配；含中文的走子串
    if not re.search(r"[a-z0-9]", kw) or re.search(r"[\u4e00-\u9fff]", kw):
        return kw in text

    start = 0
    while True:
        i = text.find(kw, start)
        if i < 0:
            return False
        before_ok = (i == 0) or not re.match(r"[a-z0-9_]", text[i - 1])
        end = i + len(kw)
        after_ok = (end >= len(text)) or not re.match(r"[a-z0-9_]", text[end])
        if before_ok and after_ok:
            return True
        start = i + 1


def _tokenize(text):
    """切分中英词元，用于无模型时的相似度打分。

    英文/数字按词切；中文切成二元组（相邻两字），避免依赖分词库。
    """
    text = (text or "").lower()
    tokens = set()
    for w in re.findall(r"[a-z0-9_+#.]{2,}", text):
        tokens.add(w)
    for seg in re.findall(r"[\u4e00-\u9fff]+", text):
        if len(seg) == 1:
            tokens.add(seg)
        else:
            for i in range(len(seg) - 1):
                tokens.add(seg[i:i + 2])
    return tokens


# 泛化动作词：几乎出现在任何任务描述里，不具区分度，
# 打分时剔除，避免"设计/开发/系统"这类词把宽泛专家抬到最高分。
STOP_TOKENS = {
    "设计", "开发", "优化", "管理", "分析", "系统", "方案", "制定", "实现",
    "搭建", "建设", "处理", "支持", "服务", "工作", "流程", "方法", "问题",
    "需求", "相关", "进行", "一个", "如何", "怎么", "帮我", "需要", "以及",
    "作流",  # 「工作流」的 bigram 残片：高频泛化词，不应决定专家排序
    "我们", "你们", "可以", "这个", "那个", "什么",
}

# 泛化动作词的降权系数：在分类退化打分中，命中泛化词只按 1/4 计分。
# 用「降权」而非「剔除」——剔除会让纯泛化词输入（如"处理一下这个需求"）
# 连候选都产不出，直接掉进默认兜底，比错误分类更难排查。
GENERIC_TOKEN_WEIGHT = 0.25

# 置信度低于此值时，调用方（SKILL.md / 工作流）应提示澄清或升级判断，
# 而不是把分类结果当定论使用。
LOW_CONFIDENCE_THRESHOLD = 0.5


@lru_cache(maxsize=1)
def _category_descriptions():
    """读取 config/categories.json 的 description 作为类目语义画像。

    当前只有部分类目有 description；缺失时返回空串，不报错。
    以后补齐 32 类后，无需改代码即可参与词元层打分。
    """
    path = os.path.join(CONFIG_DIR, "categories.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return {
        key: (value or {}).get("description", "")
        for key, value in data.items()
        if isinstance(value, dict)
    }


def _category_affinity_score(task_tokens, keywords, stop_weight=None, description=""):
    """单分类的亲和度打分（0~1）。泛化词按 stop_weight 降权计分。

    与 `_keyword_score` 的区别：本函数只服务**分类**（task_tokens 对分类
    关键词表），`_keyword_score` 服务**专家选型**（对专家名称/描述/提示词）。
    两者的分词与降权口径保持一致，避免同一份词在不同的路由层得到相反结论。
    """
    if stop_weight is None:
        stop_weight = GENERIC_TOKEN_WEIGHT
    if not task_tokens:
        return 0.0

    kw_tokens = _tokenize(" ".join(keywords) + " " + (description or ""))
    if not kw_tokens:
        return 0.0

    hits = task_tokens & kw_tokens
    if not hits:
        return 0.0

    # 命中泛化词的按降权系数计，命中领域词的按 1.0 计
    weighted = sum(
        stop_weight if token in STOP_TOKENS else 1.0 for token in hits
    )
    return weighted / float(len(task_tokens))


def _load_prompt_head(expert, limit=800):
    """读取专家提示词文件开头部分，用于在无模型时提供更丰富的领域词。

    800 字上限是刻意的：旧实现读 3000 字，prompt_hits 事实上压过 name，
    导致“描述写得长”的专家占绝对便宜。
    """
    filename = expert.get("file")
    if not filename:
        return ""
    path = os.path.join(AGENTS_DIR, filename)
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read(limit)
    except (OSError, UnicodeDecodeError):
        return ""


@lru_cache(maxsize=1)
def _expert_token_stats():
    """331 位专家语料的 token 文档频率（df）与总数。

    只读一次并缓存；df 用来过滤“专家/测试/评估”这类高 df 噪声，
    避免它们靠 name 的 3 倍权重或长 prompt 决定专家排序。
    """
    df = Counter()
    experts = load_experts() or []
    for expert in experts:
        tokens = (
            _tokenize(expert.get("name", ""))
            | _tokenize(expert.get("description", ""))
            | _tokenize(_load_prompt_head(expert))
        )
        df.update(tokens)
    return df, len(experts)


LOW_INFO_TOKENS = {"专家"}
ROUTER_META_LOW_INFO = {"专家", "测试", "评估", "审计", "审查", "分析", "操作"}
ROUTER_META_TOKEN_HINTS = ("路由", "分类", "误判", "专家", "准确", "词面", "词元")
INSTALL_META_HINTS = ("安装", "注册", "插件")


def _is_low_information(token, task_tokens):
    """低区分度 token：不参与专家排序，避免“专家/测试/评估”噪声决胜。"""
    if token in LOW_INFO_TOKENS:
        return True
    if token in ROUTER_META_LOW_INFO and any(
            h in task_tokens for h in ROUTER_META_TOKEN_HINTS):
        return True
    # 安装/注册语境下，「审计/操作」是顺带动作，不是财务/安全域证据。
    if token in {"审计", "操作"} and any(
            h in task_tokens for h in INSTALL_META_HINTS):
        return True
    return False


def _filtered_hits(effective, field_tokens, task_tokens):
    return {
        t for t in effective & field_tokens
        if not _is_low_information(t, task_tokens)
    }


def _token_idf(token):
    df, total = _expert_token_stats()
    if total <= 0:
        return 0.0
    return math.log(1.0 + total / float(1 + df.get(token, 0)))


def _keyword_score_raw(task_tokens, expert):
    """任务词元与专家名称/描述/提示词的重叠原始分（可 > 1.0）。

    **仅用于排序与决胜**：raw 分保留了「命中几个字段」的区分度，
    name/desc/prompt 三项全中时理论值可达 1.667。

    为什么需要它：如果排序也用截顶后的值，raw=1.667 与 raw=1.333 会双双
    变成 1.0 被判为并列，稳定排序退回候选声明序——实测「翻译」会因此
    选中 raw 更低的「语言翻译专家」而不是「技术翻译专家」。
    """
    effective = {t for t in task_tokens if t not in STOP_TOKENS}
    if not effective:
        effective = task_tokens
    if not effective:
        return 0.0
    total = len(effective)
    name_hits = _filtered_hits(
        effective, _tokenize(expert.get("name", "")), task_tokens)
    desc_hits = _filtered_hits(
        effective, _tokenize(expert.get("description", "")), task_tokens)
    prompt_hits = _filtered_hits(
        effective, _tokenize(_load_prompt_head(expert)), task_tokens)
    return (
        3.0 * len(name_hits) + 1.0 * len(desc_hits) + 1.0 * len(prompt_hits)
    ) / float(3.0 * total)


def _keyword_score(task_tokens, expert):
    """任务词元与专家名称/描述/提示词的重叠打分（0~1，对外契约）。

    权重设计：名称命中 3 倍、描述与提示词命中各 1 倍。
    名称是专家身份的浓缩；描述与提示词提供领域词覆盖，
    但不该让"描述写得长"的专家占绝对便宜，故低于名称权重。

    归一化说明：raw 上限是 (3+1+1)/3 ≈ 1.667，会突破文档声称的 0~1 值域。
    对外用 min(1.0, ...) 截顶保证分数可比、可供阈值判断；
    **排序与决胜必须用 `_keyword_score_raw`**，否则会抹掉区分度。
    """
    return min(1.0, _keyword_score_raw(task_tokens, expert))


def embedding_coarse_screen(task_description, candidates, top_n=5):
    """
    第二层：Embedding 粗筛
    返回：top_n 个候选专家

    优先使用 Embedding 向量相似度；服务不可用时退化为词元重叠打分
    （而非直接截取前 N 个）。若打分全为 0 且分类内专家数 <= top_n，全部返回。
    """
    if not candidates:
        return []

    try:
        from embedding_client import get_embedding, compute_similarity
        task_emb = get_embedding(task_description)
        if task_emb:
            scored = []
            for expert in candidates:
                expert_text = f"{expert.get('name', '')} {expert.get('description', '')} {expert.get('category', '')}"
                emb = get_embedding(expert_text)
                if emb:
                    score = compute_similarity(task_emb, emb)
                    scored.append((score, expert))
            if scored:
                scored.sort(key=lambda x: x[0], reverse=True)
                return [e for _, e in scored[:top_n]]
    except Exception:
        pass

    # 退化：词元重叠打分排序（用 raw 分，保留区分度；截顶会把不同档压成并列）
    task_tokens = _tokenize(task_description)
    scored = sorted(
        candidates,
        key=lambda e: _keyword_score_raw(task_tokens, e),
        reverse=True,
    )
    return scored[:top_n]


def llm_verdict(task_description, top_candidates, return_basis=False):
    """
    第三层：语义精判

    参数:
        return_basis (bool): 为 True 时返回 (expert, basis)，
            basis 取 "semantic"（LLM 真的判过）或 "heuristic"（词元计数兜底）。

    返回：
        默认 —— selected_expert (dict) 或 None
        return_basis=True —— (selected_expert, basis)

    **关于 basis 的设计意图（重要）**：
    `_call_llm` 恒返回 None 是刻意设计——本插件依赖宿主会话正在使用的模型，
    不额外配置 LLM 服务。但 SKILL.md 承诺的「LLM 精判」在无模型时**并没有
    真正发生**：这里的兜底只是「描述里出现过哪两个字」的词元计数，不是语义
    判断。实测「实现用户登录接口」会选中「飞书集成开发工程师」，仅因其
    描述含「登录」二字，而「后端架构师」描述写的是「API 开发」——词不同不命中。

    因此 basis="heuristic" 时，调用方（主控 AI）**必须自己重新做语义判断**，
    不能把本函数的返回值当作已完成的精判结果。
    """
    if not top_candidates:
        return (None, "heuristic") if return_basis else None

    try:
        selected_id = select_expert_with_llm(task_description, top_candidates)
        if selected_id:
            for expert in top_candidates:
                if expert.get("id") == selected_id:
                    return (expert, "semantic") if return_basis else expert
    except Exception:
        pass

    # 退化：按词元重叠打分选最优（用 raw 分决胜，避免截顶把不同档压成并列）
    task_tokens = _tokenize(task_description)
    scored = [(_keyword_score_raw(task_tokens, e), idx, e) for idx, e in enumerate(top_candidates)]
    best_score = max(s for s, _, _ in scored)

    # 全无相关性：不盲选
    if best_score <= 0.0:
        return (None, "heuristic") if return_basis else None

    # 退化为精确相等比较：得分是浮点数，ratio 归一后才比较。
    # 判平标记（P4，2026-11-23）：`best_score` 若只由一个候选独占，主控可以信
    # 「分最高」；若多个候选并列，最终选择退化为「取候选顺序最靠前者」，
    # 那一票没有任何语义依据。旧实现不暴露这个区别——主控看到 0.1667
    # 无法判断是「唯一最高」还是「并列取首」。
    # 实测：任务「审查并验证…插件…」两候选都是 0.1667，name_hits 分别为 1 和 2，
    # 按顺序取了 name_hits=1 的那个。这里在候选上打 tied 标记，并在
    # score_breakdown 里带出 tied_count，让复核者一眼看出该不该改判。
    tied = [e for score, _idx, e in scored if score == best_score]
    tied_count = len(tied)
    for score, _idx, expert in scored:
        expert["tied"] = (score == best_score and tied_count > 1)

    # 同分时取候选顺序最靠前者（稳定决胜，结果与输入顺序一致而非随机）
    for score, _idx, expert in scored:
        if score == best_score:
            return (expert, "heuristic") if return_basis else expert
    return (None, "heuristic") if return_basis else None


def score_breakdown(task_description, expert):
    """专家打分明细：名称/描述/提示词各自命中多少个任务词元。

    主控做语义精判时靠这个明细判断 Python 的排序是否可信——
    例如「飞书集成开发工程师 desc_hits=1 命中『登录』」一眼就能看出是词面巧合。

    tied（P4）：该候选是否与首名**并列最高分**。True 时最终选择退化为
    「取候选顺序最靠前者」，那一票没有语义依据——必须按业务语义改判，
    不能因为「它在第一位」就采信。
    """
    task_tokens = _tokenize(task_description)
    effective = {t for t in task_tokens if t not in STOP_TOKENS} or task_tokens
    name_hits = _filtered_hits(
        effective, _tokenize(expert.get("name", "")), task_tokens)
    desc_hits = _filtered_hits(
        effective, _tokenize(expert.get("description", "")), task_tokens)
    prompt_hits = _filtered_hits(
        effective, _tokenize(_load_prompt_head(expert)), task_tokens)
    return {
        "name_hits": len(name_hits),
        "desc_hits": len(desc_hits),
        "prompt_hits": len(prompt_hits),
        "name_idf": round(sum(_token_idf(t) for t in name_hits), 4),
        "desc_idf": round(sum(_token_idf(t) for t in desc_hits), 4),
        "prompt_idf": round(sum(_token_idf(t) for t in prompt_hits), 4),
        "filtered_low_info": sorted(
            (effective & (
                _tokenize(expert.get("name", ""))
                | _tokenize(expert.get("description", ""))
                | _tokenize(_load_prompt_head(expert))
            )) - (name_hits | desc_hits | prompt_hits)
        ),
        "matched_in_name": sorted(name_hits),
        "matched_in_desc": sorted(desc_hits),
        "raw_score": round(_keyword_score_raw(task_tokens, expert), 4),
        "tied": bool(expert.get("tied", False)),
    }


def build_dispatch_for_expert(expert_name, task_description, context_summary="", role_prefix=""):
    """按主控指定的专家名生成派发单（语义判断权在主控）。

    主控做语义精判后，用本函数直接按自己的判断生成派发单，
    不再受 Python 启发式排序的约束。

    role_prefix（I3，enforce-domain-routing）：主控改判派发时拼在
    dispatch.prompt **首段**的角色契约前缀（如 _role_contract_prefix("analyst")
    的产物）——改判路径不丢角色契约；默认空串保持既有行为（prompt=任务
    原文，一字不差）。

    专家名不存在时抛 ValueError——静默降级会让主控误以为派发成功。
    """
    all_experts = load_experts()
    target = None
    for e in all_experts:
        if e.get("name") == expert_name:
            target = e
            break
    if target is None:
        # N-04：给出近似专家名建议，降低主控排查成本（如「后端架构市」→「后端架构师」）。
        # 仍抛 ValueError 不静默降级——建议只是错误信息的一部分。
        import difflib
        names = [e.get("name") for e in all_experts if e.get("name")]
        close = difflib.get_close_matches(expert_name or "", names, n=3, cutoff=0.5)
        hint = ("；最接近的是：%s" % "、".join(close)) if close else ""
        raise ValueError(
            "未找到专家：%r%s。可用 zcode_expert_system.load_experts() 查看全部 %d 位专家名。"
            % (expert_name, hint, len(names)))
    return dispatch_expert(target, task_description, context_summary,
                           role_prefix=role_prefix)


def dispatch_manager(category, task_description, selected_expert, top_candidates):
    """
    派发领域总经理
    返回：manager_result (dict)
    """
    from datetime import datetime

    manager_id = get_manager(category)
    category_experts = get_experts_by_category(category)

    manager_result = {
        "agent": manager_id,
        "display_name": manager_id,
        "display_label": f"经理：{manager_id}",
        "category": category,
        # L1 修复：无专家时 status 为 no_expert（与 expert_result.skipped 对齐），
        # 有专家时才为 dispatched/plan_ready。避免消费方误判总经理派发成功。
        "status": "dispatched" if selected_expert else "no_expert",
        "plan": [],
        "assigned_expert": selected_expert,
        "candidates": top_candidates,
        "dispatched_at": datetime.now().isoformat(),
        "available_experts_count": len(category_experts),
    }

    if selected_expert:
        manager_result["plan"] = [
            {
                "step": 1,
                "description": task_description,
                "expert_id": selected_expert.get("id"),
                "expert_name": selected_expert.get("name"),
                "expert_file": selected_expert.get("file"),
                "target": f"使用 {selected_expert.get('name')} 的专业能力完成任务",
            }
        ]
        manager_result["status"] = "plan_ready"

    return manager_result


def _qualified_subagent_type(expert_name):
    """按运行平台决定子代理派发名。

    Claude Code 要求 <插件名>:<frontmatter.name> 的限定形式；
    ZCode 使用中文裸名。用 CLAUDE_PLUGIN_ROOT 是否注入作判据。
    """
    if os.environ.get("CLAUDE_PLUGIN_ROOT"):
        return "zcode-expert-system:%s" % expert_name
    return expert_name


def dispatch_expert(selected_expert, task_description, context_summary="", role_prefix=""):
    """
    生成专家派发指令（本模块不直接调用 Agent 工具）。

    Python 进程无法直接调用 ZCode 的 Agent 工具，因此这里返回一份
    **可执行的派发单**：调用方（主控 AI）按 `dispatch.subagent_type`
    用 Agent 工具真正派发。status 明确为 "pending_dispatch"，避免
    消费方误以为已经派发完成。

    331 位专家均已注册为 ZCode 子代理，subagent_type 即专家中文名。

    role_prefix（I3，enforce-domain-routing）：非空时拼在 prompt 首段
    （契约文本自带结尾换行）——主控改判路径不丢角色契约；默认空串
    保持既有行为。
    """
    from datetime import datetime

    if not selected_expert:
        return {
            "agent": "expert-unknown",
            "status": "skipped",
            "reason": "no expert selected",
        }

    expert_name = selected_expert.get("name")
    prompt = task_description
    if context_summary:
        prompt = f"{task_description}\n\n【前序上下文】\n{context_summary}"
    if role_prefix:
        prompt = f"{role_prefix}{prompt}"

    display_label = f"专家：{expert_name}"
    return {
        "agent": selected_expert.get("id", "expert-unknown"),
        "expert_name": expert_name,
        # 宿主 UI 直接用这个字段展示专家身份；不要只显示 "Agent"。
        "display_name": expert_name,
        "display_label": display_label,
        "expert_category": selected_expert.get("category"),
        "expert_file": selected_expert.get("file"),
        # pending_dispatch：等待主控用 Agent 工具实际派发
        "status": "pending_dispatch",
        "dispatch": {
            "tool": "Agent",
            "subagent_type": _qualified_subagent_type(expert_name),
            # Agent/Task 的可见标题优先显示专家名。
            "description": display_label,
            "prompt": prompt,
        },
        "fallback": (
            f"若子代理清单中无「{expert_name}」，"
            f"则读取 agents/{selected_expert.get('file')} 的提示词，代入该专家人格直接执行"
        ),
        "task_description": task_description,
        "context_summary": context_summary,
        "dispatched_at": datetime.now().isoformat(),
    }


def build_context(task_id, category, manager_id, top_candidates, selected_expert, manager_result, expert_result, persist=True):
    """
    构建上下文
    返回：context (dict)

    persist（I2，enforce-domain-routing）：True（默认）保持既有行为——
    尝试把 context 落盘 result-*.json；False 跳过持久化（readonly 分析
    不写上下文），context 结构照常返回（调用方返回结构不变）。
    """
    from datetime import datetime

    context = {
        # N-06：task_id 精度由秒级提升到微秒级（%f），与 context-manager.py
        # 的 result 文件名口径（%Y%m%d-%H%M%S%f）一致。秒级下同一秒内两次
        # 独立调用生成相同 task_id，导致 _load_context_summary 按 task_id
        # 回填时，第二个任务读到第一个任务的历史摘要并注入派发单。
        "task_id": task_id or f"task-{datetime.now().strftime('%Y%m%d-%H%M%S%f')}",
        "category": category,
        "manager_id": manager_id,
        "top_candidates": top_candidates,
        "selected_expert": selected_expert,
        "manager_result": manager_result,
        "expert_result": expert_result,
        "created_at": datetime.now().isoformat(),
    }

    # 尝试持久化（I2：persist=False 时整体跳过——readonly 不写 result-*.json）
    if persist:
        try:
            import importlib.util
            context_module_path = os.path.join(CONTEXT_DIR, "context-manager.py")
            if os.path.isfile(context_module_path):
                spec = importlib.util.spec_from_file_location("context_manager", context_module_path)
                context_manager_module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(context_manager_module)
                ExpertContext = context_manager_module.ExpertContext
                ctx = ExpertContext()
                ctx.save_context(context["task_id"], selected_expert.get("id", "none") if selected_expert else "none", context)
        except Exception as exc:
            context["context_persist_warning"] = str(exc)

    return context


def _load_context_summary(task_id):
    """取某任务的历史摘要，供派发时注入【前序上下文】。

    上下文存储是可选组件：context-manager.py 缺失或加载失败时返回空串，
    路由照常工作（不能因为历史摘要读不到就让整条路由失败）。
    """
    if not task_id:
        return ""
    try:
        import importlib.util
        cm_path = os.path.join(CONTEXT_DIR, "context-manager.py")
        if not os.path.isfile(cm_path):
            return ""
        spec = importlib.util.spec_from_file_location("context_manager", cm_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        ctx = module.ExpertContext()
        return ctx.get_context_summary(task_id) or ""
    except Exception:
        return ""


def zcode_expert_system(task_description, task_id=None, persist=True):
    """
    主入口：执行完整路由流程

    参数:
        task_description (str): 待执行的任务描述
        task_id (str, optional): 会话内任务标识。传入时会在派发专家前
            从上下文存储取回该任务的历史摘要，作为 context_summary 注入
            派发单；不传则退化为一次性路由（无前序上下文）。
        persist (bool, optional): True（默认）保持既有行为——路由结果
            落盘 result-*.json；False 跳过持久化（I2，enforce-domain-routing：
            readonly 分析不写上下文），其余返回结构不变。

    返回:
        dict: 包含 category, confidence, confidence_detail, alternatives,
              manager_id, selected_expert, manager_result, expert_result, context

    confidence < LOW_CONFIDENCE_THRESHOLD 时，调用方（SKILL.md 路由层）
    应先向老板澄清任务领域，而不是直接采信分类结果派专家。
    """
    if not task_description:
        task_description = ""

    # 第一层：任务分类（带置信度、备选与证据明细）
    category, confidence, alternatives, confidence_detail = (
        classify_task_with_evidence(task_description)
    )

    # 获取对应的领域总经理
    manager_id = get_manager(category)

    # 获取该分类下的所有专家
    candidates = get_experts_by_category(category)

# 分类完全无信号时，不再往下挑专家。
    # 理由：conf=0 说明任务描述与 32 个分类毫无匹配，此时在 DEFAULT_CATEGORY
    # 里挑专家只能靠泛化词的微小词元重叠（实测「写个季度汇报」会选中
    # 旅行规划师，score=0.067），属于纯粹的数字巧合，不是相关性判断。
    # 此时返回 selected_expert=None，由调用方按 routing_warning 去澄清。
    if confidence <= 0.0:
        top_candidates = []
        selected_expert = None
        selection_basis = "none"
    else:
        # 第二层：粗筛（Embedding 可用则用向量，否则词元重叠）
        top_candidates = embedding_coarse_screen(task_description, candidates, top_n=5)
        # 第三层：语义精判 —— basis 告诉我们精判是否真的发生
        selected_expert, selection_basis = llm_verdict(
            task_description, top_candidates, return_basis=True)

        # 给每个候选补上评分明细，供主控审核 Python 的选择是否可信
        _task_tokens_for_score = _tokenize(task_description)
        for e in top_candidates:
            e["score"] = round(_keyword_score(_task_tokens_for_score, e), 4)
            e["score_detail"] = score_breakdown(task_description, e)

    # H2 修复：分类置信度 >0 但无匹配专家时，显式暴露矛盾，避免满分置信度误导消费方。
    # 仅当 confidence>0 且 selected_expert is None 时置 no_expert=True，并把 confidence
    # 降为 0.0（与 conf=0 的「无信号」语义对齐），同时 semantic_selection_required
    # 仍为 True（LLM 不可用时精判仍待主控）。这样消费方按 conf 判断不会误判满分。
    no_expert = False
    if confidence > 0.0 and selected_expert is None:
        no_expert = True
        confidence = 0.0

    # 语义精判是否仍待主控完成：LLM 不可用时 Python 的挑选只是词元计数，
    # 不是语义判断。必须显式暴露，否则主控会直接采信错误结果。
    semantic_selection_required = (selection_basis != "semantic") and bool(top_candidates)

    # 派发领域总经理
    manager_result = dispatch_manager(
        category=category,
        task_description=task_description,
        selected_expert=selected_expert,
        top_candidates=top_candidates,
    )

    # 派发专家执行
    #
    # context_summary 唯一来源是上下文存储（_load_context_summary → 磁盘
    # result-*.json 回填，见 context-manager.py get_context_summary）。
    # dispatch_manager 从不写 context_summary 键——旧实现这里的
    # manager_result.get(...) 兜底恒空串，属死代码，随接线复活一并删除
    # （P8 批次四 Task 14）：保留它会让读者误以为存在第二数据源。
    context_summary = _load_context_summary(task_id)
    expert_result = dispatch_expert(
        selected_expert=selected_expert,
        task_description=task_description,
        context_summary=context_summary,
    )

    # 构建上下文（带上 task_id，使历史摘要可按任务归属存储）
    context = build_context(
        task_id=task_id,
        category=category,
        manager_id=manager_id,
        top_candidates=top_candidates,
        selected_expert=selected_expert,
        manager_result=manager_result,
        expert_result=expert_result,
        persist=persist,
    )

    # 路由告警：两个独立触发条件，不可只判置信度
    #
    # ① selected_expert 为 None —— 无论 confidence 多高都必须告警。
    #    实测「编译报错」返回较高 confidence（关键词「报错」命中 devops）但
    #    该分类下没有匹配专家 → selected_expert=None。若只按 conf<0.5 判，
    #    调用方看到 1.0 会直接按 selected_expert 派发，拿到 None 后无规则可依，
    #    属静默失效。
    # ② confidence 低于阈值 —— 分类本身可能错，建议先澄清领域。
    routing_warning = None
    warnings = []
    if semantic_selection_required:
        warnings.append(
            "语义精判待完成：本插件不额外配置 LLM 服务（依赖会话模型），"
            "Python 侧的专家挑选只是「描述里出现过哪两个字」的词元计数，"
            "不是语义判断。主控必须自己复核 top_candidates 的 score_detail，"
            "按业务语义定夺，或用 build_dispatch_for_expert(专家名) 覆盖此建议。"
        )
    if selected_expert is None:
        warnings.append(
            "无可用专家：分类「%s」下未能选出匹配专家"
            "（置信度 %.3f）。请向老板澄清任务领域，或指定专家类别后重试。"
            % (category, confidence)
        )
    if confidence < LOW_CONFIDENCE_THRESHOLD:
        warnings.append(
            "分类置信度 %.3f 低于阈值 %s；分类「%s」可能有误%s。"
            "建议先向老板澄清任务领域，再派发专家。"
            % (confidence, LOW_CONFIDENCE_THRESHOLD, category,
               ("，备选：" + "、".join(alternatives)) if alternatives else "")
        )
    # P4：判平必须说出口——同分时 selected_expert 只是「候选顺序靠前者」，
    # 那一票没有语义依据。不说出来，主控会把并列当唯一最高直接采信。
    tied_names = [e.get("name") for e in top_candidates if e.get("tied")]
    if len(tied_names) > 1:
        warnings.append(
            "判平：最高分 %.4f 由 %d 位候选并列（%s），selected_expert 只是"
            "「候选顺序最靠前者」——这一票没有语义依据，必须按业务语义改判，"
            "不得因它在第一位而采信。"
            % (max([e.get("score") or 0 for e in top_candidates] or [0]),
               len(tied_names), "、".join(n for n in tied_names if n))
        )
    if warnings:
        routing_warning = " ".join(warnings)

    return {
        "category": category,
        "confidence": confidence,
        "confidence_detail": confidence_detail,
        "alternatives": alternatives,
        "routing_warning": routing_warning,
        # H2 修复标记：分类置信度>0 但无匹配专家时置 True，消费方据此不得按 conf 直接派发
        "no_expert": no_expert,
        # 判平标记（P4）：最高分是否由多个候选并列——True 时 selected_expert
        # 的取胜依据是「候选顺序」而非分值，主控必须改判或明示采信理由。
        # 的取胜依据是「候选顺序」而非分值，主控必须改判或明示采信理由。
        "score_tied": len([e for e in top_candidates if e.get("tied")]) > 1,
        # 语义精判是否仍待主控完成（True 时不得直接采信 selected_expert）
        "semantic_selection_required": semantic_selection_required,
        # 本次选择的依据：semantic=模型判过 / heuristic=词元计数 / none=无候选
        "selection_basis": selection_basis,
        "manager_id": manager_id,
        "top_candidates": top_candidates,
        "selected_expert": selected_expert,
        "manager_result": manager_result,
        "expert_result": expert_result,
        "context": context,
    }


if __name__ == "__main__":
    # 缺陷 #3：CP936 终端下 emoji（config/experts.json 的 emoji 字段）会经
    # top_candidates 透出到 ensure_ascii=False 的 JSON，触发 UnicodeEncodeError。
    # 必须先重配 stdout 再做任何输出。逻辑与 zcode_dev_workflow.py 同名函数一致。
    _force_utf8_stdout()
    if len(sys.argv) > 1 and sys.argv[1] in ("--help", "-h"):
        print("用法：python zcode_expert_system.py [\"<任务描述>\"]")
        sys.exit(0)
    task = sys.argv[1] if len(sys.argv) > 1 else "设计一个支持高并发的后端 API 接口"
    result = zcode_expert_system(task)
    print(json.dumps(result, ensure_ascii=False, indent=2))