"""
诊断脚本：检查图谱中 seed 节点周围的所有引用边。
回答：为什么 RFC9000 没有出现在 ContextPack 的 references 中？
"""
import json
import os
import networkx as nx

_SRC_DIR = os.path.dirname(os.path.abspath(__file__))

def main():
    save_dir = "../../RFC_9250/"
    vector_dir = os.path.join(save_dir, "vector_store")
    cache_dir = vector_dir
    embedding_model = "BAAI/bge-large-en-v1.5"
    cache_key = f"9250_d1_{embedding_model.replace('/', '_')}"
    cache_file = os.path.join(cache_dir, f"cache_{cache_key}.json")

    with open(cache_file, "r") as f:
        cache_meta = json.load(f)
    graph = nx.read_graphml(cache_meta["graph_path"])

    seed = "RFC9250_Sec4.1"
    child = "RFC9250_Sec4.1.1"

    # ═══════════════════════════════════════════════════════════
    # 1. Seed 节点的所有出度边
    # ═══════════════════════════════════════════════════════════
    print(f"{'='*70}")
    print(f"1. {seed} 的所有出度边")
    print(f"{'='*70}")
    for u, v, d in graph.out_edges(seed, data=True):
        print(f"  {u} --[{d.get('edge_type', '?')}]--> {v}")
    if not list(graph.out_edges(seed)):
        print("  (无出度边)")

    # ═══════════════════════════════════════════════════════════
    # 2. 子节点 Sec 4.1.1 的所有出度边
    # ═══════════════════════════════════════════════════════════
    print(f"\n{'='*70}")
    print(f"2. {child} 的所有出度边")
    print(f"{'='*70}")
    for u, v, d in graph.out_edges(child, data=True):
        print(f"  {u} --[{d.get('edge_type', '?')}]--> {v}")
    if not list(graph.out_edges(child)):
        print("  (无出度边)")

    # ═══════════════════════════════════════════════════════════
    # 3. 全局搜索：图谱中有没有任何指向 RFC9000 的边？
    # ═══════════════════════════════════════════════════════════
    print(f"\n{'='*70}")
    print(f"3. 全局搜索：图谱中是否存在 RFC9000 相关节点/边？")
    print(f"{'='*70}")

    # 搜索节点
    rfc9000_nodes = [n for n in graph.nodes() if "9000" in n.upper()]
    print(f"  包含 '9000' 的节点 ({len(rfc9000_nodes)}):")
    for n in rfc9000_nodes:
        d = dict(graph.nodes[n])
        print(f"    {n}: type={d.get('node_type', '?')}, title={d.get('title', '')}")

    # 搜索边（目标包含 9000）
    rfc9000_edges = [(u, v, d) for u, v, d in graph.edges(data=True) if "9000" in v.upper()]
    print(f"\n  指向 '9000' 节点的边 ({len(rfc9000_edges)}):")
    for u, v, d in rfc9000_edges:
        print(f"    {u} --[{d.get('edge_type', '?')}]--> {v}")

    # ═══════════════════════════════════════════════════════════
    # 4. 全局统计：图谱中所有 edge_type 分布
    # ═══════════════════════════════════════════════════════════
    print(f"\n{'='*70}")
    print(f"4. 图谱中 edge_type 全局统计")
    print(f"{'='*70}")
    edge_type_counts = {}
    for u, v, d in graph.edges(data=True):
        et = d.get("edge_type", "unknown")
        edge_type_counts[et] = edge_type_counts.get(et, 0) + 1
    for et, count in sorted(edge_type_counts.items()):
        print(f"  {et}: {count}")

    # ═══════════════════════════════════════════════════════════
    # 5. 列出所有 cites_* 边（跨文档引用）
    # ═══════════════════════════════════════════════════════════
    print(f"\n{'='*70}")
    print(f"5. 全部 cites_* 引用边")
    print(f"{'='*70}")
    cites_edges = [(u, v, d) for u, v, d in graph.edges(data=True)
                   if d.get("edge_type", "").startswith("cites_")]
    for u, v, d in cites_edges:
        print(f"  {u} --[{d.get('edge_type')}]--> {v}")
    if not cites_edges:
        print("  (无 cites_* 边!)")

    # ═══════════════════════════════════════════════════════════
    # 6. RFC9250 原文中是否提到 RFC 9000？检查 Section text
    # ═══════════════════════════════════════════════════════════
    print(f"\n{'='*70}")
    print(f"6. Section 文本中是否提到 RFC 9000 / QUIC?")
    print(f"{'='*70}")
    for n, d in graph.nodes(data=True):
        if d.get("rfc_id") != "RFC9250":
            continue
        text = d.get("text", "") or ""
        if "9000" in text or "QUIC" in text:
            sec_id = d.get("section_id", n)
            # 找出包含引用的行
            lines = [l.strip() for l in text.split("\n") if "9000" in l or "QUIC" in l]
            print(f"\n  {sec_id} \"{d.get('title', '')}\":")
            for l in lines[:5]:
                print(f"    > {l[:120]}")


if __name__ == "__main__":
    main()
