"""
Phase 1 & 2 详细检查脚本。
只运行图谱构建和 ContextPack 组装，输出：
  1. seed 节点原文
  2. 图谱拓扑详情（seed 周围的节点和边）
  3. 完整的 ContextPack 结构
"""
import json
import os
import sys
import networkx as nx

_SRC_DIR = os.path.dirname(os.path.abspath(__file__))

from rfc_processor.orchestrator import RFCGraphOrchestrator
from rfc_processor.graph_knowledge_base import GraphKnowledgeBase
from rfc_processor.rag_router import GraphRAGRouter, SemanticRanker, SentenceTransformerQueryBackend
from rfc_processor.embedding_store import NumpyEmbeddingStore


def banner(title: str):
    w = 70
    print(f"\n╔{'═' * w}╗")
    print(f"║  {title:<{w - 2}}║")
    print(f"╚{'═' * w}╝")


def main():
    rfc_id = "9250"
    seed_section_id = "RFC9250_Sec4.1"
    save_dir = "../../RFC_9250_txt/"
    vector_dir = os.path.join(save_dir, "vector_store")
    cache_dir = os.path.join(save_dir, "vector_store")
    embedding_model = "BAAI/bge-large-en-v1.5"

    # ── 加载图谱（优先用缓存）─────────────────────────────────
    cache_key = f"{rfc_id}_d1_{embedding_model.replace('/', '_')}"
    cache_file = os.path.join(cache_dir, f"cache_{cache_key}.json")
    npy_path = os.path.join(vector_dir, "section_embeddings.npy")
    index_path = os.path.join(vector_dir, "section_embedding_index.json")

    if os.path.exists(cache_file):
        with open(cache_file, "r") as f:
            cache_meta = json.load(f)
        graph_path = cache_meta.get("graph_path")
        graph = nx.read_graphml(graph_path)
        print(f"[Phase1] 从缓存加载图谱: {graph.number_of_nodes()} nodes, {graph.number_of_edges()} edges")
    else:
        print("[Phase1] 无缓存，正在构建图谱...")
        orchestrator = RFCGraphOrchestrator(
            max_depth=1, save_dir=save_dir,
            enable_embeddings=True, vector_dir=vector_dir,
        )
        graph = orchestrator.fetch_and_build(rfc_id)

    # ═══════════════════════════════════════════════════════════
    # 1. Seed 节点原文
    # ═══════════════════════════════════════════════════════════
    banner("1. Seed 节点原文")

    if not graph.has_node(seed_section_id):
        print(f"  ERROR: 图谱中不存在节点 {seed_section_id}")
        print(f"  可用 Section 节点:")
        for n, d in graph.nodes(data=True):
            if d.get("node_type") == "Section":
                print(f"    {n}: {d.get('title', '')}")
        return

    seed_data = dict(graph.nodes[seed_section_id])
    seed_text = seed_data.get("text", "")
    print(f"  ID:    {seed_section_id}")
    print(f"  Title: {seed_data.get('title', '')}")
    print(f"  Type:  {seed_data.get('node_type', '')}")
    print(f"  RFC:   {seed_data.get('rfc_id', '')}")
    print(f"  SecNo: {seed_data.get('sec_num', '')}")
    print(f"  Text length: {len(seed_text)} chars")
    print(f"\n  ── 原文内容 ──")
    print(seed_text if seed_text else "  [空]")
    print(f"  ── 原文结束 ──")

    # ═══════════════════════════════════════════════════════════
    # 2. 图谱拓扑详情 (seed 周围)
    # ═══════════════════════════════════════════════════════════
    banner("2. 图谱拓扑详情（以 Seed 为中心）")

    # 2a. 入度边（谁指向 seed）
    in_edges = list(graph.in_edges(seed_section_id, data=True))
    print(f"\n  入度边 ({len(in_edges)}):")
    for u, v, d in in_edges:
        edge_type = d.get("edge_type", "?")
        u_data = graph.nodes[u] if graph.has_node(u) else {}
        u_title = u_data.get("title", "")
        print(f"    {u} \"{u_title}\" --[{edge_type}]--> {v}")

    # 2b. 出度边（seed 指向谁）
    out_edges = list(graph.out_edges(seed_section_id, data=True))
    print(f"\n  出度边 ({len(out_edges)}):")
    for u, v, d in out_edges:
        edge_type = d.get("edge_type", "?")
        v_data = graph.nodes[v] if graph.has_node(v) else {}
        v_title = v_data.get("title", "")
        v_type = v_data.get("node_type", "?")
        print(f"    {u} --[{edge_type}]--> {v} \"{v_title}\" (type={v_type})")

    # 2c. 子节点详情（has_subsection 出度）
    print(f"\n  子节点详情:")
    for u, v, d in out_edges:
        if d.get("edge_type") == "has_subsection":
            child_data = dict(graph.nodes[v])
            child_text = child_data.get("text", "")
            print(f"\n    ── {v} \"{child_data.get('title', '')}\" ({len(child_text)} chars) ──")
            if child_text:
                # 显示前 500 字符
                preview = child_text[:500]
                print(f"    {preview}{'...' if len(child_text) > 500 else ''}")
            else:
                print(f"    [空]")

    # 2d. 父节点详情（has_subsection 入度）
    print(f"\n  父节点详情:")
    for u, v, d in in_edges:
        if d.get("edge_type") in ("has_subsection", "has_section"):
            parent_data = dict(graph.nodes[u]) if graph.has_node(u) else {}
            parent_text = parent_data.get("text", "")
            print(f"    {u} \"{parent_data.get('title', '')}\" ({len(parent_text)} chars)")

    # 2e. 全局概览：RFC9250 的所有 Section 节点
    print(f"\n  RFC9250 全部 Section 节点:")
    rfc_sections = []
    for n, d in graph.nodes(data=True):
        if d.get("rfc_id") == "RFC9250" and d.get("node_type") == "Section":
            text_len = len(d.get("text", "") or "")
            rfc_sections.append((d.get("sec_num", ""), n, d.get("title", ""), text_len))
    rfc_sections.sort()
    for sec_num, nid, title, tlen in rfc_sections:
        marker = " ◄── SEED" if nid == seed_section_id else ""
        print(f"    {sec_num:>8}  {nid:<30} \"{title}\" ({tlen} chars){marker}")

    # ═══════════════════════════════════════════════════════════
    # 3. 完整 ContextPack
    # ═══════════════════════════════════════════════════════════
    banner("3. ContextPack 构建结果")

    kb = GraphKnowledgeBase(graph)

    ranker = None
    if os.path.exists(npy_path) and os.path.exists(index_path):
        ranker = SemanticRanker(
            query_backend=SentenceTransformerQueryBackend(embedding_model),
            embedding_store=NumpyEmbeddingStore(npy_path=npy_path, index_path=index_path),
            min_score=-1.0,
        )

    context_pack = GraphRAGRouter(kb, ranker).build_context_pack(seed_section_id)

    # 打印 trace
    print("\n  [Trace]")
    for t in context_pack.get("trace", []):
        print(f"    {t}")

    # 打印结构化 ContextPack（截断长文本）
    def truncate_text(obj, max_len=300):
        if isinstance(obj, dict):
            out = {}
            for k, v in obj.items():
                if k in ("text", "content", "source_text") and isinstance(v, str) and len(v) > max_len:
                    out[k] = v[:max_len] + f"... [{len(v)} chars total]"
                else:
                    out[k] = truncate_text(v, max_len)
            return out
        elif isinstance(obj, list):
            return [truncate_text(x, max_len) for x in obj]
        return obj

    # 完整版保存到文件
    output_dir = os.path.join(_SRC_DIR, "output")
    os.makedirs(output_dir, exist_ok=True)
    full_path = os.path.join(output_dir, f"{seed_section_id}_context_pack_full.json")
    with open(full_path, "w", encoding="utf-8") as f:
        json.dump(context_pack, f, ensure_ascii=False, indent=2)

    # 截断版打印到终端
    preview = truncate_text(context_pack, max_len=300)
    # 移除 trace 避免重复
    preview.pop("trace", None)
    print(f"\n  [ContextPack 结构 (文本字段截断至300字符)]")
    print(json.dumps(preview, ensure_ascii=False, indent=2))

    print(f"\n  [OUTPUT] 完整 ContextPack 已保存: {full_path}")


if __name__ == "__main__":
    main()
