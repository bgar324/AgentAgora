# Handoff: Thread-centered deliberation (WIP branch, intentionally dirty)

- **Date:** 2026-08-25
- **Branch:** `feat/thread-centered-deliberation` (all work is uncommitted-until-now WIP on top of `main@ffab0d3`, PR #17 merge)
- **PR intent:** DO NOT MERGE. This PR exists to transfer context and code. It is known-red (4 unit failures, unexecuted e2e, missing data migration). The next agent continues from this branch.
- **Verification at handoff:** `uv run --no-sync pytest tests/test_focused.py tests/test_focused_lineage.py tests/test_focused_hermetic.py tests/test_focused_model_routing.py tests/test_focused_clustering.py tests/test_supabase_persistence.py tests/test_openrouter_schema.py -q` → **88 passed, 4 failed** (§6). `pnpm --dir web-ui exec tsc --noEmit` → clean. `ruff format`/`ruff check` clean on every file this branch touches (repo has pre-existing lint debt elsewhere; leave it). Playwright e2e **updated but never executed** (§7). No live-provider run.

---

## 1. North star (front-to-back goals of this session)

This session moved the focused-panel product through three stacked goals. All three are on this one branch.

### Goal A — Scalar Working Hypothesis (done, superseded parts of the old 4-part model)
`HypothesisDev` collapsed from four parts (`problem`, `previous_work`, `reasoning`, `hypothesis`) to **one scalar `hypothesis`** ("possible solution"). Consequences implemented:
- `WorkspaceState.schema_version: Literal[6]` introduced (main had **no** schema_version field; all previously persisted data is implicitly **v5**).
- `src/agora/focused/migrations.py` (new): `migrate_v5_payloads` collapses persisted 4-part hypothesis dicts (`applied_hypothesis`, `baseline_hypothesis`, `hypothesis`, `hypothesis_before`, `hypothesis_proposal`, `steps`, and `step_sources`) to the scalar shape.
- SQLite (`persistence.py`) and Supabase (`supabase_persistence.py`) both archive the pre-migration payload into `focused_workspace_archives` (SQLite table created inline; Supabase table via `supabase/migrations/20260825220000_focused_workspace_archives.sql`, **not yet applied to any Supabase project**) and migrate rows once, revision-checked.
- `HypothesisVersion.step_sources` now only meaningfully tracks `{"hypothesis": <version-id>}`; `merge_hypotheses` takes a single combined `hypothesis` (UI: one "Combined hypothesis" textarea in `MergeModal`), `selected_parts` is gone from the API.
- UI: `HYPOTHESIS_PARTS` reduced to the single "Possible solution" part; apply-confirmation modal shows before/after prose instead of per-part checkboxes.

### Goal B — Deliberation recentred on Threads (Youngseung's directive; mostly done)
Youngseung: the interaction logic already exists in `src/agora/deliberation` (`thread.py`, `resolution.py`, `revision.py`, `document.py`, canonical schemas in `src/agora/schemas/deliberation.py`). Interface mapping he specified:
1. fragments/facets = current state of a Perspective (Perspective panel)
2. **Threads** = the scientific issues / disagreements / open questions being deliberated
3. conversation within a Thread = argumentation via challenges, replies, evidence, refinement
4. resolutions/revisions = the outcome: what changed in the Perspective and the Working Hypothesis

Implemented in the focused module:
- `DeliberationThread` model (`id`, `title`, `question`, `context`, `facets[1..4]`, `perspective_names`, `hypothesis_fragments`) on `DeliberationState.threads` and archived on `DeliberationCompletion.threads`.
- `agents.suggest_deliberation_threads(perspectives, hypothesis, provider, demo)` proposes 2–5 Threads (LLM task `suggest_deliberation_threads`, reasoning role); deterministic fallbacks: an antibiotic-specific trio when `demo=True`, a generic trio otherwise. Generated during `initialize_deliberation` (which now also preserves an existing baseline instead of regenerating it, and can backfill Threads for panels that predate them — see the "Identify Threads" empty-state card in the drawer).
- `run_round(session_id, deliberation_id, *, lead_iid, thread_id, progress_generation)` — the API (`RoundRequest.thread_id`), hook (`runRound(deliberationId, leadIid, threadId)`), and UI all select a **Thread**, not facets. `DeliberationRound.thread_id` records it; `DeliberationRound.facets` is now derived metadata (`thread.facets`).
- Turn vocabulary aligned with the canonical `Contribution.kind`: `Turn.relation ∈ {answer, reply, support, challenge}`, `TurnKind.reply` replaces `response`; `position→answer`, `qualify/response→reply` in the agent fallbacks.
- **Thread-level judgment**: `ThreadVerdict` (one verdict per round with `facets: list`, replacing per-facet `FacetVerdict` + `DeliberationRound.verdicts` list → `DeliberationRound.verdict: ThreadVerdict | None`). `agents.judge_thread` (task `judge_thread`), `agents.assent_to_shared_ground` now takes the Thread object, `agents.summarize_thread` (task `summarize_thread`) replaces `summarize_round`. `DeliberationPoint.facet` → `facets: list`.
- Demo produces a real two-exchange arc: scripted assent qualifies in exchange 1 (with a challenge + `challenge_turn_id`), accepts in exchange 2; lead replies target the challenger's turn (`reply_to_turn_id`); `MIN_DELIBERATION_EXCHANGES` guards single-exchange stops.
- UI (`stage-deliberation.tsx`): Thread picker cards (title, question, context, facet chips, hypothesis-fragment quotes, per-Thread discussed-round history, `data-testid="thread-card-<id>"`), "Start Thread" CTA, `RoundRecord` renders Thread title, exchanges with moderator checks, **Thread finding** (verdict card), **Thread resolution** (moderator synthesis), **Perspective delta** (every reflection, revised or unchanged), and **Working hypothesis delta** (before/proposed, `data-testid="thread-<n>-hypothesis-delta"`). Copy sweep round→Thread across drawer, canvas panel statuses, chat queueing.

### Goal C — Kat's conceptualization (assessment done; protocol decisions OPEN)
Kat circulated `~/Downloads/deliberation.md` ("DELIBERATION MODEL / LOOP / CANVAS / OUTPUT") and asked, before committing: does the interaction protocol/representation make sense? My assessment (delivered in-session): **the model is coherent and nearly isomorphic to `src/agora/deliberation`** (`Thread`, `Contribution.kind answer/reply/support/challenge`, tri-part `Resolution` consensus/disagreement/open_question, `FacetRevision`, `decide_resolution` close/edit-close/keep-open/reopen = the USER REVIEW block). Six genuine divergences from the current focused implementation, each a protocol decision:
1. **Who closes a Thread** — doc: researcher reviews the Resolution (Accept/Edit/Reject/Keep Open); current: moderator loop auto-closes on unanimity/exchange-limit and the researcher only reviews the hypothesis delta.
2. **Open-question loop (F→J→D)** — doc: Resolution open questions re-enter as new suggested Threads; current: they become Research Problems / child Investigations only, Threads are generated once at initialize.
3. **Proposals** — doc: every Perspective proposes; hypothesis synthesizes. Current: lead alone drafts the baseline.
4. **Revision scope** — doc + canonical `reflect_perspectives`: every *affected* Perspective revises; current: lead only (`reflect_on_round`).
5. **User as discussant** — doc shows `CHALLENGE · You` inside the Thread transcript; current: researcher chat is a separate panel conversation.
6. **Evidence layer** — doc cites Observation-level propositions (O#/S# with provenance, canonical `agora.research.evidence`); focused cites paper IDs.

Recommended sequencing if confirmed: 1, 2, 4 are the committing changes; 3, 5, 6 separable follow-ons. Also: doc's RELATED FRAGMENTS are *per-Perspective*; `DeliberationThread` currently holds a flat facet list + names — the per-Perspective form is more faithful and cheap.

### Kat's latest guidance (verbatim, arrived at handoff time — this REFRAMES Goal B)
> "i'd say fragments are the representation and traceability layer of deliberation. they help surface where Perspectives differ, give context during a Thread, and show what changed afterward.
>
> so they remain important, but they shouldn't determine the discussion itself. because of that, i don't think fragment-based deliberation should be the main contribution, and we may need to reframe that part."

**Directive for the next agent:** treat fragments strictly as (a) difference-surfacing when Threads are suggested, (b) context during a Thread, (c) the delta record afterward. They must NOT steer the conversation. Remaining fragment-coupling to unwind:
- `agents.open_statement` / `answer_statement` still anchor prompts and fallbacks on `thread.facets[0]` ("ACTIVE FACET" framing is gone but `facet = thread.facets[0]` still selects the evidence and stamps `Turn.facet`). The Thread `question` should drive the opening; facets only as supplied context.
- `ThreadVerdict.facets` is required (1–4) and `DeliberationThread.facets` is required — consider making facet linkage optional metadata (per-Perspective RELATED FRAGMENTS) rather than a structural constraint.
- `DEMO_SHARED_GROUND` is facet-keyed; the demo `shared_ground` join in `run_round` keys off Thread facets.
- `recommend_questions` fallback templates are facet-keyed.
- `reflect_on_round` still revises only "active facets" of the lead.
- UI: facet chips on Thread cards and Thread finding are fine as traceability, but the "X lenses" copy in "How this panel works" should be checked against the reframe.

---

## 2. What is on this branch (by area)

Backend (`src/agora/focused/` + `src/agora/api/focused.py`):
- `models.py`: scalar `HypothesisDev`; `WorkspaceState.schema_version=6`; `DeliberationThread`, `DeliberationThreadDraft`, `DeliberationThreads` (LLM output: `threads` field); `ThreadVerdict`, `ThreadVerdictDraft`, `ThreadVerdictOutput`; `DeliberationRound.{thread_id, verdict}` (list `verdicts` removed); `DeliberationPoint.facets`; `Turn.relation` answer/reply/support/challenge; `TurnKind.reply`; `DeliberationState.threads`; `DeliberationCompletion.threads`.
- `agents.py`: `suggest_deliberation_threads`, Thread-scoped `open_statement`/`answer_statement`/`assent_to_shared_ground`, `judge_thread`, `summarize_thread` (+ `_normalize_thread_summary`, `_point_from_verdict` on `ThreadVerdict`), reflection/consensus/recommendation paths on `point.facets`.
- `routing.py`: tasks `suggest_deliberation_threads`, `judge_thread`, `summarize_thread` (old `identify_deliberation_issues`/`judge_facet`/`summarize_round` removed; `TASK_ROLES` consistency check passes).
- `service.py`: baseline-preserving `initialize_deliberation` + Thread generation/backfill; `_restart_deliberation` clears `threads`; `run_round` is Thread-driven end-to-end (whole-Thread transcript to judge/assent, challenge-targeted `reply_to_turn_id`, Thread context as first-exchange moderator feedback, `round_state.verdict`, `summarize_thread`); archive copies `threads`.
- `persistence.py` / `supabase_persistence.py` / `migrations.py` / `importer.py`: v5→v6 migrate-on-load with archive tables (see §5 blocker for what the migration does NOT yet cover).
- `api/focused.py`: `RoundRequest{lead_iid, thread_id, progress_generation}`.

Frontend (`web-ui/`):
- `types/focused.ts`: mirrors all model changes (`schema_version: 6`, `DeliberationThread`, `ThreadVerdict`, `verdict`, `threads`, scalar-only hypothesis usage, relation/kind unions).
- `hooks/use-focused.ts`: `runRound(..., threadId)` posts `thread_id`.
- `features/focused/stage-deliberation.tsx`: Thread picker, Thread-centred `RoundRecord` (finding/resolution/Perspective delta/hypothesis delta), single-part hypothesis editor, scalar apply modal, backfill card, copy sweep.
- `features/focused/workspace-map.tsx`: scalar `MergeModal` (combined-hypothesis textarea), lineage copy.
- `e2e/investigation-lineage.spec.ts`: rewritten for `thread_id` API payloads, demo Thread titles ("Acute benefit versus ecological harm", "Mechanism of downstream harm", "Targeting without delayed cure"), "Start Thread", scalar apply/merge, `1/3 discussed`, Thread-resolution labels. **Never run** (§7).

Not on this branch: `pyproject.toml` already declared `supabase>=2.24.0` on main; `uv.lock` was deliberately left at main's version (it does not resolve supabase — pre-existing main inconsistency; env has the package installed, tests run with `--no-sync`). Decide whether to regenerate the lock in the follow-up.

## 3. Untouched by instruction
`apps/… n/a`. `src/agora/deliberation/**`, `src/agora/schemas/deliberation.py`, `src/agora/workflow/**` (the canonical Thread machinery) are intentionally untouched — the reframe should *reuse* them, per Youngseung. Pre-existing repo lint debt (api/router.py, client/base.py, workflow/*, deliberation/thread.py import order, etc.) left alone.

## 4. Key mechanics the next agent must know
- **Demo gating is two different flags.** `self._demo(session)` (workspace created with `demo=True`) gates scripted assent (qualify→accept) and Thread fallback selection; `state.clustering.method == "demo_seeds"` gates the `DEMO_SHARED_GROUND` consensus injection in `judge_thread`. Tests that build workspaces with `demo=True` but never run a search get demo assent but NOT demo shared ground.
- Demo fallback Threads: `Acute benefit versus ecological harm` (scope+significance), `Mechanism of downstream harm` (explanation), `Targeting without delayed cure` (approach+significance). Test helpers `_thread_id(service, session_id, facet)` pick the first Thread containing a facet — significance resolves to Thread 1.
- `MIN_DELIBERATION_EXCHANGES`/`MAX_DELIBERATION_EXCHANGES` bound the exchange loop; unanimity before MIN is ignored.
- `_fallback_consensus_hypothesis` appends "It should also account for <shared>" unless the shared text is already a substring — the source of the flip-flopping equality assertion in §6.4.
- Progress stream kinds are still `round_stage`/`round_turn`/`round_check` (kept for wire compatibility; UI copy says Thread).

## 5. DO-NOT-MERGE blockers (in order)
1. **v5→v6 migration is incomplete for rounds.** `migrate_v5_payloads` only rewrites hypothesis shapes. Persisted v5 rounds also contain `turns[].kind="response"`, `relation ∈ {position, qualify, response}`, `verdicts: [FacetVerdict]`, `moderator_checks[].verdict.facet`, and resolution points with `facet` — all now fail Pydantic validation and would quarantine every real workspace on load. Extend `_collapse_hypotheses`-style transforms to map: kind `response→reply`; relation `position→answer`, `qualify→reply`, `response→reply`; `verdicts[0]`→`verdict` with `facet`→`facets=[facet]` (merge or drop extras); same for `moderator_checks[].verdict`; `DeliberationPoint.facet→facets`. Add fixture tests with a real v5 round payload (extend `tests/test_focused_lineage.py::test_v5_sqlite_snapshot_is_archived_and_migrated_without_data_loss` and the Supabase twin, which currently only cover hypothesis fields).
2. **Four unit failures** (§6) — mechanical.
3. **Supabase DDL**: apply `supabase/migrations/20260825220000_focused_workspace_archives.sql` to the project before deploying persistence changes.
4. **E2E suite unexecuted** (§7).
5. Kat's reframe (§1 Goal C) — do not build more fragment-driven behavior; unwind the couplings listed there.

## 6. The four known test failures (exact fixes)
1. `test_focused.py::test_resolution_creates_unsettled_fallback_without_forced_conflict` — the consensus-only fallback unsettled point now says "The Thread reached agreement but did not test that agreement outside the represented findings."; the test still asserts `"boundary" in rationale`. Update the assertion (or reword the fallback in `agents.summarize_thread`).
2. `test_focused.py::test_hypothesis_uses_consensus_only` — fixtures still build `DeliberationPoint(facet="…")`; field is now `facets=["…"]`.
3. `test_focused.py::test_shared_ground_assent_fails_closed_without_provider` — passes the string `"scope"` where `assent_to_shared_ground` now takes a `DeliberationThread`; pass `_scientific_thread("scope")`.
4. `test_focused.py::test_consensus_threads_propose_and_evolve_the_working_hypothesis` — asserts round 2 changes the hypothesis, but it observably does NOT (`evolved.hypothesis.hypothesis == first_candidate`). I flip-flopped this assertion twice; the honest state: with Thread-level shared ground, round 1 appends "shared scope account; shared significance account", and round 2 (approach+significance Thread) leaves the candidate unchanged even though its ground ("shared approach account; shared significance account") is not a verbatim substring — **debug `_fallback_consensus_hypothesis`/the round-2 proposal path before choosing the assertion**; do not just flip it again. Decide the intended product behavior (should overlapping-facet ground count as already-incorporated?) and pin THAT.

## 7. E2E status
`web-ui/e2e/investigation-lineage.spec.ts` was fully rewritten for the new flow but **has not been executed** (needs the dev server harness, `pnpm --dir web-ui test:e2e`). Expect drift around: Thread card accessible names (title+question+context concatenation), `Start Thread`, `1/3 discussed`, `Queued for after this Thread`, `Saving the completed Thread.`, `Archived Thread 1` region, `Thread resolution` / `Moderator synthesis` labels, `Possible solution` textarea label (`Possible solution hypothesis step`), `Combined hypothesis` textarea, `Compare H1 with H2` merge dialog, `thread-card-*` / `thread-<n>-hypothesis-delta` testids, and reply/challenge chips (`Responding to T…`, lowercase `challenge` relation text). The old `facet-history-*` testids are gone.

## 8. Ordered TODO for the next agent
1. Fix §6.2 and §6.3 (pure mechanics), then §6.1, then root-cause §6.4.
2. Complete the v5→v6 round migration (§5.1) with fixture tests; only then is the branch shippable.
3. Run the Playwright suite; reconcile §7.
4. Apply the reframe (§1 Goal C): Thread question drives `open_statement`/`answer_statement`; facets demoted to context/traceability; consider per-Perspective RELATED FRAGMENTS on `DeliberationThread`.
5. Await/implement Kat's protocol decisions (§1 Goal C list): start with 1 (researcher closes Threads via Resolution review — reuse `decide_resolution` semantics), 2 (open questions → suggested Threads), 4 (affected-Perspective reflection via the canonical `reflect_perspectives` pattern).
6. Naming residue once behavior settles: `run_round`→`run_thread`, `DeliberationRound`→ Thread record, `reflect_on_round`, progress-kind strings, `RoundResolution` — rename in one sweep WITH a schema migration; don't dribble.
7. Decide `uv.lock` (regenerate to resolve supabase, or keep `--no-sync`).
8. Demo determinism (long-standing, see `.handoffs/2026-08-25-*` and memory): a deterministic Demo provider implementing the same structured task boundary as live is still the durable fix; the scripted assent added here covers the visible two-exchange arc only.

## 9. How to verify
```bash
uv run --no-sync pytest tests/test_focused.py tests/test_focused_lineage.py \
  tests/test_focused_hermetic.py tests/test_focused_model_routing.py \
  tests/test_focused_clustering.py tests/test_supabase_persistence.py \
  tests/test_openrouter_schema.py -q
pnpm --dir web-ui exec tsc --noEmit
git diff --name-only origin/main | grep '\.py$' | xargs uv run --no-sync ruff check
# e2e (unrun): pnpm --dir web-ui test:e2e
```
