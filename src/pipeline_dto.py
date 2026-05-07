# -*- coding: utf-8 -*-
"""
Pipeline 数据传输对象与配置。
纯数据定义，不包含编排逻辑。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from IR_extractor.ir_pipeline import IRExtractionResult
from maude_generator.dto import GenerationResult


# =========================================================
# PipelineConfig
# =========================================================

@dataclass
class PipelineConfig:
    """全流程统一配置。"""
    rfc_save_dir: str = "../../RFCs_Test/"
    rfc_max_depth: int = 1
    enable_embeddings: bool = True
    embedding_model: str = "BAAI/bge-large-en-v1.5"

    # ── 缓存配置 ────────────────────────────────────────────
    use_cache: bool = True           # 是否启用 Phase 1&2 缓存
    force_rebuild: bool = False      # 强制重建图谱和 embedding
    cache_dir: Optional[str] = None  # 缓存目录，None 则使用 vector_store

    provider_name: Optional[str] = None
    config_path: str = "llm/config.yaml"  # LLM 配置已移到 llm/ 目录
    model_name: Optional[str] = None

    ir_temperature: float = 0.0
    ir_max_tokens: int = 8192  # 增大以避免输出截断
    ir_max_retries: int = 2
    ir_timeout: float = 120.0
    enable_ir_repair: bool = False

    maude_executable: str = "maude"
    contract_path: str = "maude_parser/output/maude_contract.json"  # Maude contract for registry
    enable_feedback_repair: bool = False

    # ── Debug 配置 ────────────────────────────────────────────
    debug: bool = False  # 是否输出详细调试信息


# =========================================================
# Phase 5 / 6 DTOs
# =========================================================

@dataclass
class ExecutionResult:
    """Phase 5 输出：形式化执行诊断。"""
    success: bool
    stdout: str = ""
    stderr: str = ""
    diagnostics: List[Dict[str, Any]] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


@dataclass
class RepairResult:
    """Phase 6 输出：闭环修正结果。"""
    success: bool
    repaired_ir: Optional[Dict[str, Any]] = None
    repair_notes: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


@dataclass
class EndToEndResult:
    """全流程汇总结果。"""
    success: bool
    rfc_id: str = ""
    seed_section: str = ""
    context_pack: Optional[Dict[str, Any]] = None
    extraction: Optional[IRExtractionResult] = None
    generation: Optional[GenerationResult] = None
    execution: Optional[ExecutionResult] = None
    repair: Optional[RepairResult] = None
    final_ir: Optional[Dict[str, Any]] = None
    final_code: str = ""
    errors: List[str] = field(default_factory=list)
    trace: List[str] = field(default_factory=list)
