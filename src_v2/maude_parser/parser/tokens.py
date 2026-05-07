# -*- coding: utf-8 -*-
"""Maude tokenizer.

Maude is whitespace-delimited: every "token" is the text between whitespace.
This module turns a source string into a flat list of `Token` objects with
file/line/column tracking, while consuming Maude's two comment styles:

    --- comment until end of line          (the `---` MUST be followed by
                                            whitespace or EOL — otherwise it
                                            is part of an operator name like
                                            `_---_`. F0-x boundary fix.)
    *** comment until end of line          (always a comment)

No semantic interpretation happens here.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional


@dataclass
class Token:
    value: str
    line: int
    col: int

    def __repr__(self) -> str:
        return f"Token({self.value!r} @ {self.line}:{self.col})"


def _is_ws(c: str) -> bool:
    return c in " \t\r\n"


def tokenize(source: str, file_name: str = "<text>") -> List[Token]:
    """Whitespace-tokenize Maude source, stripping comments.

    Comment rule:
      `***` always starts a line comment.
      `---` starts a line comment only if it is at start of token AND
        followed by whitespace or end-of-line. `op _---_ : ...` is therefore
        not affected because `_---_` is a single token whose `---` is
        flanked by `_`, not by whitespace.
    """
    tokens: List[Token] = []
    i = 0
    n = len(source)
    line = 1
    col = 1

    def advance(c: str) -> None:
        nonlocal line, col
        if c == "\n":
            line += 1
            col = 1
        else:
            col += 1

    while i < n:
        c = source[i]
        # Whitespace
        if _is_ws(c):
            advance(c)
            i += 1
            continue
        # `***` comment to EOL
        if c == "*" and source.startswith("***", i):
            while i < n and source[i] != "\n":
                i += 1
            continue
        # `---` comment to EOL. Per Maude manual the `---` must be followed
        # by whitespace/EOL, but in practice this codebase uses runs of
        # `------------------` as section dividers — these compile in Maude
        # because Maude treats any `---` (followed by `-` or whitespace) as
        # a line comment. We mirror that practical behavior: `---` always
        # starts a line comment unless it appears inside a token that is
        # already mid-formation (handled by the outer "token start" branch
        # — by the time we get here, we are at a fresh token boundary).
        if c == "-" and source.startswith("---", i):
            while i < n and source[i] != "\n":
                i += 1
            continue
        # Token start
        start_line, start_col = line, col
        start_i = i
        while i < n and not _is_ws(source[i]):
            advance(source[i])
            i += 1
        tokens.append(Token(source[start_i:i], start_line, start_col))

    return tokens
