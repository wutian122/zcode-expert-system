#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Embedding 客户端：通过会话中正在使用的模型获取 Embedding 向量
"""

import json
import os

# 注意：本插件完全依赖会话中正在使用的模型，不额外配置 Embedding 服务。
# 如果需要直接调用外部 Embedding API，请在此处添加实现。
#
# 此处原有 `import requests`，但全文件从未使用，且仓库无
# requirements/setup.py/pyproject。危害不是「多一个包」：
# 调用方 `zcode_expert_system.py` 用 try/except 包住
# `from embedding_client import …`，环境缺 requests 时会被静默吞掉——
# 功能正确降级，但故障完全不可见。删掉它让「零三方依赖」成为真事实。

def get_embedding(text):
    """
    计算文本的 embedding
    返回：embedding 向量；未配置服务时返回 None（降级）
    """
    # 注意：本插件完全依赖会话中正在使用的模型，不额外配置 Embedding 服务。
    # 如果需要直接调用外部 Embedding API，请在此处添加实现。
    return None


def compute_similarity(embedding1, embedding2):
    """计算两个 embedding 的余弦相似度"""
    if not embedding1 or not embedding2:
        return 0.0
    dot_product = sum(a * b for a, b in zip(embedding1, embedding2))
    norm1 = sum(a * a for a in embedding1) ** 0.5
    norm2 = sum(b * b for b in embedding2) ** 0.5
    if norm1 == 0 or norm2 == 0:
        return 0.0
    return dot_product / (norm1 * norm2)


if __name__ == "__main__":
    # 测试
    emb = get_embedding("测试")
    print("Embedding dimension:", len(emb) if emb else "None")