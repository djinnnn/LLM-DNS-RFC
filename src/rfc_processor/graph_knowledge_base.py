import networkx as nx
from typing import Dict, Any, List, Optional, Tuple

class GraphKnowledgeBase:
    """
    图知识库访问层 (DAO)
    封装底层 NetworkX 复杂操作，向上层 RAG 提供领域驱动的图查询接口。
    """
    def __init__(self, graph: nx.DiGraph):
        self.graph = graph

    # ==========================================
    # 1. 基础访问 (Basic Access)
    # ==========================================
    def get_node_data(self, node_id: str) -> Optional[Dict[str, Any]]:
        """获取单一节点的完整属性字典"""
        if self.graph.has_node(node_id):
            return dict(self.graph.nodes[node_id])
        return None

    def get_document_nodes(self) -> List[str]:
        """获取图中所有的根文档节点 ID"""
        return [n for n, d in self.graph.nodes(data=True) if d.get('node_type') == 'RFCDocument']

    # ==========================================
    # 2. 本地结构路由 (Local Structure Routing)
    # ==========================================
    def get_ancestor_chain(self, node_id: str) -> List[Dict[str, Any]]:
        """
        向上路由：获取当前节点的作用域 (Scope)。
        沿着 has_subsection 边反向遍历，返回从顶级章节到当前章节父节点的路径。
        """
        ancestors = []
        current_node = node_id
        
        # 假设树结构无环，向上追溯至没有 has_subsection 入度边为止
        while True:
            parents = [u for u, v, d in self.graph.in_edges(current_node, data=True) 
                       if d.get('edge_type') == 'has_subsection']
            if not parents:
                break
            
            parent_id = parents[0] # 在标准的文档树中，一个 section 只有一个直接 parent
            parent_data = self.get_node_data(parent_id)
            if parent_data:
                ancestors.insert(0, parent_data) # 保证从大章节到小章节的顺序
            current_node = parent_id
            
        return ancestors

    def get_descendants(self, node_id: str) -> List[Dict[str, Any]]:
        """
        向下路由：获取当前节点的子级动作细节。
        沿着 has_subsection 边正向遍历获取直接子节点。
        """
        children = []
        for u, v, d in self.graph.out_edges(node_id, data=True):
            if d.get('edge_type') == 'has_subsection':
                child_data = self.get_node_data(v)
                if child_data:
                    children.append(child_data)
        
        # 按照 sec_num 排序，保证上下文的词法连续性
        children.sort(key=lambda x: x.get('sec_num', ''))
        return children

    # ==========================================
    # 3. 引用关系路由 (Reference Routing)
    # ==========================================
    def get_references(self, node_id: str) -> Dict[str, List[Dict[str, Any]]]:
        """
        横向路由：提取当前节点向外的所有引用，并按粒度和内部/外部进行分类。
        返回格式:
        {
            "internal": [...],            # 文档内交叉引用
            "external_precise": [...],    # 细粒度到 Section 的外部引用
            "external_coarse": [...]      # 粗粒度到整篇 RFC 的外部引用
        }
        """
        result = {
            "internal": [],
            "external_precise": [],
            "external_coarse": []
        }
        
        for u, v, d in self.graph.out_edges(node_id, data=True):
            edge_type = d.get('edge_type')
            target_data = self.get_node_data(v)
            if not target_data:
                # 目标节点尚不存在于图中 (未被解析)，仅返回其 ID 占位
                target_data = {"id": v, "node_type": "Unknown", "title": "Unresolved Reference"}

            # 为了后续 RAG 能够感知引用性质，将 edge_type 注入到返回结果中
            target_data["_reference_type"] = edge_type

            if edge_type == 'cites_internal':
                result["internal"].append(target_data)
            elif edge_type in ['cites_normative', 'cites_informative', 'cites_unspecified']:
                node_type = target_data.get('node_type')
                if node_type == 'Section' or "_Sec" in v:
                    result["external_precise"].append(target_data)
                else:
                    result["external_coarse"].append(target_data)
                    
        return result

    # ==========================================
    # 4. 结构化过滤 (Filtering)
    # ==========================================
    def is_valid_protocol_section(self, node_id: str) -> bool:
        """
        硬规则过滤：判断节点是否包含有效的状态机转换语义。
        裁剪掉 IANA Considerations, Acknowledgements 等噪音节点，避免 RAG 语义污染。
        """
        data = self.get_node_data(node_id)
        if not data:
            return False
            
        if data.get('node_type') != 'Section':
            return False
            
        title = data.get('title', '').lower()
        
        # 噪音黑名单
        noise_keywords = [
            'acknowledgements', 'acknowledgments',
            'iana considerations', 
            'security considerations',
            'references', 'normative references', 'informative references',
            'author\'s address', 'authors\' addresses'
        ]
        
        if any(keyword in title for keyword in noise_keywords):
            return False
            
        if data.get('is_appendix', False):
            return False
            
        return True

    def get_aggregated_references(self, node_id: str) -> Dict[str, List[Dict[str, Any]]]:
        """
        向下递归聚合：不仅提取当前节点的引用，同时递归遍历所有子节点，
        将子树中包含的所有内部/外部引用汇总去重后返回。
        """
        aggregated_result = {
            "internal": [],
            "external_precise": [],
            "external_coarse": []
        }
        
        # 记录已处理的 target ID，防止重复添加
        seen_targets = set()
        
        # 内部递归函数
        def _collect_refs(current_node):
            # 1. 收集当前节点的直接引用
            direct_refs = self.get_references(current_node)
            for key in aggregated_result.keys():
                for ref in direct_refs[key]:
                    ref_id = ref.get('id', ref.get('section_id', ref.get('rfc_id')))
                    if ref_id and ref_id not in seen_targets:
                        seen_targets.add(ref_id)
                        aggregated_result[key].append(ref)
            
            # 2. 沿着 has_subsection 边递归收集子节点引用
            for u, v, d in self.graph.out_edges(current_node, data=True):
                if d.get('edge_type') == 'has_subsection':
                    _collect_refs(v)

        _collect_refs(node_id)
        return aggregated_result