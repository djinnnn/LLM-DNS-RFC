from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from llm.llm_client import BaseLLMClient, LLMError, LLMResponseError


@dataclass
class IRExtractionInput:
    """
    输入给 IR 抽取器的数据对象。
    目前先支持最核心字段，后面可以逐步扩展。
    """
    source_text: str
    context_pack: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class IRExtractionResult:
    """
    IR 抽取结果。
    """
    success: bool
    ir: Optional[Dict[str, Any]] = None
    raw_response_text: str = ""
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


class PromptBuilder:
    """
    负责把 source_text / context_pack 组装成 prompt。
    """

    def build_system_prompt(self) -> str:
        return (
            "You are an expert in DNS protocol formalization.\n"
            "Your task is to extract ECA-style (Event-Condition-Action) rules from RFC text "
            "for formal verification in Maude rewriting logic.\n"
            "You must identify all protocol behaviors — including those expressed implicitly "
            "(e.g., 'is indicated by selecting X' implies the actor MUST select X).\n"
            "Return JSON only. Do not include markdown fences or explanations outside JSON."
        )

    def build_user_prompt(self, data: IRExtractionInput) -> str:
        metadata_str = json.dumps(data.metadata, ensure_ascii=False, indent=2) if data.metadata else "{}"

        # 从 context_pack 中提取结构化上下文（不再 dump 整个 JSON）
        ctx_parts = []
        if data.context_pack:
            # ancestors
            ancestors = data.context_pack.get("local_structure", {}).get("ancestors", [])
            if ancestors:
                anc_strs = []
                for a in ancestors:
                    if isinstance(a, dict):
                        anc_strs.append(f"  - {a.get('sec_num', '?')} {a.get('title', '')}")
                ctx_parts.append("Parent sections:\n" + "\n".join(anc_strs))

            # descendants (include their text as supplementary content)
            descendants = data.context_pack.get("local_structure", {}).get("descendants", [])
            if descendants:
                for d in descendants:
                    if isinstance(d, dict):
                        d_text = d.get("text", "") or d.get("content", "") or ""
                        if d_text:
                            ctx_parts.append(
                                f"Subsection {d.get('sec_num', '?')}: {d.get('title', '')}\n"
                                f'"""\n{d_text}\n"""'
                            )

            # normative references
            refs = data.context_pack.get("references", {})
            norm_sec = refs.get("normative", {}).get("section_level", [])
            if norm_sec:
                ref_strs = []
                for r in norm_sec:
                    t = r.get("target_node", {})
                    ref_strs.append(f"  - {t.get('section_id', '?')} {t.get('title', '')}")
                ctx_parts.append("Normative section references:\n" + "\n".join(ref_strs))

            # semantic expansion
            sem = data.context_pack.get("semantic_expansion", [])
            if sem:
                sem_strs = []
                for s in sem:
                    r = s.get("retrieved_section", {})
                    r_text = r.get("text", "") or r.get("content", "") or ""
                    if r_text:
                        sem_strs.append(
                            f"  [{r.get('section_id', '?')}] {r.get('title', '')}: "
                            f"{r_text[:300]}..."
                        )
                ctx_parts.append("Related sections (semantic expansion):\n" + "\n".join(sem_strs))

        context_str = "\n\n".join(ctx_parts) if ctx_parts else "(no additional context)"

        return f"""
Extract all protocol behavior rules from the following RFC text into ECA-style IR.
The source text is the primary section; subsections below it contain more detailed requirements.
Extract rules from BOTH the source text AND any subsection text provided.

## Target IR format

```json
{{
  "semantic_rules": [
    {{
      "id": "string (unique rule identifier, e.g. server-listen-port-853)",
      "modality": "MUST | SHOULD | MAY | MUST_NOT | UNSPECIFIED",
      "actor": {{
        "name": "string — use specific DNS roles: DNS client, DNS server, resolver, stub resolver, nameserver. Avoid generic terms like 'endpoint' or 'implementation'.",
        "type": "role | component | endpoint"
      }},
      "event": {{
        "kind": "recv | send | timeout | internal | state_trigger",
        "expr": "string (natural language description)"
      }},
      "conditions": [
        {{
          "kind": "guard | state_check | predicate",
          "expr": "string"
        }}
      ],
      "actions": [
        {{
          "kind": "send | state_update | drop | ignore | reply | error | transition",
          "expr": "string"
        }}
      ],
      "provenance": {{
        "document": "string (e.g. RFC9250)",
        "section": "string (e.g. Section 4.1)",
        "anchor": "string (key phrase)",
        "source_text": "string (verbatim excerpt)"
      }}
    }}
  ]
}}
```

## Source text (primary section)

\"\"\"
{data.source_text}
\"\"\"

## Additional context

{context_str}

## Metadata

{metadata_str}

## Few-shot examples

Below are two examples showing how RFC text maps to ECA-style IR.

### Example 1 — Explicit MUST, single actor, init event

RFC text: "By default, a DNS server that supports DoQ MUST listen for and accept QUIC connections on the dedicated UDP port 853, unless there is a mutual agreement to use another port."

```json
{{
  "semantic_rules": [
    {{
      "id": "server-listen-port-853",
      "modality": "MUST",
      "actor": {{ "name": "DNS server", "type": "role" }},
      "event": {{ "kind": "internal", "expr": "server supports DoQ" }},
      "conditions": [
        {{ "kind": "guard", "expr": "no mutual agreement to use another port" }}
      ],
      "actions": [
        {{ "kind": "state_update", "expr": "listen for and accept QUIC connections on UDP port 853" }}
      ],
      "provenance": {{
        "document": "RFC9250",
        "section": "Section 4.1.1",
        "anchor": "MUST listen for and accept",
        "source_text": "By default, a DNS server that supports DoQ MUST listen for and accept QUIC connections on the dedicated UDP port 853, unless there is a mutual agreement to use another port."
      }}
    }}
  ]
}}
```

### Example 2 — MUST NOT, error handling, conditional event

RFC text: "Servers MUST NOT continue processing a DNS transaction if they receive a RESET_STREAM request from the client before the client indicates the STREAM FIN."

```json
{{
  "semantic_rules": [
    {{
      "id": "server-stop-on-reset-stream",
      "modality": "MUST_NOT",
      "actor": {{ "name": "DNS server", "type": "role" }},
      "event": {{ "kind": "recv", "expr": "receive RESET_STREAM request from client" }},
      "conditions": [
        {{ "kind": "guard", "expr": "client has not yet indicated STREAM FIN" }}
      ],
      "actions": [
        {{ "kind": "drop", "expr": "stop processing the DNS transaction" }}
      ],
      "provenance": {{
        "document": "RFC9250",
        "section": "Section 4.3.1",
        "anchor": "MUST NOT continue processing",
        "source_text": "Servers MUST NOT continue processing a DNS transaction if they receive a RESET_STREAM request from the client before the client indicates the STREAM FIN."
      }}
    }}
  ]
}}
```

## Requirements

1. Return valid JSON only.
2. Extract rules from BOTH the source text AND any subsection text provided above.
3. For **modality inference**:
   - If the text uses RFC 2119 keywords (MUST, SHOULD, MAY, MUST_NOT), use them directly.
   - If the text describes a mandatory behavior without an explicit keyword (e.g., "is indicated by selecting X", "connections are established as described in Y"), infer the appropriate modality (typically MUST).
   - Use UNSPECIFIED only when the obligation level is genuinely ambiguous.
4. For **actor identification**:
   - Use specific DNS roles: "DNS client", "DNS server", "resolver", "stub resolver", "nameserver".
   - If both client and server must perform the same action, create separate rules for each.
   - Avoid generic terms like "endpoint" or "implementation".
5. The "provenance.source_text" MUST be a verbatim excerpt from the provided text.
6. Each distinct protocol requirement should be a separate rule.
""".strip()



class IRValidator:
    """
    对 IR 结构做基础校验。
    当前先做最小校验。
    """

    def validate(self, ir_json: Dict[str, Any]) -> List[str]:
        errors: List[str] = []

        if not isinstance(ir_json, dict):
            return ["IR 顶层必须是 dict"]

        if "semantic_rules" not in ir_json:
            return ["IR 缺少顶层字段 semantic_rules"]

        if not isinstance(ir_json["semantic_rules"], list):
            return ["IR 字段 semantic_rules 必须是 list"]

        for idx, rule in enumerate(ir_json["semantic_rules"]):
            if not isinstance(rule, dict):
                errors.append(f"semantic_rules[{idx}] 必须是 dict")
                continue

            required_fields = ["id", "modality", "actor", "event", "conditions", "actions", "provenance"]
            for field_name in required_fields:
                if field_name not in rule:
                    errors.append(f"semantic_rules[{idx}] 缺少字段: {field_name}")

            # actor 子字段校验
            if "actor" in rule and isinstance(rule["actor"], dict):
                for sub in ["name", "type"]:
                    if sub not in rule["actor"]:
                        errors.append(f"semantic_rules[{idx}].actor 缺少字段: {sub}")

            # event 子字段校验
            if "event" in rule and isinstance(rule["event"], dict):
                for sub in ["kind", "expr"]:
                    if sub not in rule["event"]:
                        errors.append(f"semantic_rules[{idx}].event 缺少字段: {sub}")

        return errors


class IRRepairer:
    """
    当模型输出结构不合格时，后续可以在这里做 repair round。
    当前先放 placeholder。
    """

    def repair(
        self,
        llm_client: BaseLLMClient,
        invalid_json: Dict[str, Any],
        validation_errors: List[str],
    ) -> Dict[str, Any]:
        # placeholder:
        # 后面可以加：
        # - 基于 validation_errors 的二次提示修复
        # - JSON schema repair
        # - fallback 映射
        return invalid_json


class IRExtractionPipeline:
    """
    IR 提取主流程。
    """

    def __init__(
        self,
        llm_client: BaseLLMClient,
        prompt_builder: Optional[PromptBuilder] = None,
        validator: Optional[IRValidator] = None,
        repairer: Optional[IRRepairer] = None,
        cache_dir: Optional[str] = None,
    ):
        self.llm_client = llm_client
        self.prompt_builder = prompt_builder or PromptBuilder()
        self.validator = validator or IRValidator()
        self.repairer = repairer or IRRepairer()
        # 缓存目录：默认在 IR_extractor/.ir_cache/
        self.cache_dir = cache_dir or os.path.join(
            os.path.dirname(os.path.abspath(__file__)), ".ir_cache"
        )

    @staticmethod
    def _cache_key(data: IRExtractionInput) -> str:
        """根据输入内容生成缓存 key（sha256 前 16 位）。"""
        blob = json.dumps({
            "source_text": data.source_text,
            "context_pack": data.context_pack,
            "metadata": data.metadata,
        }, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(blob.encode()).hexdigest()[:16]

    def _load_cache(self, key: str) -> Optional[IRExtractionResult]:
        path = os.path.join(self.cache_dir, f"{key}.json")
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                cached = json.load(f)
            return IRExtractionResult(
                success=cached["success"],
                ir=cached.get("ir"),
                raw_response_text=cached.get("raw_response_text", ""),
                errors=cached.get("errors", []),
                warnings=cached.get("warnings", []),
            )
        except Exception:
            return None

    def _save_cache(self, key: str, result: IRExtractionResult) -> None:
        os.makedirs(self.cache_dir, exist_ok=True)
        path = os.path.join(self.cache_dir, f"{key}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({
                "success": result.success,
                "ir": result.ir,
                "raw_response_text": result.raw_response_text,
                "errors": result.errors,
                "warnings": result.warnings,
            }, f, ensure_ascii=False, indent=2)

    def run(
        self,
        data: IRExtractionInput,
        temperature: float = 0.0,
        max_tokens: Optional[int] = 2000,
        timeout: Optional[float] = 120.0,
        max_retries: int = 2,
        enable_repair: bool = False,
        debug: bool = False,
        use_cache: bool = True,
    ) -> IRExtractionResult:
        # ── 缓存命中检查 ──
        cache_key = self._cache_key(data)
        if use_cache:
            cached = self._load_cache(cache_key)
            if cached is not None:
                if debug:
                    print(f"[DEBUG] IR cache HIT (key={cache_key})")
                return cached
            elif debug:
                print(f"[DEBUG] IR cache MISS (key={cache_key})")

        system_prompt = self.prompt_builder.build_system_prompt()
        user_prompt = self.prompt_builder.build_user_prompt(data)

        # Debug: 输出完整的 prompt 内容
        if debug:
            print("[DEBUG] " + "=" * 50)
            print("[DEBUG] IR Extraction: 完整 Prompt 内容")
            print(f"[DEBUG]   system_prompt ({len(system_prompt)} chars)")
            print(f"[DEBUG]   user_prompt ({len(user_prompt)} chars)")
            print(f"[DEBUG]   max_tokens: {max_tokens}")
            print("[DEBUG] --- USER PROMPT START ---")
            # 显示完整的 user_prompt（截取前 3000 字符）
            if len(user_prompt) > 3000:
                print(user_prompt[:3000])
                print(f"\n... [截断，剩余 {len(user_prompt) - 3000} chars] ...")
            else:
                print(user_prompt)
            print("[DEBUG] --- USER PROMPT END ---")
            print("[DEBUG] " + "=" * 50)

        try:
            raw_text = self.llm_client.generate(
                prompt=user_prompt,
                system_prompt=system_prompt,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=timeout,
                max_retries=max_retries,
            )
        except LLMError as e:
            return IRExtractionResult(
                success=False,
                raw_response_text="",
                errors=[f"LLM 调用失败: {str(e)}"],
            )

        try:
            ir_json = json.loads(raw_text)
        except json.JSONDecodeError as e:
            return IRExtractionResult(
                success=False,
                raw_response_text=raw_text,
                errors=[f"模型输出不是合法 JSON: {str(e)}"],
            )

        validation_errors = self.validator.validate(ir_json)

        if validation_errors and enable_repair:
            repaired_ir = self.repairer.repair(
                llm_client=self.llm_client,
                invalid_json=ir_json,
                validation_errors=validation_errors,
            )
            ir_json = repaired_ir
            validation_errors = self.validator.validate(ir_json)

        if validation_errors:
            return IRExtractionResult(
                success=False,
                ir=ir_json,
                raw_response_text=raw_text,
                errors=validation_errors,
            )

        result = IRExtractionResult(
            success=True,
            ir=ir_json,
            raw_response_text=raw_text,
        )

        # 成功时写入缓存
        if use_cache:
            self._save_cache(cache_key, result)
            if debug:
                print(f"[DEBUG] IR cache SAVED (key={cache_key})")

        return result