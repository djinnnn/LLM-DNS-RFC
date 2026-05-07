# -*- coding: utf-8 -*-
"""Maude module parser (recursive descent over whitespace tokens).

Output: `Module / Op / Equation / Rule / View` AST (see ../models/maude_ast.py).
Forbidden: any actor / attribute / message semantics. That all lives in
../semantics/.

What this parser knows:
  - Module headers: `fmod NAME is ... endfm`, `mod NAME is ... endm`
  - Statements: `sort(s)`, `subsort(s)` (chained!), `op` / `ops`, `var(s)`,
    `eq` / `ceq`, `rl` / `crl`, `view`, `pr` / `inc` / `ex`
  - Mixfix op names containing `.`, `;`, `:`, `_`
  - Op attribute lists `[ctor assoc comm id: nil prec 10 format (...)]`
  - Parameterized sorts `Foo{X}` (kept as a single sort token)
  - Comment boundary: `---` only starts a comment when followed by whitespace

What it does NOT know:
  - Term structure of eq/rl LHS/RHS — those are kept as raw whitespace-joined
    strings (that's what downstream consumes; structural term trees are a
    backlog item in stage_0_redesign.md §9).
  - Theory `th/endth`, parameterized modules `mod M{X :: TH}`, `omod`.
"""
from __future__ import annotations

import os
from typing import Dict, List, Optional, Tuple

from ..models.maude_ast import Equation, Module, Op, Rule, View
from .tokens import Token, tokenize


class MaudeSyntaxError(Exception):
    def __init__(self, message: str, file: str, line: int, col: int, near_text: str = ""):
        self.file = file
        self.line = line
        self.col = col
        self.near_text = near_text
        super().__init__(f"{file}:{line}:{col}: {message}  (near: {near_text!r})")


# Statement-terminator sentinel: the literal `.` token (operator names that
# include a period embed it inside a multi-char token like `_._`, never as
# a standalone `.` token, because they are surrounded by underscores. The
# whitespace-tokenizer guarantees this — any `.` appearing between
# whitespace is the statement terminator.
_DOT = "."


class _Cursor:
    """Stream of tokens with peek/expect helpers."""

    def __init__(self, tokens: List[Token], file_name: str) -> None:
        self.tokens = tokens
        self.i = 0
        self.file = file_name

    def peek(self, k: int = 0) -> Optional[Token]:
        j = self.i + k
        if j < len(self.tokens):
            return self.tokens[j]
        return None

    def take(self) -> Token:
        if self.i >= len(self.tokens):
            raise MaudeSyntaxError("unexpected end of input", self.file, 0, 0)
        t = self.tokens[self.i]
        self.i += 1
        return t

    def take_value(self) -> str:
        return self.take().value

    def at_end(self) -> bool:
        return self.i >= len(self.tokens)

    def expect(self, value: str) -> Token:
        t = self.peek()
        if t is None or t.value != value:
            ctx = t.value if t else "<EOF>"
            line = t.line if t else 0
            col = t.col if t else 0
            raise MaudeSyntaxError(
                f"expected {value!r}", self.file, line, col, ctx
            )
        return self.take()


# =========================================================================
# Top-level entry points
# =========================================================================

class MaudeParser:
    """Accumulates parsed modules across multiple files (parity with old API)."""

    def __init__(self) -> None:
        self.modules: Dict[str, Module] = {}

    def parse_file(self, path: str) -> List[Module]:
        with open(path, "r", encoding="utf-8") as f:
            src = f.read()
        return self.parse_text(src, file_name=os.path.basename(path))

    def parse_text(self, source: str, file_name: str = "<text>") -> List[Module]:
        toks = tokenize(source, file_name)
        cur = _Cursor(toks, file_name)
        out: List[Module] = []
        while not cur.at_end():
            t = cur.peek()
            assert t is not None
            v = t.value
            if v in ("fmod", "mod"):
                m = _parse_module(cur)
                self.modules[m.name] = m
                out.append(m)
            elif v == "view":
                # Top-level view (allowed). Old extractor parsed views inside
                # any module body; we surface them by attaching to a synthetic
                # placeholder OR by storing them on the most recent module.
                # For parity we attach to the most recent module if any;
                # otherwise drop with a warning to stderr.
                view = _parse_view(cur)
                if out:
                    out[-1].views.append(view)
                # else: silently dropped to keep AST clean.
            elif v in ("set",):
                # Maude commands like `set show advisories off .` — skip until `.`
                _skip_until_dot(cur)
            else:
                # Unknown top-level token — skip one token to avoid infinite loop
                cur.take()
        return out


def parse_text(source: str, file_name: str = "<text>") -> List[Module]:
    return MaudeParser().parse_text(source, file_name)


def parse_file(path: str) -> List[Module]:
    return MaudeParser().parse_file(path)


# =========================================================================
# Module body
# =========================================================================

def _parse_module(cur: _Cursor) -> Module:
    head = cur.take()
    mod_type = head.value  # 'fmod' or 'mod'
    name_tok = cur.take()
    cur.expect("is")
    end_kw = "endfm" if mod_type == "fmod" else "endm"

    module = Module(name=name_tok.value, type=mod_type)

    while True:
        t = cur.peek()
        if t is None:
            raise MaudeSyntaxError(
                f"unterminated module {name_tok.value!r} (expected {end_kw})",
                cur.file, name_tok.line, name_tok.col,
            )
        if t.value == end_kw:
            cur.take()
            break
        # Both `endfm` & `endm` are valid module terminators in the wild —
        # accept either to be lenient (some files mix them).
        if t.value in ("endfm", "endm"):
            cur.take()
            break
        _parse_statement_into_module(cur, module)

    return module


def _parse_statement_into_module(cur: _Cursor, module: Module) -> None:
    head = cur.peek()
    assert head is not None
    kw = head.value

    if kw in ("pr", "inc", "ex", "extending", "protecting", "including"):
        cur.take()
        kind = {
            "pr": "pr", "protecting": "pr",
            "inc": "inc", "including": "inc",
            "ex": "ex", "extending": "ex",
        }[kw]
        # Names until `.`, separated by `+`
        names_buf: List[str] = []
        while True:
            t = cur.peek()
            if t is None or t.value == _DOT:
                break
            tok = cur.take().value
            if tok == "+":
                continue
            names_buf.append(tok)
        if cur.peek() and cur.peek().value == _DOT:
            cur.take()
        for name in names_buf:
            # strip any trailing punctuation that snuck in
            clean = name.strip(",")
            if clean:
                module.imports.append((kind, clean))
        return

    if kw in ("sort", "sorts"):
        cur.take()
        names = _take_until_dot(cur)
        module.sorts.extend(_filter_sort_names(names))
        return

    if kw in ("subsort", "subsorts"):
        cur.take()
        names = _take_until_dot(cur)
        module.subsorts.extend(_parse_subsort_chain(names))
        return

    if kw in ("op", "ops"):
        cur.take()
        ops = _parse_op_decl(cur, plural=(kw == "ops"))
        module.ops.extend(ops)
        return

    if kw in ("var", "vars"):
        cur.take()
        toks = _take_until_dot(cur)
        # Format:  X1 X2 ... : Sort
        if ":" in toks:
            colon_i = toks.index(":")
            var_names = toks[:colon_i]
            sort_part = toks[colon_i + 1:]
            sort = sort_part[0] if sort_part else ""
            if sort:
                module.vars.setdefault(sort, []).extend(var_names)
        return

    if kw == "eq":
        cur.take()
        toks = _take_until_dot(cur)
        lhs, rhs = _split_on_eq(toks)
        module.eqs.append(Equation(lhs=" ".join(lhs), rhs=" ".join(rhs), is_conditional=False))
        return

    if kw == "ceq":
        cur.take()
        toks = _take_until_dot(cur)
        # Format: LHS = RHS if COND
        lhs, rest = _split_on_eq(toks)
        rhs, cond = _split_on_if(rest)
        module.eqs.append(Equation(
            lhs=" ".join(lhs), rhs=" ".join(rhs),
            condition=" ".join(cond) if cond else None,
            is_conditional=True,
        ))
        return

    if kw == "rl":
        cur.take()
        # Optional [name] :
        name, body_toks = _parse_rule_head_until_dot(cur)
        lhs, rhs = _split_on_arrow(body_toks)
        module.rules.append(Rule(
            name=name, lhs=" ".join(lhs), rhs=" ".join(rhs), is_conditional=False
        ))
        return

    if kw == "crl":
        cur.take()
        name, body_toks = _parse_rule_head_until_dot(cur)
        lhs, rest = _split_on_arrow(body_toks)
        rhs, cond = _split_on_if(rest)
        module.rules.append(Rule(
            name=name, lhs=" ".join(lhs), rhs=" ".join(rhs),
            condition=" ".join(cond) if cond else None,
            is_conditional=True,
        ))
        return

    # Unknown statement keyword — skip until `.` to keep going. This is
    # deliberately lenient: better to ignore one weird statement than abort.
    _skip_until_dot(cur)


# =========================================================================
# Helpers — consume tokens up to `.`
# =========================================================================

def _take_until_dot(cur: _Cursor) -> List[str]:
    out: List[str] = []
    while True:
        t = cur.peek()
        if t is None:
            return out
        if t.value == _DOT:
            cur.take()
            return out
        # Be careful: inside attribute brackets `[...]` a `.` is theoretically
        # not a statement terminator. In practice Maude attribute lists never
        # contain `.`, so we don't track depth.
        out.append(cur.take_value())


def _skip_until_dot(cur: _Cursor) -> None:
    while True:
        t = cur.peek()
        if t is None:
            return
        if t.value == _DOT:
            cur.take()
            return
        cur.take()


# =========================================================================
# Subsort chain:  A B C  <  X  Y  Z
# =========================================================================

def _filter_sort_names(toks: List[str]) -> List[str]:
    out: List[str] = []
    for t in toks:
        if t and t not in (",",):
            out.append(t)
    return out


def _parse_subsort_chain(toks: List[str]) -> List[Tuple[str, str]]:
    """`A B  <  X Y  <  Z` -> children=[A,B], parents1=[X,Y], parents2=[Z]
    Produce the cross-product of consecutive groups: (a, p) for a in A's group,
    p in next group; AND (p, q) for p in X's group, q in Z's group, etc.
    For single chain `A < B C` (the F0-1 case) → [(A, B), (A, C)].
    """
    # Split toks on '<'
    groups: List[List[str]] = [[]]
    for t in toks:
        if t == "<":
            groups.append([])
        else:
            if t and t != ",":
                groups[-1].append(t)
    out: List[Tuple[str, str]] = []
    for i in range(len(groups) - 1):
        for child in groups[i]:
            for parent in groups[i + 1]:
                out.append((child, parent))
    return out


# =========================================================================
# Op declaration — `op NAME : Arity ... -> Coarity [attrs] .`
#                  `ops N1 N2 N3 : Arity ... -> Coarity [attrs] .`
# =========================================================================

def _parse_op_decl(cur: _Cursor, plural: bool) -> List[Op]:
    # Collect everything up to `.`
    toks = _take_until_dot(cur)
    # Find the first standalone `:` (it separates names from arity)
    # NB: mixfix op names like `to_:_` contain `:` inside them — but those are
    # single tokens (whitespace surrounds them), so a standalone `:` token is
    # unambiguous.
    try:
        colon_i = toks.index(":")
    except ValueError:
        return []
    names_part = toks[:colon_i]
    after = toks[colon_i + 1:]

    # Find `->`
    try:
        arrow_i = after.index("->")
    except ValueError:
        return []
    arity_part = after[:arrow_i]
    rest = after[arrow_i + 1:]

    # Coarity is the next single token (possibly with `{X}` attached).
    if not rest:
        return []
    coarity = rest[0]
    rest = rest[1:]

    # Optional attribute list `[ ... ]` — may span multiple tokens because
    # we tokenize on whitespace; need to glue from the token starting with `[`
    # until the token ending with `]`.
    attrs = _parse_attribute_block(rest)

    arity = _parse_sort_list(arity_part)
    op_names = _split_op_names(names_part, plural=plural)

    out: List[Op] = []
    for name in op_names:
        is_attr = name.endswith(":_")  # Hint only; semantics layer reclassifies.
        out.append(Op(name=name, arity=arity, coarity=coarity, attrs=attrs, is_attribute=is_attr))
    return out


def _parse_attribute_block(toks: List[str]) -> List[str]:
    """Find `[ ... ]` and split the inside into attribute words.
    Tokens may look like `[ctor` `comm` `assoc` `id:` `nil]` — we glue, strip
    the brackets, then split into words.
    """
    if not toks:
        return []
    # Locate first token starting with `[`
    start = None
    for i, t in enumerate(toks):
        if t.startswith("["):
            start = i
            break
    if start is None:
        return []
    end = None
    for j in range(start, len(toks)):
        if toks[j].endswith("]"):
            end = j
            break
    if end is None:
        return []
    inner_tokens = list(toks[start:end + 1])
    inner_tokens[0] = inner_tokens[0].lstrip("[")
    inner_tokens[-1] = inner_tokens[-1].rstrip("]")
    return [w for w in inner_tokens if w]


def _parse_sort_list(toks: List[str]) -> List[str]:
    out: List[str] = []
    for t in toks:
        if t and t != ",":
            out.append(t)
    return out


def _split_op_names(toks: List[str], plural: bool) -> List[str]:
    """Single op: one mixfix name (one token).
    `ops` plural: multiple tokens, each a name.
    """
    if not plural:
        # Some declarations use `op` with multiple names too in old codebase.
        # Be lenient: if multiple tokens and none looks like a sort/Maude
        # keyword separator, treat them all as op names.
        return [t for t in toks if t]
    return [t for t in toks if t]


# =========================================================================
# eq / rl helpers
# =========================================================================

def _split_on_eq(toks: List[str]) -> Tuple[List[str], List[str]]:
    try:
        i = toks.index("=")
    except ValueError:
        return toks, []
    return toks[:i], toks[i + 1:]


def _split_on_if(toks: List[str]) -> Tuple[List[str], List[str]]:
    # split on standalone `if`
    for i, t in enumerate(toks):
        if t == "if":
            return toks[:i], toks[i + 1:]
    return toks, []


def _split_on_arrow(toks: List[str]) -> Tuple[List[str], List[str]]:
    try:
        i = toks.index("=>")
    except ValueError:
        return toks, []
    return toks[:i], toks[i + 1:]


def _parse_rule_head_until_dot(cur: _Cursor) -> Tuple[str, List[str]]:
    """Parse `[name] : <body>` returning (name, body_toks_until_dot).

    Also handles unnamed rules `rl LHS => RHS .` (rare) by returning name=''.
    """
    toks = _take_until_dot(cur)
    name = ""
    body = toks
    if toks and toks[0].startswith("[") and "]" in "".join(toks[:5]):
        # Glue the bracketed name back together.
        # Find the token containing `]`.
        end_i = None
        for j, t in enumerate(toks):
            if t.endswith("]"):
                end_i = j
                break
        if end_i is not None:
            joined = " ".join(toks[: end_i + 1])
            # Strip leading [ and trailing ]
            inner = joined.strip()[1:-1].strip()
            name = inner
            after = toks[end_i + 1:]
            # Optional `:` before body
            if after and after[0] == ":":
                after = after[1:]
            body = after
    return name, body


# =========================================================================
# View
# =========================================================================

def _parse_view(cur: _Cursor) -> View:
    cur.expect("view")
    name = cur.take_value()
    cur.expect("from")
    from_mod = cur.take_value()
    cur.expect("to")
    to_mod = cur.take_value()
    cur.expect("is")
    sort_mapping: Dict[str, str] = {}
    while True:
        t = cur.peek()
        if t is None:
            break
        if t.value == "endv":
            cur.take()
            break
        if t.value == "sort":
            cur.take()
            src = cur.take_value()
            cur.expect("to")
            tgt = cur.take_value().rstrip(".")
            sort_mapping[src] = tgt
            # consume trailing `.`
            t2 = cur.peek()
            if t2 and t2.value == _DOT:
                cur.take()
        else:
            cur.take()
    return View(name=name, from_module=from_mod, to_module=to_mod, sort_mapping=sort_mapping)
