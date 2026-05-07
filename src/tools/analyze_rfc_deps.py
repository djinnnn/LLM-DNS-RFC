"""
RFC 依赖链分析脚本
递归遍历所有规范性引用 (cites_normative)，统计：
  1. 涉及的独立 RFC 文档总数
  2. 最大依赖层数
  3. 每层包含的 RFC 列表
支持可视化：
  --viz  生成深度分布柱状图 + 依赖关系图
"""
import os
import re
import sys
from collections import defaultdict

import matplotlib
matplotlib.use("Agg")  # 无头模式，直接保存文件
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import networkx as nx

from orchestrator import RFCGraphOrchestrator


def analyze_deps(root_rfc: str, save_dir: str):
    """
    用 orchestrator 做 BFS 递归下载所有规范性引用的 RFC，
    然后从构建好的全局图中按 cites_normative 边重建依赖层次。
    """

    # ── Phase 1: 递归构建全局图（不限深度，不加载 embedding） ──
    print(f"=== 开始递归构建 RFC {root_rfc} 的全局依赖图 ===")
    print(f"    save_dir = {save_dir}")
    print(f"    enable_embeddings = False")
    print()

    orchestrator = RFCGraphOrchestrator(
        max_depth=999,           # 不限深度
        save_dir=save_dir,
        enable_embeddings=False,  # 不需要 embedding，纯图遍历
    )
    graph = orchestrator.fetch_and_build(root_rfc)

    print(f"\n=== 图谱构建完成 ===")
    print(f"    visited_rfcs: {len(orchestrator.visited_rfcs)} 个")
    print(f"    图节点总数: {graph.number_of_nodes()}")
    print(f"    图边总数:   {graph.number_of_edges()}")

    # ── Phase 2: 从全局图中按 cites_normative 边做 BFS 重建依赖层次 ──
    # 收集所有 cites_normative 边，构建 RFC → RFC 的邻接表
    #   边的格式: section节点 --cites_normative--> RFCxxxx (document node)
    #   需要找出 section 所属的 RFC
    adj = defaultdict(set)  # parent_rfc → {child_rfc, ...}
    for u, v, data in graph.edges(data=True):
        if data.get("edge_type") != "cites_normative":
            continue
        # u 是 section 节点，找出它属于哪个 RFC
        u_data = graph.nodes.get(u, {})
        parent_rfc = u_data.get("rfc_id", "")
        # v 是目标 RFC id (如 "RFC1035")，排除 section 级节点 (如 "RFC1035_Sec4.2")
        child_rfc = v if re.fullmatch(r"RFC\d+", v) else ""
        if parent_rfc and child_rfc and parent_rfc != child_rfc:
            adj[parent_rfc].add(child_rfc)

    # BFS 从 root 出发
    root_id = f"RFC{root_rfc}"
    depth_map = {root_id: 0}
    queue = [root_id]
    head = 0

    while head < len(queue):
        current = queue[head]
        head += 1
        for child in sorted(adj.get(current, [])):
            if child not in depth_map:
                depth_map[child] = depth_map[current] + 1
                queue.append(child)

    # ── Phase 3: 汇总输出 ──
    depth_to_rfcs = defaultdict(list)
    for rfc_id, d in depth_map.items():
        depth_to_rfcs[d].append(rfc_id)

    max_depth = max(depth_map.values()) if depth_map else 0
    total_rfcs = len(depth_map)

    print()
    print("=" * 60)
    print(f"  RFC {root_rfc} 依赖链分析结果")
    print("=" * 60)
    print(f"  涉及的独立 RFC 文档总数: {total_rfcs}")
    print(f"  依赖层数最多有: {max_depth} 层")
    print("-" * 60)

    for d in range(max_depth + 1):
        rfcs = sorted(depth_to_rfcs[d])
        print(f"  [Depth {d}] ({len(rfcs):>3} 个): {', '.join(rfcs)}")

    print("=" * 60)

    return adj, depth_map, depth_to_rfcs, max_depth, total_rfcs


# ════════════════════════════════════════════════════════════
# 可视化
# ════════════════════════════════════════════════════════════

# 每层对应的颜色
_DEPTH_COLORS = [
    "#E74C3C",  # 0 - 红
    "#E67E22",  # 1 - 橙
    "#F1C40F",  # 2 - 黄
    "#2ECC71",  # 3 - 绿
    "#1ABC9C",  # 4 - 青
    "#3498DB",  # 5 - 蓝
    "#9B59B6",  # 6 - 紫
    "#8E44AD",  # 7 - 深紫
    "#95A5A6",  # 8+ - 灰
]


def _color_for_depth(d: int) -> str:
    return _DEPTH_COLORS[min(d, len(_DEPTH_COLORS) - 1)]


def plot_depth_distribution(depth_to_rfcs, max_depth, total_rfcs,
                            root_rfc: str, out_path: str):
    """柱状图：每层 RFC 数量分布"""
    depths = list(range(max_depth + 1))
    counts = [len(depth_to_rfcs[d]) for d in depths]
    colors = [_color_for_depth(d) for d in depths]

    fig, ax = plt.subplots(figsize=(10, 5))
    bars = ax.bar(depths, counts, color=colors, edgecolor="white", linewidth=0.8)

    # 在柱子上方标注数量
    for bar, count in zip(bars, counts):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 1,
                str(count), ha="center", va="bottom", fontsize=11, fontweight="bold")

    ax.set_xlabel("Dependency Depth", fontsize=12)
    ax.set_ylabel("Number of RFCs", fontsize=12)
    ax.set_title(f"RFC {root_rfc} — Normative Dependency Depth Distribution\n"
                 f"(Total: {total_rfcs} RFCs, Max Depth: {max_depth})",
                 fontsize=13, fontweight="bold")
    ax.set_xticks(depths)
    ax.set_xticklabels([f"Depth {d}" for d in depths])
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    print(f"  [✓] 深度分布图已保存: {out_path}")


def plot_dependency_graph(adj, depth_map, depth_to_rfcs, max_depth,
                          root_rfc: str, out_path: str):
    """依赖引用关系图：同心圆放射布局，适合 PPT 展示"""
    import math

    # ── 构建 NetworkX 有向图（仅文档级） ──
    G = nx.DiGraph()
    for parent, children in adj.items():
        if parent not in depth_map:
            continue
        for child in children:
            if child in depth_map:
                G.add_edge(parent, child)
    for rfc_id in depth_map:
        if not G.has_node(rfc_id):
            G.add_node(rfc_id)

    # ── 同心圆放射布局（固定画布，半径归一化） ──
    canvas_r = 14.0  # 最外圈半径（坐标单位，画布 ±15）
    pos = {}
    # 等比环间距，depth 0 在圆心，depth max_depth 在 canvas_r
    ring_radii = [0.0] + [canvas_r * d / max_depth for d in range(1, max_depth + 1)]

    for d in range(max_depth + 1):
        rfcs = sorted(depth_to_rfcs[d])
        n = len(rfcs)
        if d == 0:
            pos[rfcs[0]] = (0.0, 0.0)
        else:
            radius = ring_radii[d]
            for i, rfc_id in enumerate(rfcs):
                angle = 2 * math.pi * i / n - math.pi / 2
                pos[rfc_id] = (radius * math.cos(angle), radius * math.sin(angle))

    # ── 节点大小分级 ──
    node_colors = [_color_for_depth(depth_map.get(nd, 0)) for nd in G.nodes()]
    node_sizes = []
    for nd in G.nodes():
        d = depth_map.get(nd, 0)
        if d == 0:
            node_sizes.append(2800)
        elif d == 1:
            node_sizes.append(900)
        elif d == 2:
            node_sizes.append(420)
        elif d <= 4:
            node_sizes.append(250)
        else:
            node_sizes.append(180)

    # ── 绘制 ──
    total_nodes = G.number_of_nodes()
    fig, ax = plt.subplots(figsize=(32, 32))
    ax.set_facecolor("white")
    fig.patch.set_facecolor("white")

    # 淡色同心参考圆 + 层号
    for d in range(1, max_depth + 1):
        r = ring_radii[d]
        circle = plt.Circle((0, 0), r, fill=False,
                             color="#E8E8E8", linewidth=0.8, linestyle="--")
        ax.add_patch(circle)
        ax.text(r + 0.6, 0.6,
                f"Depth {d}", fontsize=13, color="#BBBBBB",
                ha="left", va="bottom", fontstyle="italic")

    # 边
    for u, v in G.edges():
        du, dv = depth_map.get(u, 0), depth_map.get(v, 0)
        span = abs(dv - du)
        alpha = 0.30 if span <= 1 else 0.12
        ax.annotate("",
                     xy=pos[v], xytext=pos[u],
                     arrowprops=dict(arrowstyle="-|>",
                                     color="#AAAAAA",
                                     alpha=alpha,
                                     lw=0.4,
                                     shrinkA=5, shrinkB=5,
                                     connectionstyle="arc3,rad=0.08"))

    # 节点
    nx.draw_networkx_nodes(
        G, pos, ax=ax,
        node_color=node_colors, node_size=node_sizes,
        edgecolors="white", linewidths=1.0, alpha=0.93,
    )

    # 标签分级
    for target_d, fsize, fweight, fcolor in [
        (0, 16, "bold", "white"),
        (1, 11, "bold", "#222222"),
        (2, 8,  "bold", "#444444"),
        (3, 6,  "normal", "#555555"),
        (4, 5,  "normal", "#666666"),
    ]:
        labels = {nd: nd.replace("RFC", "") if target_d > 0 else nd
                  for nd in G.nodes() if depth_map.get(nd, 99) == target_d}
        if labels:
            nx.draw_networkx_labels(G, pos, labels=labels, ax=ax,
                                    font_size=fsize, font_weight=fweight,
                                    font_color=fcolor)

    # 图例
    legend_patches = []
    for d in range(max_depth + 1):
        cnt = len(depth_to_rfcs[d])
        legend_patches.append(
            mpatches.Patch(color=_color_for_depth(d),
                           label=f"Depth {d}   ({cnt} RFCs)")
        )
    leg = ax.legend(handles=legend_patches, loc="lower right", fontsize=16,
                    title="Dependency Depth", title_fontsize=18,
                    framealpha=0.95, edgecolor="#CCCCCC", fancybox=True,
                    borderpad=1.2, labelspacing=0.8)
    leg.get_title().set_fontweight("bold")

    ax.set_title(
        f"RFC {root_rfc} — Normative Reference Dependency Graph\n"
        f"{total_nodes} RFCs  ·  {G.number_of_edges()} edges  ·  max depth {max_depth}",
        fontsize=24, fontweight="bold", pad=24
    )
    ax.set_aspect("equal")
    ax.axis("off")

    fig.tight_layout()
    fig.savefig(out_path, dpi=200, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"  [✓] 依赖关系图已保存: {out_path}")


if __name__ == "__main__":
    # 用法: python analyze_rfc_deps.py <rfc_number> [save_dir] [--viz]
    # 示例: python analyze_rfc_deps.py 9250 --viz
    #        python analyze_rfc_deps.py 7858 ../../RFC_7858/ --viz
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = {a for a in sys.argv[1:] if a.startswith("--")}

    target = args[0] if len(args) > 0 else "9250"
    save = args[1] if len(args) > 1 else f"../../RFC_{target}/"
    do_viz = "--viz" in flags

    result = analyze_deps(target, save)

    if do_viz and result:
        adj, depth_map, depth_to_rfcs, max_depth, total_rfcs = result
        viz_dir = os.path.join(save, "viz")
        os.makedirs(viz_dir, exist_ok=True)

        print(f"\n=== 正在生成可视化 (保存到 {viz_dir}) ===")
        plot_depth_distribution(
            depth_to_rfcs, max_depth, total_rfcs,
            root_rfc=target,
            out_path=os.path.join(viz_dir, f"rfc{target}_depth_distribution.png"),
        )
        plot_dependency_graph(
            adj, depth_map, depth_to_rfcs, max_depth,
            root_rfc=target,
            out_path=os.path.join(viz_dir, f"rfc{target}_dependency_graph.png"),
        )