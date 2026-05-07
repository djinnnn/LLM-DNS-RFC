from typing import Dict, Any, List, Set, Optional
from .graph_knowledge_base import GraphKnowledgeBase
import numpy as np
from sentence_transformers import SentenceTransformer


class SentenceTransformerQueryBackend:
    def __init__(self, model_name: str = "BAAI/bge-large-en-v1.5"):
        self.model = SentenceTransformer(model_name)

    def encode_query(self, text: str) -> np.ndarray:
        text = (text or "").strip()
        query = f"Represent this RFC section for retrieval: {text}"
        vec = self.model.encode([query], normalize_embeddings=True)[0]
        return np.asarray(vec, dtype=np.float32)


class SemanticRanker:
    def __init__(
        self,
        query_backend: SentenceTransformerQueryBackend,
        embedding_store,
        min_score: float = -1.0
    ):
        self.query_backend = query_backend
        self.embedding_store = embedding_store
        self.min_score = min_score

    def rank(
        self,
        query_text: str,
        candidate_sections: List[Dict[str, Any]],
        top_k: int = 3
    ) -> List[Dict[str, Any]]:
        if not candidate_sections or top_k <= 0:
            return []

        query_vec = self.query_backend.encode_query(query_text)

        valid_sections = []
        embedding_ids = []

        for sec in candidate_sections:
            emb_id = sec.get("embedding_id") or sec.get("id")
            if not emb_id:
                continue
            valid_sections.append(sec)
            embedding_ids.append(emb_id)

        if not embedding_ids:
            return []

        valid_ids, matrix = self.embedding_store.get_many(embedding_ids)
        if len(valid_ids) == 0:
            return []

        id_to_section = {
            (sec.get("embedding_id") or sec.get("id")): sec
            for sec in valid_sections
        }

        scores = matrix @ query_vec
        ranked_indices = np.argsort(-scores)

        results = []
        for idx in ranked_indices:
            emb_id = valid_ids[idx]
            score = float(scores[idx])

            if score < self.min_score:
                continue

            results.append({
                "node": id_to_section[emb_id],
                "score": score
            })

            if len(results) >= top_k:
                break

        return results


class GraphRAGRouter:
    """
    围绕 seed section 构建 ContextPack。

    路由策略：
    1. 先抽取 local structure
    2. 再消费聚合引用
    3. 按 (normative / informative) × (section-level / document-level) 分类
    4. 对 document-level 引用执行候选筛选 + 语义排序
    """

    def __init__(self, kb: GraphKnowledgeBase, ranker: SemanticRanker):
        self.kb = kb
        self.ranker = ranker

    def build_context_pack(
        self,
        seed_node_id: str,
        normative_top_k_per_doc: int = 2,
        informative_top_k_per_doc: int = 1,
        enable_informative_expansion: bool = False
    ) -> Dict[str, Any]:
        context_pack = {
            "seed": {},
            "local_structure": {
                "ancestors": [],
                "descendants": []
            },
            "references": {
                "normative": {
                    "section_level": [],
                    "document_level": []
                },
                "informative": {
                    "section_level": [],
                    "document_level": []
                }
            },
            "semantic_expansion": [],
            "trace": []
        }

        # --------------------------------------------------
        # 1. Seed
        # --------------------------------------------------
        seed_data = self.kb.get_node_data(seed_node_id)
        if not seed_data:
            context_pack["trace"].append(f"[Error] 无法找到 Seed 节点: {seed_node_id}")
            return context_pack

        context_pack["seed"] = self._normalize_node(seed_node_id, seed_data)
        context_pack["trace"].append(f"[Seed] 锚定节点: {seed_node_id}")

        seed_text = seed_data.get("text", "") or ""

        # --------------------------------------------------
        # 2. Local structure
        # --------------------------------------------------
        ancestors = self.kb.get_ancestor_chain(seed_node_id) or []
        descendants = self.kb.get_descendants(seed_node_id) or []

        context_pack["local_structure"]["ancestors"] = ancestors
        context_pack["local_structure"]["descendants"] = descendants

        context_pack["trace"].append(
            f"[Local] 获取到 {len(ancestors)} 个父级作用域, {len(descendants)} 个直接子节点"
        )

        # --------------------------------------------------
        # 3. Aggregated references
        # --------------------------------------------------
        refs = self.kb.get_aggregated_references(seed_node_id) or {}
        # context_pack["trace"].append(f"[Refs Raw] {refs}")

        normalized_refs = self._normalize_aggregated_refs(refs)
        context_pack["trace"].append(
            f"[Refs] 归一化后引用数: {len(normalized_refs)}"
        )

        # --------------------------------------------------
        # 4. Route references
        # --------------------------------------------------
        section_seen: Set[str] = set()
        document_seen: Set[str] = set()
        semantic_seen: Set[str] = set()

        for ref in normalized_refs:
            bucket = self._classify_reference(ref)

            if bucket is None:
                context_pack["trace"].append(
                    f"[Weak] 忽略弱关联: target={ref.get('target_id')}, ref_type={ref.get('ref_type')}"
                )
                continue

            target_id = ref.get("target_id")
            target_node = ref.get("target_node", {})
            ref_type = ref.get("ref_type", "unknown")

            if bucket == "normative_section":
                dedup_key = target_id or target_node.get("section_id")
                if dedup_key and dedup_key not in section_seen:
                    section_seen.add(dedup_key)
                    context_pack["references"]["normative"]["section_level"].append({
                        "target_node": target_node,
                        "evidence": {"ref_type": ref_type}
                    })
                    context_pack["trace"].append(
                        f"[Normative/Section] 纳入显式 section 引用: {dedup_key}"
                    )

            elif bucket == "normative_document":
                if target_id and target_id not in document_seen:
                    document_seen.add(target_id)
                    context_pack["references"]["normative"]["document_level"].append({
                        "target_doc": target_node,
                        "evidence": {"ref_type": ref_type}
                    })
                    context_pack["trace"].append(
                        f"[Normative/Document] 纳入文档级引用: {target_id}"
                    )

                    self._expand_document_reference(
                        context_pack=context_pack,
                        seed_text=seed_text,
                        target_doc_id=target_id,
                        ref_type=ref_type,
                        top_k=normative_top_k_per_doc,
                        semantic_seen=semantic_seen
                    )

            elif bucket == "informative_section":
                dedup_key = target_id or target_node.get("section_id")
                if dedup_key and dedup_key not in section_seen:
                    section_seen.add(dedup_key)
                    context_pack["references"]["informative"]["section_level"].append({
                        "target_node": target_node,
                        "evidence": {"ref_type": ref_type}
                    })
                    context_pack["trace"].append(
                        f"[Informative/Section] 记录 section 引用: {dedup_key}"
                    )

            elif bucket == "informative_document":
                if target_id and target_id not in document_seen:
                    document_seen.add(target_id)
                    context_pack["references"]["informative"]["document_level"].append({
                        "target_doc": target_node,
                        "evidence": {"ref_type": ref_type}
                    })
                    context_pack["trace"].append(
                        f"[Informative/Document] 记录文档级引用: {target_id}"
                    )

                    if enable_informative_expansion:
                        self._expand_document_reference(
                            context_pack=context_pack,
                            seed_text=seed_text,
                            target_doc_id=target_id,
                            ref_type=ref_type,
                            top_k=informative_top_k_per_doc,
                            semantic_seen=semantic_seen
                        )

        return context_pack

    # ======================================================
    # Internal helpers
    # ======================================================
    def _expand_document_reference(
        self,
        context_pack: Dict[str, Any],
        seed_text: str,
        target_doc_id: str,
        ref_type: str,
        top_k: int,
        semantic_seen: Set[str]
    ) -> None:
        """
        对 document-level 引用执行：
        1. 规则筛选
        2. 语义排序
        3. 纳入 semantic_expansion
        """
        candidate_sections = self._filter_candidate_sections(target_doc_id)

        if not candidate_sections:
            context_pack["trace"].append(
                f"  -> [Expand] {target_doc_id} 无合法候选 section"
            )
            return

        context_pack["trace"].append(
            f"  -> [Expand] {target_doc_id} 候选 section 数: {len(candidate_sections)}"
        )

        ranked = self.ranker.rank(
            query_text=seed_text,
            candidate_sections=candidate_sections,
            top_k=top_k
        )

        if not ranked:
            context_pack["trace"].append(
                f"  -> [Expand] {target_doc_id} 语义排序结果为空"
            )
            return

        for item in ranked:
            node = item.get("node", {})
            score = item.get("score", 0.0)
            sec_id = node.get("id") or node.get("section_id")

            if not sec_id or sec_id in semantic_seen:
                continue

            semantic_seen.add(sec_id)

            context_pack["semantic_expansion"].append({
                "source_doc_id": target_doc_id,
                "retrieved_section": node,
                "score": score,
                "evidence": {"ref_type": ref_type}
            })

            context_pack["trace"].append(
                f"  -> [Semantic] 命中 {node.get('section_id', sec_id)}, score={score}"
            )

    def _filter_candidate_sections(self, target_doc_id: str) -> List[Dict[str, Any]]:
        """
        规则筛选 placeholder：
        从目标 RFC 文档中选出合法 Section 候选。
        """
        candidates: List[Dict[str, Any]] = []

        for node_id, node_data in self.kb.graph.nodes(data=True):
            if node_data.get("node_type") != "Section":
                continue
            if node_data.get("rfc_id") != target_doc_id:
                continue
            if not self.kb.is_valid_protocol_section(node_id):
                continue

            candidates.append(self._normalize_node(node_id, dict(node_data)))

        return candidates

    def _classify_reference(self, ref: Dict[str, Any]) -> Optional[str]:
        """
        将聚合引用分类为：
        - normative_section
        - normative_document
        - informative_section
        - informative_document
        - None (弱关联或忽略)
        """
        ref_type = ref.get("ref_type")
        target_kind = ref.get("target_kind")

        if ref_type in ("cites_normative", "cites_internal"):
            if target_kind == "Section":
                return "normative_section"
            if target_kind == "RFCDocument":
                return "normative_document"

        if ref_type == "cites_informative":
            if target_kind == "Section":
                return "informative_section"
            if target_kind == "RFCDocument":
                return "informative_document"

        return None

    def _normalize_aggregated_refs(self, refs: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        将当前 KB 的聚合引用结果归一化为统一格式。
        兼容当前已有输出：
        - internal
        - external_precise
        - external_coarse
        """
        normalized: List[Dict[str, Any]] = []

        for item in refs.get("internal", []):
            normalized.append({
                "target_kind": item.get("node_type"),
                "target_id": item.get("id") or item.get("section_id"),
                "target_node": dict(item),
                "ref_type": item.get("_reference_type", "cites_internal")
            })

        for item in refs.get("external_precise", []):
            normalized.append({
                "target_kind": item.get("node_type"),
                "target_id": item.get("id") or item.get("section_id"),
                "target_node": dict(item),
                "ref_type": item.get("_reference_type", "cites_normative")
            })

        for item in refs.get("external_coarse", []):
            normalized.append({
                "target_kind": item.get("node_type"),
                "target_id": item.get("rfc_id") or item.get("id"),
                "target_node": dict(item),
                "ref_type": item.get("_reference_type", "cites_unspecified")
            })

        return normalized

    def _normalize_node(self, node_id: str, node_data: Dict[str, Any]) -> Dict[str, Any]:
        normalized = dict(node_data)
        normalized["id"] = node_id
        return normalized