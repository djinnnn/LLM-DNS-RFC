# -*- coding: utf-8 -*-
"""
Maude 提取器
从 Maude 源文件提取结构信息
"""
import re
from collections import defaultdict
from typing import Dict, List, Tuple, Optional
from ..models.maude_ast import Module, Op, Equation, Rule, View


class MaudeExtractor:
    """Maude 结构提取器"""
    
    def __init__(self):
        self.modules: Dict[str, Module] = {}
        self.actor_types: List[str] = []
        self.actor_attributes: Dict[str, List[Tuple[str, str, str]]] = defaultdict(list)
    
    def parse_file(self, file_path: str) -> None:
        """解析单个 Maude 文件"""
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # 移除注释
        content = re.sub(r'---.*?\n', '\n', content)
        content = re.sub(r'\*\*\*.*?\n', '\n', content)
        
        self._parse_modules(content)
    
    def _parse_modules(self, content: str) -> None:
        """解析模块定义"""
        module_pattern = r'\b(fmod|mod)\s+([\w-]+)\s+is(.*?)\b(endfm|endm)\b'
        
        for match in re.finditer(module_pattern, content, re.DOTALL):
            mod_type, mod_name, mod_body, _ = match.groups()
            
            module = Module(name=mod_name, type=mod_type)
            module.imports = self._parse_imports(mod_body)
            module.sorts = self._parse_sorts(mod_body)
            module.subsorts = self._parse_subsorts(mod_body)
            module.ops = self._parse_ops(mod_body)
            module.vars = self._parse_vars(mod_body)
            module.eqs = self._parse_equations(mod_body)
            
            if mod_type == 'mod':
                module.rules = self._parse_rules(mod_body)
            
            module.views = self._parse_views(mod_body)
            
            self.modules[mod_name] = module
            self._extract_actor_info(module)
    
    def _parse_imports(self, content: str) -> List[Tuple[str, str]]:
        """解析模块导入"""
        imports = []
        for match in re.finditer(r'\b(inc|pr)\s+([^\.]+)\.?', content):
            imp_type, imp_names = match.groups()
            for name in re.findall(r'[\w-]+', imp_names):
                imports.append((imp_type, name))
        return imports
    
    def _parse_sorts(self, content: str) -> List[str]:
        """解析 sort 声明"""
        sorts = []
        for match in re.finditer(r'\bsort(?:s)?\s+([\w\s]+)\s*\.?', content):
            sort_names = match.group(1).strip()
            sorts.extend(re.findall(r'\w+', sort_names))
        return sorts
    
    def _parse_subsorts(self, content: str) -> List[Tuple[str, str]]:
        """解析 subsort 关系"""
        subsorts = []
        for match in re.finditer(r'\bsubsort(?:s)?\s+([\w\s]+)<\s*(\w+)\s*\.?', content):
            children_str, parent = match.groups()
            children = re.findall(r'\w+', children_str)
            for child in children:
                subsorts.append((child, parent))
        return subsorts
    
    def _parse_ops(self, content: str) -> List[Op]:
        """解析操作符定义"""
        ops = []
        op_pattern = r'\b(ops?\s+)((?:[^\.]|\n)+?)\s*:\s*([\w\s{},]+?)\s*->\s*(\w+)\s*(?:\[([^\]]+)\])?\s*\.'
        
        for match in re.finditer(op_pattern, content, re.MULTILINE):
            _, op_names_str, arity_str, coarity, attrs_str = match.groups()
            
            attrs = []
            if attrs_str:
                attrs = [a.strip() for a in attrs_str.split()]
            
            arity = self._parse_sort_list(arity_str)
            op_names = self._extract_op_names(op_names_str)
            
            for op_name in op_names:
                is_attr = op_name.endswith(':_')
                ops.append(Op(
                    name=op_name,
                    arity=arity,
                    coarity=coarity,
                    attrs=attrs,
                    is_attribute=is_attr
                ))
        
        return ops
    
    def _extract_op_names(self, op_str: str) -> List[str]:
        """提取操作符名称"""
        names = []
        for part in re.split(r'\s+', op_str.strip()):
            part = part.strip()
            if part and part not in ['(', ')']:
                names.append(part)
        return names if names else [op_str]
    
    def _parse_sort_list(self, sort_str: str) -> List[str]:
        """解析类型列表"""
        sorts = []
        for match in re.finditer(r'(\w+)(?:\{(\w+)\})?', sort_str):
            base, param = match.groups()
            if param:
                sorts.append(f"{base}{{{param}}}")
            else:
                sorts.append(base)
        return sorts
    
    def _parse_vars(self, content: str) -> Dict[str, List[str]]:
        """解析变量声明"""
        vars_dict = defaultdict(list)
        for match in re.finditer(r'\bvar(?:s)?\s+([\w\s\']+)\s*:\s*(\w+)\s*\.?', content):
            var_names_str, sort = match.groups()
            var_names = re.findall(r'\w[\w\']*', var_names_str)
            vars_dict[sort].extend(var_names)
        return dict(vars_dict)
    
    def _parse_equations(self, content: str) -> List[Equation]:
        """解析等式"""
        eqs = []
        
        # 无条件等式
        for match in re.finditer(r'\beq\s+([^=]+?)\s*=\s*([^\.]+?)\s*\.', content, re.DOTALL):
            lhs, rhs = match.groups()
            eqs.append(Equation(lhs=lhs.strip(), rhs=rhs.strip(), is_conditional=False))
        
        # 条件等式
        for match in re.finditer(r'\bceq\s+([^=]+?)\s*=\s*([^\.]+?)\s+if\s+(.+?)\s*\.', content, re.DOTALL):
            lhs, rhs, cond = match.groups()
            eqs.append(Equation(lhs=lhs.strip(), rhs=rhs.strip(), condition=cond.strip(), is_conditional=True))
        
        return eqs
    
    def _parse_rules(self, content: str) -> List[Rule]:
        """解析重写规则"""
        rules = []
        
        # 无条件规则
        rl_pattern = r'\brl\s+\[([^\]]+)\]\s*:\s*([\s\S]*?)\s*=>\s*([\s\S]*?)\s*\.'
        for match in re.finditer(rl_pattern, content):
            name, lhs, rhs = match.groups()
            if ' if ' not in rhs:
                rules.append(Rule(name=name.strip(), lhs=lhs.strip(), rhs=rhs.strip(), is_conditional=False))
        
        # 条件规则
        crl_pattern = r'\bcrl\s+\[([^\]]+)\]\s*:\s*([\s\S]*?)\s*=>\s*([\s\S]*?)\s+if\s+([\s\S]*?)\s*\.'
        for match in re.finditer(crl_pattern, content):
            name, lhs, rhs, cond = match.groups()
            rules.append(Rule(name=name.strip(), lhs=lhs.strip(), rhs=rhs.strip(), 
                            condition=cond.strip(), is_conditional=True))
        
        return rules
    
    def _parse_views(self, content: str) -> List[View]:
        """解析视图定义"""
        views = []
        view_pattern = r'\bview\s+(\w+)\s+from\s+(\w+)\s+to\s+(\w+)\s+is(.*?)\bendv\b'
        
        for match in re.finditer(view_pattern, content, re.DOTALL):
            view_name, from_mod, to_mod, view_body = match.groups()
            sort_mapping = {}
            
            for smatch in re.finditer(r'sort\s+(\w+)\s+to\s+(\w+)', view_body):
                src, tgt = smatch.groups()
                sort_mapping[src] = tgt
            
            views.append(View(name=view_name, from_module=from_mod, 
                            to_module=to_mod, sort_mapping=sort_mapping))
        
        return views
    
    def _extract_actor_info(self, module: Module) -> None:
        """提取 Actor 类型和属性信息"""
        for op in module.ops:
            if op.coarity == 'ActorType' and op.arity == []:
                self.actor_types.append(op.name)
            
            if op.is_attribute or op.coarity == 'Attribute':
                attr_name = op.name.replace(':_', '').replace(':', '')
                if op.arity:
                    param_sort = op.arity[0]
                    for actor_type in self.actor_types:
                        self.actor_attributes[actor_type].append((attr_name, param_sort, op.name))
