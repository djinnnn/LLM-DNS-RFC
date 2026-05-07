# -*- coding: utf-8 -*-
"""Heuristic dispatcher (C1-y).

Reads `config/inference_rules.yaml`. A miss emits a stderr warning via
`logging` (logger name `leaf_edns.stage0.inference`) and returns the default
value. The contract is NEVER polluted with a "couldn't infer" marker — that
discipline is what makes downstream Phase 4a `NormalizationRegistry` happy
(it sees only positive facts; it surfaces unresolved itself).
"""
from __future__ import annotations

import logging
import os
from typing import Dict, List, Optional, Tuple

import yaml

LOGGER = logging.getLogger("leaf_edns.stage0.inference")

_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config", "inference_rules.yaml")


def _load_rules() -> Dict:
    with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


_RULES = _load_rules()


def _match_any(text: str, needles: List[str]) -> bool:
    lo = text.lower()
    return any(n.lower() in lo for n in needles)


# =========================================================================
# event_pattern
# =========================================================================

def infer_event(rule_name: str) -> str:
    """rule.name → event_pattern. Default: `unknown_event` + stderr warning."""
    branches = _RULES.get("event_patterns", [])
    for branch in branches:
        needles = branch.get("if_name_contains_any", [])
        if not _match_any(rule_name, needles):
            continue
        # Sub-dispatch (e.g. `recv` → query/response/referral)
        sub = branch.get("sub_dispatch", [])
        if sub:
            for sb in sub:
                sneedles = sb.get("if_name_contains_any", [])
                if _match_any(rule_name, sneedles):
                    return sb["pattern"]
            # `recv` matched but no sub-branch did — fall through to warning
            break
        if "pattern" in branch:
            return branch["pattern"]
    LOGGER.warning("event_pattern miss for rule %r → unknown_event", rule_name)
    return "unknown_event"


# =========================================================================
# state_access mode
# =========================================================================

def classify_attr_access(attr_label: str) -> str:
    """attr_label → 'read' or 'read-write'. Never warns (a 'read' default is
    semantically valid; warnings would be noise)."""
    keywords = _RULES.get("state_access", {}).get("write_keywords", [])
    if _match_any(attr_label, keywords):
        return "read-write"
    return "read"


# =========================================================================
# action_slots
# =========================================================================

def infer_action_slots(rule_name: str, rhs: str) -> List[Dict[str, str]]:
    """rule.rhs → list of action-slot dicts. Empty list = no match (no warn:
    many rules legitimately have no externally-observable action)."""
    out: List[Dict[str, str]] = []
    for spec in _RULES.get("action_slots", []):
        needles = spec.get("if_rhs_contains_any", [])
        if _match_any(rhs or "", needles):
            out.append({
                "slot_id": f"{rule_name}{spec['suffix']}",
                "action_type": spec["slot_type"],
                "description": spec["description"],
            })
    return out


# =========================================================================
# rule_tags
# =========================================================================

def tag_rule(rule_name: str, actor_role: str, is_conditional: bool) -> Dict[str, str]:
    tags: Dict[str, str] = {"entity_type": "rule", "actor": actor_role}
    rt = _RULES.get("rule_tags", {})
    for key, branches in rt.items():
        for branch in branches:
            needles = branch.get("if_name_contains_any", [])
            if _match_any(rule_name, needles):
                tags[key] = branch["value"]
                break
    tags["complexity"] = "conditional" if is_conditional else "simple"
    return tags


# =========================================================================
# sort categories
# =========================================================================

def sort_category(sort_name: str) -> str:
    cats = _RULES.get("sort_categories", {})
    for cat, needles in cats.items():
        if _match_any(sort_name, needles):
            # Normalize to legacy spelling
            return {"dns_record": "dns-record"}.get(cat, cat)
    return "other"
