# -*- coding: utf-8 -*-
"""
接口契约数据结构
用于 JSON IR 导出，支持 RFC 到 Maude 的映射
"""
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Set
from enum import Enum


class AccessMode(Enum):
    """状态访问模式"""
    READ = "read"
    WRITE = "write"
    READ_WRITE = "read-write"


@dataclass
class StateAccess:
    """状态访问契约"""
    attribute: str
    sort: str
    mode: AccessMode
    is_inherited: bool = False
    inherited_from: Optional[str] = None


@dataclass
class GuardSlot:
    """Guard 条件占位符"""
    slot_id: str
    description: str
    rfc_reference: Optional[str] = None
    template: Optional[str] = None  # 可选的模板表达式


@dataclass
class ActionSlot:
    """Action 动作占位符"""
    slot_id: str
    action_type: str  # "state_update", "send_message", "cache_operation"
    description: str
    rfc_reference: Optional[str] = None
    template: Optional[str] = None


@dataclass
class SortContract:
    """Sort 接口契约"""
    name: str
    constructors: List[Dict[str, any]] = field(default_factory=list)  # {"name": str, "params": List[str]}
    operators: List[Dict[str, any]] = field(default_factory=list)     # {"name": str, "arity": List[str], "coarity": str}
    subsorts: List[str] = field(default_factory=list)
    supersorts: List[str] = field(default_factory=list)
    defined_in: str = ""
    used_by_actors: Set[str] = field(default_factory=set)


@dataclass
class ActorContract:
    """Actor 接口契约"""
    name: str
    inherits_from: Optional[str] = None
    state_interface: Dict[str, StateAccess] = field(default_factory=dict)
    message_interface: Dict[str, List[str]] = field(default_factory=dict)  # {"receives": [...], "sends": [...]}
    rules_handled: List[str] = field(default_factory=list)
    defined_in: str = ""


@dataclass
class RuleContract:
    """Rule 接口契约（带 Slot 占位符）"""
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
    """完整的 Maude 项目接口契约"""
    metadata: Dict[str, any] = field(default_factory=dict)
    sorts: Dict[str, SortContract] = field(default_factory=dict)
    actors: Dict[str, ActorContract] = field(default_factory=dict)
    rules: Dict[str, RuleContract] = field(default_factory=dict)
    modules: Dict[str, Dict[str, any]] = field(default_factory=dict)
    sort_hierarchy: Dict[str, List[str]] = field(default_factory=dict)


@dataclass
class EntityTags:
    """实体标签"""
    entity_id: str
    entity_type: str  # "sort", "actor", "rule", "module"
    tags: Dict[str, any] = field(default_factory=dict)


@dataclass
class TaggingSystem:
    """标签体系（独立于契约）"""
    metadata: Dict[str, any] = field(default_factory=dict)
    entity_tags: Dict[str, EntityTags] = field(default_factory=dict)  # entity_id -> EntityTags
    tag_index: Dict[str, List[str]] = field(default_factory=dict)  # tag_key -> [entity_ids]
