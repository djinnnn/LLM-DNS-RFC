import networkx as nx
from global_recursor import RFCGraphOrchestrator

def analyze_dependency_chain(graph: nx.DiGraph, root_rfc: str):
    """
    将包含 Section 的细粒度图投影为文档级依赖图，
    并打印规范性引用的传递依赖链。
    """
    doc_graph = nx.DiGraph()

    # 1. 构建文档级投影图 (Document Projection)
    for u, v, data in graph.edges(data=True):
        if data.get("edge_type") == "cites_normative":
            # 源节点通常是 Section (例如 RFC7858_Sec3.1)
            # 目标节点是 RFC 文档 (例如 RFC5246)
            src_doc = u.split('_')[0]
            tgt_doc = v
            
            # 过滤掉自引用
            if src_doc != tgt_doc:
                doc_graph.add_edge(src_doc, tgt_doc)

    if root_rfc not in doc_graph:
        print(f"未在图中发现 {root_rfc} 的出度引用。")
        return

    # 2. 递归打印依赖树 (DFS)
    visited = set()

    def print_tree(current_node: str, depth: int, prefix: str = ""):
        if current_node in visited:
            print(f"{prefix}├── {current_node} (已在其他路径展开 / 循环依赖)")
            return
            
        print(f"{prefix}├── {current_node}")
        visited.add(current_node)
        
        # 获取所有规范性引用的下游文档
        successors = list(doc_graph.successors(current_node))
        for i, succ in enumerate(successors):
            is_last = (i == len(successors) - 1)
            next_prefix = prefix + ("    " if is_last else "│   ")
            print_tree(succ, depth + 1, next_prefix)

    print(f"\n=== {root_rfc} 的规范性引用传递依赖树 (Document Level) ===")
    print_tree(root_rfc, 0)
    
    # 3. 统计信息
    print("\n--- 依赖统计 ---")
    print(f"涉及的独立 RFC 文档总数: {len(doc_graph.nodes())}")
    
    # 计算最大深度
    try:
        max_path_length = max(len(p) for p in nx.all_simple_paths(doc_graph, root_rfc, target=None) if p) - 1
        print(f"最长无环依赖路径深度: {max_path_length}")
    except nx.NetworkXNoPath:
        print("最长无环依赖路径深度: 0")


if __name__ == "__main__":
    target_rfc = "7858"
    save_directory = "../../RFCs_Test/"
    
    # 将递归深度设置为 3，观察依赖链的爆炸情况
    test_depth = 3
    print(f"开始抓取与构建图谱 (Root: RFC {target_rfc}, Max Depth: {test_depth})...")
    print("注意：深度大于 1 时，可能需要下载数十个 RFC 文件，耗时较长。")
    
    orchestrator = RFCGraphOrchestrator(max_depth=test_depth, save_dir=save_directory)
    global_graph = orchestrator.fetch_and_build(target_rfc)
    
    analyze_dependency_chain(global_graph, root_rfc=f"RFC{target_rfc}")