# -*- coding: utf-8 -*-
"""
带缓存的 ContextPack 构建器。
封装 Phase 1（图谱构建）+ Phase 2（ContextPack 组装）的缓存管理逻辑，
使 Pipeline 编排器不需要关心缓存细节。
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional, Tuple

import networkx as nx

from .orchestrator import RFCGraphOrchestrator
from .graph_knowledge_base import GraphKnowledgeBase
from .rag_router import GraphRAGRouter, SemanticRanker, SentenceTransformerQueryBackend
from .embedding_store import NumpyEmbeddingStore


class CachedContextBuilder:
    """
    Phase 1 & 2 统一入口：构建图谱 + 组装 ContextPack，自带缓存管理。

    缓存 key = rfc_id + max_depth + embedding_model，
    缓存文件存在 vector_store/cache_*.json。
    """

    def __init__(
        self,
        rfc_save_dir: str,
        max_depth: int = 1,
        embedding_model: str = "BAAI/bge-large-en-v1.5",
        enable_embeddings: bool = True,
        use_cache: bool = True,
        force_rebuild: bool = False,
        cache_dir: Optional[str] = None,
    ) -> None:
        self.rfc_save_dir = rfc_save_dir
        self.max_depth = max_depth
        self.embedding_model = embedding_model
        self.enable_embeddings = enable_embeddings
        self.use_cache = use_cache
        self.force_rebuild = force_rebuild
        self.cache_dir = cache_dir or os.path.join(rfc_save_dir, "vector_store")

    def build(self, rfc_id: str, seed_section_id: str) -> Tuple[Dict[str, Any], List[str]]:
        """
        构建 ContextPack，优先使用缓存。
        返回 (context_pack, trace_lines)。
        """
        os.makedirs(self.cache_dir, exist_ok=True)

        cache_key = f"{rfc_id}_d{self.max_depth}_{self.embedding_model.replace('/', '_')}"
        cache_file = os.path.join(self.cache_dir, f"cache_{cache_key}.json")

        vector_dir = os.path.join(self.rfc_save_dir, "vector_store")
        npy_path = os.path.join(vector_dir, "section_embeddings.npy")
        index_path = os.path.join(vector_dir, "section_embedding_index.json")

        # ── 尝试使用缓存 ─────────────────────────────────────────
        if self.use_cache and not self.force_rebuild and os.path.exists(cache_file):
            result = self._try_load_cache(cache_file, npy_path, index_path, seed_section_id)
            if result is not None:
                return result

        # ── 正常构建流程 ─────────────────────────────────────────
        orchestrator = RFCGraphOrchestrator(
            max_depth=self.max_depth,
            save_dir=self.rfc_save_dir,
            enable_embeddings=self.enable_embeddings,
            vector_dir=vector_dir,
        )
        graph = orchestrator.fetch_and_build(rfc_id)
        kb = GraphKnowledgeBase(graph)

        ranker = self._build_ranker(npy_path, index_path)
        context_pack = GraphRAGRouter(kb, ranker).build_context_pack(seed_section_id)

        # ── 保存缓存 ─────────────────────────────────────────────
        self._save_cache(cache_file, cache_key, graph, rfc_id, npy_path, index_path)

        trace = [
            f"[Phase1] 图谱构建完成  nodes={graph.number_of_nodes()}  edges={graph.number_of_edges()}",
            "[Phase2] ContextPack 组装完成",
        ]
        return context_pack, trace

    # ─── 内部方法 ─────────────────────────────────────────────

    def _try_load_cache(
        self,
        cache_file: str,
        npy_path: str,
        index_path: str,
        seed_section_id: str,
    ) -> Optional[Tuple[Dict[str, Any], List[str]]]:
        """尝试从缓存加载图谱并构建 ContextPack。成功返回结果，失败返回 None。"""
        try:
            with open(cache_file, "r") as f:
                cache_meta = json.load(f)

            # 验证缓存完整性：embedding 文件必须存在
            if not (os.path.exists(npy_path) and os.path.exists(index_path)):
                return None

            graph_path = cache_meta.get("graph_path")
            if not (graph_path and os.path.exists(graph_path)):
                return None

            graph = nx.read_graphml(graph_path)
            kb = GraphKnowledgeBase(graph)

            ranker = self._build_ranker(npy_path, index_path) if self.enable_embeddings else None
            context_pack = GraphRAGRouter(kb, ranker).build_context_pack(seed_section_id)

            trace = [
                f"[Phase1] 从缓存加载图谱  nodes={graph.number_of_nodes()}  edges={graph.number_of_edges()}",
                "[Phase2] ContextPack 组装完成（使用缓存）",
            ]
            return context_pack, trace
        except Exception:
            return None

    def _build_ranker(self, npy_path: str, index_path: str) -> Optional[SemanticRanker]:
        """构建语义排序器（如果 embedding 文件存在）。"""
        if not (os.path.exists(npy_path) and os.path.exists(index_path)):
            return None
        return SemanticRanker(
            query_backend=SentenceTransformerQueryBackend(self.embedding_model),
            embedding_store=NumpyEmbeddingStore(npy_path=npy_path, index_path=index_path),
            min_score=-1.0,
        )

    def _save_cache(
        self,
        cache_file: str,
        cache_key: str,
        graph: nx.DiGraph,
        rfc_id: str,
        npy_path: str,
        index_path: str,
    ) -> None:
        """保存图谱和缓存元信息。失败不影响主流程。"""
        if not self.use_cache:
            return
        try:
            graph_path = os.path.join(self.cache_dir, f"graph_{cache_key}.graphml")
            nx.write_graphml(graph, graph_path)

            cache_meta = {
                "rfc_id": rfc_id,
                "max_depth": self.max_depth,
                "embedding_model": self.embedding_model,
                "graph_path": graph_path,
                "npy_path": npy_path,
                "index_path": index_path,
            }
            with open(cache_file, "w") as f:
                json.dump(cache_meta, f, indent=2)
        except Exception:
            # 缓存保存失败不影响主流程
            pass
