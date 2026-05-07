# -*- coding: utf-8 -*-
"""
Normalization Registry for IR → Maude code generation.

包含 6 个子注册表：
  1. ModalityRegistry      — RFC 义务词归一化 (MUST/SHOULD/MAY ...)
  2. RoleRegistry          — LLM role 名 → Maude ActorType
  3. EventPatternRegistry  — LLM event type → Maude event pattern
  4. ActionOpsRegistry     — LLM action 描述 → Maude action type
  5. PredicateRegistry     — Maude guard predicates（从 contract 动态加载）
  6. AttributeRegistry     — actor 状态属性（从 contract 动态加载）

设计原则：
  - 数据与代码分离：静态映射从 config/*.yaml 加载
  - 只匹配已有 Maude 词汇：无法匹配的标记为 unresolved
  - unresolved 项是新协议行为的核心，需要后续处理
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

import yaml


# =========================================================
# 工具函数
# =========================================================

_CONFIG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config")


def _load_yaml(filename: str) -> Dict[str, Any]:
    """从 config/ 目录加载 YAML 文件。"""
    path = os.path.join(_CONFIG_DIR, filename)
    if not os.path.exists(path):
        raise FileNotFoundError(f"Config not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _build_alias_map(yaml_data: Dict[str, List[str]]) -> List[Tuple[str, str]]:
    """
    从 {canonical: [alias1, alias2, ...]} 构建 (alias_lower, canonical) 列表。
    按 alias 长度降序排列，保证长模式优先匹配。
    """
    pairs: List[Tuple[str, str]] = []
    for canonical, aliases in yaml_data.items():
        for alias in aliases:
            pairs.append((alias.lower().strip(), canonical))
    pairs.sort(key=lambda x: len(x[0]), reverse=True)
    return pairs


def _match_alias(text: str, alias_pairs: List[Tuple[str, str]]) -> Optional[str]:
    """在 alias 列表中按子串匹配，返回 canonical 值或 None。"""
    lower = text.lower().strip()
    for alias, canonical in alias_pairs:
        if alias in lower:
            return canonical
    return None


# =========================================================
# Unresolved 标记
# =========================================================

UNRESOLVED = "__unresolved__"


@dataclass
class UnresolvedItem:
    """记录一个无法映射到已有 Maude 词汇的项。"""
    field_name: str     # 哪个字段无法匹配 (role / event / action / condition)
    original_value: str # LLM 输出的原始值
    rule_id: str = ""   # 所属 ECA rule 的 id
    context: str = ""   # 额外上下文信息


# =========================================================
# 1. Modality Registry
# =========================================================

class ModalityRegistry:
    """RFC 义务词 → 归一化 modality。"""

    VALID = {"must", "must_not", "should", "should_not", "may"}

    def __init__(self) -> None:
        yaml_data = _load_yaml("modality.yaml")
        self._pairs = _build_alias_map(yaml_data)

    def normalize(self, text: str) -> Optional[str]:
        """
        从文本中识别并返回归一化的 modality。
        返回 None 表示未识别到任何 modality。
        """
        return _match_alias(text, self._pairs)

    @staticmethod
    def is_mandatory(modality: Optional[str]) -> bool:
        return modality in ("must", "must_not")

    @staticmethod
    def is_negative(modality: Optional[str]) -> bool:
        return modality in ("must_not", "should_not")


# =========================================================
# 2. Role Registry
# =========================================================

class RoleRegistry:
    """LLM role 名 → Maude ActorType（仅限 contract 中已有的）。"""

    def __init__(self, contract_actors: Optional[Set[str]] = None) -> None:
        yaml_data = _load_yaml("role_aliases.yaml")
        self._pairs = _build_alias_map(yaml_data)
        # 从 contract 获取合法 actor 集合；yaml 中的 canonical 应与之一致
        self._valid: Set[str] = contract_actors or {c for _, c in self._pairs}

    def normalize(self, role: str) -> Optional[str]:
        """返回 Maude ActorType，无法匹配返回 None（标记 unresolved）。"""
        return _match_alias(role, self._pairs)

    def is_valid(self, actor_type: str) -> bool:
        return actor_type in self._valid

    def all_roles(self) -> Set[str]:
        return set(self._valid)


# =========================================================
# 3. Event Pattern Registry
# =========================================================

class EventPatternRegistry:
    """LLM event type → Maude event pattern。"""

    def __init__(self, contract_events: Optional[Set[str]] = None) -> None:
        yaml_data = _load_yaml("event_aliases.yaml")
        self._pairs = _build_alias_map(yaml_data)
        # YAML canonical 值 + contract 值都视为合法
        yaml_canonicals = {c for _, c in self._pairs}
        self._valid: Set[str] = yaml_canonicals | (contract_events or set())

    def normalize(self, event_type: str) -> Optional[str]:
        """返回 Maude event pattern，无法匹配返回 None（标记 unresolved）。"""
        return _match_alias(event_type, self._pairs)

    def is_valid(self, event_pattern: str) -> bool:
        return event_pattern in self._valid

    def all_patterns(self) -> Set[str]:
        return set(self._valid)


# =========================================================
# 4. Action Ops Registry
# =========================================================

class ActionOpsRegistry:
    """LLM action 描述 → Maude action type。"""

    def __init__(self, contract_action_types: Optional[Set[str]] = None) -> None:
        yaml_data = _load_yaml("action_aliases.yaml")
        self._pairs = _build_alias_map(yaml_data)
        # YAML canonical 值 + contract 值都视为合法
        yaml_canonicals = {c for _, c in self._pairs}
        self._valid: Set[str] = yaml_canonicals | (contract_action_types or set())

    def normalize(self, action_expr: str) -> Optional[str]:
        """返回 Maude action type，无法匹配返回 None（标记 unresolved）。"""
        return _match_alias(action_expr, self._pairs)

    def is_valid(self, action_type: str) -> bool:
        return action_type in self._valid

    def all_action_types(self) -> Set[str]:
        return set(self._valid)


# =========================================================
# 5. Predicate Registry（从 contract 动态加载）
# =========================================================

@dataclass
class PredicateEntry:
    """一个 guard predicate 的描述。"""
    name: str
    maude_template: str                # guard 模板（来自 contract 的 guard_slots.template）
    source_rule: str = ""              # 来源规则 id
    description: str = ""
    required_sorts: List[str] = field(default_factory=list)


class PredicateRegistry:
    """
    从 maude_contract.json 的 rules[].guard_slots 动态加载。
    只包含 Maude 模型中已有的 guard 表达式。
    """

    def __init__(self) -> None:
        self._predicates: Dict[str, PredicateEntry] = {}

    def load_from_contract(self, contract: Dict[str, Any]) -> None:
        """从 contract dict 提取 guard_slots。"""
        rules = contract.get("rules", {})
        for rule_id, rule_data in rules.items():
            for slot in rule_data.get("guard_slots", []):
                template = slot.get("template", "")
                if not template:
                    continue
                slot_id = slot.get("slot_id", rule_id)
                self._predicates[slot_id] = PredicateEntry(
                    name=slot_id,
                    maude_template=template,
                    source_rule=rule_id,
                    description=slot.get("description", ""),
                )

    def lookup(self, keyword: str) -> Optional[PredicateEntry]:
        """精确 key 查找。"""
        return self._predicates.get(keyword)

    def search(self, text: str) -> List[PredicateEntry]:
        """模糊搜索：返回 template 中包含 text 的所有 predicate。"""
        lower = text.lower()
        return [p for p in self._predicates.values()
                if lower in p.maude_template.lower() or lower in p.name.lower()]

    def all_predicates(self) -> Dict[str, PredicateEntry]:
        return dict(self._predicates)

    def __len__(self) -> int:
        return len(self._predicates)


# =========================================================
# 6. Attribute Registry（从 contract 动态加载）
# =========================================================

@dataclass
class AttributeEntry:
    """一个 actor 状态属性的描述。"""
    name: str
    sort: str
    mode: str          # "read" | "read-write"
    actors: List[str]


class AttributeRegistry:
    """从 maude_contract.json 的 actors[].state_interface 动态加载。"""

    def __init__(self) -> None:
        self._attributes: Dict[str, AttributeEntry] = {}

    def load_from_contract(self, contract: Dict[str, Any]) -> None:
        """从 contract dict 提取属性信息。"""
        actors = contract.get("actors", {})
        for actor_name, actor_data in actors.items():
            state_iface = actor_data.get("state_interface", {})
            for attr_name, attr_info in state_iface.items():
                if attr_name == "_":
                    continue
                sort_name = attr_info.get("sort", "Unknown")
                mode = attr_info.get("mode", "read")
                if attr_name in self._attributes:
                    if actor_name not in self._attributes[attr_name].actors:
                        self._attributes[attr_name].actors.append(actor_name)
                else:
                    self._attributes[attr_name] = AttributeEntry(
                        name=attr_name, sort=sort_name, mode=mode, actors=[actor_name],
                    )

    def lookup(self, attr_name: str) -> Optional[AttributeEntry]:
        return self._attributes.get(attr_name)

    def writable_attributes(self) -> Dict[str, AttributeEntry]:
        return {k: v for k, v in self._attributes.items() if v.mode == "read-write"}

    def attributes_for_actor(self, actor: str) -> Dict[str, AttributeEntry]:
        return {k: v for k, v in self._attributes.items() if actor in v.actors}

    def is_valid(self, attr_name: str) -> bool:
        return attr_name in self._attributes

    def all_attributes(self) -> Dict[str, AttributeEntry]:
        return dict(self._attributes)

    def __len__(self) -> int:
        return len(self._attributes)


# =========================================================
# 统一入口：NormalizationRegistry
# =========================================================

class NormalizationRegistry:
    """
    统一的归一化注册表，聚合所有子注册表。

    - 静态注册表 (modality/role/event/action) 从 config/*.yaml 加载
    - 动态注册表 (predicate/attribute) 从 maude_contract.json 加载
    - 所有无法匹配的项标记为 unresolved
    """

    def __init__(self, contract_path: Optional[str] = None) -> None:
        # 从 contract 提取已有 actor/event/action_type 集合
        contract: Dict[str, Any] = {}
        contract_actors: Optional[Set[str]] = None
        contract_events: Optional[Set[str]] = None
        contract_action_types: Optional[Set[str]] = None

        if contract_path and os.path.exists(contract_path):
            with open(contract_path, "r", encoding="utf-8") as f:
                contract = json.load(f)
            # 从 contract 中提取合法集合
            contract_actors = set(contract.get("actors", {}).keys())
            contract_events = {
                r.get("event_pattern", "")
                for r in contract.get("rules", {}).values()
                if r.get("event_pattern") and r["event_pattern"] != "unknown_event"
            }
            contract_action_types = set()
            for r in contract.get("rules", {}).values():
                for slot in r.get("action_slots", []):
                    at = slot.get("action_type", "")
                    if at:
                        contract_action_types.add(at)

        # 初始化静态注册表（从 YAML 加载别名，从 contract 加载合法集合）
        self.modality = ModalityRegistry()
        self.role = RoleRegistry(contract_actors=contract_actors)
        self.event = EventPatternRegistry(contract_events=contract_events)
        self.action = ActionOpsRegistry(contract_action_types=contract_action_types)

        # 初始化动态注册表（从 contract 加载）
        self.predicate = PredicateRegistry()
        self.attribute = AttributeRegistry()
        if contract:
            self.predicate.load_from_contract(contract)
            self.attribute.load_from_contract(contract)

        # unresolved 收集器
        self._unresolved: List[UnresolvedItem] = []

    def add_unresolved(self, item: UnresolvedItem) -> None:
        """记录一个无法匹配的项。"""
        self._unresolved.append(item)

    def get_unresolved(self) -> List[UnresolvedItem]:
        return list(self._unresolved)

    def clear_unresolved(self) -> None:
        self._unresolved.clear()

    def debug_summary(self) -> str:
        """返回所有子注册表的 debug 摘要。"""
        lines = [
            "=" * 60,
            "[DEBUG] NormalizationRegistry Summary",
            "=" * 60,
            f"  Modalities : {len(ModalityRegistry.VALID)} entries",
            f"  Roles      : {len(self.role.all_roles())} actor types  {self.role.all_roles()}",
            f"  Events     : {len(self.event.all_patterns())} patterns  {self.event.all_patterns()}",
            f"  Actions    : {len(self.action.all_action_types())} types  {self.action.all_action_types()}",
            f"  Predicates : {len(self.predicate)} guard slots (from contract)",
            f"  Attributes : {len(self.attribute)} state attrs (from contract)",
        ]
        if self._unresolved:
            lines.append(f"  Unresolved : {len(self._unresolved)} items")
            for u in self._unresolved:
                lines.append(f"    [{u.field_name}] \"{u.original_value}\" (rule: {u.rule_id})")
        lines.append("=" * 60)
        return "\n".join(lines)
