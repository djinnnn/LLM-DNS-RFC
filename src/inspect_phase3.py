"""
Phase 3 单独调试脚本：IR 抽取。
不运行 Phase 1&2（直接从缓存的 ContextPack 加载），
不运行 Phase 4+。

输出：
  1. 完整的 system prompt
  2. 完整的 user prompt
  3. LLM 原始响应
  4. 解析后的 IR 结构
  5. 校验结果

用法:
  python inspect_phase3.py                         # 默认用 seed text
  python inspect_phase3.py --merge-descendants     # 合并子节点文本到 source_text
  python inspect_phase3.py --section RFC9250_Sec4.1.1  # 换一个 section
  python inspect_phase3.py --source-text "自定义文本..."
  python inspect_phase3.py --no-cache              # 不使用 IR 缓存，强制调用 LLM
"""
import argparse
import json
import os
import sys

_SRC_DIR = os.path.dirname(os.path.abspath(__file__))

from llm.llm_client import resolve_llm_endpoint
from llm.factory import create_llm_client
from IR_extractor.ir_pipeline import (
    IRExtractionInput,
    IRExtractionPipeline,
    PromptBuilder,
    IRValidator,
)


def banner(title: str):
    w = 70
    print(f"\n╔{'═' * w}╗")
    print(f"║  {title:<{w - 2}}║")
    print(f"╚{'═' * w}╝")


def load_context_pack(section_id: str) -> dict:
    """从 Phase 1&2 的缓存加载 ContextPack。"""
    # 先试 output 目录
    output_path = os.path.join(_SRC_DIR, "output", f"{section_id}_context_pack_full.json")
    if os.path.exists(output_path):
        with open(output_path, "r", encoding="utf-8") as f:
            return json.load(f)

    # 如果没有，从图谱重新构建
    print(f"[INFO] 未找到缓存的 ContextPack ({output_path})，从图谱构建...")
    import networkx as nx
    from rfc_processor.graph_knowledge_base import GraphKnowledgeBase
    from rfc_processor.rag_router import GraphRAGRouter, SemanticRanker, SentenceTransformerQueryBackend
    from rfc_processor.embedding_store import NumpyEmbeddingStore

    save_dir = "../../RFC_9250/"
    vector_dir = os.path.join(save_dir, "vector_store")
    cache_key = "9250_d1_BAAI_bge-large-en-v1.5"
    cache_file = os.path.join(vector_dir, f"cache_{cache_key}.json")

    with open(cache_file, "r") as f:
        cache_meta = json.load(f)
    graph = nx.read_graphml(cache_meta["graph_path"])
    kb = GraphKnowledgeBase(graph)

    npy_path = os.path.join(vector_dir, "section_embeddings.npy")
    index_path = os.path.join(vector_dir, "section_embedding_index.json")
    ranker = None
    if os.path.exists(npy_path) and os.path.exists(index_path):
        ranker = SemanticRanker(
            query_backend=SentenceTransformerQueryBackend("BAAI/bge-large-en-v1.5"),
            embedding_store=NumpyEmbeddingStore(npy_path=npy_path, index_path=index_path),
            min_score=-1.0,
        )

    context_pack = GraphRAGRouter(kb, ranker).build_context_pack(section_id)

    # 保存供下次使用
    os.makedirs(os.path.join(_SRC_DIR, "output"), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(context_pack, f, ensure_ascii=False, indent=2)
    print(f"[INFO] ContextPack 已保存: {output_path}")

    return context_pack


def get_source_text(context_pack: dict, merge_descendants: bool = False) -> str:
    """从 ContextPack 提取 source_text。"""
    seed = context_pack.get("seed", {})
    seed_text = seed.get("text", "") or seed.get("content", "") or ""

    if not merge_descendants:
        return seed_text

    # 合并子节点文本
    parts = [seed_text] if seed_text else []
    descendants = context_pack.get("local_structure", {}).get("descendants", [])
    for desc in descendants:
        if isinstance(desc, dict):
            desc_text = desc.get("text", "") or desc.get("content", "") or ""
            if desc_text:
                desc_title = desc.get("title", "")
                desc_sec = desc.get("sec_num", "")
                header = f"--- Section {desc_sec}: {desc_title} ---" if desc_sec else ""
                if header:
                    parts.append(header)
                parts.append(desc_text)

    return "\n\n".join(parts)


def main():
    parser = argparse.ArgumentParser(description="Phase 3 IR 抽取独立调试")
    parser.add_argument("--section", default="RFC9250_Sec4.1",
                        help="seed section ID (default: RFC9250_Sec4.1)")
    parser.add_argument("--merge-descendants", action="store_true",
                        help="将子节点文本合并到 source_text")
    parser.add_argument("--source-text", default=None,
                        help="手动指定 source_text（覆盖 ContextPack 中的文本）")
    parser.add_argument("--no-cache", action="store_true",
                        help="不使用 IR 缓存，强制重新调用 LLM")
    parser.add_argument("--model", default="gemini-3.1-pro-preview",
                        help="LLM 模型名 (default: gemini-3.1-pro-preview)")
    parser.add_argument("--provider", default=None,
                        help="LLM provider 名 (default: config.yaml 的 default_provider)")
    args = parser.parse_args()

    # ═══════════════════════════════════════════════════════════
    # 0. 加载 ContextPack
    # ═══════════════════════════════════════════════════════════
    banner("0. 加载 ContextPack")
    context_pack = load_context_pack(args.section)
    seed = context_pack.get("seed", {})
    print(f"  Section: {args.section}")
    print(f"  Title:   {seed.get('title', '')}")

    # ═══════════════════════════════════════════════════════════
    # 1. 准备 source_text
    # ═══════════════════════════════════════════════════════════
    banner("1. Source Text 准备")
    if args.source_text:
        source_text = args.source_text
        print(f"  来源: 命令行手动指定")
    else:
        source_text = get_source_text(context_pack, merge_descendants=args.merge_descendants)
        if args.merge_descendants:
            print(f"  来源: seed + descendants 合并")
        else:
            print(f"  来源: seed.text")

    print(f"  长度: {len(source_text)} chars")
    print(f"\n  ── Source Text 全文 ──")
    print(source_text)
    print(f"  ── Source Text 结束 ({len(source_text)} chars) ──")

    # ═══════════════════════════════════════════════════════════
    # 2. 构造 Prompt（不调用 LLM，先看 prompt）
    # ═══════════════════════════════════════════════════════════
    banner("2. LLM Prompt 构造")

    ir_input = IRExtractionInput(
        source_text=source_text,
        context_pack=context_pack,
        metadata={"doc_id": f"RFC9250", "section": args.section},
    )

    prompt_builder = PromptBuilder()
    system_prompt = prompt_builder.build_system_prompt()
    user_prompt = prompt_builder.build_user_prompt(ir_input)

    print(f"\n  ── System Prompt ({len(system_prompt)} chars) ──")
    print(system_prompt)
    print(f"  ── End System Prompt ──")

    print(f"\n  ── User Prompt ({len(user_prompt)} chars) ──")
    print(user_prompt)
    print(f"  ── End User Prompt ──")

    # ═══════════════════════════════════════════════════════════
    # 3. 调用 LLM
    # ═══════════════════════════════════════════════════════════
    banner("3. LLM 调用")

    endpoint = resolve_llm_endpoint(
        provider_name=args.provider,
        config_path="llm/config.yaml",
    )
    llm_client = create_llm_client(
        provider=endpoint["provider"],
        model_name=args.model or endpoint.get("model_name", ""),
        api_key=endpoint["api_key"],
        base_url=endpoint.get("base_url"),
        default_timeout=120.0,
        default_max_tokens=8192,
        default_max_retries=2,
    )
    print(f"  Provider: {endpoint.get('provider')}")
    print(f"  Model:    {args.model}")
    print(f"  Base URL: {endpoint.get('base_url', 'N/A')}")

    pipeline = IRExtractionPipeline(llm_client=llm_client)

    result = pipeline.run(
        data=ir_input,
        temperature=0.0,
        max_tokens=8192,
        timeout=120.0,
        max_retries=2,
        enable_repair=False,
        debug=True,
        use_cache=not args.no_cache,
    )

    # ═══════════════════════════════════════════════════════════
    # 4. 结果分析
    # ═══════════════════════════════════════════════════════════
    banner("4. IR 抽取结果")

    print(f"  Success: {result.success}")
    print(f"  Errors:  {result.errors}")
    print(f"  Warnings: {result.warnings}")

    if result.raw_response_text:
        print(f"\n  ── LLM 原始响应 ({len(result.raw_response_text)} chars) ──")
        print(result.raw_response_text)
        print(f"  ── End LLM 响应 ──")

    if result.ir:
        rules = result.ir.get("semantic_rules", [])
        print(f"\n  提取到 {len(rules)} 条 semantic_rules:")
        for i, rule in enumerate(rules):
            print(f"\n  ── Rule {i}: {rule.get('id', '?')} ──")
            print(f"    modality: {rule.get('modality', '?')}")
            actor = rule.get('actor', {})
            print(f"    actor:    {actor.get('name', '?')} (type={actor.get('type', '?')})")
            event = rule.get('event', {})
            print(f"    event:    {event.get('kind', '?')}: {event.get('expr', '?')}")
            for j, cond in enumerate(rule.get('conditions', [])):
                print(f"    cond[{j}]:  {cond.get('kind', '?')}: {cond.get('expr', '?')}")
            for j, act in enumerate(rule.get('actions', [])):
                print(f"    act[{j}]:   {act.get('kind', '?')}: {act.get('expr', '?')}")
            prov = rule.get('provenance', {})
            print(f"    source:   {prov.get('document', '?')} {prov.get('section', '?')}")
            src_text = prov.get('source_text', '')
            if src_text:
                print(f"    excerpt:  {src_text[:150]}{'...' if len(src_text) > 150 else ''}")

        # 校验
        validator = IRValidator()
        errors = validator.validate(result.ir)
        if errors:
            print(f"\n  ── 校验错误 ({len(errors)}) ──")
            for e in errors:
                print(f"    {e}")
        else:
            print(f"\n  ── 校验通过 ──")

    # 保存结果
    output_dir = os.path.join(_SRC_DIR, "output")
    os.makedirs(output_dir, exist_ok=True)

    if result.ir:
        ir_path = os.path.join(output_dir, f"{args.section}_phase3_ir.json")
        with open(ir_path, "w", encoding="utf-8") as f:
            json.dump(result.ir, f, ensure_ascii=False, indent=2)
        print(f"\n  [OUTPUT] IR saved: {ir_path}")

    # 保存完整的调试信息
    debug_info = {
        "section": args.section,
        "source_text_length": len(source_text),
        "merge_descendants": args.merge_descendants,
        "system_prompt": system_prompt,
        "user_prompt": user_prompt,
        "llm_response": result.raw_response_text,
        "success": result.success,
        "errors": result.errors,
        "ir": result.ir,
    }
    debug_path = os.path.join(output_dir, f"{args.section}_phase3_debug.json")
    with open(debug_path, "w", encoding="utf-8") as f:
        json.dump(debug_info, f, ensure_ascii=False, indent=2)
    print(f"  [OUTPUT] Debug info saved: {debug_path}")


if __name__ == "__main__":
    main()
