# -*- coding: utf-8 -*-
"""
JSON 导出器
将 Maude 结构提取为接口契约 JSON 格式
"""
import json
from typing import Dict, List, Set, Any
from collections import defaultdict
from ..models.maude_ast import Module, Rule, Op
from ..models.contract import (
    MaudeContract, SortContract, ActorContract, RuleContract,
    StateAccess, AccessMode, GuardSlot, ActionSlot,
    TaggingSystem, EntityTags
)


class JSONExporter:
    """JSON 契约导出器"""
    
    def __init__(self, modules: Dict[str, Module], actor_types: List[str], 
                 actor_attributes: Dict[str, List[tuple]]):
        self.modules = modules
        self.actor_types = actor_types
        self.actor_attributes = actor_attributes
        
    def export_contract(self) -> MaudeContract:
        """导出完整的接口契约"""
        contract = MaudeContract()
        
        # 元数据
        contract.metadata = {
            "model_type": "nondet-dns",
            "version": "1.0",
            "total_modules": len(self.modules),
            "total_actors": len(self.actor_types),
            "total_rules": sum(len(m.rules) for m in self.modules.values())
        }
        
        # 提取 Sort 契约
        contract.sorts = self._extract_sort_contracts()
        
        # 提取 Actor 契约
        contract.actors = self._extract_actor_contracts()
        
        # 提取 Rule 契约
        contract.rules = self._extract_rule_contracts()
        
        # 提取模块信息
        contract.modules = self._extract_module_info()
        
        # 提取 Sort 层级
        contract.sort_hierarchy = self._extract_sort_hierarchy()
        
        return contract
    
    def _extract_sort_contracts(self) -> Dict[str, SortContract]:
        """提取 Sort 接口契约"""
        sort_contracts = {}
        sort_to_module = {}
        sort_to_actors = defaultdict(set)
        
        # 收集所有 Sort 定义
        for mod_name, module in self.modules.items():
            for sort in module.sorts:
                if sort not in sort_contracts:
                    sort_contracts[sort] = SortContract(name=sort, defined_in=mod_name)
                    sort_to_module[sort] = mod_name
            
            # 收集构造器和操作符
            for op in module.ops:
                if op.coarity in sort_contracts:
                    if 'ctor' in op.attrs:
                        sort_contracts[op.coarity].constructors.append({
                            "name": op.name,
                            "params": op.arity
                        })
                    else:
                        sort_contracts[op.coarity].operators.append({
                            "name": op.name,
                            "arity": op.arity,
                            "coarity": op.coarity
                        })
        
        # 收集 subsort 关系
        for module in self.modules.values():
            for child, parent in module.subsorts:
                if parent in sort_contracts:
                    sort_contracts[parent].subsorts.append(child)
                if child in sort_contracts:
                    sort_contracts[child].supersorts.append(parent)
        
        # 标记被 Actor 使用的 Sort
        for actor_name, attrs in self.actor_attributes.items():
            for attr_name, param_sort, _ in attrs:
                sort_to_actors[param_sort].add(actor_name)
        
        for sort_name, actors in sort_to_actors.items():
            if sort_name in sort_contracts:
                sort_contracts[sort_name].used_by_actors = actors
        
        return sort_contracts
    
    def _extract_actor_contracts(self) -> Dict[str, ActorContract]:
        """提取 Actor 接口契约"""
        actor_contracts = {}
        
        for actor_name in self.actor_types:
            contract = ActorContract(name=actor_name)
            
            # 提取状态接口
            if actor_name in self.actor_attributes:
                for attr_name, param_sort, full_op_name in self.actor_attributes[actor_name]:
                    # 简单启发式：cache/queue 等是 read-write，其他默认 read
                    mode = AccessMode.READ_WRITE if any(
                        kw in attr_name.lower() 
                        for kw in ['cache', 'queue', 'budget', 'queries', 'blocked', 'sent']
                    ) else AccessMode.READ
                    
                    contract.state_interface[attr_name] = StateAccess(
                        attribute=attr_name,
                        sort=param_sort,
                        mode=mode
                    )
            
            # 提取消息接口（从规则推断）
            receives = set()
            sends = set()
            rules_handled = []
            
            for module in self.modules.values():
                for rule in module.rules:
                    # 简单启发式：规则名包含 actor 名称
                    if actor_name.lower() in rule.name.lower():
                        rules_handled.append(rule.name)
                        
                        # 推断消息类型
                        if 'recv' in rule.name.lower():
                            if 'query' in rule.name.lower():
                                receives.add('query')
                            if 'response' in rule.name.lower() or 'ans' in rule.name.lower():
                                receives.add('response')
                        
                        if 'send' in rule.name.lower() or 'reply' in rule.name.lower():
                            sends.add('response')
            
            contract.message_interface = {
                "receives": list(receives),
                "sends": list(sends)
            }
            contract.rules_handled = rules_handled
            
            # 查找定义模块
            for mod_name, module in self.modules.items():
                for op in module.ops:
                    if op.name == actor_name and op.coarity == 'ActorType':
                        contract.defined_in = mod_name
                        break
            
            actor_contracts[actor_name] = contract
        
        return actor_contracts
    
    def _extract_rule_contracts(self) -> Dict[str, RuleContract]:
        """提取 Rule 接口契约（带 Slot 占位符）"""
        rule_contracts = {}
        
        for module in self.modules.values():
            for rule in module.rules:
                rule_id = f"{module.name}:{rule.name}"
                
                # 推断 Actor 角色
                actor_role = self._infer_actor_role(rule.name)
                
                # 推断事件模式
                event_pattern = self._infer_event_pattern(rule.name, rule.lhs)
                
                # 推断状态读写
                state_reads, state_writes = self._infer_state_access(rule.lhs, rule.rhs, actor_role)
                
                # 创建 Guard Slots（如果是条件规则）
                guard_slots = []
                if rule.is_conditional and rule.condition:
                    guard_slots.append(GuardSlot(
                        slot_id=f"{rule.name}-guard",
                        description=f"Condition for {rule.name}",
                        template=rule.condition
                    ))
                
                # 创建 Action Slots（从 RHS 推断）
                action_slots = self._infer_action_slots(rule.name, rule.rhs)
                
                contract = RuleContract(
                    rule_id=rule_id,
                    rule_name=rule.name,
                    actor_role=actor_role,
                    event_pattern=event_pattern,
                    guard_slots=guard_slots,
                    action_slots=action_slots,
                    state_reads=state_reads,
                    state_writes=state_writes,
                    is_conditional=rule.is_conditional,
                    defined_in=module.name
                )
                
                rule_contracts[rule_id] = contract
        
        return rule_contracts
    
    def _infer_actor_role(self, rule_name: str) -> str:
        """从规则名推断 Actor 角色"""
        rule_lower = rule_name.lower()
        for actor in self.actor_types:
            if actor.lower() in rule_lower:
                return actor
        
        # 启发式推断
        if 'client' in rule_lower:
            return 'Client'
        elif 'resolver' in rule_lower:
            return 'Resolver'
        elif 'nameserver' in rule_lower or 'ns' in rule_lower:
            return 'Nameserver'
        elif 'monitor' in rule_lower:
            return 'Monitor'
        
        return 'Unknown'
    
    def _infer_event_pattern(self, rule_name: str, lhs: str) -> str:
        """推断事件模式"""
        if 'recv' in rule_name.lower():
            if 'query' in rule_name.lower():
                return 'recv query(...)'
            elif 'response' in rule_name.lower() or 'ans' in rule_name.lower():
                return 'recv response(...)'
            elif 'referral' in rule_name.lower():
                return 'recv referral(...)'
        elif 'start' in rule_name.lower():
            return 'init'
        elif 'timeout' in rule_name.lower():
            return 'timeout'
        
        return 'unknown_event'
    
    def _infer_state_access(self, lhs: str, rhs: str, actor_role: str) -> tuple:
        """推断状态读写"""
        reads = []
        writes = []
        
        if actor_role in self.actor_attributes:
            for attr_name, _, _ in self.actor_attributes[actor_role]:
                # 简单启发式：LHS 中出现即为读
                if attr_name in lhs:
                    reads.append(attr_name)
                # RHS 中出现且与 LHS 不同即为写
                if attr_name in rhs and rhs.count(attr_name) > lhs.count(attr_name):
                    writes.append(attr_name)
        
        return reads, writes
    
    def _infer_action_slots(self, rule_name: str, rhs: str) -> List[ActionSlot]:
        """推断 Action Slots"""
        slots = []
        
        # 启发式推断常见动作
        if 'cache' in rhs.lower():
            slots.append(ActionSlot(
                slot_id=f"{rule_name}-cache-update",
                action_type="cache_operation",
                description="Update cache with new records"
            ))
        
        if 'send' in rhs.lower() or 'msg' in rhs.lower():
            slots.append(ActionSlot(
                slot_id=f"{rule_name}-send-msg",
                action_type="send_message",
                description="Send message to another actor"
            ))
        
        return slots
    
    def _generate_rule_tags(self, rule_name: str, actor_role: str) -> Dict[str, Any]:
        """生成规则标签"""
        tags = {
            "entity_type": "rule",
            "actor": actor_role
        }
        
        rule_lower = rule_name.lower()
        
        # 消息类型标签
        if 'query' in rule_lower:
            tags["msg_pattern"] = "query"
        elif 'response' in rule_lower or 'ans' in rule_lower:
            tags["msg_pattern"] = "response"
        
        # 行为标签
        if 'recv' in rule_lower:
            tags["behavior"] = "receive"
        elif 'send' in rule_lower or 'reply' in rule_lower:
            tags["behavior"] = "send"
        
        # 复杂度标签
        tags["complexity"] = "conditional" if 'crl' in rule_lower else "simple"
        
        return tags
    
    def _extract_module_info(self) -> Dict[str, Dict[str, Any]]:
        """提取模块信息"""
        module_info = {}
        
        for mod_name, module in self.modules.items():
            module_info[mod_name] = {
                "type": module.type,
                "imports": [{"type": imp_type, "module": imp_name} 
                           for imp_type, imp_name in module.imports],
                "sorts_defined": module.sorts,
                "rules_defined": [r.name for r in module.rules],
                "operators_count": len(module.ops),
                "equations_count": len(module.eqs)
            }
        
        return module_info
    
    def _extract_sort_hierarchy(self) -> Dict[str, List[str]]:
        """提取 Sort 层级关系"""
        hierarchy = defaultdict(list)
        
        for module in self.modules.values():
            for child, parent in module.subsorts:
                hierarchy[parent].append(child)
        
        return dict(hierarchy)
    
    def export_to_json(self, output_path: str, indent: int = 2) -> None:
        """导出为 JSON 文件（仅契约，不含标签）"""
        contract = self.export_contract()
        contract_dict = self._contract_to_dict(contract)
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(contract_dict, f, indent=indent, ensure_ascii=False)
    
    def export_tagging_system(self, output_path: str, indent: int = 2) -> None:
        """导出标签体系（独立文件）"""
        tagging = self._build_tagging_system()
        tagging_dict = self._tagging_to_dict(tagging)
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(tagging_dict, f, indent=indent, ensure_ascii=False)
    
    def _contract_to_dict(self, contract: MaudeContract) -> Dict[str, Any]:
        """将契约对象转换为字典"""
        return {
            "metadata": contract.metadata,
            "sorts": {
                name: {
                    "name": sort.name,
                    "constructors": sort.constructors,
                    "operators": sort.operators,
                    "subsorts": sort.subsorts,
                    "supersorts": sort.supersorts,
                    "defined_in": sort.defined_in,
                    "used_by_actors": list(sort.used_by_actors)
                }
                for name, sort in contract.sorts.items()
            },
            "actors": {
                name: {
                    "name": actor.name,
                    "inherits_from": actor.inherits_from,
                    "state_interface": {
                        attr_name: {
                            "attribute": access.attribute,
                            "sort": access.sort,
                            "mode": access.mode.value,
                            "is_inherited": access.is_inherited,
                            "inherited_from": access.inherited_from
                        }
                        for attr_name, access in actor.state_interface.items()
                    },
                    "message_interface": actor.message_interface,
                    "rules_handled": actor.rules_handled,
                    "defined_in": actor.defined_in
                }
                for name, actor in contract.actors.items()
            },
            "rules": {
                rule_id: {
                    "rule_id": rule.rule_id,
                    "rule_name": rule.rule_name,
                    "actor_role": rule.actor_role,
                    "event_pattern": rule.event_pattern,
                    "guard_slots": [
                        {
                            "slot_id": slot.slot_id,
                            "description": slot.description,
                            "rfc_reference": slot.rfc_reference,
                            "template": slot.template
                        }
                        for slot in rule.guard_slots
                    ],
                    "action_slots": [
                        {
                            "slot_id": slot.slot_id,
                            "action_type": slot.action_type,
                            "description": slot.description,
                            "rfc_reference": slot.rfc_reference,
                            "template": slot.template
                        }
                        for slot in rule.action_slots
                    ],
                    "state_reads": rule.state_reads,
                    "state_writes": rule.state_writes,
                    "message_sends": rule.message_sends,
                    "is_conditional": rule.is_conditional,
                    "defined_in": rule.defined_in,
                    "rfc_references": rule.rfc_references
                }
                for rule_id, rule in contract.rules.items()
            },
            "modules": contract.modules,
            "sort_hierarchy": contract.sort_hierarchy
        }
    
    def _build_tagging_system(self) -> TaggingSystem:
        """构建标签体系"""
        tagging = TaggingSystem()
        tagging.metadata = {
            "description": "Maude DNS Model Tagging System",
            "version": "1.0",
            "total_entities": 0
        }
        
        # 为 Rules 生成标签
        for module in self.modules.values():
            for rule in module.rules:
                rule_id = f"{module.name}:{rule.name}"
                actor_role = self._infer_actor_role(rule.name)
                tags = self._generate_rule_tags(rule.name, actor_role)
                
                entity_tags = EntityTags(
                    entity_id=rule_id,
                    entity_type="rule",
                    tags=tags
                )
                tagging.entity_tags[rule_id] = entity_tags
                
                # 构建标签索引
                for tag_key, tag_value in tags.items():
                    index_key = f"{tag_key}:{tag_value}"
                    if index_key not in tagging.tag_index:
                        tagging.tag_index[index_key] = []
                    tagging.tag_index[index_key].append(rule_id)
        
        # 为 Actors 生成标签
        for actor_name in self.actor_types:
            entity_tags = EntityTags(
                entity_id=actor_name,
                entity_type="actor",
                tags={
                    "entity_type": "actor",
                    "role": actor_name,
                    "has_state": len(self.actor_attributes.get(actor_name, [])) > 0
                }
            )
            tagging.entity_tags[actor_name] = entity_tags
            
            for tag_key, tag_value in entity_tags.tags.items():
                index_key = f"{tag_key}:{tag_value}"
                if index_key not in tagging.tag_index:
                    tagging.tag_index[index_key] = []
                tagging.tag_index[index_key].append(actor_name)
        
        # 为 Sorts 生成标签
        for module in self.modules.values():
            for sort in module.sorts:
                tags = {
                    "entity_type": "sort",
                    "defined_in": module.name,
                    "is_actor_type": sort in self.actor_types
                }
                
                # 推断 Sort 类别
                if "Msg" in sort or "Query" in sort or "Response" in sort:
                    tags["category"] = "message"
                elif "Cache" in sort:
                    tags["category"] = "cache"
                elif "Record" in sort:
                    tags["category"] = "dns-record"
                elif "Address" in sort or "Name" in sort:
                    tags["category"] = "identifier"
                else:
                    tags["category"] = "other"
                
                entity_tags = EntityTags(
                    entity_id=sort,
                    entity_type="sort",
                    tags=tags
                )
                tagging.entity_tags[sort] = entity_tags
                
                for tag_key, tag_value in tags.items():
                    index_key = f"{tag_key}:{tag_value}"
                    if index_key not in tagging.tag_index:
                        tagging.tag_index[index_key] = []
                    tagging.tag_index[index_key].append(sort)
        
        tagging.metadata["total_entities"] = len(tagging.entity_tags)
        return tagging
    
    def _tagging_to_dict(self, tagging: TaggingSystem) -> Dict[str, Any]:
        """将标签体系转换为字典"""
        return {
            "metadata": tagging.metadata,
            "entity_tags": {
                entity_id: {
                    "entity_id": tags.entity_id,
                    "entity_type": tags.entity_type,
                    "tags": tags.tags
                }
                for entity_id, tags in tagging.entity_tags.items()
            },
            "tag_index": tagging.tag_index
        }
