# -*- coding: utf-8 -*-
"""
Stage 0 probe — Maude contract 抽取 (walk-pipeline)

目的:
    在最小输入 (Maude/src/common/actor.maude, 58 行) 上跑通整条
    "regex 抽取 → MaudeContract → JSON" 流水线，让你看到每一步
    实际产出什么样的数据结构。

运行:
    cd src/
    python -m tests.walkthrough.stage_0_maude_contract

输出:
    1. 内部 AST (MaudeExtractor.modules) 的关键字段
    2. actor_types / actor_attributes 状态
    3. 完整的 MaudeContract dict (会写到 src/tmp_output/walkthrough/stage_0_contract.json)
    4. JSON 中 sorts / actors / rules / sort_hierarchy 的精简打印

不会覆盖 src/maude_parser/output/maude_contract.json。
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, is_dataclass
from pprint import pprint

_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.abspath(os.path.join(_HERE, "..", ".."))
_REPO = os.path.abspath(os.path.join(_SRC, ".."))
sys.path.insert(0, _SRC)

from maude_parser.extractors.maude_extractor import MaudeExtractor  # noqa: E402
from maude_parser.exporters.json_exporter import JSONExporter  # noqa: E402


# ---------- helpers ---------- #

def _module_summary(mod) -> dict:
    return {
        "name": mod.name,
        "type": mod.type,
        "imports": mod.imports,
        "sorts": mod.sorts,
        "subsorts": mod.subsorts,
        "n_ops": len(mod.ops),
        "ops_sample": [
            {"name": o.name, "arity": o.arity, "coarity": o.coarity,
             "attrs": o.attrs, "is_attribute": o.is_attribute}
            for o in mod.ops[:6]
        ],
        "vars": mod.vars,
        "n_eqs": len(mod.eqs),
        "n_rules": len(mod.rules),
        "views": [(v.name, v.from_module, v.to_module, v.sort_mapping) for v in mod.views],
    }


def _to_jsonable(obj):
    if is_dataclass(obj):
        return _to_jsonable(asdict(obj))
    if isinstance(obj, dict):
        return {k: _to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_jsonable(x) for x in obj]
    if isinstance(obj, set):
        return sorted(_to_jsonable(x) for x in obj)
    return obj


def main() -> None:
    target = os.path.join(_REPO, "Maude", "src", "common", "actor.maude")
    print(f"[INPUT] {target}")
    print(f"[INPUT] file size: {os.path.getsize(target)} bytes")
    print()

    extractor = MaudeExtractor()
    extractor.parse_file(target)

    # ---- 1. 内部 AST ---- #
    print("=" * 70)
    print("1) MaudeExtractor.modules (after parse_file)")
    print("=" * 70)
    for name, mod in extractor.modules.items():
        print(f"\n--- module: {name} ---")
        pprint(_module_summary(mod), sort_dicts=False, width=110)

    print()
    print("=" * 70)
    print("2) actor_types & actor_attributes")
    print("=" * 70)
    print(f"actor_types       = {extractor.actor_types}")
    print(f"actor_attributes  = {dict(extractor.actor_attributes)}")
    print()
    print("# 注意: 在 actor.maude 这个最小输入里, 没有任何 op 的 coarity 是 'ActorType',")
    print("# 因此 actor_types 应当是空 list. 这印证了 Stage 0 对 actor 识别的硬约定 ——")
    print("# 真正的 actor 定义住在 Maude/src/nondet-model/dns.maude.")

    # ---- 3. JSON contract ---- #
    exporter = JSONExporter(
        modules=extractor.modules,
        actor_types=extractor.actor_types,
        actor_attributes=extractor.actor_attributes,
    )

    out_dir = os.path.join(_SRC, "tmp_output", "walkthrough")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "stage_0_contract.json")
    exporter.export_to_json(out_path)
    print()
    print("=" * 70)
    print(f"3) MaudeContract written to: {out_path}")
    print("=" * 70)

    with open(out_path, "r", encoding="utf-8") as f:
        contract = json.load(f)

    print(f"\nkeys at top level: {list(contract.keys())}")
    print(f"\nmetadata: {contract.get('metadata')}")
    print(f"\nsorts ({len(contract.get('sorts', {}))}): {list(contract.get('sorts', {}).keys())}")
    print(f"\nactors: {list(contract.get('actors', {}).keys())}  "
          f"(empty when input has no ActorType ops)")
    print(f"\nrules: {list(contract.get('rules', {}).keys())}  "
          f"(empty when input is a fmod-only file)")
    print(f"\nsort_hierarchy:")
    pprint(contract.get("sort_hierarchy", {}), sort_dicts=False, width=110)

    # 单独打印一个 sort 的完整契约, 便于看到 ctor / ops / subsorts 是怎么聚合上去的
    print()
    print("--- example: contract['sorts']['Address'] ---")
    pprint(contract.get("sorts", {}).get("Address", {}), sort_dicts=False, width=110)


if __name__ == "__main__":
    main()
