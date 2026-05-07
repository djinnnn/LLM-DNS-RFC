# -*- coding: utf-8 -*-
"""Maude AST 数据结构（从 src/ 移植，未改）。"""
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional


@dataclass
class Module:
    name: str
    type: str  # 'fmod' or 'mod'
    imports: List[Tuple[str, str]] = field(default_factory=list)  # (kind, name)
    sorts: List[str] = field(default_factory=list)
    subsorts: List[Tuple[str, str]] = field(default_factory=list)  # (child, parent)
    ops: List["Op"] = field(default_factory=list)
    vars: Dict[str, List[str]] = field(default_factory=dict)
    eqs: List["Equation"] = field(default_factory=list)
    rules: List["Rule"] = field(default_factory=list)
    views: List["View"] = field(default_factory=list)


@dataclass
class Op:
    name: str
    arity: List[str]
    coarity: str
    attrs: List[str]
    is_attribute: bool = False  # 仅作为 hint 字段保留, 真正归属判定下沉到 semantics/


@dataclass
class Equation:
    lhs: str
    rhs: str
    condition: Optional[str] = None
    is_conditional: bool = False


@dataclass
class Rule:
    name: str
    lhs: str
    rhs: str
    condition: Optional[str] = None
    is_conditional: bool = False


@dataclass
class View:
    name: str
    from_module: str
    to_module: str
    sort_mapping: Dict[str, str] = field(default_factory=dict)
