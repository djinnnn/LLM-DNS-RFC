# -*- coding: utf-8 -*-
"""Stage 0 pipeline orchestrator.

Wires: parser → semantics → exporters. Cross-cutting boundaries (file paths,
output dir) live ONLY here. Sub-modules don't read each other's outputs from
disk; everything is in-memory dataclasses.
"""
from __future__ import annotations

import logging
import os
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

from .exporters.dot_exporter import DOTExporter
from .exporters.json_exporter import JSONExporter
from .parser import MaudeParser
from .semantics import ActorResolver, ActorSemantics

LOGGER = logging.getLogger("leaf_edns.stage0.pipeline")


# Default file list mirrors the old `pipeline.py main()` (see backlog item
# F0-5: turn this into a CLI / yaml in a follow-up issue).
DEFAULT_INPUT_FILES = [
    "Maude/src/common/actor.maude",
    "Maude/src/common/parameters.maude",
    "Maude/src/common/label_graph.maude",
    "Maude/src/common/prelim.maude",
    "Maude/src/common/_aux.maude",
    "Maude/src/nondet-model/_aux.maude",
    "Maude/src/nondet-model/dns.maude",
]


def run(
    input_files: Optional[List[str]] = None,
    output_dir: Optional[str] = None,
    project_root: Optional[str] = None,
) -> Tuple[str, ActorSemantics]:
    """Parse → semantics → exporters. Returns (contract_path, semantics)."""
    project_root = project_root or _default_project_root()
    input_files = input_files or DEFAULT_INPUT_FILES
    output_dir = output_dir or os.path.join(
        os.path.dirname(__file__), "output"
    )
    os.makedirs(output_dir, exist_ok=True)

    parser = MaudeParser()
    for rel in input_files:
        path = rel if os.path.isabs(rel) else os.path.join(project_root, rel)
        parser.parse_file(path)
    LOGGER.info("parsed %d modules from %d files", len(parser.modules), len(input_files))

    sem = ActorResolver().resolve(parser.modules)
    LOGGER.info(
        "actors=%d bindings=%d unresolved=%d",
        len(sem.actor_types), len(sem.bindings), len(sem.unresolved_attribute_ops),
    )

    # Contract JSON
    json_exp = JSONExporter(parser.modules, sem)
    contract_path = os.path.join(output_dir, "maude_contract.json")
    tagging_path = os.path.join(output_dir, "tagging_system.json")
    json_exp.export_to_json(contract_path)
    json_exp.export_tagging_system(tagging_path)

    # DOT graphs (best-effort; uses legacy shape for parity)
    actor_attr_map = _legacy_actor_attribute_map(sem)
    try:
        dot_exp = DOTExporter(parser.modules, sem.actor_types, actor_attr_map)
        dot_exp.export_all(output_dir)
    except Exception as e:  # pragma: no cover — diagnostics only
        LOGGER.warning("DOT export failed: %s", e)

    return contract_path, sem


def _legacy_actor_attribute_map(sem: ActorSemantics) -> Dict[str, List[tuple]]:
    """Bridge to the legacy `Dict[actor, List[(label, sort, op_name)]]` shape
    used by the unchanged dot_exporter.
    """
    out: Dict[str, List[tuple]] = defaultdict(list)
    for b in sem.bindings:
        out[b.actor_type].append((b.attr_label, b.param_sort, b.attr_op_name))
    return dict(out)


def _default_project_root() -> str:
    # src_v2/maude_parser/pipeline.py  →  project root is two parents up.
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.abspath(os.path.join(here, "..", ".."))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(name)s [%(levelname)s] %(message)s")
    contract_path, sem = run()
    print(f"contract written to {contract_path}")
    print(f"actors: {sem.actor_types}")
    print(f"bindings: {len(sem.bindings)}  unresolved attr ops: {len(sem.unresolved_attribute_ops)}")
