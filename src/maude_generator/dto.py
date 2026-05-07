# -*- coding: utf-8 -*-
"""
Maude Generator 数据传输对象。
"""
from dataclasses import dataclass, field
from typing import List


@dataclass
class GenerationResult:
    """Phase 4 输出：IR → Maude 源代码。"""
    success: bool
    generated_code: str = ""
    target_name: str = ""
    errors: List[str] = field(default_factory=list)
