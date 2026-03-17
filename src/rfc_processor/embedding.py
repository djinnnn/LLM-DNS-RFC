from __future__ import annotations

import json
import os
from typing import Dict, Any, List, Tuple

import numpy as np
import networkx as nx
from sentence_transformers import SentenceTransformer


class SectionEmbeddingIndexer:
    """
    负责：
    1. 为 Section 节点分配 embedding_id
    2. 构造 embedding 文本
    3. 离线计算并缓存归一化向量
    4. 导出到 .npy + .json
    """

    def __init__(
        self,
        model_name: str = "BAAI/bge-large-en-v1.5",
        vector_dir: str = "../../RFCs/vector_store/"
    ):
        self.model_name = model_name
        self.vector_dir = vector_dir
        os.makedirs(self.vector_dir, exist_ok=True)

        self.model = SentenceTransformer(model_name)

        self.matrix_path = os.path.join(self.vector_dir, "section_embeddings.npy")
        self.index_path = os.path.join(self.vector_dir, "section_embedding_index.json")

        self.embedding_ids: List[str] = []
        self.embedding_texts: List[str] = []
        self.id_to_row: Dict[str, int] = {}

    def prepare_subgraph(self, subgraph: nx.DiGraph) -> None:
        """
        为子图中的 Section 节点补 embedding_id，并登记待编码文本。
        注意：这里只做登记，不立即落盘。
        """
        print("========[DEBUG prepare]============")
        for node_id, node_data in subgraph.nodes(data=True):
            if node_data.get("node_type") != "Section":
                continue

            embedding_id = node_data.get("embedding_id") or node_id
            subgraph.nodes[node_id]["embedding_id"] = embedding_id

            print("[DEBUG prepare]", node_id, "->", subgraph.nodes[node_id].get("embedding_id"))
            #break

            if embedding_id in self.id_to_row:
                continue

            text = self._build_section_embedding_text(node_data)
            if not text:
                continue

            self.id_to_row[embedding_id] = len(self.embedding_ids)
            self.embedding_ids.append(embedding_id)
            self.embedding_texts.append(text)

    def finalize(self) -> None:
        """
        批量计算所有登记的 section embeddings，并导出存储。
        """
        if not self.embedding_texts:
            return

        embeddings = self.model.encode(
            self.embedding_texts,
            normalize_embeddings=True
        )
        matrix = np.asarray(embeddings, dtype=np.float32)

        np.save(self.matrix_path, matrix)

        with open(self.index_path, "w", encoding="utf-8") as f:
            json.dump(self.id_to_row, f, ensure_ascii=False, indent=2)

    def _build_section_embedding_text(self, node_data: Dict[str, Any]) -> str:
        sec_num = node_data.get("sec_num", "") or ""
        title = node_data.get("title", "") or ""
        text = node_data.get("text", "") or ""

        parts: List[str] = []
        if sec_num:
            parts.append(f"Section {sec_num}")
        if title:
            parts.append(title)
        if text:
            parts.append(text)

        return "\n".join(parts).strip()