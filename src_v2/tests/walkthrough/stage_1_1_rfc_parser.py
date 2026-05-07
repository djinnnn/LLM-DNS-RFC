# -*- coding: utf-8 -*-
"""Stage 1.1 — `RFCGraphBuilder` walkthrough probe.

What this probe is FOR:
- Show the user, on a tiny hand-crafted RFC, exactly what nodes and edges
  `parse_xml_string` and `parse_text_string` produce.
- Exercise the few non-trivial branches: <references> handling,
  cross-reference precise vs coarse merging, internal references,
  is_reference_section short-circuit.

NOT for:
- correctness assertions. Output is meant to be *read*, not asserted.
- network. Inputs are inline strings. No `RFCs/` cache touched.

Run:
  cd src_v2 && ../venv/bin/python -m tests.walkthrough.stage_1_1_rfc_parser
"""
from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from pprint import pformat


# Hook the legacy `src/` package onto sys.path. The walkthrough probe lives
# in src_v2 but exercises the unmodified Stage 1 code in src/.
_HERE = os.path.dirname(os.path.abspath(__file__))
_LEGACY_SRC = os.path.abspath(os.path.join(_HERE, "..", "..", "..", "src"))
if _LEGACY_SRC not in sys.path:
    sys.path.insert(0, _LEGACY_SRC)

from rfc_processor.rfc_parser import RFCGraphBuilder  # noqa: E402


# =============================================================================
# Tiny inputs — both formats encode roughly the same RFC.
# Designed to hit:
#   * Section + Subsection (so has_section / has_subsection both fire)
#   * Appendix (uppercase normalization)
#   * Internal forward reference (Section X)
#   * Precise external reference (Section X of RFCY)
#   * Coarse external reference ([RFCY] standalone)
#   * Reference section that should NOT contribute as a citation source
# =============================================================================

MINI_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<rfc xmlns:xi="http://www.w3.org/2001/XInclude" docName="draft-mini">
  <front>
    <title>Mini Example RFC</title>
  </front>
  <middle>
    <section pn="section-1">
      <name>Introduction</name>
      <t>This document defines a tiny example. See <xref target="RFC1035"/> for
      DNS basics. Refer to Section 2 for the meat.</t>
    </section>
    <section pn="section-2">
      <name>Protocol</name>
      <t>The protocol uses Section 4.1 of RFC1035 for encoding and also
      borrows ideas from [RFC2181].</t>
      <section pn="section-2.1">
        <name>Encoding</name>
        <t>Encoding details. Cf. (Section 3.1).</t>
      </section>
    </section>
  </middle>
  <back>
    <references pn="section-3">
      <name>Normative References</name>
      <reference anchor="RFC1035"><front><title>DNS Imp</title></front></reference>
      <reference anchor="RFC2181"><front><title>Clarif</title></front></reference>
    </references>
    <section pn="section-a">
      <name>Worked Example</name>
      <t>Appendix body referencing [RFC9999] which we never declare.</t>
    </section>
  </back>
</rfc>
"""

MINI_TXT = """\
Mini Example RFC

Table of Contents

   1.  Introduction ............................. 1
   2.  Protocol ................................. 1
   2.1.  Encoding ............................... 2
   3.  Normative References ..................... 2
   Appendix A.  Worked Example .................. 2

1.  Introduction

   This document defines a tiny example.  See [RFC1035] for DNS basics.
   Refer to Section 2 for the meat.

2.  Protocol

   The protocol uses Section 4.1 of RFC1035 for encoding and also
   borrows ideas from [RFC2181].

2.1.  Encoding

   Encoding details.  Cf. (Section 3.1).

3.  Normative References

   [RFC1035]
   [RFC2181]

Appendix A.  Worked Example

   Appendix body referencing [RFC9999] which we never declare.
"""


# =============================================================================
# Pretty-printer: dumps a graph in a way the user can scan.
# =============================================================================

def dump_graph(label: str, builder: RFCGraphBuilder) -> None:
    g = builder.get_graph()
    print(f"\n{'=' * 72}\n  {label}\n{'=' * 72}")
    print(f"|V|={g.number_of_nodes()}  |E|={g.number_of_edges()}")

    # Nodes — group by node_type for readability.
    by_type: dict = defaultdict(list)
    for n, d in g.nodes(data=True):
        by_type[d.get("node_type", "?")].append((n, d))

    for ntype in ("RFCDocument", "Section", "?"):
        nodes = by_type.get(ntype, [])
        if not nodes:
            continue
        print(f"\n--- nodes [{ntype}] ({len(nodes)}) ---")
        for nid, data in sorted(nodes, key=lambda kv: kv[0]):
            # Truncate long text fields so the dump stays readable.
            shown = {k: _shorten(v) for k, v in data.items()}
            print(f"  {nid}")
            for k in sorted(shown):
                print(f"      {k}: {shown[k]}")

    # Edges — group by edge_type, sort within group.
    edges_by_type: dict = defaultdict(list)
    for u, v, d in g.edges(data=True):
        edges_by_type[d.get("edge_type", "?")].append((u, v))

    print(f"\n--- edges by edge_type ---")
    for etype in sorted(edges_by_type):
        triples = sorted(edges_by_type[etype])
        print(f"  [{etype}] ({len(triples)})")
        for u, v in triples:
            target_exists = g.has_node(v)
            mark = "" if target_exists else "  (DANGLING — target node not in graph)"
            print(f"      {u}  ->  {v}{mark}")


def _shorten(v):
    if isinstance(v, str) and len(v) > 80:
        return repr(v[:77] + "...")
    return repr(v)


# =============================================================================
# Sanity probes the user can directly verify against the input.
# =============================================================================

def sanity_summary(label: str, builder: RFCGraphBuilder) -> None:
    g = builder.get_graph()
    print(f"\n--- sanity ({label}) ---")
    sec_nodes = [(n, d) for n, d in g.nodes(data=True) if d.get("node_type") == "Section"]
    print(f"  section count: {len(sec_nodes)}")
    appendix = [n for n, d in sec_nodes if d.get("is_appendix")]
    print(f"  appendix sections: {appendix}")
    refsecs = [n for n, d in sec_nodes if d.get("is_reference_section")]
    print(f"  reference sections (skipped by xref edge builder): {refsecs}")

    # Citation breakdown (was each xref pair classified as expected?)
    cite_edges = [
        (u, v, d.get("edge_type"))
        for u, v, d in g.edges(data=True)
        if str(d.get("edge_type", "")).startswith("cites_")
    ]
    by_type: dict = defaultdict(list)
    for u, v, t in cite_edges:
        by_type[t].append((u, v))
    print(f"  citation edges:")
    for t in sorted(by_type):
        print(f"    {t} ({len(by_type[t])})")
        for u, v in sorted(by_type[t]):
            print(f"      {u}  ->  {v}")


# =============================================================================
# Main
# =============================================================================

def main() -> None:
    # XML path
    xml_builder = RFCGraphBuilder("RFC9001")  # arbitrary doc id
    xml_builder.parse_xml_string(MINI_XML)
    dump_graph("XML PATH — parse_xml_string", xml_builder)
    sanity_summary("xml", xml_builder)

    # TXT path
    txt_builder = RFCGraphBuilder("RFC9001")
    txt_builder.parse_text_string(MINI_TXT, title="Mini Example RFC")
    dump_graph("TXT PATH — parse_text_string", txt_builder)
    sanity_summary("txt", txt_builder)


if __name__ == "__main__":
    main()
