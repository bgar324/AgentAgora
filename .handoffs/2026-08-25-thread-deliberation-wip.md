# Thread-centered deliberation — continuation record

- **Date:** 2026-08-25 (original handoff superseded the same day)
- **Branch:** `feat/thread-centered-deliberation` (PR #18)
- **Status:** The handoff's §8 acceptance criteria are implemented and verified. The
  branch is no longer known-red. This file replaces the original WIP handoff; the
  original is recoverable from git history (`5859faa`).

## What the original handoff required → what landed

### 1. The four unit failures (§6) — fixed, root-caused
- §6.1/§6.2/§6.3 were mechanical (assertion text, `DeliberationPoint.facets`,
  `assent_to_shared_ground` Thread argument).
- §6.4 root cause: the demo reflection fallback stamped the *joined* multi-facet
  consensus text onto **each** active facet of the lead, corrupting the Perspective
  and breaking the next round's facet-equality judgment. Pinned product behavior:
  - `reflect_on_round` demo fallback aligns `"; "`-joined ground segments to
    `point.facets` one-to-one and skips no-op revisions.
  - `_fallback_consensus_hypothesis` is segment-aware: only novel segments append;
    fully-incorporated ground returns the current hypothesis unchanged (and it stays
    confirmed). Overlapping-facet ground **does** count as already incorporated.
  - Tests: `test_consensus_threads_propose_and_evolve_the_working_hypothesis`
    (searched-demo, DEMO_SHARED_GROUND; asserts no duplicate re-append) and
    `test_already_incorporated_shared_ground_keeps_hypothesis_confirmed`.

### 2. v5→v6 round migration (§5.1) — complete
`migrate_v5_payloads` now rewrites round payloads in investigations, chat, and
completion history: turn vocabulary (`response→reply`, `position→answer`,
`qualify→reply` for both kind and relation), per-facet `verdicts` → one merged
Thread `verdict` (first verdict's finding wins; facets/supporting/positions/
evidence merge; archive keeps originals), `moderator_checks[].verdict.facet` →
`facets`, and resolution point `facet` → `facets`. Note: origin/main's real v5
shapes have no `relation`, no `moderator_checks`, and no `response` kind — those
mappings defend intermediate dev snapshots; the true production hazards were
`verdicts` (silent drop) and point `facet` (quarantine). Fixture: shared
`tests/conftest.py::legacy_v5_deliberation` exercised by the SQLite lineage test
and the Supabase twin.

### 3. Kat's reframe — fragments are representation/traceability only
- `open_statement`/`answer_statement` are driven by the Thread **question**;
  evidence selection uses `_thread_evidence` (own related fragments → thread
  facets → scope) as supporting context only.
- `DeliberationThread.facets`, `ThreadVerdict.facets`, `DeliberationPoint.facets`,
  `DeliberationRound.facets` are optional traceability metadata (no min-length).
- Per-Perspective RELATED FRAGMENTS: `ThreadPerspectiveLink` on
  `DeliberationThread.related` (and the LLM draft); thread suggestion prompts ask
  for per-Perspective links; the picker renders them.
- `recommend_questions` fallback templates are source-kind-keyed, not facet-keyed.
- `judge_thread`'s fallback equality guards `facets or FACETS`; the demo
  shared-ground join guards empty facet lists.
- Drawer copy states facets "surface where Perspectives differ and record what
  changed … without setting the agenda."

### 4. Protocol decisions 1, 2, 4 — implemented
- **1 (researcher closes Threads):** `decide_thread_resolution(session, delib,
  round_n, decision=accept|edit|keep_open, summary?, note?)` +
  `PUT …/rounds/{n}/resolution`. Accept/edit close the resolution (edit replaces
  `resolution.summary`); keep-open leaves the Thread re-runnable. `run_round` and
  `complete_deliberation` refuse while the last completed round is undecided.
  UI: per-round review card (`thread-<n>-resolution-review` /
  `…-resolution-decision` testids); Start Thread disabled with a hint while a
  review is pending. Re-running an accepted Thread is intentionally allowed
  (effectively a reopen); the archive keeps every round.
- **2 (open-question loop F→J→D):** each round's new recommended questions also
  append as suggested `DeliberationThread`s (`source_round` provenance, "From
  Thread N" badge), deduped against existing thread questions, ≤2/round, ≤10 total.
- **4 (affected-Perspective reflection):** every participant reflects each round
  (lead first, concurrent TaskGroup); each agent's facets/version update;
  `round.reflections` records all. `revised_perspective` remains the lead delta.

### 5. Kat's Document (output-idea.md) — implemented
`DeliberationDocument{title, sections[], open_questions[]}` with
`DocumentSection{thread_id, title, hypothesis, explanation}`.
`agents.synthesize_document` (task `synthesize_document`, evaluation role) with a
deterministic fallback: accepted/edited rounds become sections (a re-discussed
Thread supersedes its earlier section); open questions = open recommended
questions + never-closed Thread questions. Generated at `complete_deliberation`
(which now also requires the final round's review), archived on completions,
rendered in the drawer (`deliberation-document` testid).

### 6. Demo behavioral parity — closed at the agent-function boundary
Every deliberation-path agent now has a complete deterministic demo/fallback
implementation producing live-shaped outcomes: thread suggestion, question-driven
statements, scripted two-exchange assent, shared-ground judgment, segment-aligned
reflection for all participants, segment-aware hypothesis incorporation,
source-kind question templates, and the fallback Document. The §8.8 idea of a
`DemoProvider` behind `_structured` is unsound as specified: that boundary
receives prompt *strings*, so a deterministic provider would have to parse
prompts. If a provider-shaped demo is still wanted, `_structured` must first be
redesigned to pass typed task inputs — a separate effort.

## Verification (all green)
```bash
uv run --no-sync pytest tests/test_focused.py tests/test_focused_lineage.py \
  tests/test_focused_hermetic.py tests/test_focused_model_routing.py \
  tests/test_focused_clustering.py tests/test_supabase_persistence.py \
  tests/test_openrouter_schema.py -q        # 97 passed
pnpm --dir web-ui exec tsc --noEmit         # clean
git diff --name-only origin/main | grep '\.py$' | xargs ruff check   # clean
pnpm --dir web-ui test:e2e                  # executed; see PR checks
```

## Environment note
The repo `.venv` had been a symlink into `/tmp/agent-agora-github-review/.venv`,
whose pure-Python packages were stripped by macOS tmp cleanup. It is now a real
in-repo venv built with `uv sync --dev`. `uv.lock` was regenerated (§8.7 decided:
regenerate) — it now resolves `supabase`, so `--no-sync` is a convenience, not a
requirement.

## Still open (intentionally)
- **Naming sweep (§8.6):** `run_round`→`run_thread`, `DeliberationRound`→Thread
  record, progress-kind strings, `RoundResolution` — one sweep WITH a schema
  migration once behavior settles.
- **Protocol decisions 3, 5, 6:** every-Perspective proposals, user-as-discussant
  inside the Thread transcript, Observation-level evidence.
- **Supabase DDL:** apply
  `supabase/migrations/20260825220000_focused_workspace_archives.sql` to the
  project before deploying the persistence changes.
- **DO NOT MERGE** until the user approves PR #18.
