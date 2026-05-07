# -*- coding: utf-8 -*-
"""
Rule-based Normalizer for semantic IR → Maude-ready IR.

职责：
  1. modality 归一化
  2. actor.name → Maude ActorType 映射
  3. event.kind/expr → Maude event pattern 映射
  4. actions[].kind/expr → Maude action type 映射
  5. conditions[].expr → predicate 匹配（尝试）
  6. 无法匹配的项标记为 unresolved

输入：semantic_ir.json 格式的 dict
输出：同结构 dict，每条 rule 增加 _normalized 子对象
"""
from __future__ import annotations

import copy
import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .registry import NormalizationRegistry, UnresolvedItem

logger = logging.getLogger(__name__)


class RuleBasedNormalizer:
    """
    确定性字段清洗 + 基础映射。
    不调用 LLM，只用 registry 中的静态/动态映射表。
    """

    def __init__(self, registry: NormalizationRegistry) -> None:
        self.registry = registry

    def normalize(self, ir: Dict[str, Any]) -> Dict[str, Any]:
        """
        对整个 IR 做归一化。
        返回深拷贝后的 IR，原始 IR 不被修改。
        """
        result = copy.deepcopy(ir)
        rules = result.get("semantic_rules", [])

        self.registry.clear_unresolved()

        for idx, rule in enumerate(rules):
            norm = self._normalize_rule(rule, idx)
            rule["_normalized"] = norm

        logger.debug(
            "[Normalizer] processed %d rules, %d unresolved items",
            len(rules), len(self.registry.get_unresolved()),
        )
        return result

    def _normalize_rule(self, rule: Dict[str, Any], idx: int) -> Dict[str, Any]:
        """
        对单条 semantic_rule 做归一化，返回 _normalized 子对象。
        """
        rule_id = rule.get("id", f"rule_{idx}")
        norm: Dict[str, Any] = {"rule_id": rule_id, "resolved": True}

        # 1. modality
        norm["modality"] = self._normalize_modality(rule, rule_id)

        # 2. actor → Maude ActorType
        norm["actor_type"] = self._normalize_actor(rule, rule_id)

        # 3. event → Maude event pattern
        norm["event_pattern"] = self._normalize_event(rule, rule_id)

        # 4. actions → Maude action types
        norm["action_types"] = self._normalize_actions(rule, rule_id)

        # 5. conditions → predicate 匹配
        norm["predicates"] = self._normalize_conditions(rule, rule_id)

        # 如果任何字段是 unresolved，标记整条规则
        if any(v is None for v in [norm["modality"], norm["actor_type"], norm["event_pattern"]]):
            norm["resolved"] = False
        if any(a is None for a in norm["action_types"]):
            norm["resolved"] = False

        return norm

    # ─── 各字段归一化 ────────────────────────────────────────────

    def _normalize_modality(self, rule: Dict[str, Any], rule_id: str) -> Optional[str]:
        raw = rule.get("modality", "")
        if not raw:
            return None

        result = self.registry.modality.normalize(raw)
        if result is None:
            logger.debug("[Normalizer] modality unresolved: '%s' (rule: %s)", raw, rule_id)
            self.registry.add_unresolved(UnresolvedItem(
                field_name="modality", original_value=raw, rule_id=rule_id,
            ))
        return result

    def _normalize_actor(self, rule: Dict[str, Any], rule_id: str) -> Optional[str]:
        actor = rule.get("actor", {})
        raw = actor.get("name", "") if isinstance(actor, dict) else str(actor)
        if not raw:
            return None

        result = self.registry.role.normalize(raw)
        if result is None:
            logger.debug("[Normalizer] actor unresolved: '%s' (rule: %s)", raw, rule_id)
            self.registry.add_unresolved(UnresolvedItem(
                field_name="role", original_value=raw, rule_id=rule_id,
            ))
        return result

    def _normalize_event(self, rule: Dict[str, Any], rule_id: str) -> Optional[str]:
        event = rule.get("event", {})
        # 同时尝试 kind 和 expr
        kind = event.get("kind", "") if isinstance(event, dict) else ""
        expr = event.get("expr", "") if isinstance(event, dict) else ""

        # 先尝试用 kind 匹配
        result = self.registry.event.normalize(kind) if kind else None
        # 如果 kind 匹配失败，尝试用 expr 匹配
        if result is None and expr:
            result = self.registry.event.normalize(expr)

        if result is None:
            combined = f"{kind}: {expr}" if kind and expr else (kind or expr)
            logger.debug("[Normalizer] event unresolved: '%s' (rule: %s)", combined, rule_id)
            self.registry.add_unresolved(UnresolvedItem(
                field_name="event", original_value=combined, rule_id=rule_id,
                context=f"kind={kind}, expr={expr}",
            ))
        return result

    def _normalize_actions(self, rule: Dict[str, Any], rule_id: str) -> List[Optional[str]]:
        actions = rule.get("actions", [])
        results: List[Optional[str]] = []

        for i, action in enumerate(actions):
            kind = action.get("kind", "") if isinstance(action, dict) else ""
            expr = action.get("expr", "") if isinstance(action, dict) else str(action)

            # 先尝试用 expr 匹配（更具体）
            result = self.registry.action.normalize(expr) if expr else None
            # 如果 expr 失败，尝试用 kind 匹配
            if result is None and kind:
                result = self.registry.action.normalize(kind)

            if result is None:
                combined = f"{kind}: {expr}" if kind and expr else (kind or expr)
                logger.debug(
                    "[Normalizer] action[%d] unresolved: '%s' (rule: %s)", i, combined, rule_id
                )
                self.registry.add_unresolved(UnresolvedItem(
                    field_name="action", original_value=combined, rule_id=rule_id,
                    context=f"kind={kind}, expr={expr}",
                ))
            results.append(result)

        return results

    def _normalize_conditions(self, rule: Dict[str, Any], rule_id: str) -> List[Dict[str, Any]]:
        """
        尝试将 conditions 匹配到已有的 Maude predicates。
        返回每个 condition 的匹配结果（可能为 None）。
        """
        conditions = rule.get("conditions", [])
        results: List[Dict[str, Any]] = []

        for i, cond in enumerate(conditions):
            expr = cond.get("expr", "") if isinstance(cond, dict) else str(cond)
            kind = cond.get("kind", "") if isinstance(cond, dict) else ""

            # 在 predicate registry 中搜索
            matched = self.registry.predicate.search(expr) if expr else []

            if matched:
                results.append({
                    "original_expr": expr,
                    "matched_predicates": [
                        {"name": p.name, "template": p.maude_template, "source_rule": p.source_rule}
                        for p in matched
                    ],
                    "resolved": True,
                })
            else:
                logger.debug(
                    "[Normalizer] condition[%d] unresolved: '%s' (rule: %s)", i, expr, rule_id
                )
                self.registry.add_unresolved(UnresolvedItem(
                    field_name="condition", original_value=expr, rule_id=rule_id,
                    context=f"kind={kind}",
                ))
                results.append({
                    "original_expr": expr,
                    "matched_predicates": [],
                    "resolved": False,
                })

        return results


# =========================================================
# LLM 辅助归一化
# =========================================================

@dataclass
class MaudeProposal:
    """LLM 对单个 unresolved 项提出的 Maude 代码建议。"""
    unresolved_field: str       # action / event / condition / role
    original_value: str         # LLM 输出的原始值
    rule_id: str                # 所属规则 id
    strategy: str               # "reuse_existing" | "new_operator" | "new_sort" | "skip"
    maude_fragment: str         # 建议的 Maude 代码片段
    explanation: str            # LLM 对建议的解释
    confidence: str             # "high" | "medium" | "low"
    approved: Optional[bool] = None  # 人工审核结果，None=待审核


class LLMAssistedNormalizer:
    """
    第二层：LLM 语义归并。

    对 RuleBasedNormalizer 无法处理的 unresolved 项调用 LLM，
    让它基于已有 Maude 词汇表提出代码建议。

    结果保存到 proposals/ 目录供人工审核 (L3)。
    """

    PROPOSALS_DIR = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "proposals"
    )

    def __init__(self, registry: NormalizationRegistry, llm_client: Any = None) -> None:
        self.registry = registry
        self.llm_client = llm_client  # BaseLLMClient，后续注入

    # ─── 主入口 ──────────────────────────────────────────────

    def assist_normalize(
        self,
        normalized_ir: Dict[str, Any],
        unresolved_items: List[UnresolvedItem],
        context_pack: Optional[Dict[str, Any]] = None,
        save_proposals: bool = True,
    ) -> Dict[str, Any]:
        """
        对 unresolved 项调用 LLM 提出 Maude 代码建议。

        Returns:
            更新后的 normalized_ir（_normalized 中增加 _proposals 字段）
        """
        if not unresolved_items:
            logger.debug("[LLMAssist] no unresolved items, skipping")
            return normalized_ir

        if self.llm_client is None:
            logger.warning(
                "[LLMAssist] llm_client not configured, %d unresolved items remain",
                len(unresolved_items),
            )
            return normalized_ir

        # 1. 构造 prompt
        system_prompt = self._build_system_prompt()
        user_prompt = self._build_user_prompt(unresolved_items, context_pack)

        logger.debug("[LLMAssist] calling LLM for %d unresolved items", len(unresolved_items))

        # 2. 调用 LLM
        try:
            raw_text = self.llm_client.generate(
                prompt=user_prompt,
                system_prompt=system_prompt,
                temperature=0.1,
                max_tokens=4096,
                timeout=120.0,
                max_retries=2,
            )
        except Exception as e:
            logger.error("[LLMAssist] LLM call failed: %s", e)
            return normalized_ir

        # 3. 解析 LLM 响应
        proposals = self._parse_proposals(raw_text, unresolved_items)
        logger.info("[LLMAssist] got %d proposals from LLM", len(proposals))

        # 4. 保存 proposals 供人工审核
        if save_proposals and proposals:
            self._save_proposals(proposals)

        # 5. 将 proposals 挂到 normalized_ir 的对应规则上
        result = copy.deepcopy(normalized_ir)
        self._attach_proposals(result, proposals)

        return result

    # ─── Prompt 构造 ─────────────────────────────────────────

    def _build_system_prompt(self) -> str:
        return (
            "You are an expert in Maude rewriting logic and DNS protocol formalization.\n"
            "Your task is to propose Maude code fragments for protocol behaviors that don't yet "
            "exist in the current Maude model.\n"
            "Return JSON only. Do not include markdown fences or explanations outside JSON."
        )

    def _build_user_prompt(
        self,
        unresolved_items: List[UnresolvedItem],
        context_pack: Optional[Dict[str, Any]] = None,
    ) -> str:
        # 收集已有词汇摘要
        vocab = self._build_vocabulary_summary()

        # 构造 unresolved 项列表
        items_desc = []
        for i, item in enumerate(unresolved_items):
            items_desc.append({
                "index": i,
                "field": item.field_name,
                "value": item.original_value,
                "rule_id": item.rule_id,
                "context": item.context,
            })

        items_json = json.dumps(items_desc, ensure_ascii=False, indent=2)
        context_str = json.dumps(context_pack, ensure_ascii=False, indent=2) if context_pack else "{}"

        return f"""
I have protocol behaviors extracted from RFC text that cannot be mapped to the existing Maude DNS model.
Please propose Maude code fragments for each unresolved item.

## Existing Maude Vocabulary

{vocab}

## Unresolved Items

{items_json}

## RFC Context (if available)

{context_str}

## Required Output Format

Return a JSON array of proposals, one per unresolved item:
```
{{
  "proposals": [
    {{
      "index": 0,
      "strategy": "reuse_existing | new_operator | new_sort | skip",
      "maude_fragment": "the Maude code fragment (operator declaration, rule fragment, etc.)",
      "explanation": "why this mapping is appropriate",
      "confidence": "high | medium | low"
    }}
  ]
}}
```

### Strategy Guide:
- **reuse_existing**: The behavior can be expressed using existing operators/sorts with different parameters
- **new_operator**: A new Maude operator is needed (provide the `op` declaration)
- **new_sort**: A new Maude sort is needed (provide `sort` + related `op` declarations)
- **skip**: The behavior is too abstract or implementation-specific to formalize

### Rules:
1. Prefer reuse_existing when possible
2. For new_operator/new_sort, follow the naming conventions of existing operators
3. maude_fragment must be syntactically valid Maude
4. Be conservative: if uncertain, use "skip" with a clear explanation
""".strip()

    def _build_vocabulary_summary(self) -> str:
        """构造 Maude 已有词汇的紧凑摘要，供 LLM prompt 使用。"""
        lines = []

        lines.append("### Actor Types")
        for role in sorted(self.registry.role.all_roles()):
            lines.append(f"  - {role}")

        lines.append("\n### Event Patterns")
        for pat in sorted(self.registry.event.all_patterns()):
            lines.append(f"  - {pat}")

        lines.append("\n### Action Types")
        for at in sorted(self.registry.action.all_action_types()):
            lines.append(f"  - {at}")

        lines.append("\n### Guard Predicates (examples)")
        preds = self.registry.predicate.all_predicates()
        for name, entry in list(preds.items())[:8]:
            lines.append(f"  - {name}: {entry.maude_template}")
        if len(preds) > 8:
            lines.append(f"  ... ({len(preds) - 8} more)")

        lines.append("\n### State Attributes (examples)")
        attrs = self.registry.attribute.all_attributes()
        for name, entry in list(attrs.items())[:8]:
            lines.append(f"  - {name} : {entry.sort} ({entry.mode})")
        if len(attrs) > 8:
            lines.append(f"  ... ({len(attrs) - 8} more)")

        return "\n".join(lines)

    # ─── 响应解析 ────────────────────────────────────────────

    def _parse_proposals(
        self, raw_text: str, unresolved_items: List[UnresolvedItem]
    ) -> List[MaudeProposal]:
        """解析 LLM 的 JSON 响应为 MaudeProposal 列表。"""
        proposals: List[MaudeProposal] = []

        try:
            data = json.loads(raw_text)
        except json.JSONDecodeError:
            # 尝试从 markdown 代码块中提取 JSON
            import re
            match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw_text, re.DOTALL)
            if match:
                try:
                    data = json.loads(match.group(1))
                except json.JSONDecodeError:
                    logger.error("[LLMAssist] failed to parse LLM response as JSON")
                    return proposals
            else:
                logger.error("[LLMAssist] failed to parse LLM response as JSON")
                return proposals

        raw_proposals = data.get("proposals", [])
        for p in raw_proposals:
            idx = p.get("index", -1)
            if idx < 0 or idx >= len(unresolved_items):
                continue
            item = unresolved_items[idx]
            proposals.append(MaudeProposal(
                unresolved_field=item.field_name,
                original_value=item.original_value,
                rule_id=item.rule_id,
                strategy=p.get("strategy", "skip"),
                maude_fragment=p.get("maude_fragment", ""),
                explanation=p.get("explanation", ""),
                confidence=p.get("confidence", "low"),
            ))

        return proposals

    # ─── 保存 proposals 供人工审核 ───────────────────────────

    def _save_proposals(self, proposals: List[MaudeProposal]) -> str:
        """保存 proposals 到 proposals/ 目录，返回文件路径。"""
        os.makedirs(self.PROPOSALS_DIR, exist_ok=True)

        import datetime
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"proposals_{ts}.json"
        path = os.path.join(self.PROPOSALS_DIR, filename)

        data = []
        for p in proposals:
            data.append({
                "rule_id": p.rule_id,
                "field": p.unresolved_field,
                "original_value": p.original_value,
                "strategy": p.strategy,
                "maude_fragment": p.maude_fragment,
                "explanation": p.explanation,
                "confidence": p.confidence,
                "approved": p.approved,
            })

        with open(path, "w", encoding="utf-8") as f:
            json.dump({"proposals": data}, f, ensure_ascii=False, indent=2)

        logger.info("[LLMAssist] proposals saved to %s", path)
        return path

    # ─── 将 proposals 挂到 normalized_ir ─────────────────────

    def _attach_proposals(
        self, normalized_ir: Dict[str, Any], proposals: List[MaudeProposal]
    ) -> None:
        """将 proposals 按 rule_id 挂到对应规则的 _normalized._proposals 字段。"""
        # rule_id → proposals 映射
        by_rule: Dict[str, List[Dict[str, Any]]] = {}
        for p in proposals:
            entry = {
                "field": p.unresolved_field,
                "original_value": p.original_value,
                "strategy": p.strategy,
                "maude_fragment": p.maude_fragment,
                "explanation": p.explanation,
                "confidence": p.confidence,
            }
            by_rule.setdefault(p.rule_id, []).append(entry)

        for rule in normalized_ir.get("semantic_rules", []):
            rule_id = rule.get("id", "")
            if rule_id in by_rule and "_normalized" in rule:
                rule["_normalized"]["_proposals"] = by_rule[rule_id]
