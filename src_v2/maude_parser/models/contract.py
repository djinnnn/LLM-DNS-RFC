# -*- coding: utf-8 -*-
"""接口契约数据结构（从 src/ 移植 + 加 `unresolved` 字段）。

`MaudeContract.unresolved` 用于 B2-y：声明了但任何 rule LHS 未引用过的
attribute op 写到这里；下游 Phase 4a NormalizationRegistry 不读它（已确认
src/maude_generator/registry.py:310-345 仅访问 actors/rules/sorts/sort_hierarchy），
故新字段对 Phase 4a 零影响。
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Set


class AccessMode(Enum):
    READ = "read"
    WRITE = "write"
    READ_WRITE = "read-write"


@dataclass
class StateAccess:
    attribute: str
    sort: str
    mode: AccessMode
    is_inherited: bool = False
    inherited_from: Optional[str] = None


@dataclass
class GuardSlot:
    slot_id: str
    description: str
    rfc_reference: Optional[str] = None
    template: Optional[str] = None


@dataclass
class ActionSlot:
    slot_id: str
    action_type: str
    description: str
    rfc_reference: Optional[str] = None
    template: Optional[str] = None


@dataclass
class SortContract:
    name: str
    constructors: List[Dict[str, object]] = field(default_factory=list)
    operators: List[Dict[str, object]] = field(default_factory=list)
    subsorts: List[str] = field(default_factory=list)
    supersorts: List[str] = field(default_factory=list)
    defined_in: str = ""
    used_by_actors: Set[str] = field(default_factory=set)


@dataclass
class ActorContract:
    name: str
    inherits_from: Optional[str] = None
    state_interface: Dict[str, StateAccess] = field(default_factory=dict)
    message_interface: Dict[str, List[str]] = field(default_factory=dict)
    rules_handled: List[str] = field(default_factory=list)
    defined_in: str = ""


@dataclass
class RuleContract:
    rule_id: str
    rule_name: str
    actor_role: str
    event_pattern: str
    guard_slots: List[GuardSlot] = field(default_factory=list)
    action_slots: List[ActionSlot] = field(default_factory=list)
    state_reads: List[str] = field(default_factory=list)
    state_writes: List[str] = field(default_factory=list)
    message_sends: List[str] = field(default_factory=list)
    is_conditional: bool = False
    defined_in: str = ""
    rfc_references: List[str] = field(default_factory=list)


@dataclass
class MaudeContract:
    metadata: Dict[str, object] = field(default_factory=dict)
    sorts: Dict[str, SortContract] = field(default_factory=dict)
    actors: Dict[str, ActorContract] = field(default_factory=dict)
    rules: Dict[str, RuleContract] = field(default_factory=dict)
    modules: Dict[str, Dict[str, object]] = field(default_factory=dict)
    sort_hierarchy: Dict[str, List[str]] = field(default_factory=dict)
    # NEW (B2-y): 声明了但任何 rule LHS 未引用过的 attribute op 名
    unresolved: Dict[str, List[str]] = field(default_factory=dict)


@dataclass
class EntityTags:
    entity_id: str
    entity_type: str
    tags: Dict[str, object] = field(default_factory=dict)


@dataclass
class TaggingSystem:
    metadata: Dict[str, object] = field(default_factory=dict)
    entity_tags: Dict[str, EntityTags] = field(default_factory=dict)
    tag_index: Dict[str, List[str]] = field(default_factory=dict)
