# August 26 session learnings

**Scope.** What the August 25→26 Hypothesis Studio session taught: PR #18 from known-red handoff through Kat's canonical engine port, the frontend quality pass, and the merge to `main = 3ace411`. Every code pointer below was verified against that tree.

**Verification.** Each entry names the commit or file:line evidence. The session's gates: 109 backend tests, 21/21 Playwright, `tsc` clean, changed-file Ruff clean, live production probes. Nothing in this document is aspirational; each lesson cost or saved something concrete in this session.

---

## Accepted (8)

### L1. Before merging a migration-dependent change, probe the exact production object it depends on

A migration file in the repo says nothing about the database. The REST layer with a service key is a free ground-truth probe: one `select ... limit 1` against the exact table distinguishes "applied" from "missing" (PostgREST answers PGRST205 for missing). This session's probe found `focused_workspace_archives` absent **and** both production workspaces still schema v5 — the merged code would have crashed backend startup on the next deploy, because the archive upsert ran unguarded inside the load path.

Evidence: probe output (404 PGRST205; 2 legacy rows) in the session transcript; the unguarded path was `supabase_persistence.py:150` inside `_migrate_legacy_row`, called from `load()`.

Corollary: an earlier probe against the *wrong* table (`focused_workspace_snapshots`, which exists) had produced false confidence. Probe the object you depend on, not a neighbor.

### L2. When you cannot run the DDL, ship the degraded-mode guard in the same change

Blocked on credentials is not blocked on safety. The guard converts "missing DDL = startup crash + quarantine sweep" into "legacy rows skipped untouched, error log names the exact migration file, rows return after DDL + restart". Crucially it must **bypass the quarantine path**: quarantine deletes from the live table, so routing an infrastructure error into it turns a config gap into data loss.

Evidence: `src/agora/focused/supabase_persistence.py:197-215` (catch `APIError` before the quarantining `except`), regression test `tests/test_supabase_persistence.py::test_missing_archive_table_skips_row_without_mutation` (asserts: no crash, no quarantine writes, snapshot payload byte-identical, and normal migration once the table exists).

### L3. Removing a user input can silently sever a backend contract fed only by that input

"Just remove the field" is a UI instruction with a data-flow blast radius. `research_questions` was populated **only** by user input or a branch's origin question; removing the textarea silently emptied `QuestionReach` and bypassed the entire question-driven retrieval contract (answer tier, paper assessment, coverage ranking) for live sessions. The check is one grep: who *writes* the field, and what stops running when it is always empty.

Evidence: writers were `service.py:802` (user input), `:857` (origin question), `:1275` (brief update) — nothing else; the dead machinery was `service.py:1343-1383` and `:1877-1882`. Fix: `agents.derive_research_questions` (new `FocusedTask`, `service.py:1331-1337`), hermetic-tested end-to-end (`test_questionless_live_start_derives_research_questions` proves derivation → `question_reach` → question-kind queries → `reached=True`).

### L4. Bind a button's spinner to its command's identity, not to "anything is busy"

A single global `busy` flag keyed every control: the clicked button often showed nothing while a spinner appeared in an unrelated progress trail — the user read it as "loading state duplicated somewhere else on the page". The working contract: each mutation has a stable label (`use-focused.ts`), a button spins only when `busy === itsLabel` (plus local identity for per-item buttons like Open Thread), everything else merely disables, and at most one spinner renders per surface.

Evidence: `web-ui/src/features/focused/stage-dialogue.tsx` `BUSY` map (:20-26) and per-card `openingId` state; verified live mid-flight for all five commands (exactly one spinner each).

### L5. Host a vendored engine behind an interface with a deterministic twin

Kat's dspy engine and a `DemoDialogueEngine` implement the same informal interface (same method names/kwargs, canonical return types). Every cascade — opening, selection, thread discussion, researcher challenge, decision, reflection, report — became cheaply provable: 10 protocol unit tests run in seconds, the e2e demo journey runs without any LLM, and the live path differs only in which engine the service constructs. The twin must satisfy the *canonical validators* (evidence non-empty, support relation present, version fields), which forced it to be honest about schema shape.

Evidence: `src/agora/focused/dialogue.py` (`LiveDialogueEngine` / `DemoDialogueEngine`), `tests/test_focused_dialogue.py` (10 tests), `web-ui/e2e/dialogue-protocol.spec.ts` (2 journeys).

### L6. Persist foreign-schema state verbatim as one optional field on the existing aggregate

`SessionState.dialogue: DialogueState | None = None` holds Kat's schema objects unmodified (append-only versioned lists, latest-id-wins accessors). Result: zero migration for either store, wire format = engine format = persistence format, and old payloads load untouched. The alternative (translating into bespoke rows/models) would have created a second contract to keep in sync with her repo.

Evidence: `src/agora/focused/models.py` `DialogueState` (canonical imports aliased `Canon*`); persistence round-trip proven across a process restart with no migration code added.

### L7. Import-order invariants need a mechanical guard, or the formatter will delete them

`import dspy` installs a lazy numpy alias; if `numpy.typing` loads later (via `agora.db.vector`), numpy circular-imports (`cannot import name 'NDArray' from partially initialized numpy._typing`). A defensive numpy-first import fixed it — then `ruff --fix` alphabetized `dspy` before `numpy` and reintroduced the crash, caught only because tests ran in a fresh process afterward. The durable form is `# isort: off/on` around the ordered pair with a comment stating *why*.

Evidence: `src/agora/focused/dialogue.py:24-29`; the regression appeared and was fixed inside one session (`932dd6f` predecessor commits).

### L8. Treat advisories as hypotheses; adjudicate each against the live tree before acting

Three advisories this session, three different verdicts: one **correct** (`_call` vs `_guard` — the named symbol really didn't exist), one **stale** (a dangling `<DialogueOpening />` that the full-file rewrite had already eliminated; `grep` exits 1 on merged main, and `tsc` could not have passed otherwise), one a **judgment tradeoff** (question derivation scope — resolved by flagging the decision on the PR rather than reverting). The uniform move: reproduce the claim read-only first; the answer determines whether you fix code, fix nothing, or fix the decision record.

Evidence: session transcript; the stale-advisory check was `grep -n DialogueOpening web-ui/src/features/focused/stage-dialogue.tsx` → no matches at `3ace411`.

---

## Rejected (3)

| # | Tempting claim | Why rejected |
|---|---|---|
| R1 | "The `StageDialogue` fallback branch should render a recovery UI." | The state is unreachable by construction: the store *derives* stage on restore (`deliberations.length > 0 \|\| dialogue !== null`), and in-session transitions only enter the panel stage with dialogue present. UI for an unreachable state is speculative surface; the empty main is correct. |
| R2 | "Hold all frontend work until Kat's design spec arrives." | The safe subset was already pinned by her messages (Document central, Discussion panel, Canvas toggle, no typed questions), and a working surface is what she was asked to test. The churn risk was bounded to one file over a stable hook/type layer, and stated on the PR. Sequencing concerns are real; total freeze was not the answer. |
| R3 | "Skip the e2e rerun; the backend guard can't affect the frontend." | The suite caught two legacy-panel journeys broken by the `usesDialogue` routing earlier in the same session — UI-reachable behavior changed even when a diff looked backend-only. Route changes to entry points always re-run the journey suite. |

---

## Backlog, structurally enforceable

| # | Item | Status after this session |
|---|---|---|
| S1 | Foreign `/tmp` venv | **APPLIED.** Real in-repo `.venv`, Python 3.11.15, `uv sync --dev`; `uv.lock` resolves supabase. Playwright's hardcoded `.venv/bin/uvicorn` now points at a real binary. |
| S2 | `run-e2e.mjs` swallows argv | **Unapplied; cost grew again.** Suite is now 21 tests / ~2.5 min; this session ran it in full four times for want of `-g`. The fix is still one spread operator (`web-ui/scripts/run-e2e.mjs:16`). |
| S3 | No CI | Unapplied (`.github/` absent). PR #18 merged with Vercel builds as the only automated signal. |
| S4 | Gate scopes unpinned | Unapplied (`pyproject.toml` still has no `[tool.pytest.ini_options]` / `[tool.ruff]`). |
| S5 | Schema version on persisted state | **APPLIED** by the v5→v6 work: `WorkspaceState.schema_version: Literal[6]`, migrate-on-load keyed on it, pre-migration archives in both stores. |
| S6 | Hand-duplicated enums across the wire | **Worse:** the canonical deliberation schemas are now also hand-mirrored in TS (`web-ui/src/types/focused.ts` `Canon*` block). Codegen from OpenAPI or an equality test is overdue. |
| S7 | Module growth unanswered | Growing: `service.py` 4,290, `agents.py` 2,087, new `dialogue.py` 1,546, `stage-deliberation.tsx` 3,565 (retained for legacy), new `stage-dialogue.tsx` 962. |
| S8 | No repo memory file | Unapplied (`AGENTS.md` absent). The `.handoffs/` docs carry this weight for now. |
| S9 *(new)* | e2e harness leaves stale Next dev-locks | A failed run leaves `next-server` + `.next-e2e/dev/lock`; the next run fails with "config.webServer was not able to start". Mechanism: pre-run cleanup in `run-e2e.mjs` (kill lock pid, clear 8011/3011) instead of tribal `kill -9`. |

---

## Summary

Two clusters. **Production-boundary discipline** (L1, L2): the repo's migration story was complete and tested, and none of it said anything about the database it would meet; one REST probe and one guard turned a would-be outage into a logged, reversible degradation. **Hosting someone else's engine** (L5, L6, L7): the useful posture was maximal verbatimness — her schemas persisted as-is, her functions called as-is, a deterministic twin for proof — with our code confined to bridges and command orchestration, and the one real integration hazard (import order) pinned mechanically.

| | Count |
|---|---|
| Accepted | 8 |
| Rejected | 3 |
| Backlog | 9 tracked; 2 applied this session (S1, S5), 1 worsened (S6), 1 new (S9) |
