# -*- coding: utf-8 -*-
"""
Maude Generator 模块 (Phase 4)。
normalized IR → 归一化 → 校验 → Maude 重写规则。
"""
from .dto import GenerationResult
from .registry import NormalizationRegistry, UnresolvedItem
from .normalizer import RuleBasedNormalizer, LLMAssistedNormalizer
from .validator import MaudeValidator, ValidationResult, BatchValidationResult
from .generator import MaudeGenerator

__all__ = [
    "GenerationResult",
    "NormalizationRegistry",
    "UnresolvedItem",
    "RuleBasedNormalizer",
    "LLMAssistedNormalizer",
    "MaudeValidator",
    "ValidationResult",
    "BatchValidationResult",
    "MaudeGenerator",
]
