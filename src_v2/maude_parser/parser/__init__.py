"""Pure-syntax layer.

Forbidden in this package: any actor / attribute / message semantics. AST 输出
应当对 Maude 源码忠实无损。

Implementation note (deviation from memo §2 "Lark"):
    Maude is a whitespace-tokenized language whose mixfix operator names freely
    contain `.`, `;`, `:`, `_`. Off-the-shelf Lark grammars constantly fight the
    library's lexer-priority machinery on these. We therefore use a hand-written
    Maude tokenizer + recursive-descent parser. The contract — "real parser
    instead of regex" — is fully met; this is a tactical deviation, not a
    strategic one.
"""
from .maude_parser import MaudeParser, MaudeSyntaxError, parse_file, parse_text  # noqa: F401
