# -*- coding: utf-8 -*-
"""Actor / attribute resolver — implements B2-y of stage_0_redesign.md §3.

Replaces two coupled bugs of the legacy regex extractor:
  F0-2: `is_attribute` was decided by `name.endswith(':_')` and false-positived
        on message constructors `to_:_`, `to_from_:_`.
  F0-3: actor → attribute association was a "broadcast to all known actors"
        loop, with no grounding in Maude type information.

This module replaces both with type-driven facts:

  - Actor types come from `coarity == 'ActorType'` nullary ops (unchanged).
  - Attribute ops come from `coarity == 'Attribute'` (NOT name suffix).
  - Actor → attribute binding is reverse-engineered from rule LHS patterns
    `< <addr> : <ActorType> | <attr_op_names_seq> >`. Bindings only count
    when there is direct evidence in a rule LHS.

Attribute ops declared but not bound to any actor (= never appear inside an
actor pattern in any rule LHS) are surfaced via `unresolved_attribute_ops`.
B2-y: this list is written *silently* into `MaudeContract.unresolved`; no
warning is emitted.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from ..models.maude_ast import Module, Op


@dataclass
class AttrBinding:
    actor_type: str
    attr_op_name: str
    attr_label: str          # `cache:_` -> `cache`
    param_sort: str
    source_rule_id: Optional[str] = None  # First rule LHS that proved it


@dataclass
class ActorSemantics:
    actor_types: List[str] = field(default_factory=list)
    attribute_ops: Dict[str, Op] = field(default_factory=dict)
    bindings: List[AttrBinding] = field(default_factory=list)
    unresolved_attribute_ops: List[Op] = field(default_factory=list)

    def attributes_of(self, actor: str) -> List[AttrBinding]:
        return [b for b in self.bindings if b.actor_type == actor]


class ActorResolver:
    """Stateless resolver. `resolve()` ingests a `{name: Module}` dict."""

    def resolve(self, modules: Dict[str, Module]) -> ActorSemantics:
        sem = ActorSemantics()

        # 1. Actor types (nullary ops with coarity ActorType).
        for module in modules.values():
            for op in module.ops:
                if op.coarity == "ActorType" and not op.arity:
                    if op.name not in sem.actor_types:
                        sem.actor_types.append(op.name)

        # 2. Attribute ops (coarity Attribute, regardless of name).
        for module in modules.values():
            for op in module.ops:
                if op.coarity == "Attribute":
                    sem.attribute_ops[op.name] = op

        # 3. Reverse-engineer bindings from rule LHS patterns.
        # Index attribute ops by their `attr_label` (the prefix before `:_`),
        # because that's what appears in rule LHS — e.g. `cache: CACHE`, not
        # the full op name `cache:_`.
        seen_pairs: Set[Tuple[str, str]] = set()
        actor_set = set(sem.actor_types)
        label_to_op: Dict[str, Op] = {}
        for op in sem.attribute_ops.values():
            label = _strip_attr_suffix(op.name)
            # If two ops share a label (rare), keep the first; this is best-effort.
            label_to_op.setdefault(label, op)
        label_set = set(label_to_op.keys())

        for module in modules.values():
            for rule in module.rules:
                rule_id = f"{module.name}:{rule.name}"
                for actor_type, attr_labels in _extract_actor_patterns(
                    rule.lhs, actor_set, label_set
                ):
                    for label in attr_labels:
                        op = label_to_op.get(label)
                        if op is None:
                            continue
                        key = (actor_type, op.name)
                        if key in seen_pairs:
                            continue
                        seen_pairs.add(key)
                        sem.bindings.append(
                            AttrBinding(
                                actor_type=actor_type,
                                attr_op_name=op.name,
                                attr_label=label,
                                param_sort=op.arity[0] if op.arity else "",
                                source_rule_id=rule_id,
                            )
                        )

        # 4. Unresolved = declared but never bound.
        bound = {b.attr_op_name for b in sem.bindings}
        sem.unresolved_attribute_ops = [
            op for name, op in sem.attribute_ops.items() if name not in bound
        ]
        return sem


def _strip_attr_suffix(op_name: str) -> str:
    """`cache:_` → `cache`; `db:_` → `db`; `foo` → `foo`."""
    if op_name.endswith(":_"):
        return op_name[:-2]
    if op_name.endswith(":"):
        return op_name[:-1]
    return op_name


def _extract_actor_patterns(
    lhs: str, actor_set: Set[str], attr_set: Set[str]
) -> List[Tuple[str, List[str]]]:
    """Mini tokenizer for `< <addr> : <ActorType> | <attr_calls> >`.

    Returns a list of (actor_type, [attr_op_names]). Multiple actor patterns
    in one LHS are returned as separate tuples. Attributes are matched
    nominally — we look for known attribute op names appearing inside the
    `| ... >` body and record every match.

    Implementation note: we deliberately tokenize on whitespace + bracket
    boundaries rather than using regex, mirroring how the parser tokenizes
    the source. Only `<`, `:`, `|`, `>` matter structurally; everything else
    is content tokens we look up in `attr_set`.
    """
    if not lhs:
        return []
    out: List[Tuple[str, List[str]]] = []

    # Tokenize: split keeping `<`, `>`, `:`, `|`, `(`, `)`, `,` as separators.
    toks = _split_pattern(lhs)

    # Walk tokens looking for `<` ... `:` <Identifier> `|` ... `>` blocks.
    i = 0
    n = len(toks)
    while i < n:
        if toks[i] != "<":
            i += 1
            continue
        # Find the matching `>` (track nesting).
        depth = 1
        j = i + 1
        while j < n and depth > 0:
            if toks[j] == "<":
                depth += 1
            elif toks[j] == ">":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        if j >= n:
            break  # unmatched <
        block = toks[i + 1: j]
        # Inside the block, find `:` then identifier in actor_set, then `|`.
        try:
            colon_pos = block.index(":")
        except ValueError:
            i = j + 1
            continue
        # Actor type = first non-trivial token after `:`
        actor_type = None
        k = colon_pos + 1
        while k < len(block):
            tok = block[k]
            if tok and tok not in (" ",):
                actor_type = tok
                break
            k += 1
        if actor_type is None or actor_type not in actor_set:
            i = j + 1
            continue
        try:
            pipe_pos = block.index("|", k)
        except ValueError:
            i = j + 1
            continue
        attr_block = block[pipe_pos + 1:]
        # Collect attribute op names appearing in attr_block.
        seen_in_block: List[str] = []
        for tok in attr_block:
            if tok in attr_set and tok not in seen_in_block:
                seen_in_block.append(tok)
        out.append((actor_type, seen_in_block))
        i = j + 1
    return out


_PATTERN_SEPS = {"<", ">", ":", "|", "(", ")", ","}


def _split_pattern(s: str) -> List[str]:
    """Whitespace-tokenize, then peel structural punctuation off token edges."""
    raw = s.split()
    out: List[str] = []
    for word in raw:
        out.extend(_peel(word))
    return out


def _peel(word: str) -> List[str]:
    """Pull leading/trailing structural punctuation into separate tokens.

    `<a>` -> ['<', 'a', '>'];  `cache(c),` -> ['cache', '(', 'c', ')', ',']
    Inside the word we also split on structural seps to expose nested calls.
    """
    if not word:
        return []
    out: List[str] = []
    cur = ""
    for ch in word:
        if ch in _PATTERN_SEPS:
            if cur:
                out.append(cur)
                cur = ""
            out.append(ch)
        else:
            cur += ch
    if cur:
        out.append(cur)
    return out
