# -*- coding: utf-8 -*-
"""
Maude AST 数据结构
从原 maude_parser.py 提取的核心数据类
"""
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional


@dataclass
class Module:
    """Maude模块结构"""
    name: str
    type: str  # 'fmod' 或 'mod'
    imports: List[Tuple[str, str]] = field(default_factory=list)  # (类型, 模块名) 如 ('inc', 'AUX')
    sorts: List[str] = field(default_factory=list)
    subsorts: List[Tuple[str, str]] = field(default_factory=list)  # (child, parent)
    ops: List['Op'] = field(default_factory=list)
    vars: Dict[str, List[str]] = field(default_factory=dict)  # sort -> [var_names]
    eqs: List['Equation'] = field(default_factory=list)
    rules: List['Rule'] = field(default_factory=list)
    views: List['View'] = field(default_factory=list)


@dataclass
class Op:
    """操作符定义"""
    name: str
    arity: List[str]  # 参数类型列表
    coarity: str      # 返回类型
    attrs: List[str]  # [ctor], [assoc], [comm] 等
    is_attribute: bool = False  # 是否是Actor属性 (以 :_ 结尾)


@dataclass
class Equation:
    """等式定义 (eq/ceq)"""
    lhs: str          # 左侧模式
    rhs: str          # 右侧表达式
    condition: Optional[str] = None  # ceq的条件
    is_conditional: bool = False


@dataclass
class Rule:
    """重写规则 (rl/crl)"""
    name: str         # 规则标签如 [client-start]
    lhs: str          # 左侧配置模式
    rhs: str          # 右侧配置模式
    condition: Optional[str] = None  # crl的条件
    is_conditional: bool = False


@dataclass
class View:
    """视图定义"""
    name: str
    from_module: str
    to_module: str
    sort_mapping: Dict[str, str] = field(default_factory=dict)
