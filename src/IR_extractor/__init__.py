# -*- coding: utf-8 -*-
"""
IR Extractor 模块 (Phase 3)。
通过 LLM 从 RFC 文本中抽取 ECA-style 中间表示 (Intermediate Representation)。
"""
from .ir_pipeline import (
    IRExtractionInput,
    IRExtractionResult,
    IRExtractionPipeline,
)

__all__ = [
    "IRExtractionInput",
    "IRExtractionResult",
    "IRExtractionPipeline",
]
