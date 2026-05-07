# -*- coding: utf-8 -*-
"""
DOT 可视化导出器
从原 maude_parser.py 迁移的 Graphviz 导出逻辑
"""
from typing import Dict, List
from collections import defaultdict
from ..models.maude_ast import Module


class DOTExporter:
    """DOT 可视化导出器"""
    
    def __init__(self, modules: Dict[str, Module], actor_types: List[str],
                 actor_attributes: Dict[str, List[tuple]]):
        self.modules = modules
        self.actor_types = actor_types
        self.actor_attributes = actor_attributes
    
    def export_all(self, output_dir: str) -> None:
        """导出所有可视化文件"""
        import os
        os.makedirs(output_dir, exist_ok=True)
        
        self.export_sort_hierarchy(os.path.join(output_dir, "sort_hierarchy.dot"))
        self.export_actor_structure(os.path.join(output_dir, "actor_structure.dot"))
        self.export_module_deps(os.path.join(output_dir, "module_deps.dot"))
        
        print(f"\nDOT files exported to: {output_dir}/")
        print("  - sort_hierarchy.dot    (Sort inheritance tree)")
        print("  - actor_structure.dot   (Actor type & attributes)")
        print("  - module_deps.dot       (Module dependency graph)")
        print("\nRender with: dot -Tsvg sort_hierarchy.dot -o sort_hierarchy.svg")
    
    def export_sort_hierarchy(self, filepath: str) -> None:
        """生成Sort层次结构DOT文件"""
        lines = ['digraph SortHierarchy {']
        lines.append('  rankdir=BT;  // Bottom to Top')
        lines.append('  node [shape=box, style=rounded, fontname="Helvetica"];')
        lines.append('  edge [arrowhead=empty];')
        lines.append('')
        
        hierarchy = self._get_sort_hierarchy()
        all_sorts = set()
        
        for parent, children in hierarchy.items():
            all_sorts.add(parent)
            for child in children:
                all_sorts.add(child)
        
        color_map = {
            'Actor': '#E8F4F8', 'Config': '#FFF4E6', 'Msg': '#E8F8E8',
            'Cache': '#FFE6E6', 'Record': '#F0E6FF', 'Address': '#E6F0FF',
            'Name': '#F8F8E8', 'Query': '#E8F8F0', 'Response': '#F0E8F8',
        }
        
        for sort in sorted(all_sorts):
            color = '#F0F0F0'
            for key, c in color_map.items():
                if key in sort:
                    color = c
                    break
            lines.append(f'  "{sort}" [fillcolor="{color}", style="rounded,filled"];')
        
        lines.append('')
        
        for parent, children in hierarchy.items():
            for child in children:
                lines.append(f'  "{child}" -> "{parent}";')
        
        lines.append('}')
        
        with open(filepath, 'w') as f:
            f.write('\n'.join(lines))
    
    def export_actor_structure(self, filepath: str) -> None:
        """生成Actor结构DOT文件（HTML表格格式）"""
        lines = ['digraph ActorStructure {']
        lines.append('  rankdir=LR;  // Left to Right')
        lines.append('  node [shape=none, fontname="Helvetica"];')
        lines.append('')
        
        for actor_type in sorted(self.actor_types):
            attrs = self.actor_attributes.get(actor_type, [])
            
            html_label = f'<<TABLE BORDER="0" CELLBORDER="1" CELLSPACING="0" BGCOLOR="#E8F4F8">'
            html_label += f'<TR><TD BGCOLOR="#1976D2" COLSPAN="2"><FONT COLOR="white"><B>{actor_type}</B></FONT></TD></TR>'
            
            for name, sort, _ in attrs[:10]:
                html_label += f'<TR><TD>{name}</TD><TD>{sort}</TD></TR>'
            
            if len(attrs) > 10:
                html_label += f'<TR><TD COLSPAN="2">... ({len(attrs)-10} more)</TD></TR>'
            
            html_label += '</TABLE>>'
            
            lines.append(f'  "{actor_type}" [label={html_label}];')
        
        lines.append('')
        lines.append('}')
        
        with open(filepath, 'w') as f:
            f.write('\n'.join(lines))
    
    def export_module_deps(self, filepath: str) -> None:
        """生成模块依赖DOT文件"""
        lines = ['digraph ModuleDeps {']
        lines.append('  rankdir=TB;  // Top to Bottom')
        lines.append('  node [shape=box, fontname="Helvetica"];')
        lines.append('')
        
        for name, mod in self.modules.items():
            color = '#E8F4F8' if mod.type == 'fmod' else '#FFF4E6'
            shape = 'box' if mod.type == 'fmod' else 'box3d'
            lines.append(f'  "{name}" [label="{name}", fillcolor="{color}", style="filled", shape={shape}];')
        
        lines.append('')
        
        for name, mod in self.modules.items():
            for imp_type, imp_name in mod.imports:
                if imp_name in self.modules:
                    style = 'dashed' if imp_type == 'pr' else 'solid'
                    color = '#666666' if imp_type == 'pr' else '#0066CC'
                    lines.append(f'  "{name}" -> "{imp_name}" [style={style}, color="{color}"];')
        
        lines.append('}')
        
        with open(filepath, 'w') as f:
            f.write('\n'.join(lines))
    
    def _get_sort_hierarchy(self) -> Dict[str, List[str]]:
        """获取Sort层次结构"""
        hierarchy = defaultdict(list)
        for module in self.modules.values():
            for child, parent in module.subsorts:
                hierarchy[parent].append(child)
        return dict(hierarchy)
