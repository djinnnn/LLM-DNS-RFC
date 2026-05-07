"""
RFC 协议形式化全流程 Pipeline
==============================
整体数据流：

  RFC 文档 (RFC ID)
    └─ Phase 1: RFC 图谱构建     → rfc_processor/orchestrator.py
    └─ Phase 2: ContextPack 组装 → rfc_processor/context_builder.py
    └─ Phase 3: IR 抽取          → IR_extractor/ir_pipeline.py  [已实现]
    └─ Phase 4: Maude 代码生成   → maude_generator/
    └─ Phase 5: 形式化执行       [PLACEHOLDER]
    └─ Phase 6: 闭环修正         [PLACEHOLDER]

运行方式（从 src/ 目录）：
  python main.py
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

_SRC_DIR = os.path.dirname(os.path.abspath(__file__))

# ─── Pipeline DTOs & Config ──────────────────────────────────────────────────
from pipeline_dto import (
    PipelineConfig,
    ExecutionResult,
    RepairResult,
    EndToEndResult,
)
from pipeline_reporter import PipelineReporter

# ─── LLM 客户端 ─────────────────────────────────────────────────────────────
from llm.llm_client import BaseLLMClient, resolve_llm_endpoint
from llm.factory import create_llm_client

# ─── Phase 3 组件（IR 抽取）──────────────────────────────────────────────────
from IR_extractor.ir_pipeline import (
    IRExtractionInput,
    IRExtractionPipeline,
)

# ─── Phase 4 组件（Maude 代码生成）───────────────────────────────────────────
from maude_generator.generator import MaudeGenerator
from maude_generator.registry import NormalizationRegistry
from maude_generator.normalizer import RuleBasedNormalizer
from maude_generator.validator import MaudeValidator

# ─── Phase 1 & 2 组件（RFC 图谱 + ContextPack）──────────────────────────────
_RFC_AVAILABLE = False
_RFC_IMPORT_ERR = ""
try:
    from rfc_processor.context_builder import CachedContextBuilder
    _RFC_AVAILABLE = True
except ImportError as _e:
    _RFC_IMPORT_ERR = str(_e)


# =========================================================
# Phase 5: 形式化执行 [PLACEHOLDER]
# =========================================================

class FormalExecutor:
    """
    Phase 5: 调用 Maude 执行生成的代码。
    TODO: subprocess 调用 maude 二进制，解析 stderr 诊断。
    """

    def __init__(self, maude_executable: str = "maude"):
        self.maude_executable = maude_executable

    def execute(self, generated_code: str, target_name: str = "output.maude") -> ExecutionResult:
        # TODO: subprocess.run([self.maude_executable, ...], capture_output=True, timeout=...)
        return ExecutionResult(success=True)


# =========================================================
# Phase 6: 闭环修正 [PLACEHOLDER]
# =========================================================

class ClosedLoopRepairController:
    """
    Phase 6: 基于执行诊断驱动的闭环修正。
    TODO: diagnostics → LLM self-reflection repair → IR patch。
    """

    def repair_from_feedback(
        self,
        llm_client: BaseLLMClient,
        normalized_ir: Dict[str, Any],
        generated_code: str,
        diagnostics: List[Dict[str, Any]],
    ) -> RepairResult:
        # TODO: 根据 diagnostics 驱动 IR / 代码修正
        return RepairResult(
            success=True,
            repaired_ir=normalized_ir,
            repair_notes=["placeholder: no modification applied"],
        )


# =========================================================
# 全流程编排器
# =========================================================

class FormalizationPipeline:
    """
    RFC 协议形式化全流程编排器。
    各阶段失败时尽早返回并保留已有结果。
    """
    def __init__(
        self,
        config: PipelineConfig,
        llm_client: Optional[BaseLLMClient] = None,
        extraction_pipeline: Optional[IRExtractionPipeline] = None,
        generator: Optional[MaudeGenerator] = None,
        normalizer: Optional[RuleBasedNormalizer] = None,
        maude_validator: Optional[MaudeValidator] = None,
        registry: Optional[NormalizationRegistry] = None,
        executor: Optional[FormalExecutor] = None,
        repair_controller: Optional[ClosedLoopRepairController] = None,
    ):
        self.config = config
        self.reporter = PipelineReporter(debug=config.debug)
        self.llm_client = llm_client or self._build_llm_client(config)
        self.extraction_pipeline = extraction_pipeline or IRExtractionPipeline(
            llm_client=self.llm_client
        )
        # registry 必须先初始化，normalizer / validator 依赖它
        contract_abs = os.path.join(_SRC_DIR, config.contract_path)
        self.registry = registry or NormalizationRegistry(contract_path=contract_abs)
        self.normalizer = normalizer or RuleBasedNormalizer(self.registry)
        self.maude_validator = maude_validator or MaudeValidator(self.registry)
        self.generator = generator or MaudeGenerator()
        self.executor = executor or FormalExecutor(config.maude_executable)
        self.repair_controller = repair_controller or ClosedLoopRepairController()

        # Phase 1&2 上下文构建器（惰性初始化，仅在 rfc_processor 可用时）
        self.context_builder: Optional[CachedContextBuilder] = None
        if _RFC_AVAILABLE:
            self.context_builder = CachedContextBuilder(
                rfc_save_dir=config.rfc_save_dir,
                max_depth=config.rfc_max_depth,
                embedding_model=config.embedding_model,
                enable_embeddings=config.enable_embeddings,
                use_cache=config.use_cache,
                force_rebuild=config.force_rebuild,
                cache_dir=config.cache_dir,
            )

    @staticmethod
    def _build_llm_client(config: PipelineConfig) -> BaseLLMClient:
        endpoint = resolve_llm_endpoint(
            provider_name=config.provider_name,
            config_path=config.config_path,
        )
        return create_llm_client(
            provider=endpoint["provider"],
            model_name=config.model_name or endpoint.get("model_name", ""),
            api_key=endpoint["api_key"],
            base_url=endpoint.get("base_url"),
            default_timeout=config.ir_timeout,
            default_max_tokens=config.ir_max_tokens,
            default_max_retries=config.ir_max_retries,
        )

    def run(
        self,
        rfc_id: str,
        seed_section_id: str,
        section_text: Optional[str] = None,  # None 时自动从图谱获取
        extra_metadata: Optional[Dict[str, Any]] = None,
    ) -> EndToEndResult:
        trace: List[str] = [f"[Pipeline] 启动  rfc={rfc_id}  seed={seed_section_id}"]
        rpt = self.reporter

        # ── Phase 1 & 2 ───────────────────────────────────────────
        rpt.banner("Phase 1 & 2: RFC 图谱构建 + ContextPack 组装")
        try:
            if not self.context_builder:
                raise ImportError(f"rfc_processor 不可用: {_RFC_IMPORT_ERR}")
            context_pack, p12_trace = self.context_builder.build(rfc_id, seed_section_id)
            trace.extend(p12_trace)
            for t in p12_trace:
                rpt.detail(t)
            rpt.print_context_summary(context_pack)

        except Exception as e:
            trace.append(f"[Phase1/2] 失败: {e}")
            return EndToEndResult(
                success=False, rfc_id=rfc_id, seed_section=seed_section_id,
                errors=[str(e)], trace=trace,
            )

        # ── 自动获取 section_text ──────────────────────────────────
        if section_text is None:
            # 从 context_pack 的 seed 中提取原始文本（尝试多个可能的字段名）
            seed = context_pack.get("seed", {}) if context_pack else {}
            section_text = (
                seed.get("content", "") or 
                seed.get("text", "") or 
                seed.get("body", "") or
                seed.get("raw_text", "")
            )
            if not section_text:
                if self.config.debug:
                    rpt.debug_msg(f"[警告] seed 无内容，实际字段: {list(seed.keys())}")
                    rpt.debug_msg(f"[警告] seed 完整内容: {json.dumps(seed, ensure_ascii=False, indent=2)[:1000]}")
                trace.append("[Pipeline] 错误: 无法从图谱获取 section_text，请手动传入")
                return EndToEndResult(
                    success=False, rfc_id=rfc_id, seed_section=seed_section_id,
                    context_pack=context_pack,
                    errors=["section_text is None and cannot be extracted from graph"],
                    trace=trace,
                )
            trace.append(f"[Pipeline] 自动获取 section_text ({len(section_text)} chars)")

        # ── Phase 3: IR 抽取 ───────────────────────────────────────
        rpt.banner("Phase 3: IR 抽取 (LLM)")
        rpt.detail(f"Input: section_text ({len(section_text)} chars)")

        extraction_result = self.extraction_pipeline.run(
            data=IRExtractionInput(
                source_text=section_text,
                context_pack=context_pack,
                metadata={"doc_id": f"RFC{rfc_id}", "section": seed_section_id,
                          **(extra_metadata or {})},
            ),
            temperature=self.config.ir_temperature,
            max_tokens=self.config.ir_max_tokens,
            timeout=self.config.ir_timeout,
            max_retries=self.config.ir_max_retries,
            enable_repair=self.config.enable_ir_repair,
            debug=self.config.debug,
        )
        trace.append(f"[Phase3] IR 抽取  success={extraction_result.success}")

        rpt.detail(f"Result: success={extraction_result.success}")
        if extraction_result.errors:
            rpt.detail(f"Errors: {extraction_result.errors}")
        if extraction_result.ir:
            rules_count = len(extraction_result.ir.get('semantic_rules', []))
            rpt.detail(f"Extracted {rules_count} semantic_rules")
        if extraction_result.raw_response_text and self.config.debug:
            raw = extraction_result.raw_response_text
            print(f"\n  ── LLM Response ({len(raw)} chars) ──")
            print(raw)
            print(f"  ── End LLM Response ──\n")

        if not extraction_result.success or not extraction_result.ir:
            return EndToEndResult(
                success=False, rfc_id=rfc_id, seed_section=seed_section_id,
                context_pack=context_pack, extraction=extraction_result,
                errors=extraction_result.errors, trace=trace,
            )

        # ── Phase 4: 归一化 + 校验 + Maude 代码生成 ─────────────

        # 4a: 归一化
        rpt.banner("Phase 4a: 规则归一化 (Rule-based)")
        normalized_ir = self.normalizer.normalize(extraction_result.ir)
        unresolved = self.registry.get_unresolved()
        trace.append(f"[Phase4a] 归一化  unresolved={len(unresolved)}")
        rpt.detail(f"Registry: {len(self.registry.role.all_roles())} roles, "
                    f"{len(self.registry.event.all_patterns())} events, "
                    f"{len(self.registry.action.all_action_types())} actions, "
                    f"{len(self.registry.predicate)} predicates")
        rpt.print_normalization_detail(normalized_ir)
        if unresolved:
            rpt.detail(f"Unresolved items: {len(unresolved)}")
            for u in unresolved:
                rpt.detail(f"  [{u.field_name}] \"{u.original_value}\" (rule: {u.rule_id})", 4)

        # 4b: 校验
        rpt.banner("Phase 4b: Maude 校验")
        validation_result = self.maude_validator.validate(normalized_ir)
        trace.append(
            f"[Phase4b] 校验  valid={validation_result.valid_count}/{validation_result.total}"
            f"  generatable={validation_result.generatable_count}"
        )
        rpt.detail(f"Total: {validation_result.total}  Valid: {validation_result.valid_count}  "
                    f"Generatable: {validation_result.generatable_count}")
        for vr in validation_result.rule_results:
            status = "✓" if vr.is_valid else "✗"
            gen = "GEN" if vr.can_generate else "SKIP"
            rpt.detail(f"  [{status}|{gen}] {vr.rule_id}")
            for e in vr.errors:
                rpt.detail(f"    ERROR: {e}", 4)
            for w in vr.warnings:
                rpt.detail(f"    WARN:  {w}", 4)

        # 4c: Maude 代码生成
        rpt.banner("Phase 4c: Maude 代码生成")
        generation_result = self.generator.generate(normalized_ir, validation=validation_result)
        trace.append(f"[Phase4c] Maude 生成  success={generation_result.success}")
        rpt.detail(f"Result: success={generation_result.success}")
        if generation_result.errors:
            rpt.detail(f"Errors: {generation_result.errors}")
        if generation_result.generated_code and self.config.debug:
            print(f"\n  ── Generated Maude Code ──")
            print(generation_result.generated_code)
            print(f"  ── End Generated Code ──\n")

        if not generation_result.success:
            return EndToEndResult(
                success=False, rfc_id=rfc_id, seed_section=seed_section_id,
                context_pack=context_pack, extraction=extraction_result,
                generation=generation_result,
                final_ir=normalized_ir,
                errors=generation_result.errors, trace=trace,
            )

        # ── Phase 5: 形式化执行 ────────────────────────────────────
        rpt.banner("Phase 5: 形式化执行 [PLACEHOLDER]")
        execution_result = self.executor.execute(
            generated_code=generation_result.generated_code,
            target_name=generation_result.target_name,
        )
        trace.append(f"[Phase5] 形式化执行  success={execution_result.success}")
        rpt.detail(f"Result: success={execution_result.success} (placeholder — 未实际调用 Maude)")

        # ── Phase 6: 闭环修正（可选）──────────────────────────────
        repair_result = None
        final_ir = normalized_ir
        final_code = generation_result.generated_code

        if self.config.enable_feedback_repair and execution_result.diagnostics:
            repair_result = self.repair_controller.repair_from_feedback(
                llm_client=self.llm_client,
                normalized_ir=normalized_ir,
                generated_code=generation_result.generated_code,
                diagnostics=execution_result.diagnostics,
            )
            trace.append(f"[Phase6] 闭环修正  success={repair_result.success}")
            if repair_result.success and repair_result.repaired_ir is not None:
                final_ir = repair_result.repaired_ir
                regen = self.generator.generate(final_ir)
                if regen.success:
                    final_code = regen.generated_code

        success = extraction_result.success and generation_result.success and execution_result.success
        trace.append(f"[Pipeline] 结束  success={success}")

        rpt.banner(f"Pipeline 完成  success={success}")

        return EndToEndResult(
            success=success,
            rfc_id=rfc_id,
            seed_section=seed_section_id,
            context_pack=context_pack,
            extraction=extraction_result,
            generation=generation_result,
            execution=execution_result,
            repair=repair_result,
            final_ir=final_ir,
            final_code=final_code,
            trace=trace,
        )


# =========================================================
# Demo 入口
# =========================================================

def run_demo() -> None:
    config = PipelineConfig(
        rfc_save_dir="../../RFC_9250/",
        rfc_max_depth=1,
        config_path="llm/config.yaml",
        model_name="gemini-3.1-pro-preview",
        debug=True,
    )
    pipeline = FormalizationPipeline(config=config)
    result = pipeline.run(
        rfc_id="9250",
        seed_section_id="RFC9250_Sec4.1",
    )

    # ── 终端摘要 ──────────────────────────────────────────────
    print("\n" + "=" * 64)
    print(f"  RESULT  : {'SUCCESS' if result.success else 'FAILED'}")
    print(f"  RFC     : {result.rfc_id}   Section: {result.seed_section}")
    print("=" * 64)

    print("\n[TRACE]")
    for line in result.trace:
        print(f"  {line}")

    if result.errors:
        print("\n[ERRORS]")
        for e in result.errors:
            print(f"  {e}")

    # ── 保存输出文件 ──────────────────────────────────────────
    output_dir = os.path.join(_SRC_DIR, "output")
    os.makedirs(output_dir, exist_ok=True)

    section_tag = result.seed_section.replace("/", "_")

    if result.final_ir:
        ir_path = os.path.join(output_dir, f"{section_tag}_ir.json")
        with open(ir_path, "w", encoding="utf-8") as f:
            json.dump(result.final_ir, f, ensure_ascii=False, indent=2)
        print(f"\n[OUTPUT] IR saved to: {ir_path}")

    if result.final_code:
        code_path = os.path.join(output_dir, f"{section_tag}.maude")
        with open(code_path, "w", encoding="utf-8") as f:
            f.write(result.final_code)
        print(f"[OUTPUT] Maude code saved to: {code_path}")

    if result.context_pack:
        ctx_path = os.path.join(output_dir, f"{section_tag}_context_pack.json")
        with open(ctx_path, "w", encoding="utf-8") as f:
            json.dump(result.context_pack, f, ensure_ascii=False, indent=2)
        print(f"[OUTPUT] ContextPack saved to: {ctx_path}")


if __name__ == "__main__":
    run_demo()
