import os
import sys
import json

# 添加 llm/ 到 path 以支持 flat import
_PARENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LLMM_DIR = os.path.join(_PARENT_DIR, "llm")
if _LLMM_DIR not in sys.path:
    sys.path.insert(0, _LLMM_DIR)

from factory import create_llm_client
from ir_pipeline import IRExtractionInput, IRExtractionPipeline
from llm_client import resolve_llm_endpoint


def main():
    model_name = "gemini-3.1-pro-preview"
    endpoint = resolve_llm_endpoint("proxy")

    llm_client = create_llm_client(
        provider=endpoint["provider"],
        model_name=model_name,
        api_key=endpoint["api_key"],
        base_url=endpoint.get("base_url"),
        default_timeout=endpoint.get("timeout", 120),
        default_max_tokens=endpoint.get("max_tokens", 8192),
        default_max_retries=endpoint.get("max_retries", 2),
    )

    pipeline = IRExtractionPipeline(llm_client=llm_client)

    data = IRExtractionInput(
        source_text="If the resolver receives a query and the name is not blocked, it must forward the query to the nameserver.",
        context_pack={"role_hint": "Resolver"},
        metadata={"doc_id": "RFC-PLACEHOLDER"},
    )

    result = pipeline.run(data=data, max_tokens=8192, debug=True)

    print("success =", result.success)
    print("errors  =", result.errors)
    print(json.dumps(result.ir, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()