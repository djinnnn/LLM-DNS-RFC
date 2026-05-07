# -*- coding: utf-8 -*-
"""
Validator for normalized IR → Maude codegen feasibility.

四层校验：
  1. Registry 检查：归一化后的值是否在 registry 合法集合中
  2. Schema 检查：_normalized 结构是否完整
  3. Required args 检查：已映射的 action/predicate 是否具备必需参数
  4. Codegen feasibility 检查：整条规则是否满足最小代码生成条件
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .registry import NormalizationRegistry

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """单条规则的校验结果。"""
    rule_id: str
    is_valid: bool                     # 是否通过全部校验
    can_generate: bool                 # 是否满足最小代码生成条件
    errors: List[str] = field(default_factory=list)    # 必须修复的问题
    warnings: List[str] = field(default_factory=list)  # 可忽略的问题


@dataclass
class BatchValidationResult:
    """整批规则的校验结果。"""
    total: int = 0
    valid_count: int = 0
    generatable_count: int = 0
    rule_results: List[ValidationResult] = field(default_factory=list)

    @property
    def all_valid(self) -> bool:
        return self.valid_count == self.total

    def debug_summary(self) -> str:
        lines = [
            "=" * 60,
            "[DEBUG] Validation Summary",
            "=" * 60,
            f"  Total rules     : {self.total}",
            f"  Valid            : {self.valid_count}",
            f"  Generatable      : {self.generatable_count}",
            f"  Invalid          : {self.total - self.valid_count}",
        ]
        for r in self.rule_results:
            status = "OK" if r.is_valid else "FAIL"
            gen = "GEN" if r.can_generate else "SKIP"
            lines.append(f"  [{status}|{gen}] {r.rule_id}")
            for e in r.errors:
                lines.append(f"    ERROR: {e}")
            for w in r.warnings:
                lines.append(f"    WARN:  {w}")
        lines.append("=" * 60)
        return "\n".join(lines)


class MaudeValidator:
    """
    校验 normalized IR 是否满足 Maude 代码生成要求。
    """

    def __init__(self, registry: NormalizationRegistry) -> None:
        self.registry = registry

    def validate(self, normalized_ir: Dict[str, Any]) -> BatchValidationResult:
        """校验整批 semantic_rules。"""
        rules = normalized_ir.get("semantic_rules", [])
        batch = BatchValidationResult(total=len(rules))

        for idx, rule in enumerate(rules):
            result = self._validate_rule(rule, idx)
            batch.rule_results.append(result)
            if result.is_valid:
                batch.valid_count += 1
            if result.can_generate:
                batch.generatable_count += 1

        logger.debug(
            "[Validator] %d/%d valid, %d/%d generatable",
            batch.valid_count, batch.total,
            batch.generatable_count, batch.total,
        )
        return batch

    def _validate_rule(self, rule: Dict[str, Any], idx: int) -> ValidationResult:
        rule_id = rule.get("id", f"rule_{idx}")
        norm = rule.get("_normalized")

        errors: List[str] = []
        warnings: List[str] = []

        # ── 1. Schema 检查：_normalized 是否存在且结构完整 ──
        if norm is None:
            return ValidationResult(
                rule_id=rule_id, is_valid=False, can_generate=False,
                errors=["missing _normalized (rule was not normalized)"],
            )

        required_norm_fields = ["rule_id", "modality", "actor_type", "event_pattern",
                                "action_types", "predicates", "resolved"]
        for f in required_norm_fields:
            if f not in norm:
                errors.append(f"_normalized missing field: {f}")

        if errors:
            return ValidationResult(
                rule_id=rule_id, is_valid=False, can_generate=False, errors=errors,
            )

        # ── 2. Registry 检查：归一化值是否在合法集合中 ──
        modality = norm.get("modality")
        if modality and modality not in self.registry.modality.VALID:
            errors.append(f"invalid modality: '{modality}'")

        actor_type = norm.get("actor_type")
        if actor_type and not self.registry.role.is_valid(actor_type):
            errors.append(f"invalid actor_type: '{actor_type}'")
        elif actor_type is None:
            warnings.append("actor_type is unresolved")

        event_pattern = norm.get("event_pattern")
        if event_pattern and not self.registry.event.is_valid(event_pattern):
            errors.append(f"invalid event_pattern: '{event_pattern}'")
        elif event_pattern is None:
            warnings.append("event_pattern is unresolved")

        action_types = norm.get("action_types", [])
        for i, at in enumerate(action_types):
            if at and not self.registry.action.is_valid(at):
                errors.append(f"invalid action_type[{i}]: '{at}'")
            elif at is None:
                warnings.append(f"action_type[{i}] is unresolved")

        # ── 3. Required args 检查 ──
        # 对于已 resolved 的 action，检查是否有对应的 expr 描述
        actions = rule.get("actions", [])
        for i, action in enumerate(actions):
            if i < len(action_types) and action_types[i] is not None:
                expr = action.get("expr", "") if isinstance(action, dict) else ""
                if not expr:
                    warnings.append(f"action[{i}] ({action_types[i]}) has no expr description")

        # 对于 send_message 类型，检查是否能推断出目标 actor
        for i, at in enumerate(action_types):
            if at == "send_message" and i < len(actions):
                expr = actions[i].get("expr", "") if isinstance(actions[i], dict) else ""
                # 简单检查：expr 中是否包含 "to" 指示目标
                if expr and "to" not in expr.lower() and "from" not in expr.lower():
                    warnings.append(f"action[{i}] (send_message) has no target actor hint in expr")

        # ── 4. Codegen feasibility 检查 ──
        # 最小生成条件：actor_type 已知即可生成骨架规则
        # unresolved 的 event/action/condition 会以 TODO 注释形式保留
        can_generate = True

        if actor_type is None:
            can_generate = False
            warnings.append("actor_type unresolved, cannot generate rule")

        resolved_actions = [at for at in action_types if at is not None]
        if not resolved_actions:
            warnings.append("no resolved actions, rule body will be TODO placeholders")

        if event_pattern is None:
            warnings.append("event_pattern unresolved, will generate with TODO trigger")

        if modality is None:
            warnings.append("modality unresolved, will default to 'must'")

        is_valid = len(errors) == 0

        return ValidationResult(
            rule_id=rule_id,
            is_valid=is_valid,
            can_generate=can_generate and is_valid,
            errors=errors,
            warnings=warnings,
        )
