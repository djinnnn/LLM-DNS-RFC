# -*- coding: utf-8 -*-
"""
Maude Parser Pipeline
主流程：解析 → 提取 → 导出
"""
import os
from typing import List
from .extractors.maude_extractor import MaudeExtractor
from .exporters.json_exporter import JSONExporter
from .exporters.dot_exporter import DOTExporter


class MaudeParserPipeline:
    """Maude 解析主流程"""
    
    def __init__(self):
        self.extractor = MaudeExtractor()
    
    def parse_files(self, file_paths: List[str]) -> None:
        """解析多个 Maude 文件"""
        for file_path in file_paths:
            if os.path.exists(file_path):
                print(f"Parsing {os.path.basename(file_path)}...")
                self.extractor.parse_file(file_path)
            else:
                print(f"Warning: File not found: {file_path}")
    
    def export_json(self, contract_path: str, tagging_path: str = None) -> None:
        """导出 JSON 接口契约和标签体系"""
        exporter = JSONExporter(
            self.extractor.modules,
            self.extractor.actor_types,
            self.extractor.actor_attributes
        )
        
        # 导出契约
        exporter.export_to_json(contract_path)
        print(f"\n✓ JSON contract exported to: {contract_path}")
        
        # 导出标签体系（如果指定路径）
        if tagging_path:
            exporter.export_tagging_system(tagging_path)
            print(f"✓ Tagging system exported to: {tagging_path}")
    
    def export_visualizations(self, output_dir: str) -> None:
        """导出可视化文件"""
        exporter = DOTExporter(
            self.extractor.modules,
            self.extractor.actor_types,
            self.extractor.actor_attributes
        )
        exporter.export_all(output_dir)
    
    def display_summary(self) -> None:
        """显示提取摘要"""
        print("=" * 70)
        print("MAUDE DNS MODEL - EXTRACTION SUMMARY")
        print("=" * 70)
        
        print(f"\n### MODULES: {len(self.extractor.modules)}")
        for name, mod in self.extractor.modules.items():
            print(f"  [{mod.type.upper()}] {name}")
        
        print(f"\n### ACTORS: {len(self.extractor.actor_types)}")
        for actor in self.extractor.actor_types:
            attr_count = len(self.extractor.actor_attributes.get(actor, []))
            print(f"  - {actor} ({attr_count} attributes)")
        
        total_rules = sum(len(m.rules) for m in self.extractor.modules.values())
        print(f"\n### RULES: {total_rules}")
        
        print("\n" + "=" * 70)


def main():
    """主函数示例"""
    import sys
    
    # 获取脚本所在目录
    script_dir = os.path.dirname(os.path.abspath(__file__))
    base_path = os.path.join(script_dir, "../../Maude/src")
    
    # 要解析的文件列表
    files_to_parse = [
        "common/actor.maude",
        "common/prelim.maude",
        "common/_aux.maude",
        "common/parameters.maude",
        "common/label_graph.maude",
        "nondet-model/_aux.maude",
        "nondet-model/dns.maude",
    ]
    
    full_paths = [os.path.join(base_path, f) for f in files_to_parse]
    
    pipeline = MaudeParserPipeline()
    
    pipeline.parse_files(full_paths)
    
    pipeline.display_summary()
    
    output_dir = os.path.join(script_dir, "../output")
    os.makedirs(output_dir, exist_ok=True)
    pipeline.export_json(
        contract_path=os.path.join(output_dir, "maude_contract.json"),
        tagging_path=os.path.join(output_dir, "maude_tagging.json")
    )
    
    viz_dir = os.path.join(script_dir, "../visualization")
    pipeline.export_visualizations(viz_dir)


if __name__ == "__main__":
    main()
