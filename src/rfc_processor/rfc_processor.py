# -*- coding: utf-8 -*-
from global_recursor import RFCGraphOrchestrator
from visualize import visualize_graph
from graph_knowledge_base import GraphKnowledgeBase
from rag_router import SemanticRanker, GraphRAGRouter

# def main():
#     # ==========================================
#     # Phase 1: 图谱构建 (Graph Construction)
#     # 包括：
#     #    + 解析RFC文档
#     #    + 节点构建、依赖关系提取（本文档和全局递归抓取）
#     #    + 构建图谱
#     # ==========================================
#     target_rfc_doc = "7858" 
#     # 限制 depth=0 仅解析当前文档，避免测试时触发大量网络请求
#     # 若需测试跨文件边连通性，可将其改为 depth=1
#     test_depth = 1
    
#     print(f"=== [Phase 1] 启动底座构建 (RFC {target_rfc_doc}, Depth={test_depth}) ===")
#     orchestrator = RFCGraphOrchestrator(max_depth=test_depth, save_dir="../../RFCs_Test/")
#     global_graph = orchestrator.fetch_and_build(target_rfc_doc)
    
#     print(f"构建完成。当前图谱规模: {global_graph.number_of_nodes()} 个节点, {global_graph.number_of_edges()} 条边。\n")
#     visualize_graph(global_graph, target_rfc_doc, test_depth, output_dir="../../RFCs_Test/")

#     # ==========================================
#     ## 上下文抽取的规则需要再优化一下
#     #   TODO: 应该还需要构造一个GraphKnowledgeBase层次，提供更丰富的查询接口
#     #   TODO: 接口包括：
#     #   + 基础访问
#     #   + 路由查询（包括本地结构和引用关系）
#     #   + 过滤
#     # ==========================================
#     kb = GraphKnowledgeBase(global_graph)
#     seed_node = "RFC7858_Sec3.1" #这里需要注意AST划分的层级，3. 这种节点只是一个标题容器，里面并没有实质的内容

#     # 2. 测试基础访问与过滤
#     print(f"种子节点信息: {kb.get_node_data(seed_node).get('title')}")
#     print(f"是否为有效协议段落: {kb.is_valid_protocol_section(seed_node)}")

#     # 3. 测试本地拓扑
#     ancestors = kb.get_ancestor_chain(seed_node)
#     print(f"\n父级作用域链:")
#     for p in ancestors:
#         print(f" -> {p.get('sec_num')} {p.get('title')}")

#     children = kb.get_descendants(seed_node)
#     print(f"\n下属细节章节:")
#     for c in children:
#         print(f" - {c.get('sec_num')} {c.get('title')}")

#     # 4. 测试横向引用
#     refs = kb.get_references(seed_node)
#     print(f"\n内部交叉引用: {[r.get('id', r.get('section_id')) for r in refs['internal']]}")
#     print(f"细粒度外部引用: {[r.get('id', r.get('section_id')) for r in refs['external_precise']]}")
#     print(f"粗粒度外部引用: {[r.get('id', r.get('rfc_id')) for r in refs['external_coarse']]}")

#     # # ==========================================
#     # # Phase 2: 局部路由与上下文提取 (Graph RAG)
#     # # TODO: 这里需要实现section-driven的路由和上下文提取
#     # # TODO: 根据seed section进行本地结构和跨RFC扩展
#     # # TODO: 跨RFC扩展分两类处理：
#     # #   1. section-level引用：直接引用其他RFC的section -> 把目标section纳入context
#     # #   2. document-level引用：进入目标RFC做后续选择
#     # #       2.1 规则筛选：标题重叠、术语重叠、（这一步要不要呢？）我想直接用rag做语义排序了
#     # #       2.2 语义筛选：检索最相关的语义
#     # # TODO: 组装ContextPack。输出包括：
#     # #   1. seed, reference_context, trace[optional](用于debug)
#     # #   2. 跨RFC引用：目标RFC的section层级、关键节点
#     # # ==========================================
    


#     # 这一部分先不做，属于后面IR的部分了
#     # ==========================================
#     # Phase 3: 状态机规则抽取 (LLM Extraction Placeholder)
#     # ==========================================
#     # 此处为后续调用大模型 API (如 OpenAI/Gemini) 预留接口
#     # extraction_prompt = f"你是一个协议形式化验证专家。请基于以下上下文，提取状态机规则：\n\n{prompt_context}"
#     # response = llm_client.generate(extraction_prompt)
#     # print(response)

def main():
    target_rfc_doc = "7858" 
    # 必须设为 1，确保 Document-Level 的目标文档被物理拉取并解析，才能进行 RAG 排序
    test_depth = 1 
    
    print(f"=== [Phase 1] 启动底座构建 (RFC {target_rfc_doc}, Depth={test_depth}) ===")
    orchestrator = RFCGraphOrchestrator(max_depth=test_depth, save_dir="../../RFCs_Test/")
    global_graph = orchestrator.fetch_and_build(target_rfc_doc)
    
    # === [Phase 2] 局部路由与 ContextPack 组装 ===
    print(f"\n=== [Phase 2] 执行 Graph RAG 路由 ===")
    
    kb = GraphKnowledgeBase(global_graph)
    ranker = SemanticRanker()
    router = GraphRAGRouter(kb, ranker)
    
    # 采用带有实际规则描述的 3.4 节作为 Testcase
    seed_node = "RFC7858_Sec3.1" 
    
    print(f"\n=== [Phase 1.5] 检查节点 {seed_node} 的原始图谱拓扑 ===")
    if global_graph.has_node(seed_node):
        node_data = global_graph.nodes[seed_node]
        print(f"【节点属性】")
        print(f"  - ID: {seed_node}")
        print(f"  - Node Type: {node_data.get('node_type')}")
        print(f"  - Title: {node_data.get('title')}")
        
        print(f"\n【出度边 (Outgoing Edges) - 包含 AST 结构与交叉引用】")
        out_edges = list(global_graph.out_edges(seed_node, data=True))
        if not out_edges:
            print("  -> (空) 该节点没有任何向外的连边。")
            
        for u, v, data in out_edges:
            edge_type = data.get('edge_type', 'Unknown')
            target_exists = global_graph.has_node(v)
            
            print(f"  -> [Edge Type: {edge_type}] ---> Target ID: {v}")
            print(f"     - 目标节点是否已在图中实例化: {target_exists}")
            
            if target_exists:
                target_data = global_graph.nodes[v]
                print(f"     - 目标节点类型: {target_data.get('node_type')}")
                print(f"     - 目标节点标题: {target_data.get('title', 'Unknown')}")
            print("-" * 40)
            
        print(f"\n【入度边 (Incoming Edges) - 检查父级作用域】")
        in_edges = list(global_graph.in_edges(seed_node, data=True))
        for u, v, data in in_edges:
             print(f"  -> Source ID: {u} ---> [Edge Type: {data.get('edge_type')}]")
             
    else:
        print(f"❌ 严重错误: 当前生成的图谱中不存在节点 {seed_node}。请检查 _extract_sections_from_text 的正则匹配是否漏掉了该章节。")
    print("========================================================\n")

    # ==== Stage 3 context pack construction ====
    context_pack = router.build_context_pack(seed_node)

    print("\n[执行 Trace 日志]")
    for t in context_pack["trace"]:
        print(t)

    print("\n[ContextPack 数据规约验证]")
    print(f"1. Seed 节点: {context_pack['seed'].get('section_id')}")
    print(
        f"2. Local 作用域: "
        f"{len(context_pack['local_structure']['ancestors'])} 父节点, "
        f"{len(context_pack['local_structure']['descendants'])} 子节点"
    )
    print(
        f"3. 规范性 section-level 引用: "
        f"{len(context_pack['references']['normative']['section_level'])} 个"
    )
    print(
        f"4. 规范性 document-level 引用: "
        f"{len(context_pack['references']['normative']['document_level'])} 个"
    )
    print(
        f"5. 信息性 section-level 引用: "
        f"{len(context_pack['references']['informative']['section_level'])} 个"
    )
    print(
        f"6. 信息性 document-level 引用: "
        f"{len(context_pack['references']['informative']['document_level'])} 个"
    )
    print(
        f"7. 语义扩展结果: "
        f"{len(context_pack['semantic_expansion'])} 个"
    )
    from pprint import pprint

    # print("\n[语义扩展结果原始结构]")
    # pprint(context_pack["semantic_expansion"])

    print("\n[完整 ContextPack Schema 输出]")
    pprint(context_pack, width=120, sort_dicts=False)

if __name__ == "__main__":
    main()