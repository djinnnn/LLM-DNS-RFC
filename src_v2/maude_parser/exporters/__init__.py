"""Exporters layer.

Reads AST + ActorSemantics + inference yaml, produces JSON / DOT artifacts.
Forbidden: any new semantic inference. All heuristics live in
config/inference_rules.yaml; a miss returns the default value plus a stderr
warning (C1-y in stage_0_redesign.md).
"""
from .json_exporter import JSONExporter  # noqa: F401
