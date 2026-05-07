# -*- coding: utf-8 -*-
"""Stage 1.2 — `RFCGraphOrchestrator` walkthrough probe.

Goals:
  * Show the user the BFS trace on a real RFC (RFC1034) without touching the
    network.  Local RFC text cache exists at <project_root>/RFCs/.
  * Make placeholder fate visible: which targets of `cites_normative` ended
    up as fully-instantiated nodes (the BFS reached them) vs ghost
    placeholders (BFS could not fetch them, urlopen mocked-fail).
  * Show that recursion ONLY follows doc-level `cites_normative` edges
    (`RFC<digits>$`).  Precise edges (`RFCxxxx_SecY`) do NOT enqueue.
  * Show the side-effects: which RFC files would have been written to disk
    (we point save_dir at a copy so we don't pollute the real cache).

Run:
  cd src_v2 && ../venv/bin/python -m tests.walkthrough.stage_1_2_bfs_orchestrator

NO mocking of the parser — only the network.  enable_embeddings=False so we
do not load the 1.3 embedding model in this stage.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import urllib.error
import urllib.request
from collections import Counter, defaultdict


_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_HERE, "..", "..", ".."))
_LEGACY_SRC = os.path.join(_PROJECT_ROOT, "src")
_REAL_RFC_CACHE = os.path.join(_PROJECT_ROOT, "RFCs")

if _LEGACY_SRC not in sys.path:
    sys.path.insert(0, _LEGACY_SRC)

from rfc_processor.orchestrator import RFCGraphOrchestrator  # noqa: E402


# =============================================================================
# Network kill-switch.  We replace urlopen with a hard fail so the probe is
# fully reproducible: no network, no surprise downloads, no cache mutation.
# =============================================================================

_REMOTE_ATTEMPTS: list = []


def _no_network(url, *args, **kwargs):
    _REMOTE_ATTEMPTS.append(url if isinstance(url, str) else getattr(url, "full_url", str(url)))
    raise urllib.error.URLError("network disabled by walkthrough probe")


urllib.request.urlopen = _no_network  # type: ignore[assignment]


# =============================================================================
# Run
# =============================================================================

def main() -> None:
    # Use a temp working copy of the cache so we don't accidentally mutate
    # the project's real RFCs/ dir even if a write slipped past the kill-switch.
    work_cache = tempfile.mkdtemp(prefix="walkthrough_1_2_")
    for fname in os.listdir(_REAL_RFC_CACHE):
        src = os.path.join(_REAL_RFC_CACHE, fname)
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(work_cache, fname))

    print(f"work cache: {work_cache}")
    print(f"  files copied: {sorted(os.listdir(work_cache))}")

    orch = RFCGraphOrchestrator(
        max_depth=1,
        save_dir=work_cache,
        enable_embeddings=False,   # 1.3 will be its own probe
    )

    print("\n----- BFS trace -----")
    g = orch.fetch_and_build("RFC1034")

    # ----- Summary -----
    print("\n----- visited_rfcs -----")
    print(f"  count = {len(orch.visited_rfcs)}")
    print(f"  ids   = {sorted(orch.visited_rfcs)}")

    print("\n----- remote attempts (should all be failed) -----")
    print(f"  count = {len(_REMOTE_ATTEMPTS)}")
    for url in _REMOTE_ATTEMPTS:
        print(f"  - {url}")

    # ----- Global graph stats -----
    print("\n----- global graph stats -----")
    print(f"  |V| = {g.number_of_nodes()}")
    print(f"  |E| = {g.number_of_edges()}")

    by_type: Counter = Counter()
    placeholder_ids: list = []
    instantiated_doc_ids: list = []
    for n, d in g.nodes(data=True):
        t = d.get("node_type", "<MISSING>")
        by_type[t] += 1
        if t == "<MISSING>":
            placeholder_ids.append(n)
        elif t == "RFCDocument":
            instantiated_doc_ids.append(n)
    print(f"  nodes by type: {dict(by_type)}")
    print(f"  RFCDocument nodes (= BFS actually parsed): {sorted(instantiated_doc_ids)}")
    print(f"  placeholder count (no node_type, came from add_edge auto-create): {len(placeholder_ids)}")
    print(f"  first 8 placeholders: {sorted(placeholder_ids)[:8]}")

    # Edges grouped by edge_type
    edges_by_type: Counter = Counter()
    for _, _, d in g.edges(data=True):
        edges_by_type[d.get("edge_type", "<MISSING>")] += 1
    print(f"  edges by type: {dict(edges_by_type)}")

    # ----- BFS recursion semantics: cites_normative coarse vs precise -----
    print("\n----- cites_normative target shapes -----")
    coarse = []      # target matches RFC<digits>$
    precise = []     # target like RFCxxxx_SecY
    other = []
    import re
    for u, v, d in g.edges(data=True):
        if d.get("edge_type") != "cites_normative":
            continue
        if re.fullmatch(r"RFC\d+", v):
            coarse.append((u, v))
        elif "_Sec" in v:
            precise.append((u, v))
        else:
            other.append((u, v))
    print(f"  coarse (would enqueue): {len(coarse)}")
    print(f"  precise (would NOT enqueue, sec-level): {len(precise)}")
    print(f"  other (unexpected shape): {len(other)}")
    if other:
        for u, v in other[:5]:
            print(f"    e.g.  {u}  ->  {v}")

    # Of the coarse targets, how many actually got instantiated by BFS?
    coarse_targets = {v for _, v in coarse}
    reached = sorted(coarse_targets & set(instantiated_doc_ids))
    missed = sorted(coarse_targets - set(instantiated_doc_ids))
    print(f"\n----- coarse target reachability -----")
    print(f"  coarse targets total : {len(coarse_targets)}")
    print(f"  reached (instantiated): {len(reached)}  -> {reached}")
    print(f"  missed (still ghost) : {len(missed)}")
    print(f"    e.g.  {missed[:8]}")

    # ----- Side effect: did the cache dir change? -----
    after = set(os.listdir(work_cache))
    before = {fname for fname in os.listdir(_REAL_RFC_CACHE) if os.path.isfile(os.path.join(_REAL_RFC_CACHE, fname))}
    new_files = sorted(after - before)
    print(f"\n----- cache mutations -----")
    print(f"  new files in work_cache (should be empty since network is mocked): {new_files}")

    print(f"\n(probe done; work cache left at {work_cache} for you to inspect)")


if __name__ == "__main__":
    main()
