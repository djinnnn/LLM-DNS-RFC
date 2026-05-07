# -*- coding: utf-8 -*-
"""
Pipeline 调试输出工具。
将展示逻辑从编排器中分离，保持 run() 方法干净。
"""
from __future__ import annotations

import json
from typing import Any, Dict


class PipelineReporter:
    """
    负责 Pipeline 各阶段的调试输出。
    当 debug=False 时，所有方法静默返回。
    """

    def __init__(self, debug: bool = False) -> None:
        self.debug = debug

    # ─── 基础输出 ─────────────────────────────────────────────

    def debug_msg(self, msg: str) -> None:
        """输出调试信息（仅当 debug=True）。"""
        if self.debug:
            print(f"[DEBUG] {msg}")

    def banner(self, title: str) -> None:
        """输出醒目的阶段分隔横幅。"""
        if not self.debug:
            return
        w = 64
        print()
        print(f"╔{'═' * w}╗")
        print(f"║  {title:<{w - 2}}║")
        print(f"╚{'═' * w}╝")

    def detail(self, msg: str, indent: int = 2) -> None:
        """输出缩进的调试详情行。"""
        if self.debug:
            print(f"{' ' * indent}{msg}")

    # ─── ContextPack 摘要 ─────────────────────────────────────

    def print_context_summary(self, context_pack: Dict[str, Any]) -> None:
        """紧凑输出 ContextPack 摘要。"""
        if not self.debug:
            return
        seed = context_pack.get('seed', {})
        seed_id = seed.get('id', seed.get('section_id', 'N/A'))
        seed_title = seed.get('title', '')
        seed_text = seed.get('content', '') or seed.get('text', '') or ''
        self.detail(f"Seed: {seed_id} \"{seed_title}\" ({len(seed_text)} chars)")
        if seed_text:
            preview = seed_text[:200].replace('\n', ' ')
            self.detail(f"  → {preview}{'...' if len(seed_text) > 200 else ''}", 4)

        local = context_pack.get('local_structure', {})
        ancestors = local.get('ancestors', [])
        descendants = local.get('descendants', [])
        self.detail(f"Local: {len(ancestors)} ancestors, {len(descendants)} descendants")
        for anc in ancestors:
            if isinstance(anc, dict):
                a_id = anc.get('section_id', anc.get('id', '?'))
                a_title = anc.get('title', '')
                self.detail(f"  ↑ {a_id} \"{a_title}\"", 4)
        for desc in descendants:
            if isinstance(desc, dict):
                d_id = desc.get('section_id', desc.get('id', '?'))
                d_title = desc.get('title', '')
                d_len = len(desc.get('text', '') or desc.get('content', '') or '')
                self.detail(f"  ↓ {d_id} \"{d_title}\" ({d_len} chars)", 4)

        refs = context_pack.get('references', {})
        norm_sec = refs.get('normative', {}).get('section_level', [])
        norm_doc = refs.get('normative', {}).get('document_level', [])
        info_sec = refs.get('informative', {}).get('section_level', [])
        sem = context_pack.get('semantic_expansion', [])
        self.detail(f"References: {len(norm_sec)} normative-section, {len(norm_doc)} normative-doc, {len(info_sec)} informative-section")
        self.detail(f"Semantic expansion: {len(sem)} items")
        for item in sem[:5]:
            if isinstance(item, dict):
                r = item.get('retrieved_section', {})
                self.detail(f"  ◆ {r.get('section_id', '?')} score={item.get('score', '?'):.4f}", 4)

    # ─── 归一化详情 ───────────────────────────────────────────

    def print_normalization_detail(self, normalized_ir: Dict[str, Any]) -> None:
        """逐条输出每条规则的归一化结果。"""
        if not self.debug:
            return
        rules = normalized_ir.get('semantic_rules', [])
        for rule in rules:
            rule_id = rule.get('id', '?')
            norm = rule.get('_normalized', {})
            resolved = norm.get('resolved', '?')
            self.detail(f"Rule [{rule_id}]  resolved={resolved}")

            # modality
            raw_mod = rule.get('modality', '')
            n_mod = norm.get('modality')
            mark = '✓' if n_mod else '✗'
            self.detail(f"  modality: \"{raw_mod}\" → {mark} {n_mod or 'unresolved'}", 4)

            # actor
            actor = rule.get('actor', {})
            raw_actor = actor.get('name', '') if isinstance(actor, dict) else str(actor)
            n_actor = norm.get('actor_type')
            mark = '✓' if n_actor else '✗'
            self.detail(f"  actor: \"{raw_actor}\" → {mark} {n_actor or 'unresolved'}", 4)

            # event
            event = rule.get('event', {})
            raw_event = f"{event.get('kind', '')}:{event.get('expr', '')}" if isinstance(event, dict) else str(event)
            n_event = norm.get('event_pattern')
            mark = '✓' if n_event else '✗'
            self.detail(f"  event: \"{raw_event}\" → {mark} {n_event or 'unresolved'}", 4)

            # actions
            actions = rule.get('actions', [])
            action_types = norm.get('action_types', [])
            for i, act in enumerate(actions):
                raw_act = f"{act.get('kind', '')}:{act.get('expr', '')[:60]}" if isinstance(act, dict) else str(act)
                n_act = action_types[i] if i < len(action_types) else None
                mark = '✓' if n_act else '✗'
                self.detail(f"  action[{i}]: \"{raw_act}\" → {mark} {n_act or 'unresolved'}", 4)

            # conditions
            predicates = norm.get('predicates', [])
            for i, pred in enumerate(predicates):
                expr = pred.get('original_expr', '?')
                resolved_p = pred.get('resolved', False)
                matched = pred.get('matched_predicates', [])
                mark = '✓' if resolved_p else '✗'
                match_str = matched[0]['name'] if matched else 'unresolved'
                self.detail(f"  condition[{i}]: \"{expr[:60]}\" → {mark} {match_str}", 4)
