# -*- coding: utf-8 -*-
"""
RFC Processor 模块 (Phase 1 & 2)。
Phase 1: RFC 图谱构建 — 下载、解析 RFC，构建 NetworkX 有向图。
Phase 2: ContextPack 组装 — 围绕 seed section 做本地结构提取、引用路由、语义扩展。
"""
from .orchestrator import RFCGraphOrchestrator
from .graph_knowledge_base import GraphKnowledgeBase
from .rag_router import GraphRAGRouter, SemanticRanker, SentenceTransformerQueryBackend
from .embedding_store import NumpyEmbeddingStore

__all__ = [
    "RFCGraphOrchestrator",
    "GraphKnowledgeBase",
    "GraphRAGRouter",
    "SemanticRanker",
    "SentenceTransformerQueryBackend",
    "NumpyEmbeddingStore",
]
