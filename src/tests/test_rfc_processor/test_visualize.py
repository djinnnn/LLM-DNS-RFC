import os
import networkx as nx
import matplotlib.pyplot as plt
from typing import Dict, Any

from rfc_parser import RFCGraphBuilder
from global_recursor import RFCGraphOrchestrator

def visualize_rfc_graph(graph: nx.DiGraph, root_rfc: str):
    """
    使用 matplotlib 渲染 RFC 结构图谱。
    通过颜色和线型区分节点与连边类型。
    """
    print("正在计算图的布局 (Spring Layout)...")
    # 使用 spring_layout 模拟引力，k 值控制节点间距
    pos = nx.spring_layout(graph, k=0.15, iterations=50)
    
    node_colors = []
    node_sizes = []
    
    # 1. 区分节点颜色与大小
    for node_id, data in graph.nodes(data=True):
        node_type = data.get("node_type")
        if node_type == "RFCDocument":
            node_colors.append("lightcoral")  # 根文档节点为红色
            node_sizes.append(600)
        elif node_type == "Section":
            node_colors.append("skyblue")     # 章节节点为蓝色
            node_sizes.append(200)
        else:
            # 被引用的外部 RFC 节点（仅有 ID，无详细内部数据）
            node_colors.append("lightgray")
            node_sizes.append(400)
            
    # 2. 区分边的类型与样式
    edges = graph.edges(data=True)
    
    ast_edges = [(u, v) for u, v, d in edges if d.get("edge_type") in ["has_section", "has_subsection"]]
    normative_edges = [(u, v) for u, v, d in edges if d.get("edge_type") == "cites_normative"]
    informative_edges = [(u, v) for u, v, d in edges if d.get("edge_type") == "cites_informative"]
    
    plt.figure(figsize=(16, 12))
    
    # 绘制节点
    nx.draw_networkx_nodes(graph, pos, node_color=node_colors, node_size=node_sizes, alpha=0.9, edgecolors="black")
    
    # 绘制 AST 树层级边 (实线，蓝色)
    nx.draw_networkx_edges(graph, pos, edgelist=ast_edges, edge_color="royalblue", arrows=True, arrowsize=10, alpha=0.6)
    
    # 绘制规范性引用边 (虚线，绿色)
    nx.draw_networkx_edges(graph, pos, edgelist=normative_edges, edge_color="forestgreen", style="dashed", arrows=True, arrowsize=12, alpha=0.8)
    
    # 3. 标签控制：为了防止标签重叠，只显示顶级章节、文档根节点和外部 RFC 节点
    labels = {}
    for node in graph.nodes():
        if not node.startswith(f"{root_rfc}_Sec"):
            # 外部 RFC 节点或当前文档根节点
            labels[node] = node
        else:
            # 当前文档的章节节点，仅显示层级不超过 1 的节点 (如 Sec3，不显示 Sec3.1.2)
            sec_num = graph.nodes[node].get("sec_num", "")
            if "." not in sec_num:
                labels[node] = node.replace(f"{root_rfc}_", "")
                
    nx.draw_networkx_labels(graph, pos, labels, font_size=9, font_weight="bold")
    
    # 绘制图例与标题
    plt.title(f"{root_rfc} Topology Visualization\n(Red: Document, Blue: Sections, Gray: External Refs)", fontsize=14)
    
    # 手动添加简易图例信息
    plt.text(0.01, 0.99, "Solid Blue Edge: has_section / has_subsection\nDashed Green Edge: cites_normative", 
             transform=plt.gca().transAxes, fontsize=10, verticalalignment='top', 
             bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))
    
    plt.axis("off")
    plt.tight_layout()
    print("图谱渲染完成，正在显示窗口...")
    plt.show()


if __name__ == "__main__":
    target_rfc = "7858"
    save_directory = "../../RFCs_Test/"
    
    print(f"=== 开始执行 RFC {target_rfc} 图谱构建测试 ===")
    
    # 严格限制深度为 0，防止画布被撑爆
    orchestrator = RFCGraphOrchestrator(max_depth=0, save_dir=save_directory)
    global_graph = orchestrator.fetch_and_build(target_rfc)
    
    # 验证与统计
    print("\n--- 构建结果统计 ---")
    print(f"节点总数: {global_graph.number_of_nodes()}")
    print(f"连边总数: {global_graph.number_of_edges()}")
    
    # 检查特定边是否存在以验证逻辑完备性
    normative_count = sum(1 for _, _, d in global_graph.edges(data=True) if d.get("edge_type") == "cites_normative")
    ast_count = sum(1 for _, _, d in global_graph.edges(data=True) if d.get("edge_type") in ["has_section", "has_subsection"])
    
    print(f"AST 层级边数量: {ast_count}")
    print(f"跨文档规范性引用边数量: {normative_count}")
    
    if normative_count == 0:
        print("[警告] 未提取到任何规范性引用边，请检查 `_build_cross_reference_edges` 逻辑是否被正确调用。")
    
    # 启动可视化
    visualize_rfc_graph(global_graph, root_rfc=f"RFC{target_rfc}")