import networkx as nx

# 请确保模块名与您的实际文件一致
from global_recursor import RFCGraphOrchestrator

def test_1hop_recursion():
    target_rfc = "7858_section3"
    save_directory = "./RFCs_Test/"
    
    print(f"=== 开始执行 RFC {target_rfc} 的 1-hop 递归构建测试 ===\n")
    
    # 初始化调度器，严格限制深度为 1
    orchestrator = RFCGraphOrchestrator(max_depth=1, save_dir=save_directory)
    global_graph = orchestrator.fetch_and_build(target_rfc)
    
    # ==========================================
    # 验证阶段 1：图谱宏观统计
    # ==========================================
    print("\n--- 阶段 1: 宏观统计 ---")
    print(f"全局节点总数: {global_graph.number_of_nodes()}")
    print(f"全局连边总数: {global_graph.number_of_edges()}")
    
    doc_nodes = [n for n, d in global_graph.nodes(data=True) if d.get("node_type") == "RFCDocument"]
    print(f"已成功解析并融合的 RFC 文档总数: {len(doc_nodes)}")
    print(f"完整文档列表: {doc_nodes}")

    # ==========================================
    # 验证阶段 2：种子节点与 1-hop 目标节点结构
    # ==========================================
    print("\n--- 阶段 2: 内部结构检查 ---")
    
    # 检查 Depth 0 种子节点
    assert "RFC7858" in global_graph, "图谱中缺失种子文档节点 RFC7858"
    assert "RFC7858_Sec3" in global_graph, "图谱中缺失种子文档的内部 Section 节点"
    
    # 检查 Depth 1 目标节点 (RFC 7858 规范性引用了 RFC 1035)
    assert "RFC1035" in global_graph, "缺失 1-hop 目标文档节点 RFC1035，递归链未触发"
    
    # 检查 1-hop 目标的子图融合状态：RFC 1035 必须被展开，其 Section 4 (Messages) 必须存在
    sec4_node = "RFC1035_Sec4"
    assert sec4_node in global_graph, f"1-hop 目标未能成功展开其内部结构，缺失 {sec4_node}"
    print("[通过] Depth 0 与 Depth 1 的内部 AST 结构已成功融合进全局图。")

    # ==========================================
    # 验证阶段 3：递归深度物理截断
    # ==========================================
    print("\n--- 阶段 3: 深度截断验证 ---")
    
    # 验证调度器实际发起的全量解析动作
    visited = orchestrator.visited_rfcs
    print(f"实际执行解析的文档集合 (visited_rfcs): {visited}")
    
    # 在之前的 8 层深度测试中，图谱包含了 173 个文档。
    # 深度为 1 时，文档数应有明显数量级下降（通常在 10-20 个左右）。
    assert len(visited) < 50, "触发了异常深度递归，截断机制失效"
    print(f"[通过] 截断机制生效，成功将探索空间限制在 {len(visited)} 篇文档以内。")

    print("\n✅ 所有 1-hop 递归链测试用例均已通过。")

if __name__ == "__main__":
    test_1hop_recursion()