# -*- coding: utf-8 -*-
import re
from collections import defaultdict
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


class MaudeStructParser:
    def __init__(self):
        self.modules: Dict[str, Module] = {}
        self.current_module: Optional[Module] = None
        
        # 全局sort关系（跨模块）
        self.global_subsorts: List[Tuple[str, str]] = []
        
        # Actor相关结构
        self.actor_types: List[str] = []
        self.actor_attributes: Dict[str, List[Tuple[str, str, str]]] = defaultdict(list)  # actor_type -> [(attr_name, param_sort, full_op_name)]

    def parse_file(self, file_path: str) -> None:
        """解析单个Maude文件"""
        with open(file_path, 'r') as f:
            content = f.read()
        
        # 移除注释
        content = re.sub(r'---.*?\n', '\n', content)
        content = re.sub(r'\*\*\*.*?\n', '\n', content)
        
        self._parse_modules(content)
        self._parse_global_structures(content)

    def _parse_modules(self, content: str) -> None:
        """解析模块定义 (fmod/mod)"""
        # 匹配 fmod/mod 模块 - 模块名可包含连字符
        module_pattern = r'\b(fmod|mod)\s+([\w-]+)\s+is(.*?)\b(endfm|endm)\b'
        
        for match in re.finditer(module_pattern, content, re.DOTALL):
            mod_type, mod_name, mod_body, end_keyword = match.groups()
            
            module = Module(name=mod_name, type=mod_type)
            self.current_module = module
            
            # 解析导入
            module.imports = self._parse_imports(mod_body)
            
            # 解析sorts
            module.sorts = self._parse_sorts(mod_body)
            
            # 解析subsorts
            module.subsorts = self._parse_subsorts(mod_body)
            
            # 解析操作符
            module.ops = self._parse_ops(mod_body)
            
            # 解析变量
            module.vars = self._parse_vars(mod_body)
            
            # 解析等式
            module.eqs = self._parse_equations(mod_body)
            
            # 解析规则 (仅在mod类型中)
            if mod_type == 'mod':
                module.rules = self._parse_rules(mod_body)
            
            # 解析视图
            module.views = self._parse_views(mod_body)
            
            self.modules[mod_name] = module
            
            # 提取Actor相关信息
            self._extract_actor_info(module)
        
        self.current_module = None

    def _parse_imports(self, content: str) -> List[Tuple[str, str]]:
        """解析模块导入: inc 或 pr"""
        imports = []
        # 匹配 inc 和 pr 导入
        for match in re.finditer(r'\b(inc|pr)\s+([^\.]+)\.?', content):
            imp_type, imp_names = match.groups()
            # 处理多个导入 (如 "inc A + B .")
            for name in re.findall(r'\w+', imp_names):
                imports.append((imp_type, name))
        return imports

    def _parse_sorts(self, content: str) -> List[str]:
        """解析sort声明"""
        sorts = []
        for match in re.finditer(r'\bsort(?:s)?\s+([\w\s]+)\s*\.?', content):
            sort_names = match.group(1).strip()
            sorts.extend(re.findall(r'\w+', sort_names))
        return sorts

    def _parse_subsorts(self, content: str) -> List[Tuple[str, str]]:
        """解析subsort关系"""
        subsorts = []
        # 处理多种形式: subsort A < B . / subsorts A B < C .
        for match in re.finditer(r'\bsubsort(?:s)?\s+([\w\s]+)<\s*(\w+)\s*\.?', content):
            children_str, parent = match.groups()
            children = re.findall(r'\w+', children_str)
            for child in children:
                subsorts.append((child, parent))
        return subsorts

    def _parse_ops(self, content: str) -> List[Op]:
        """解析操作符定义"""
        ops = []
        
        # 匹配 op 定义 (支持多行)
        op_pattern = r'\b(ops?\s+)((?:[^\.]|\n)+?)\s*:\s*([\w\s{},]+?)\s*->\s*(\w+)\s*(?:\[([^\]]+)\])?\s*\.'
        
        for match in re.finditer(op_pattern, content, re.MULTILINE):
            op_prefix, op_names_str, arity_str, coarity, attrs_str = match.groups()
            
            # 解析属性
            attrs = []
            if attrs_str:
                attrs = [a.strip() for a in attrs_str.split()]
            
            # 解析参数类型 (处理泛型如 List{Record})
            arity = self._parse_sort_list(arity_str)
            
            # 处理多个操作符 (ops ...)
            op_names = self._extract_op_names(op_names_str)
            
            for op_name in op_names:
                # 检测是否是Actor属性 (格式: name:_)
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
        """提取操作符名称，处理特殊语法"""
        names = []
        # 清理字符串
        op_str = op_str.strip()
        
        # 匹配普通标识符或特殊操作符 (如 __, _._, _;_, 等)
        # 特殊处理: 分割多个操作符
        for part in re.split(r'\s+', op_str):
            part = part.strip()
            if part and part not in ['(', ')']:
                names.append(part)
        
        return names if names else [op_str]

    def _parse_sort_list(self, sort_str: str) -> List[str]:
        """解析类型列表，处理泛型"""
        sorts = []
        # 匹配泛型格式: Name{Param} 或普通类型
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
        
        # 匹配 var/vars Name Name' : Sort .
        for match in re.finditer(r'\bvar(?:s)?\s+([\w\s\']+)\s*:\s*(\w+)\s*\.?', content):
            var_names_str, sort = match.groups()
            var_names = re.findall(r'\w[\w\']*', var_names_str)
            vars_dict[sort].extend(var_names)
        
        return dict(vars_dict)

    def _parse_equations(self, content: str) -> List[Equation]:
        """解析等式 (eq/ceq)"""
        eqs = []
        
        # 无条件等式: eq LHS = RHS .
        for match in re.finditer(r'\beq\s+([^=]+?)\s*=\s*([^\.]+?)\s*\.', content, re.DOTALL):
            lhs, rhs = match.groups()
            eqs.append(Equation(
                lhs=lhs.strip(),
                rhs=rhs.strip(),
                is_conditional=False
            ))
        
        # 条件等式: ceq LHS = RHS if Condition .
        for match in re.finditer(r'\bceq\s+([^=]+?)\s*=\s*([^\.]+?)\s+if\s+(.+?)\s*\.', content, re.DOTALL):
            lhs, rhs, cond = match.groups()
            eqs.append(Equation(
                lhs=lhs.strip(),
                rhs=rhs.strip(),
                condition=cond.strip(),
                is_conditional=True
            ))
        
        return eqs

    def _parse_rules(self, content: str) -> List[Rule]:
        """解析重写规则 (rl/crl) - 改进版，正确处理多行规则"""
        rules = []
        
        # 使用更精确的多行匹配：找到 rl/crl 开头，然后找到匹配的结束 .
        # 模式：rl/crl [name] : ... => ... .
        # 条件规则：crl [name] : ... => ... if ... .
        
        # 无条件规则: rl [name] : LHS => RHS .
        # 使用非贪婪匹配，但确保能跨行
        rl_pattern = r'\brl\s+\[([^\]]+)\]\s*:\s*([\s\S]*?)\s*=>\s*([\s\S]*?)\s*\.'
        for match in re.finditer(rl_pattern, content):
            name, lhs, rhs = match.groups()
            # 检查是否包含 'if' 关键字（可能是误匹配的条件规则）
            if ' if ' not in rhs:
                rules.append(Rule(
                    name=name.strip(),
                    lhs=lhs.strip(),
                    rhs=rhs.strip(),
                    is_conditional=False
                ))
        
        # 条件规则: crl [name] : LHS => RHS if Condition .
        crl_pattern = r'\bcrl\s+\[([^\]]+)\]\s*:\s*([\s\S]*?)\s*=>\s*([\s\S]*?)\s+if\s+([\s\S]*?)\s*\.'
        for match in re.finditer(crl_pattern, content):
            name, lhs, rhs, cond = match.groups()
            rules.append(Rule(
                name=name.strip(),
                lhs=lhs.strip(),
                rhs=rhs.strip(),
                condition=cond.strip(),
                is_conditional=True
            ))
        
        return rules

    def _parse_views(self, content: str) -> List[View]:
        """解析视图定义"""
        views = []
        
        view_pattern = r'\bview\s+(\w+)\s+from\s+(\w+)\s+to\s+(\w+)\s+is(.*?)\bendv\b'
        for match in re.finditer(view_pattern, content, re.DOTALL):
            view_name, from_mod, to_mod, view_body = match.groups()
            
            # 解析sort映射
            sort_mapping = {}
            for smatch in re.finditer(r'sort\s+(\w+)\s+to\s+(\w+)', view_body):
                src, tgt = smatch.groups()
                sort_mapping[src] = tgt
            
            views.append(View(
                name=view_name,
                from_module=from_mod,
                to_module=to_mod,
                sort_mapping=sort_mapping
            ))
        
        return views

    def _parse_global_structures(self, content: str) -> None:
        """解析全局结构（不在模块内的）"""
        # 全局视图 (可能在模块外)
        view_pattern = r'\bview\s+(\w+)\s+from\s+(\w+)\s+to\s+(\w+)\s+is\s+sort\s+(\w+)\s+to\s+(\w+)\s*\.?\s*\bendv\b'
        for match in re.finditer(view_pattern, content):
            view_name, from_mod, to_mod, src_sort, tgt_sort = match.groups()
            # 可以存储为全局视图

    def _extract_actor_info(self, module: Module) -> None:
        """提取Actor类型和属性信息"""
        # 查找ActorType定义: op Xxx : -> ActorType .
        for op in module.ops:
            if op.coarity == 'ActorType' and op.arity == []:
                self.actor_types.append(op.name)
            
            # 查找属性操作符 (以 :_ 结尾，返回类型是 Attribute)
            if op.is_attribute or op.coarity == 'Attribute':
                # 从操作符名称提取属性名 (如 "cache:_" -> "cache")
                attr_name = op.name.replace(':_', '').replace(':', '')
                # 关联到参数类型
                if op.arity:
                    param_sort = op.arity[0]
                    # 尝试关联到最近的Actor类型
                    for actor_type in self.actor_types:
                        self.actor_attributes[actor_type].append((attr_name, param_sort, op.name))

    def get_sort_hierarchy(self) -> Dict[str, List[str]]:
        """获取完整的sort层次结构"""
        hierarchy = defaultdict(list)
        
        # 收集所有模块的subsorts
        for module in self.modules.values():
            for child, parent in module.subsorts:
                hierarchy[parent].append(child)
        
        return dict(hierarchy)

    def get_actor_summary(self) -> Dict[str, Dict]:
        """获取Actor类型及其属性的摘要"""
        summary = {}
        
        for actor_type in self.actor_types:
            summary[actor_type] = {
                'attributes': self.actor_attributes.get(actor_type, []),
                'defined_in': [m.name for m in self.modules.values() 
                              if any(op.name == actor_type for op in m.ops)]
            }
        
        return summary

    def display(self) -> None:
        """打印完整的架构提取结果"""
        print("=" * 70)
        print("MAUDE DNS MODEL - ARCHITECTURE EXTRACTION")
        print("=" * 70)
        
        # 1. 模块结构
        print("\n### 1. MODULE STRUCTURE")
        print("-" * 50)
        for name, mod in self.modules.items():
            print(f"\n  [{mod.type.upper()}] {name}")
            if mod.imports:
                incs = [n for t, n in mod.imports if t == 'inc']
                prs = [n for t, n in mod.imports if t == 'pr']
                if incs:
                    print(f"    includes: {', '.join(incs)}")
                if prs:
                    print(f"    protects: {', '.join(prs)}")
        
        # 2. Sort层次结构
        print("\n\n### 2. SORT HIERARCHY")
        print("-" * 50)
        hierarchy = self.get_sort_hierarchy()
        for parent, children in sorted(hierarchy.items()):
            for child in children:
                print(f"  {child} ----> {parent}")
        
        # 3. Actor类型和属性
        print("\n\n### 3. ACTOR TYPES & ATTRIBUTES")
        print("-" * 50)
        actor_summary = self.get_actor_summary()
        for actor_type, info in sorted(actor_summary.items()):
            print(f"\n  Actor: {actor_type}")
            for attr_name, param_sort, full_name in info['attributes']:
                print(f"    - {attr_name} : {param_sort}")
        
        # 4. 关键操作符统计
        print("\n\n### 4. OPERATOR SUMMARY")
        print("-" * 50)
        all_ops = []
        for mod in self.modules.values():
            all_ops.extend(mod.ops)
        
        ctor_ops = [op for op in all_ops if 'ctor' in op.attrs]
        attr_ops = [op for op in all_ops if op.is_attribute]
        
        print(f"  Total operators: {len(all_ops)}")
        print(f"  Constructors: {len(ctor_ops)}")
        print(f"  Actor attributes: {len(attr_ops)}")
        
        # 5. 等式和规则统计
        print("\n\n### 5. EQUATIONS & RULES STATISTICS")
        print("-" * 50)
        total_eqs = sum(len(m.eqs) for m in self.modules.values())
        total_rules = sum(len(m.rules) for m in self.modules.values())
        ceqs = sum(len([e for e in m.eqs if e.is_conditional]) for m in self.modules.values())
        crls = sum(len([r for r in m.rules if r.is_conditional]) for m in self.modules.values())
        
        print(f"  Total equations: {total_eqs} ({ceqs} conditional)")
        print(f"  Total rewrite rules: {total_rules} ({crls} conditional)")
        
        # 列出所有规则，按类别分组
        print("\n  All Rewrite Rules:")
        all_rules = []
        for mod in self.modules.values():
            all_rules.extend([(mod.name, r) for r in mod.rules])
        
        # 按类别分组
        client_rules = [(m, r) for m, r in all_rules if 'client' in r.name.lower()]
        resolver_rules = [(m, r) for m, r in all_rules if 'resolver' in r.name.lower()]
        ns_rules = [(m, r) for m, r in all_rules if 'ns' in r.name.lower() or 'nameserver' in r.name.lower()]
        other_rules = [(m, r) for m, r in all_rules if not any(x in r.name.lower() for x in ['client', 'resolver', 'ns', 'nameserver'])]
        
        if client_rules:
            print("\n    [Client Rules]")
            for mod_name, rule in client_rules:
                print(f"      - [{rule.name}] (in {mod_name})")
        
        if resolver_rules:
            print("\n    [Resolver Rules]")
            for mod_name, rule in resolver_rules:
                print(f"      - [{rule.name}] (in {mod_name})")
        
        if ns_rules:
            print("\n    [Nameserver Rules]")
            for mod_name, rule in ns_rules:
                print(f"      - [{rule.name}] (in {mod_name})")
        
        if other_rules:
            print("\n    [Other Rules]")
            for mod_name, rule in other_rules[:10]:  # 最多显示10个其他规则
                print(f"      - [{rule.name}] (in {mod_name})")
            if len(other_rules) > 10:
                print(f"      ... and {len(other_rules) - 10} more")
        
        # 6. 视图
        print("\n\n### 6. VIEWS (Generic Instantiation)")
        print("-" * 50)
        all_views = []
        for mod in self.modules.values():
            all_views.extend(mod.views)
        
        for view in all_views:
            print(f"  {view.name}: {view.from_module} -> {view.to_module}")
            for src, tgt in view.sort_mapping.items():
                print(f"    sort {src} -> {tgt}")
        
        print("\n" + "=" * 70)

    def export_dot(self, output_dir=".") -> None:
        """导出Graphviz DOT可视化文件"""
        import os
        
        os.makedirs(output_dir, exist_ok=True)
        
        # 1. Sort层次结构图
        self._export_sort_hierarchy_dot(os.path.join(output_dir, "sort_hierarchy.dot"))
        
        # 2. Actor属性关系图
        self._export_actor_dot(os.path.join(output_dir, "actor_structure.dot"))
        
        # 3. 模块依赖图
        self._export_module_dot(os.path.join(output_dir, "module_deps.dot"))
        
        print(f"\nDOT files exported to: {output_dir}/")
        print("  - sort_hierarchy.dot    (Sort inheritance tree)")
        print("  - actor_structure.dot   (Actor type & attributes)")
        print("  - module_deps.dot       (Module dependency graph)")
        print("\nRender with: dot -Tsvg sort_hierarchy.dot -o sort_hierarchy.svg")

    def _export_sort_hierarchy_dot(self, filepath: str) -> None:
        """生成Sort层次结构DOT文件"""
        lines = ['digraph SortHierarchy {']
        lines.append('  rankdir=BT;  // Bottom to Top')
        lines.append('  node [shape=box, style=rounded, fontname="Helvetica"];')
        lines.append('  edge [arrowhead=empty];')
        lines.append('')
        
        hierarchy = self.get_sort_hierarchy()
        all_sorts = set()
        
        # 收集所有sorts
        for parent, children in hierarchy.items():
            all_sorts.add(parent)
            for child in children:
                all_sorts.add(child)
        
        # 定义节点颜色（按类别）
        color_map = {
            'Actor': '#E8F4F8',
            'Config': '#FFF4E6',
            'Msg': '#E8F8E8',
            'Cache': '#FFE6E6',
            'Record': '#F0E6FF',
            'Address': '#E6F0FF',
            'Name': '#F8F8E8',
            'Query': '#E8F8F0',
            'Response': '#F0E8F8',
        }
        
        # 定义节点
        for sort in sorted(all_sorts):
            color = '#F0F0F0'
            for key, c in color_map.items():
                if key in sort:
                    color = c
                    break
            lines.append(f'  "{sort}" [fillcolor="{color}", style="rounded,filled"];')
        
        lines.append('')
        
        # 定义边（subsort关系）
        for parent, children in hierarchy.items():
            for child in children:
                lines.append(f'  "{child}" -> "{parent}";')
        
        lines.append('}')
        
        with open(filepath, 'w') as f:
            f.write('\n'.join(lines))

    def _export_actor_dot(self, filepath: str) -> None:
        """生成Actor结构DOT文件"""
        lines = ['digraph ActorStructure {']
        lines.append('  rankdir=LR;  // Left to Right')
        lines.append('  node [shape=none, fontname="Helvetica"];')
        lines.append('')
        
        # Actor类型节点（使用HTML表格显示属性）
        actor_summary = self.get_actor_summary()
        
        for actor_type, info in sorted(actor_summary.items()):
            attrs = info['attributes']
            
            # 构建HTML表格label
            html_label = f'<<TABLE BORDER="0" CELLBORDER="1" CELLSPACING="0" BGCOLOR="#E8F4F8">'
            html_label += f'<TR><TD BGCOLOR="#1976D2" COLSPAN="2"><FONT COLOR="white"><B>{actor_type}</B></FONT></TD></TR>'
            
            for name, sort, _ in attrs[:10]:  # 最多显示10个属性
                html_label += f'<TR><TD>{name}</TD><TD>{sort}</TD></TR>'
            
            if len(attrs) > 10:
                html_label += f'<TR><TD COLSPAN="2">... ({len(attrs)-10} more)</TD></TR>'
            
            html_label += '</TABLE>>'
            
            lines.append(f'  "{actor_type}" [label={html_label}, fillcolor="#E8F4F8", style="filled"];')
        
        lines.append('')
        lines.append('}')
        
        with open(filepath, 'w') as f:
            f.write('\n'.join(lines))

    def _export_module_dot(self, filepath: str) -> None:
        """生成模块依赖DOT文件"""
        lines = ['digraph ModuleDeps {']
        lines.append('  rankdir=TB;  // Top to Bottom')
        lines.append('  node [shape=box, fontname="Helvetica"];')
        lines.append('')
        
        # 模块节点
        for name, mod in self.modules.items():
            color = '#E8F4F8' if mod.type == 'fmod' else '#FFF4E6'
            shape = 'box' if mod.type == 'fmod' else 'box3d'
            lines.append(f'  "{name}" [label="{name}", fillcolor="{color}", style="filled", shape={shape}];')
        
        lines.append('')
        
        # 依赖边
        for name, mod in self.modules.items():
            for imp_type, imp_name in mod.imports:
                if imp_name in self.modules:
                    style = 'dashed' if imp_type == 'pr' else 'solid'
                    color = '#666666' if imp_type == 'pr' else '#0066CC'
                    lines.append(f'  "{name}" -> "{imp_name}" [style={style}, color="{color}"];')
        
        lines.append('')
        lines.append('  // Legend')
        lines.append('  subgraph cluster_legend {')
        lines.append('    label="Legend";')
        lines.append('    style=dashed;')
        lines.append('    fillcolor="#F8F8F8";')
        lines.append('    "fmod" [label="Functional Module", fillcolor="#E8F4F8", shape=box];')
        lines.append('    "mod" [label="System Module", fillcolor="#FFF4E6", shape=box3d];')
        lines.append('    "include" [label="include (inc)", shape=none];')
        lines.append('    "protect" [label="protect (pr)", shape=none, fontcolor="#666666"];')
        lines.append('    edge [color="#0066CC", style=solid];')
        lines.append('    "include" -> "protect" [style=invis];')
        lines.append('  }')
        lines.append('')
        
        lines.append('}')
        
        with open(filepath, 'w') as f:
            f.write('\n'.join(lines))


# 使用示例
if __name__ == "__main__":
    parser = MaudeStructParser()
    
    # 解析核心模型文件
    import glob
    import os
    
    # 获取脚本所在目录，然后找到Maude文件夹
    script_dir = os.path.dirname(os.path.abspath(__file__))
    base_path = os.path.join(script_dir, "../Maude/src")
    
    # 按依赖顺序解析
    files_to_parse = [
        "common/actor.maude",
        "common/prelim.maude",
        "common/_aux.maude",
        "common/parameters.maude",
        "common/label_graph.maude",
        "nondet-model/_aux.maude",
        "nondet-model/dns.maude",
    ]
    
    for rel_path in files_to_parse:
        full_path = os.path.join(base_path, rel_path)
        if os.path.exists(full_path):
            print(f"Parsing {rel_path}...")
            parser.parse_file(full_path)
    
    parser.display()
    
    # 导出可视化文件
    output_dir = "./visualization"
    parser.export_dot(output_dir)