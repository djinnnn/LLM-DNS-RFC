# -*- coding: utf-8 -*-
"""JSON contract exporter (rev2).

Slimmed: this module only **assembles** facts produced by the parser and the
`ActorResolver`. All heuristic dispatch is delegated to `inference.py`; this
module is forbidden from doing string regex (see stage_0_redesign.md §1).

Per-method handling vs the legacy `src/.../json_exporter.py` (memo §4 table):

  - `_extract_sort_contracts`        → kept (small adjustment)
  - `_extract_actor_contracts`       → REWRITTEN: feeds off ActorSemantics.bindings
  - `_extract_rule_contracts`        → kept structure; heuristics → inference.*
  - `_dispatch_actor_role`           → kept (was `_infer_actor_role`); renamed
                                       to acknowledge it's dispatch, not inference
  - `_infer_event_pattern/_state_access/_action_slots/_generate_rule_tags` → DELETED;
                                       all four moved to inference.py
"""
from __future__ import annotations

import json
import logging
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

from ..models.contract import (
    AccessMode, ActionSlot, ActorContract, EntityTags, GuardSlot, MaudeContract,
    RuleContract, SortContract, StateAccess, TaggingSystem,
)
from ..models.maude_ast import Module, Rule
from ..semantics.actor_resolver import ActorSemantics
from . import inference

LOGGER = logging.getLogger("leaf_edns.stage0.exporter")


class JSONExporter:
    def __init__(self, modules: Dict[str, Module], semantics: ActorSemantics):
        self.modules = modules
        self.semantics = semantics

    # =====================================================================
    # Public entrypoints
    # =====================================================================

    def export_to_json(self, output_path: str, indent: int = 2) -> None:
        contract = self.export_contract()
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(self._contract_to_dict(contract), f, indent=indent, ensure_ascii=False)

    def export_tagging_system(self, output_path: str, indent: int = 2) -> None:
        tagging = self._build_tagging_system()
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(self._tagging_to_dict(tagging), f, indent=indent, ensure_ascii=False)

    def export_contract(self) -> MaudeContract:
        contract = MaudeContract()
        contract.metadata = {
            "model_type": "nondet-dns",
            "version": "1.0",
            "total_modules": len(self.modules),
            "total_actors": len(self.semantics.actor_types),
            "total_rules": sum(len(m.rules) for m in self.modules.values()),
        }
        contract.sorts = self._extract_sort_contracts()
        contract.actors = self._extract_actor_contracts()
        contract.rules = self._extract_rule_contracts()
        contract.modules = self._extract_module_info()
        contract.sort_hierarchy = self._extract_sort_hierarchy()
        # B2-y: surface ops declared as Attribute that no rule LHS ever uses.
        contract.unresolved = {
            "attribute_ops": sorted(o.name for o in self.semantics.unresolved_attribute_ops),
        }
        return contract

    # =====================================================================
    # Sorts (parity with legacy)
    # =====================================================================

    def _extract_sort_contracts(self) -> Dict[str, SortContract]:
        sort_contracts: Dict[str, SortContract] = {}

        # Pass 1: declarations
        for mod_name, module in self.modules.items():
            for sort in module.sorts:
                if sort not in sort_contracts:
                    sort_contracts[sort] = SortContract(name=sort, defined_in=mod_name)

        # Pass 2: ops as constructors / operators
        for module in self.modules.values():
            for op in module.ops:
                if op.coarity in sort_contracts:
                    if "ctor" in op.attrs:
                        sort_contracts[op.coarity].constructors.append({
                            "name": op.name, "params": op.arity,
                        })
                    else:
                        sort_contracts[op.coarity].operators.append({
                            "name": op.name, "arity": op.arity, "coarity": op.coarity,
                        })

        # Pass 3: subsort relationships
        for module in self.modules.values():
            for child, parent in module.subsorts:
                if parent in sort_contracts:
                    sort_contracts[parent].subsorts.append(child)
                if child in sort_contracts:
                    sort_contracts[child].supersorts.append(parent)

        # Pass 4: which actors use which sort (via bindings)
        sort_to_actors: Dict[str, set] = defaultdict(set)
        for b in self.semantics.bindings:
            if b.param_sort:
                sort_to_actors[b.param_sort].add(b.actor_type)
        for sort_name, actors in sort_to_actors.items():
            if sort_name in sort_contracts:
                sort_contracts[sort_name].used_by_actors = actors

        return sort_contracts

    # =====================================================================
    # Actors (rewritten — F0-3 fix manifests here)
    # =====================================================================

    def _extract_actor_contracts(self) -> Dict[str, ActorContract]:
        out: Dict[str, ActorContract] = {}
        # Where each actor was declared (first module containing the op).
        defined_in: Dict[str, str] = {}
        for mod_name, module in self.modules.items():
            for op in module.ops:
                if op.coarity == "ActorType" and not op.arity:
                    defined_in.setdefault(op.name, mod_name)

        for actor_name in self.semantics.actor_types:
            ac = ActorContract(name=actor_name, defined_in=defined_in.get(actor_name, ""))

            # State interface: ONLY actually-bound attributes (B2-y / F0-3).
            for b in self.semantics.attributes_of(actor_name):
                ac.state_interface[b.attr_label] = StateAccess(
                    attribute=b.attr_label,
                    sort=b.param_sort,
                    mode=AccessMode(inference.classify_attr_access(b.attr_label)),
                )

            # Message interface + rules_handled: substring-match by rule name
            # (this is dispatch, not inference; preserved per memo §4 table).
            receives: set = set()
            sends: set = set()
            rules_handled: List[str] = []
            for module in self.modules.values():
                for rule in module.rules:
                    rname = rule.name.lower()
                    if actor_name.lower() in rname:
                        rules_handled.append(rule.name)
                        if "recv" in rname:
                            if "query" in rname:
                                receives.add("query")
                            if "response" in rname or "ans" in rname:
                                receives.add("response")
                        if "send" in rname or "reply" in rname:
                            sends.add("response")
            ac.message_interface = {"receives": list(receives), "sends": list(sends)}
            ac.rules_handled = rules_handled

            out[actor_name] = ac

        return out

    # =====================================================================
    # Rules
    # =====================================================================

    def _extract_rule_contracts(self) -> Dict[str, RuleContract]:
        out: Dict[str, RuleContract] = {}
        for module in self.modules.values():
            for rule in module.rules:
                rule_id = f"{module.name}:{rule.name}"

                actor_role = self._dispatch_actor_role(rule.name)
                event_pattern = inference.infer_event(rule.name)
                state_reads, state_writes = self._derive_state_access(
                    rule.lhs, rule.rhs, actor_role
                )

                guard_slots: List[GuardSlot] = []
                if rule.is_conditional and rule.condition:
                    guard_slots.append(GuardSlot(
                        slot_id=f"{rule.name}-guard",
                        description=f"Condition for {rule.name}",
                        template=rule.condition,
                    ))

                action_dicts = inference.infer_action_slots(rule.name, rule.rhs)
                action_slots = [
                    ActionSlot(
                        slot_id=d["slot_id"],
                        action_type=d["action_type"],
                        description=d["description"],
                    )
                    for d in action_dicts
                ]

                out[rule_id] = RuleContract(
                    rule_id=rule_id,
                    rule_name=rule.name,
                    actor_role=actor_role,
                    event_pattern=event_pattern,
                    guard_slots=guard_slots,
                    action_slots=action_slots,
                    state_reads=state_reads,
                    state_writes=state_writes,
                    is_conditional=rule.is_conditional,
                    defined_in=module.name,
                )
        return out

    def _dispatch_actor_role(self, rule_name: str) -> str:
        """Substring match of actor name against rule name (legacy parity)."""
        rl = rule_name.lower()
        for actor in self.semantics.actor_types:
            if actor.lower() in rl:
                return actor
        # Conventional aliases
        if "client" in rl:
            return "Client"
        if "resolver" in rl:
            return "Resolver"
        if "nameserver" in rl or "ns" in rl:
            return "Nameserver"
        if "monitor" in rl:
            return "Monitor"
        return "Unknown"

    def _derive_state_access(
        self, lhs: str, rhs: str, actor_role: str
    ) -> Tuple[List[str], List[str]]:
        """LHS/RHS substring match against the actor's bound attribute labels.

        F0-3 manifest point: bindings are now per-actor evidence-grounded,
        so we look at THIS actor's attrs only (not all actors').
        """
        reads: List[str] = []
        writes: List[str] = []
        bindings = [b for b in self.semantics.bindings if b.actor_type == actor_role]
        for b in bindings:
            label = b.attr_label
            if label in lhs:
                reads.append(label)
            if label in rhs and rhs.count(label) > lhs.count(label):
                writes.append(label)
        return reads, writes

    # =====================================================================
    # Modules / hierarchy / serialize (parity)
    # =====================================================================

    def _extract_module_info(self) -> Dict[str, Dict[str, Any]]:
        out: Dict[str, Dict[str, Any]] = {}
        for mod_name, module in self.modules.items():
            out[mod_name] = {
                "type": module.type,
                "imports": [{"type": kind, "module": name} for kind, name in module.imports],
                "sorts_defined": module.sorts,
                "rules_defined": [r.name for r in module.rules],
                "operators_count": len(module.ops),
                "equations_count": len(module.eqs),
            }
        return out

    def _extract_sort_hierarchy(self) -> Dict[str, List[str]]:
        h: Dict[str, List[str]] = defaultdict(list)
        for module in self.modules.values():
            for child, parent in module.subsorts:
                h[parent].append(child)
        return dict(h)

    def _contract_to_dict(self, c: MaudeContract) -> Dict[str, Any]:
        return {
            "metadata": c.metadata,
            "sorts": {
                name: {
                    "name": s.name,
                    "constructors": s.constructors,
                    "operators": s.operators,
                    "subsorts": s.subsorts,
                    "supersorts": s.supersorts,
                    "defined_in": s.defined_in,
                    "used_by_actors": list(s.used_by_actors),
                }
                for name, s in c.sorts.items()
            },
            "actors": {
                name: {
                    "name": a.name,
                    "inherits_from": a.inherits_from,
                    "state_interface": {
                        attr: {
                            "attribute": ac.attribute,
                            "sort": ac.sort,
                            "mode": ac.mode.value,
                            "is_inherited": ac.is_inherited,
                            "inherited_from": ac.inherited_from,
                        }
                        for attr, ac in a.state_interface.items()
                    },
                    "message_interface": a.message_interface,
                    "rules_handled": a.rules_handled,
                    "defined_in": a.defined_in,
                }
                for name, a in c.actors.items()
            },
            "rules": {
                rid: {
                    "rule_id": r.rule_id,
                    "rule_name": r.rule_name,
                    "actor_role": r.actor_role,
                    "event_pattern": r.event_pattern,
                    "guard_slots": [
                        {
                            "slot_id": g.slot_id,
                            "description": g.description,
                            "rfc_reference": g.rfc_reference,
                            "template": g.template,
                        }
                        for g in r.guard_slots
                    ],
                    "action_slots": [
                        {
                            "slot_id": s.slot_id,
                            "action_type": s.action_type,
                            "description": s.description,
                            "rfc_reference": s.rfc_reference,
                            "template": s.template,
                        }
                        for s in r.action_slots
                    ],
                    "state_reads": r.state_reads,
                    "state_writes": r.state_writes,
                    "message_sends": r.message_sends,
                    "is_conditional": r.is_conditional,
                    "defined_in": r.defined_in,
                    "rfc_references": r.rfc_references,
                }
                for rid, r in c.rules.items()
            },
            "modules": c.modules,
            "sort_hierarchy": c.sort_hierarchy,
            "unresolved": c.unresolved,
        }

    # =====================================================================
    # Tagging system (legacy parity, heuristics → inference.*)
    # =====================================================================

    def _build_tagging_system(self) -> TaggingSystem:
        tagging = TaggingSystem()
        tagging.metadata = {
            "description": "Maude DNS Model Tagging System",
            "version": "1.0",
            "total_entities": 0,
        }
        # Rules
        for module in self.modules.values():
            for rule in module.rules:
                rule_id = f"{module.name}:{rule.name}"
                actor_role = self._dispatch_actor_role(rule.name)
                tags = inference.tag_rule(rule.name, actor_role, rule.is_conditional)
                et = EntityTags(entity_id=rule_id, entity_type="rule", tags=tags)
                tagging.entity_tags[rule_id] = et
                for k, v in tags.items():
                    tagging.tag_index.setdefault(f"{k}:{v}", []).append(rule_id)
        # Actors
        for actor_name in self.semantics.actor_types:
            tags = {
                "entity_type": "actor",
                "role": actor_name,
                "has_state": len(self.semantics.attributes_of(actor_name)) > 0,
            }
            et = EntityTags(entity_id=actor_name, entity_type="actor", tags=tags)
            tagging.entity_tags[actor_name] = et
            for k, v in tags.items():
                tagging.tag_index.setdefault(f"{k}:{v}", []).append(actor_name)
        # Sorts
        for module in self.modules.values():
            for sort in module.sorts:
                tags = {
                    "entity_type": "sort",
                    "defined_in": module.name,
                    "is_actor_type": sort in self.semantics.actor_types,
                    "category": inference.sort_category(sort),
                }
                et = EntityTags(entity_id=sort, entity_type="sort", tags=tags)
                tagging.entity_tags[sort] = et
                for k, v in tags.items():
                    tagging.tag_index.setdefault(f"{k}:{v}", []).append(sort)
        tagging.metadata["total_entities"] = len(tagging.entity_tags)
        return tagging

    def _tagging_to_dict(self, t: TaggingSystem) -> Dict[str, Any]:
        return {
            "metadata": t.metadata,
            "entity_tags": {
                eid: {"entity_id": e.entity_id, "entity_type": e.entity_type, "tags": e.tags}
                for eid, e in t.entity_tags.items()
            },
            "tag_index": t.tag_index,
        }
