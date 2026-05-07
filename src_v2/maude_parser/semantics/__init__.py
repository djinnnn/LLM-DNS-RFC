"""Semantics layer.

Reads AST, derives actor / attribute / actor-attribute binding facts.
Forbidden: any string regex / direct text scanning. Only consume the structured
AST from ../parser/.
"""
from .actor_resolver import ActorResolver, ActorSemantics, AttrBinding  # noqa: F401
