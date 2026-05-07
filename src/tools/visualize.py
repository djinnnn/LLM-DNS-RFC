import os
import networkx as nx
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

def _build_hierarchy_pos(G, root, width=1.0, vert_gap=0.2, vert_loc=0, xcenter=0.5, pos=None, parsed=None):
    """
    纯 Python 实现的树状坐标递归分配算法。
    """
    if pos is None:
        pos = {root: (xcenter, vert_loc)}
    else:
        pos[root] = (xcenter, vert_loc)
    
    if parsed is None:
        parsed = {root}

    # 仅获取子节点，忽略已解析节点，防止潜在环导致无限递归
    children = [neighbor for neighbor in G.successors(root) if neighbor not in parsed]
    parsed.update(children)

    if children:
        dx = width / len(children)
        nextx = xcenter - width/2 - dx/2
        for child in children:
            nextx += dx
            pos = _build_hierarchy_pos(G, child, width=dx, vert_gap=vert_gap, 
                                       vert_loc=vert_loc-vert_gap, xcenter=nextx,
                                       pos=pos, parsed=parsed)
    return pos

def visualize_graph(global_graph: nx.DiGraph, target_rfc_doc: str, test_depth: int, output_dir: str = ".") -> None:
    """
    将图谱可视化为严格的树状结构。
    结构边使用直线，引用边使用曲线以降低视觉干扰。
    """
    print(f"=== 执行树状图谱可视化 ===")
    
    # 1. 抽取纯 AST 结构子图，计算拓扑坐标
    ast_edges = [(u, v) for u, v, d in global_graph.edges(data=True) 
                 if d.get('edge_type') in ['has_section', 'has_subsection']]
    tree_graph = nx.DiGraph(ast_edges)
    
    root_node = f"RFC{target_rfc_doc}"
    
    # 计算基础树状布局坐标
    if root_node in tree_graph:
        pos = _build_hierarchy_pos(tree_graph, root_node, width=2.0, vert_gap=0.3)
    else:
        # 兜底：如果缺乏有效根节点，降级为默认布局
        pos = nx.spring_layout(global_graph, seed=42)

    isolated_nodes = [n for n in global_graph.nodes() if n not in pos]
    if isolated_nodes:
        # 获取树形结构当前的最低 Y 坐标，以确定底部位置
        y_values = [coords[1] for coords in pos.values()]
        min_y = min(y_values) if y_values else 0
        
        # 将灰色节点放置在树结构最下方的固定间距处
        iso_y = min_y - 0.4
        
        # 设定横向排布的中心点和节点间距
        center_x = 0.5  # 与根节点默认的 xcenter 保持对齐
        spacing = 0.15  # 横向间距，避免节点重叠
        
        # 计算起始 X 坐标，使其居中对称排布
        total_width = (len(isolated_nodes) - 1) * spacing
        start_x = center_x - total_width / 2
        
        for i, iso_node in enumerate(isolated_nodes):
            pos[iso_node] = (start_x + i * spacing, iso_y)

    plt.figure(figsize=(24, 16))

    # 2. 定义节点属性映射
    node_colors = []
    node_sizes = []
    for node, data in global_graph.nodes(data=True):
        node_type = data.get('node_type', 'Unknown')
        if node_type == 'RFCDocument':
            node_colors.append('lightcoral')
            node_sizes.append(4000)
        elif node_type == 'Section':
            node_colors.append('lightblue')
            node_sizes.append(2000)
        else:
            node_colors.append('gray')
            node_sizes.append(1000)

    # 3. 拆分连边集合以便应用不同渲染样式
    internal_ref_edges = [(u, v) for u, v, d in global_graph.edges(data=True) if d.get('edge_type') == 'cites_internal']
    normative_ref_edges = [(u, v) for u, v, d in global_graph.edges(data=True) if d.get('edge_type') == 'cites_normative']

    # 4. 渲染拓扑
    # 绘制节点
    nx.draw_networkx_nodes(global_graph, pos, node_color=node_colors, node_size=node_sizes, 
                           alpha=0.9, edgecolors='white', linewidths=2)
    
    # 绘制结构边 (直黑线)
    nx.draw_networkx_edges(global_graph, pos, edgelist=ast_edges, edge_color='black', 
                           width=2.0, arrows=True, arrowsize=20)
    
    # 绘制内部引用边 (蓝曲线，增加透明度降低视觉干扰)
    nx.draw_networkx_edges(global_graph, pos, edgelist=internal_ref_edges, edge_color='blue', 
                           width=1.5, arrows=True, arrowsize=20, alpha=0.5, connectionstyle="arc3,rad=0.3")
    
    # 绘制外部规范引用边 (红曲线)
    nx.draw_networkx_edges(global_graph, pos, edgelist=normative_ref_edges, edge_color='red', 
                           width=1.5, arrows=True, arrowsize=20, alpha=0.5, connectionstyle="arc3,rad=0.3")

    # 渲染标签
    labels = {node: node for node in global_graph.nodes()}
    nx.draw_networkx_labels(global_graph, pos, labels=labels, font_size=8, font_family='sans-serif', font_weight='bold')

    # 5. 构造图例 (Legend)
    legend_elements = [
        Line2D([0], [0], marker='o', color='w', label='Document Node (RFCDocument)', markerfacecolor='lightcoral', markersize=12),
        Line2D([0], [0], marker='o', color='w', label='Section Node (Section)', markerfacecolor='lightblue', markersize=12),
        Line2D([0], [0], color='black', lw=2, label='AST Structure (has_section/subsection)'),
        Line2D([0], [0], color='blue', lw=1.5, alpha=0.5, label='Internal Ref (cites_internal)'),
        Line2D([0], [0], color='red', lw=1.5, alpha=0.5, label='Normative Ref (cites_normative)')
    ]
    plt.legend(handles=legend_elements, loc='upper right', fontsize=12, framealpha=0.9, title="Graph Legend", title_fontsize=14)

    # 6. 保存输出
    title = f"RFC {target_rfc_doc} Tree Structure Graph (Depth={test_depth})"
    plt.title(title, fontsize=18, fontweight='bold')
    plt.axis('off')
    plt.tight_layout()

    os.makedirs(output_dir, exist_ok=True)
    output_image = os.path.join(output_dir, f"rfc{target_rfc_doc}_tree_depth{test_depth}.png")
    plt.savefig(output_image, dpi=300, bbox_inches='tight')
    plt.close() 
    print(f"树状图谱已保存为图片: {os.path.abspath(output_image)}\n")