import os
import urllib.request
import urllib.error
import ssl
import networkx as nx
from collections import deque
from typing import Optional, Set

from rfc_parser import RFCGraphBuilder
from embedding import SectionEmbeddingIndexer

## v2修改：图融合+向量索引构建
class RFCGraphOrchestrator:
    """
    全局调度器：负责调度 RFC 的下载、解析，并执行基于广度优先搜索 (BFS) 的递归图融合。
    具备本地缓存降级机制与严格的深度控制。
    """
    def __init__(
        self, 
        max_depth: int = 1, 
        save_dir: str = "../../RFCs/", 
        enable_embeddings: bool = True,
        embedding_model_name: str = "BAAI/bge-large-en-v1.5",
        vector_dir: str = "../../RFCs/vector_store/"
    ):
        self.max_depth = max_depth
        self.save_dir = save_dir
        self.global_graph = nx.DiGraph()
        self.visited_rfcs = set()
        self._ssl_context = ssl._create_unverified_context()
        
        os.makedirs(self.save_dir, exist_ok=True)

        self.enable_embeddings = enable_embeddings
        self.embedding_indexer = (
            SectionEmbeddingIndexer(
                model_name=embedding_model_name,
                vector_dir=vector_dir
            )
            if enable_embeddings else None
        )

    def fetch_and_build(self, root_rfc_id: str) -> nx.DiGraph:
        """
        基于 BFS 递归获取 RFC 并构建全局图。
        """
        # 队列存储二元组: (RFC_ID, 当前深度)
        queue = deque([(self._normalize_rfc_id(root_rfc_id), 0)])

        while queue:
            current_rfc, depth = queue.popleft()

            # 全局去重：防止循环依赖和重复解析
            if current_rfc in self.visited_rfcs:
                continue
            
            # 深度越界保护
            if depth > self.max_depth:
                continue

            print(f"[Depth {depth}] 正在解析节点: {current_rfc}")
            
            # 1. 下载并构建单文档子图 (AST)
            subgraph = self._process_single_rfc(current_rfc)
            if not subgraph:
                self.visited_rfcs.add(current_rfc)
                continue

            # 2. 将子图融合入全局图
            self.global_graph = nx.compose(self.global_graph, subgraph)
            self.visited_rfcs.add(current_rfc)

            # 3. 递归链控制：仅在未达到最大深度时，提取规范性引用并压入队列
            if depth < self.max_depth:
                normative_targets = self._get_normative_targets(subgraph)
                for target in normative_targets:
                    if target not in self.visited_rfcs:
                        queue.append((target, depth + 1))

        # New: 构建向量索引
        if self.enable_embeddings and self.embedding_indexer is not None:
            print("[Embedding] 正在离线导出 section embeddings ...")
            self.embedding_indexer.finalize()

        return self.global_graph

    def _process_single_rfc(self, rfc_id: str) -> Optional[nx.DiGraph]:
        """带本地持久化的获取与解析逻辑"""
        rfc_num = rfc_id.replace("RFC", "")
        builder = RFCGraphBuilder(rfc_id)
        
        xml_path = os.path.join(self.save_dir, f"rfc{rfc_num}.xml")
        txt_path = os.path.join(self.save_dir, f"rfc{rfc_num}.txt")

        subgraph: Optional[nx.DiGraph] = None

        # 1. 优先读取本地 XML
        if os.path.exists(xml_path):
            try:
                with open(xml_path, 'r', encoding='utf-8') as f:
                    builder.parse_xml_string(f.read())
                subgraph = builder.get_graph()
                return self._post_process_subgraph(subgraph)
                #return builder.get_graph()
            except Exception as e:
                print(f"解析本地 XML 失败 {xml_path}: {e}")

        # 2. 读取本地 TXT
        if os.path.exists(txt_path):
            try:
                with open(txt_path, 'r', encoding='utf-8') as f:
                    builder.parse_text_string(f.read())
                subgraph = builder.get_graph()
                return self._post_process_subgraph(subgraph)
            except Exception as e:
                print(f"解析本地 TXT 失败 {txt_path}: {e}")

        # 3. 远程获取 XML 并保存
        xml_url = f"https://www.rfc-editor.org/rfc/rfc{rfc_num}.xml"
        try:
            with urllib.request.urlopen(xml_url, context=self._ssl_context) as response:
                content = response.read().decode('utf-8')
                with open(xml_path, 'w', encoding='utf-8') as f:
                    f.write(content)
                builder.parse_xml_string(content)
                subgraph = builder.get_graph()
                return self._post_process_subgraph(subgraph)
        except urllib.error.URLError:
            pass 

        # 4. 远程降级获取 TXT 并保存
        txt_url = f"https://www.rfc-editor.org/rfc/rfc{rfc_num}.txt"
        try:
            with urllib.request.urlopen(txt_url, context=self._ssl_context) as response:
                content = response.read().decode('utf-8')
                with open(txt_path, 'w', encoding='utf-8') as f:
                    f.write(content)
                builder.parse_text_string(content)
                subgraph = builder.get_graph()
                return self._post_process_subgraph(subgraph)
        except urllib.error.URLError as e:
            print(f"未能获取 {rfc_id} 的任何格式数据: {e}")
            return None

    def _get_normative_targets(self, subgraph: nx.DiGraph) -> Set[str]:
        """从子图中提取所有向外的 cites_normative 目标"""
        targets = set()
        for u, v, data in subgraph.edges(data=True):
            if data.get("edge_type") == "cites_normative" and v.startswith("RFC"):
                targets.add(v)
        return targets

    def _normalize_rfc_id(self, rfc_id: str) -> str:
        s = rfc_id.strip().upper()
        return s if s.startswith("RFC") else f"RFC{s}"

    def _post_process_subgraph(self, subgraph: nx.DiGraph) -> nx.DiGraph:
        """
        对单 RFC 子图做后处理。
        当前包括：
        - Section 节点 embedding_id 分配
        - embedding 文本登记
        """
        # print("enable_embeddings =", self.enable_embeddings)
        # print("embedding_indexer is None =", self.embedding_indexer is None)
        #print("[DEBUG] post_process_subgraph called")

        if self.enable_embeddings and self.embedding_indexer is not None:
            self.embedding_indexer.prepare_subgraph(subgraph)
        return subgraph