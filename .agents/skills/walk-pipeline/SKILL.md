---
name: walk-pipeline
description: Walk the user through a multi-stage codebase (especially pipelines) one stage at a time, explaining the design and implementation of each stage and producing a minimal runnable testcase whose output the user can inspect. Builds toward an end-to-end understanding so the user can then critique and optimize the design. Use when the user says things like "帮我理解整个项目", "走查代码", "全流程调试", "stage-by-stage walkthrough", "explain the pipeline and show me what each step does", or otherwise asks for a guided tour of an unfamiliar / AI-written codebase before refactoring.
---

# Walk the Pipeline

The user has an existing codebase (often partly AI-generated) and does not yet have a confident mental model of how it actually behaves. The goal of this skill is to **rebuild that mental model stage-by-stage**, grounding every claim about the code in **a small testcase the user can actually run and inspect**, so that by the end they can make informed design decisions.

This skill is **not** a code review and **not** an architecture proposal. Those come *after*. While running this skill, resist the urge to suggest refactors mid-walkthrough — capture friction silently and surface it only at the end.

**The user is likely to redesign and modify code after this walkthrough.** Therefore every explanation must be **anchored to specific code locations** (absolute file path + line range, function/class name) so that when they decide to change something, they can jump straight to it. Vague summaries ("the parser cleans up the text") are forbidden — always: *"`clean_section()` at `@<abs>/rfc_processor/parser.py:142-178` strips trailing whitespace and merges continuation lines"*.

## Glossary

- **Stage** — one logically coherent step in the pipeline (e.g. "parse RFC text", "build embedding index", "extract IR", "generate Maude module"). One stage may span multiple files.
- **Stage contract** — the inputs, outputs, side effects, and invariants the stage promises. The thing the user must understand to reason about that stage in isolation.
- **Code map** — for each stage, the concrete list of *symbols that matter* (functions, classes, dataclasses, key globals) with their absolute file path and line ranges. The thing the user opens when they decide to modify the stage.
- **Probe** — a minimal, runnable testcase whose purpose is to **let the user see the stage's actual behavior**, not to assert correctness. It must produce concrete output (printed values, written files, diffs) the user can read.
- **Friction note** — something that smelled wrong during the walkthrough (shallow module, hidden coupling, surprising output, dead branch). Recorded but not acted on until Step 5. Each note carries the same file:line anchors so it can be turned into an edit later.

## Process

### 1. Map the stages

Before reading any single stage in depth, get the shape of the whole pipeline. Read entry points (`main.py`, top-level `README.md`, any `pipeline_*` orchestration file, top-level docs), then propose a numbered list of stages to the user in this format:

```
1. <Stage name> — <one-line purpose> — <key files>
2. ...
```

Confirm with the user:
- Is this the right decomposition? Merge / split / reorder if they push back.
- Where do they want to start? (Default: stage 1. Sometimes the user already understands the early stages and wants to start mid-pipeline.)

Do **not** start explaining stages until the map is agreed.

### 2. For each stage, in order

Work one stage at a time. Do not batch. The unit of progress is "user says they understand stage N" — not "I finished writing about stage N."

For the current stage:

**a. Read.** Open the stage's files. Trace the actual call graph from the stage's entry point to its exit. Note what state it reads, what it writes, and what it returns.

**b. Explain the contract first, implementation second, with a code map alongside.** Tell the user:
   - **Inputs** — types, where they come from, any preconditions. Cite the parameter / dataclass definition by absolute path + line range.
   - **Outputs** — types, where they go, any postconditions. Same citation discipline.
   - **Side effects** — files written, caches populated, network calls, model calls. Cite the exact line that performs each side effect.
   - **Then** the implementation: the key functions, the non-obvious logic, the data shapes that flow through. Quote short snippets (≤ ~10 lines) using the `@<abs_path>:<start>-<end>` citation format whenever the logic is subtle.
   - **Code map** — close the section with a compact table the user can use as a jump-list when editing:

     ```
     | Symbol | Location | Role in this stage |
     |---|---|---|
     | `ChunkIndex` (class) | @<abs>/rfc_processor/embedding_store.py:34-89 | in-memory store of (chunk_id, embedding) |
     | `ChunkIndex.add()` | @<abs>/rfc_processor/embedding_store.py:51-66 | inserts and re-normalises |
     ...
     ```

   Citations must be absolute paths and current line numbers — re-read the file if you are not sure the lines still match. A stale citation is worse than no citation, because the user *will* navigate to it.

   Do not paraphrase code that's already clear — point to it.

**c. Build a probe.** Write the smallest possible script that exercises **only this stage** end-to-end with realistic-but-tiny input. Requirements:

   - **Tiny input.** A few lines of RFC text, one section, one mock object — never the full corpus. The user must be able to read the input in full.
   - **Visible output.** Print intermediate values, dump structures with `pprint` / `json.dumps(indent=2)`, write small artifacts to a scratch dir. The user should *see* what the stage produced, not just that it didn't crash.
   - **No mocks unless forced.** If the stage hits an LLM or external service, prefer recording one real call and replaying it, or use a tiny real call with a cheap model. Mocks hide the thing the user is trying to understand.
   - **Self-contained.** Runnable with one command. Include the command in your message.
   - **Living location.** Put probes under a stable directory (default: `src/tests/walkthrough/stage_<N>_<slug>.py`) so the user can re-run them later. Reuse / update an existing probe rather than creating a parallel one.

**d. Run it (or have the user run it).** If you can run it safely, do. Capture the actual output. If you cannot, give the user the exact command and wait for them to paste output back.

**e. Walk the output with them.** Point at the parts of the output that confirm (or contradict) what you said in step (b). This is where misunderstandings — yours or the user's — surface. Update the explanation if the probe reveals you were wrong about the code. **Trust the probe over your reading.**

**f. Capture friction silently.** If something smelled off (a shallow wrapper, an unused branch, a surprising data shape, a hidden global), append a one-line **Friction note** to a running list. Do not pitch fixes yet.

**g. Checkpoint.** Ask the user: *"Anything unclear about this stage before we move on?"* Only advance when they say yes.

### 3. Maintain the running map

After each stage, update a short progress artifact at `src/tests/walkthrough/PROGRESS.md` (create lazily) with:

- Stages completed, with a one-sentence "what it actually does" per stage (post-probe, possibly different from the docstring).
- The **code map** for each stage (the same table from step 2b) — this is what the user opens when they sit down to redesign.
- The probe command for each stage.
- The friction notes accumulated so far, each carrying its file:line anchor.

This is the document the user keeps. Keep it terse — it is a map, not a report. When the user later starts editing, `PROGRESS.md` should be sufficient by itself to locate every relevant symbol without re-reading the source.

### 4. End-to-end probe

Once every stage has been walked individually, build one more probe that runs **the whole pipeline** on the same tiny input used in the per-stage probes (or a slightly larger one). The point is to let the user see how the stages actually compose — including any glue, ordering, or shared state that didn't belong to any single stage.

Place it at `src/tests/walkthrough/end_to_end.py`. Walk its output with the user the same way.

### 5. Surface the friction

Now — and only now — present the accumulated **Friction notes** as a numbered list. For each:

- **Where** — stage + concrete `@<abs_path>:<start>-<end>` citation(s). Multiple anchors if the friction spans files.
- **What you saw** — the concrete observation from the walkthrough or probe output. Not an opinion.
- **Why it might matter** — testability, locality, surprise, dead code, leak across stages.
- **Edit surface** — which symbols (by name + line) would have to change if the user decided to fix it. This is *not* a proposed fix; it's the smallest set of files they would have to open to even start. Lets the user gauge cost before opening the next skill.

Do **not** propose redesigns here. Hand off to the user with:

> *"Want to take any of these into `improve-codebase-architecture` for a deepening pass, or into `diagnose` if it looks like a real bug? If you already know what you want to change, we can also drop straight into edits — the code map in `PROGRESS.md` has every line anchor you'll need."*

That hand-off is the natural exit of this skill.

## Anti-patterns

- **Explaining all stages before running any probe.** The probe is what grounds the explanation; running it last defeats the skill.
- **Probes that only assert "no exception."** A green check teaches the user nothing. Output must be *legible*.
- **Mocking the interesting part.** If the stage is "call the LLM and parse its reply," do not mock the LLM — you'll mock away the thing the user came here to understand.
- **Mid-walkthrough refactor pitches.** Capture as friction; resist until step 5.
- **Skipping the checkpoint.** Advancing before the user confirms understanding makes the rest of the walkthrough useless — every later stage builds on the mental model of the earlier ones.
- **Probes that need the full corpus / full model run / 10-minute warmup.** If it's slow, the user won't re-run it, and the probe stops being a living artifact.
- **Vague citations.** "Somewhere in the parser" or `parser.py` (no line numbers) is useless once the user starts editing. Always absolute path + current line range. If you guess and the lines are wrong, you've taught the user to distrust the whole map.
- **Letting `PROGRESS.md` go stale.** If the user edits code mid-walkthrough (or you do), update line ranges in the affected code maps in the same turn. A stale map is worse than no map.
