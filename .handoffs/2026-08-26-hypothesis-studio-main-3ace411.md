# Handoff: Hypothesis Studio after PR #18

**Written:** 2026-08-26.
**Repository:** `/Users/bg/windsurf/hypothesis-studio`.
**Remote:** `github.com/bgar324/AgentAgora` (renamed from `hypothesis-studio` during this session; GitHub redirects old URLs).
**Product-code baseline:** `main@3ace411` (merge of PR #18).

This handoff records the product state after PR #18 merged. The documentation PR that adds this file is a docs-only successor to `3ace411`.

## 1. Mission

One long session (Aug 25 evening → Aug 26) moved through six linked asks:

1. Continue PR #18 from its intentionally-red handoff to its acceptance criteria: fix four known unit failures, complete the v5→v6 round-payload migration for both stores, and run the rewritten Playwright suite for the first time.
2. Replace the deliberation core with Kat's canonical framework (`agora.deliberation`) per her interface mapping and Youngseung's approval: Threads as the object of deliberation, argumentation as the mode, Perspective/hypothesis revision as the outcome, and a moderator-synthesized final Document.
3. Apply the team's protocol decisions: users never type research questions (Kat), agents auto-exchange until shared ground within bounds (Youngseung), the researcher gates every Resolution.
4. A full frontend quality pass: per-action loading states, one visual canon, cognitive-load reduction, manual browser inspection of every surface.
5. Rigorous end-to-end verification, then merge PR #18 into `main` (explicitly authorized).
6. Preserve the session in three hidden documents: this handoff, a session learnings document, and a superseding union.

All product work is merged. One **operational step remains open**: the production Supabase DDL (§4.1).

## 2. State

### Git

- `main` = `origin/main` = `3ace411`, clean tree before the docs branch.
- PR #18 is merged: <https://github.com/bgar324/AgentAgora/pull/18> (16+ commits; the final six from this session's second half: `78fd8ad` engine port, `0a95501` card spacing, `24c522b` heading tracking, `9c2c986` question removal, `a2a8439` question derivation, `932dd6f` cleanup + Supabase guard).
- No GitHub Actions exist (`.github/` absent). PR #18's only automated signals were Vercel builds. Local verification is the evidence.

### Python environment — fixed this session

`.venv` is now a **real in-repo environment, Python 3.11.15**, built with `uv sync --dev`; `uv.lock` was regenerated and resolves `supabase` (v2.31.0). The former symlink into `/tmp/agent-agora-github-review` is gone (macOS tmp-cleanup had gutted it). The August 25 warning about a foreign venv is obsolete. Backend commands that work verbatim:

```bash
PYTHONPATH=src AGORA_PERSISTENCE=sqlite AGORA_PROXY_TOKEN= \
  .venv/bin/python -m pytest tests/test_focused.py tests/test_focused_lineage.py \
  tests/test_focused_hermetic.py tests/test_focused_model_routing.py \
  tests/test_focused_clustering.py tests/test_supabase_persistence.py \
  tests/test_openrouter_schema.py tests/test_focused_dialogue.py -q
```

### Running local processes (session residue, not requirements)

| Name | Command | Notes |
|---|---|---|
| `agora-api` | `.venv/bin/uvicorn agora.focused_app:app --port 8000` | `AGORA_DATA_DIR=/tmp/dialogue-ui-data` — scratch SQLite, not `artifacts/agora.db` |
| `agora-web` | `pnpm dev` in `web-ui/`, port 3000 | serves the merged tree |
| `omp.browser.headless` | managed Chromium | |

### Production

- Railway health: `{"status":"ok"}`; workspace auth gate returns 401. Checked after the merge.
- **`focused_workspace_archives` does not exist in the production Supabase project** (REST probe: PGRST205). Both production workspaces are still schema v5.
- The backend is guarded against this (§3.4), so a deploy cannot crash startup — but legacy workspaces stay hidden until the DDL runs.

## 3. Done so far

### 3.1 PR #18, first half (continuation of the Aug 25 handoff)

The four known-red unit tests fixed at root cause (§6.4 was a demo-reflection bug stamping joined multi-facet ground onto every facet — fixed with per-segment reflection and segment-aware incorporation, not an assertion flip). v5→v6 migration extended to round payloads (turn vocabulary, `verdicts`→`verdict`, `facet`→`facets`) with predecessor-shaped fixtures for SQLite and Supabase. The rewritten e2e suite executed for the first time and reconciled (19/19). Kat's reframe applied: Thread *question* drives the discussion, facets demoted to traceability. Researcher-gated Thread closure, open questions returning as suggested Threads, per-participant reflection, and a synthesized final report. Repo renamed to AgentAgora with README rewritten for Thread semantics.

### 3.2 Kat's canonical engine is the deliberation core (`78fd8ad`)

- `src/agora/focused/dialogue.py` (1,546 lines): bridges (corpus abstracts → `Observation`s with provenance; focused Perspectives → `ResearcherProfile`s), `LiveDialogueEngine` (dspy under the Luna phase LMs), `DemoDialogueEngine` (deterministic twin of every entry point), and the researcher-command orchestrator (opening → selection → open-thread cascade → message cascade → decide cascade → report).
- The canonical modules run **unmodified**: `ProposalGenerator`, `review_panel`, `refine_panel`, `DocumentCreation`, `assign_thread`, `answer/reply/update` turns, `summarize_thread`, `decide_resolution`, `suggest_document_change`/`apply_suggestion` (+`Revision` audit), `reflect_perspectives`, `SuggestThread`. None of the poisoned imports (`workflow.run`, `api.router`, `research.model`).
- State: `SessionState.dialogue` holds canonical schema objects verbatim (append-only versioned; latest-id wins). New optional field → **zero migration** for either store.
- API: `POST /sessions/{id}/dialogue/{start,selection,threads/open,messages,decisions}` + `GET /dialogue/report`; progress streams over the existing `round_stage`/`round_turn` channel; the final `WorkspaceView` stays authoritative.
- UI: `stage-dialogue.tsx` — document-primary three-pane board (Working Document | Threads/conversation | Perspectives), intro modal on Continue, per-action loading, final-report modal. Workspaces with legacy deliberations keep the old `StageDeliberation` untouched; `usesDialogue = deliberations.length === 0` (`index.tsx:127`).

### 3.3 Protocol decisions applied

- **No user-typed research questions.** Start screen = Problem + Demo + Begin; brief shows the problem only; `parseResearchQuestions` deleted. Demo seeds its fixed set internally.
- **Live derivation** (`a2a8439`): `agents.derive_research_questions` (new `FocusedTask`, query role, Luna) runs once in live `suggest_queries` when no questions exist, so PR #11's answer-tier/coverage retrieval still functions; model failure degrades to problem-angle-only. *Flagged in the PR as a shape decision (hidden step vs visible stage) for Kat's design spec.*
- **Bounded auto-exchange** (`MAX_DIALOGUE_EXCHANGES = 2` in `dialogue.py`) implements Youngseung's auto-talk ask on top of Kat's one-reply primitive — one constant to change if she overrules.

### 3.4 Production-safety guard (`932dd6f`)

`supabase_persistence.py` `load()` catches `postgrest.exceptions.APIError` from `_migrate_legacy_row`: a missing archives table now **skips the row untouched** (no crash, no quarantine, error log names the exact migration file) and the same row migrates normally once the DDL exists. Regression-tested with a fake client raising PGRST205.

### 3.5 Frontend quality pass (`932dd6f`, plus `0a95501`, `24c522b`)

- Per-action loading: each button spins only for its own busy label (`BUSY` map in `stage-dialogue.tsx`); everything else disables; `ProgressTrail` streams text without its own spinner — one spinner per surface. Verified live for all five commands.
- Site canon: `.panel`/`.field` utilities, 13/12/11/10.5px scale, `ep-*` animations, `rounded-xl` only for chat bubbles, shared `PerspectiveDot`/`ErrorLine`, aria labels.
- Repo-wide heading tracking: base `h1–h6` = `-0.01em` in `typography.css`; `--tracking-s/-m` deleted; all 11 per-heading overrides stripped (8 div/span pseudo-headings keep theirs).
- Single intro-modal owner (`index.tsx`); the `StageDialogue` fallback renders an empty main for its unreachable-by-construction state (store derives stage from `deliberations.length > 0 || dialogue !== null`).
- Cluster-card spacing double-margin removed (uniform 10px).

### Verification actually performed

- Backend: **109 passed** (10 dialogue-protocol, question derivation, missing-archive degradation, migration fixtures both stores).
- Playwright: **21/21**, including the new `web-ui/e2e/dialogue-protocol.spec.ts` (full researcher journey + keep-open path).
- `tsc --noEmit` clean; Ruff clean on all touched files (whole-repo Ruff remains not green — pre-existing debt).
- Manual headless-Chrome inspection of every dialogue surface at 1440px and 390px; mobile scroll width is exactly 390px.
- Production probes after merge: health 200, auth gate 401, archives table 404 (PGRST205), 2 legacy v5 snapshot rows.

## 4. Open threads

1. **Apply the Supabase DDL, then restart Railway.** `npx supabase link --project-ref <ref> && npx supabase db push` applies `supabase/migrations/20260825220000_focused_workspace_archives.sql`. Until then the two legacy production workspaces are hidden (intact, unquarantined). No CLI auth existed locally this session; the `hypothesis-studio-deployment` skill has the runbook.
2. **Kat's design specifications are still incoming** (and an Anthony + April discussion may gate direction). The board implements only what her messages pin down. Churn surface: `stage-dialogue.tsx` alone; hook and wire types are stable.
3. **Question derivation shape** — hidden pre-search step today; a visible/editable stage is a design-spec call. Single-commit revert: `a2a8439`.
4. **Mid-Thread evidence retrieval** — `evidence_requests` are recorded on turns but never retrieved (needs SnippetIndex infra + a cost decision).
5. **`run-e2e.mjs` still swallows arguments** — this session ran the full 2.4–2.7-minute suite four times because targeted runs are unsafe. The one-line fix (`...process.argv.slice(2)`) is two sessions overdue.
6. **No CI** (`.github/` absent). Vercel builds were the only automated signal on a merge carrying 130 tests.

Exact first action for a new product session: `git status --short --branch`, then decide whether the task needs the Supabase DDL applied before touching production.

## 5. Decisions and constraints

1. **Kat's framework takes precedence for deliberation.** The engine is her vendored code, unmodified; our code is hosting (orchestration, bridges, demo twin). Deviations must be single-switch reversible (the exchange bound is the only one).
2. **Researcher gates are canonical:** `decide_resolution` actions `close`/`edit_close`/`keep_open`/`request_evidence` verbatim; suggestion auto-accept after a researcher-accepted Resolution mirrors her `_work_complete`.
3. **Users never type research questions.** Live derives them; demo seeds its fixture; research branches inherit their origin question. Do not resurrect the input.
4. **New workspaces route to the dialogue surface; legacy workspaces keep the old panel.** The discriminator is `deliberations.length`, and e2e seeds legacy state via the idempotent `POST /sessions/{id}/deliberations`.
5. **Import discipline:** `dialogue.py` is imported lazily inside service methods; the focused app's cold start stays dspy-free. `numpy` must import before `dspy` (`# isort: off` guard in `dialogue.py:24-29`) or `numpy.typing` circular-imports later.
6. **One busy label per command; a button spins only for its own label.** Labels live in `use-focused.ts`; the `BUSY` map in `stage-dialogue.tsx` must match.
7. **One heading-tracking convention:** base `-0.01em`; never reintroduce per-element tracking patches or the deleted `--tracking-s/-m` vars.
8. **Persist canonical objects verbatim** on the session aggregate. New surfaces should extend `SessionState` with optional fields, not new stores.

## 6. Landmines

1. **The e2e harness leaves a Next dev-lock behind.** A failed run leaves `next-server` alive with `.next-e2e/dev/lock` (`Run kill <pid> to stop it`); plain `kill` is sometimes ignored — `kill -9`, then clear ports 8011/3011 before rerunning.
2. **Ruff will re-break the numpy/dspy import order.** `--fix` sorts `dspy` before `numpy`; the `# isort: off` block in `dialogue.py` is load-bearing. The failure only appears in a fresh process.
3. **`requestJson` in the e2e spec unwraps `.active`** — assertions on "workspace" responses are actually on the active session.
4. **PGRST205 handling is deliberate degradation.** Do not "fix" the archive guard by quarantining; quarantine deletes from the snapshots table.
5. **Demo pacing:** retrieval checkpoints run at 1.05 s (`DEMO_RETRIEVAL_DELAY_SECONDS`); UI-driven demo searches take ~20 s. Dialogue demo cascades are instant.
6. **The intro modal is owned by `index.tsx` only.** Rendering `PanelIntroDialog` from `StageDialogue` reintroduces the double-modal bug the cleanup removed.
7. **`gh pr merge` can succeed while printing nothing** if an earlier invocation in the same command already merged; check `state`/`mergedAt` before retrying.
8. **Search buttons need selected queries.** "Search papers" is disabled until query rows are toggled — browser automation that skips selection stalls forever.

## Skills for the next session

- `hypothesis-studio-deployment`: the Supabase DDL + Railway restart is the first production task.
- `adversarial-review`: when Kat's design spec lands and `stage-dialogue.tsx` gets rebuilt.
- `blast-radius`: any change to `dialogue.py` cascades or persistence loading.
- `principle-prove-it-works`: the demo engine makes every cascade cheaply provable — use it before live runs.
