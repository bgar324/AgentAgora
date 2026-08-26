# 8/26-union-learnings

**What this is.** One deduplicated set of durable cross-project lessons from the August 23, August 25, and August 25→26 Hypothesis Studio sessions. It supersedes `.handoffs/2026-08-25-union-learnings.md`. Every entry is self-contained: it states its own lesson and evidence, so no source document needs to be open to use it.

**Sources.** `.handoffs/2026-08-23-session-reflection.md`, `.handoffs/2026-08-25-session-learnings.md`, `.handoffs/2026-08-25-union-learnings.md`, `.handoffs/2026-08-26-session-learnings.md`.

**Tags.** `[Aug 23]`, `[Aug 25]`, `[Aug 26]` mark origin; `[Both]`/`[All]` mark entries refined across sessions. A refinement is folded into its parent and never counted twice.

**Baselines.** Aug 23 evidence: `main = 09dd11f`. Aug 25 evidence: `main = 984af54` (PR #15). Aug 26 evidence: `main = 3ace411` (PR #18, Kat's canonical deliberation engine).

---

## Accepted (20)

### 1. A compensating prefix means the environment is the bug `[Both — resolved Aug 26]`

When a command only works with an extra prefix or environment variable, the prefix is the symptom; inspect the real path before promoting the workaround into documentation. The repository `.venv` was a symlink into another project's `/tmp` worktree on CPython 3.14 against a 3.11 image; `PYTHONPATH=src` repaired first-party resolution only, and a checked-in Playwright config hardcoded the broken path so it could no longer be routed around.

**Resolved August 26.** macOS tmp-cleanup finally gutted the symlink target mid-session, forcing the real fix: an in-repo `.venv` (Python 3.11.15) built with `uv sync --dev` and a regenerated `uv.lock` that resolves `supabase`. The two-session-old backlog item cost one more debugging hour before it was applied — the predicted trajectory of every deferred mechanical fix.

### 2. For memory incidents, suspect the import graph before the request path `[Aug 23]`

Code that never executes still costs resident memory if imported at startup. Measure `import <entrypoint>` RSS in a separate process per candidate; in-process measurement is contaminated by the harness. `import agora.app` cost ~780 MB against ~103 MB for the focused entrypoint; the fix was moving production to `agora.focused_app:app` in `Dockerfile:16`, a three-file diff. **August 26 note:** the constraint held through the engine port — `dialogue.py` (which imports dspy) is imported lazily inside service methods, keeping cold start dspy-free.

### 3. Docs, scripts, CI, tests — and inputs — are contract endpoints. Migrate them, never widen the shipped contract `[All]`

An entrypoint or invariant change is unfinished until every caller is migrated: README run-blocks, dev scripts, CI, and tests. Tests carry a special hazard — a compatibility shim added "so tests pass" reopens the shipped contract and becomes a second source of truth (the 1–2-facet shim contradicting the four-facet protocol was built and backed out on Aug 25; fixtures were migrated instead).

**Refined by August 26 — the producer direction.** A UI input can be a field's *only producer*: removing the research-questions textarea silently emptied `QuestionReach` and bypassed the entire question-driven retrieval contract (answer tier, assessment, coverage ranking) for live sessions, with no error anywhere. Before deleting an input, grep the field's writers (`service.py:802/857/1275` were all of them) and ask what stops running when it is always empty. The fix was a replacement producer (`agents.derive_research_questions`, hermetic-tested to `reached=True`), not a silent degradation.

### 4. A regression test must execute the branch that failed; historical fixtures must come from the predecessor `[Both]`

Absence proofs need a fresh subprocess; a denylist cannot express a budget. A migration's gate is not "do my legacy fixtures pass" but "does a record the old system actually produced survive" — two P1 regressions escaped a fully green five-gate suite on Aug 25 because hand-built fixtures encoded the author's post-change model (one consistent lead) instead of what the rotating-lead UI actually wrote. Corrected fixture: `tests/test_focused_lineage.py` rotates leads across rounds.

### 5. Green on the fast provider proves nothing about the slow one; a check that never ran is not a check that passed `[Both]`

Readiness is the slowest component; steady-state metrics come after container drain; a configured restart policy makes crashes present as recovery. Establish that a signal *fired* before interpreting it: no GitHub Actions exist, so Vercel "Ready" — a build signal, not a test signal — was the only automated green on merges carrying 100+ tests (PR #15 and PR #18 alike).

### 6. Exempt the one independent action, key staleness on domain identity, and prune client sets where they are derived `[Both]`

When one action must run concurrently inside a serialized system, exempt that action; never relax the lock. Key staleness on domain identity, not server revision counters (hermetic backends pin them). Client-held identity sets that outlive their source list must be re-intersected where the state is derived — a filter at one submit site is the hand-placed guard a refactor silently deletes.

### 7. A wrapper that swallows arguments gets bypassed, and the bypass is the unsafe path `[Aug 23 — third recurrence Aug 26]`

`web-ui/scripts/run-e2e.mjs:16` still spawns Playwright without `...process.argv.slice(2)`, so the safe wrapper cannot run one test, and raw targeted runs mutate tracked Next config files. The suite grew 14 → 18 → 21 tests across the three sessions; on Aug 26 the full ~2.5-minute suite ran four times for want of `-g`. The one-line fix has now been paid for three times.

### 8. Archive state written under a superseded invariant; never synthesize or retro-validate it `[Aug 25]`

Synthesizing missing fields on load claims setup the user never performed; retro-validating deadlocks records the old system legitimately wrote. Detect the legacy shape structurally and archive at a boundary the user explicitly creates (`initialize_deliberation` keys on `lead_perspective_id is None and baseline_hypothesis is None` and archives only when the researcher selects a lead). Answer "can old data satisfy the new rule?" against records the old system actually produced.

### 9. Store a stabilized role as an identity; its null state becomes the migration detector `[Aug 25]`

A derived value cannot distinguish "never established" from "happened to compute to this". `lead_perspective_id: str | None` is half the legacy predicate that made entry 8's migration detectable. Read 8 and 9 together.

### 10. Scope a generator's input to the constraint plus the current value, not the source entity `[Aug 25]`

"Revise X under constraint C" takes C and X — never the object X was derived from. A matching output type is the trap: `develop_hypothesis(revised)` type-checked while rewriting fields the round never discussed; the shipped `develop_hypothesis_from_consensus(resolution, current=...)` preserves unchanged parts by construction.

### 11. An audit field answers one question at one layer; a later action gets its own record `[Aug 25]`

`DeliberationRound.hypothesis_decision` records how the researcher resolved that round's proposal, nothing else; a later manual edit records `source_kind="edit"` elsewhere. Field reuse driven by type compatibility is how provenance quietly stops being evidence.

### 12. Render an editable set from the canonical enum; materialize missing entries as blanks `[Aug 25]`

The array is data; the enum is the contract. Iterating a server-supplied partial array deletes the exact control the user needs to fill the gap while the server still rejects the incomplete record (`stage-extraction.tsx` maps `FACETS` with blank fallthroughs).

### 13. Lint the changed surface; test the whole system `[Aug 25]`

Lint carries pre-existing debt (whole-repo Ruff: 15 unrelated findings), so scope it to changed files; tests assert a system invariant, so scope them to everything. Neither scope is pinned in `pyproject.toml` — still true at `3ace411`.

### 14. One response is authoritative; progress reporting is advisory `[Aug 25]`

A second transport for progress is a second source of truth that assertions drift toward. The generation/cursor progress channel was reused for deliberation rounds (Aug 25) and again for dialogue cascades (Aug 26); the final `WorkspaceView` response stays the only authority in both.

### 15. Before merging a migration-dependent change, probe the exact production object it depends on `[Aug 26]`

A migration file in the repo says nothing about the database it will meet. One REST `select ... limit 1` with the service key against the *exact* table is free ground truth (PostgREST returns PGRST205 for missing). The probe found `focused_workspace_archives` absent and both production workspaces still v5 — the merged code would have crashed startup on deploy, because the archive upsert ran unguarded inside `load()`. A near-miss corollary: an earlier probe of a *neighboring* table that exists had produced false confidence. Probe the dependency, not the vicinity.

### 16. When you cannot run the DDL, ship the degraded-mode guard in the same change — and never route infrastructure errors into quarantine `[Aug 26]`

Blocked on credentials is not blocked on safety. `supabase_persistence.py:197-215` catches `APIError` from the migration path and skips the row untouched (error log names the exact migration file; the row migrates normally after DDL + restart). The guard must bypass the quarantine branch: quarantine deletes from the live table, so an infra error routed there converts a config gap into data loss. Regression test: no crash, no quarantine writes, snapshot byte-identical, then normal migration once the table exists.

### 17. Bind a button's loading state to its command's identity, not to "anything is busy" `[Aug 26]`

A global busy flag keyed every control: clicked buttons showed nothing while spinners appeared in unrelated trails — read by the user as duplicated loading. Contract: each mutation has a stable label; a button spins only when `busy === itsLabel` (plus local identity for per-item buttons); everything else disables; at most one spinner per surface. `stage-dialogue.tsx` `BUSY` map + per-card `openingId`.

### 18. Host a vendored engine behind an interface with a deterministic twin `[Aug 26]`

`LiveDialogueEngine` (dspy) and `DemoDialogueEngine` implement the same entry points with canonical return types, so every cascade is cheaply provable: 10 protocol unit tests in seconds and an LLM-free e2e journey, with the live path differing only in engine construction. The twin must satisfy the canonical validators (evidence non-empty, support relation, version fields) — that constraint is what keeps it honest about schema shape.

### 19. Persist foreign-schema state verbatim as one optional field on the existing aggregate `[Aug 26]`

`SessionState.dialogue: DialogueState | None = None` holds Kat's schema objects unmodified (append-only versioned lists). Wire = engine = persistence format; zero migration for either store; old payloads load untouched. Translating into bespoke rows would have created a second contract to keep synchronized with her repository forever.

### 20. Import-order invariants need a mechanical guard, or the formatter deletes them `[Aug 26]`

`import dspy` installs a lazy numpy alias; `numpy.typing` imported later circular-imports. A numpy-first import fixed it — then `ruff --fix` alphabetized `dspy` first and reintroduced the crash, caught only by a fresh-process test run. Durable form: `# isort: off/on` around the ordered pair with the reason in a comment (`dialogue.py:24-29`). Any invariant a formatter can silently violate needs a formatter-proof carrier.

---

## The strongest five

**15+16 (as one pair), 4, 3, 8, 18.**

- **15+16** prevented this union's only would-be production outage, and the pattern (probe the dependency, guard the gap, refuse quarantine-as-error-handler) transfers to every migration-bearing merge.
- **4** remains the strongest historical item: two P1s escaped a fully green suite until predecessor-shaped data was modeled.
- **3** has now recurred in three forms across three sessions — stale README, test-driven contract widening, and producer removal — the best-evidenced repeated failure in the set.
- **8** cost the most implementation time (two backed-out migration designs) and its archive-boundary shape was reused verbatim by the Aug 26 v5→v6 work.
- **18** is the newest but did the most proof-work per line: it made a five-stage LLM protocol unit-testable and demo-drivable in one session.

Entries **1** and **7** remain excluded for the same reason as before — their real fixes are config lines. Entry 1's fix finally landed (forced by environment collapse, not by prose); entry 7's is now three sessions overdue.

---

## Consolidated structural backlog

| # | Item | Mechanism | Status at `3ace411` |
|---|---|---|---|
| S1 | Foreign `/tmp` venv, hardcoded in Playwright config | Real in-repo venv from `.python-version` | **APPLIED Aug 26** (Python 3.11.15, `uv sync --dev`, lock resolves supabase) |
| S2 | `run-e2e.mjs` swallows argv; no targeted e2e | Forward `...process.argv.slice(2)` | Unapplied; third recurrence, cost grew (21 tests, 4 full runs in one session) |
| S3 | No CI | Actions workflow + required check | Unapplied (`.github/` absent through PR #18) |
| S4 | Gate scopes re-derived from memory | `[tool.pytest.ini_options]`, Ruff scope | Unapplied |
| S5 | Schema version absent from persisted state | `schema_version` on the store, migrations keyed on it | **APPLIED** (v6: `WorkspaceState.schema_version: Literal[6]`, migrate-on-load, pre-migration archives both stores) |
| S6 | Closed contracts hand-duplicated across the wire | Codegen from OpenAPI or equality tests | **Worse:** canonical deliberation schemas now also hand-mirrored in TS (`types/focused.ts` `Canon*` block) |
| S7 | Module growth unanswered | Split decision or line budget | Growing: `service.py` 4,290; `agents.py` 2,087; new `dialogue.py` 1,546; `stage-deliberation.tsx` 3,565 (legacy-retained); new `stage-dialogue.tsx` 962 |
| S8 | No repo memory file | `AGENTS.md` with entrypoint invariant, gates, port bands | Unapplied; `.handoffs/` carries the weight |
| S9 | e2e harness leaves stale Next dev-locks (`.next-e2e/dev/lock`), failing subsequent runs | Pre-run cleanup inside `run-e2e.mjs` (kill lock pid, clear 8011/3011) | New Aug 26 |

**Carried forward, unapplied since August 23:** `tsconfig.json` exclude for `.next*`; accumulated `.next*` directories; `specter_v2` vectors on mutation responses; an OOM budget test; an entrypoint enforcement test; a health payload carrying commit and RSS; hermetic-backend contract tests; subagent cwd drift; the two project skill updates.

---

## Dedup notes

- **Aug 26 L3 (input removal severs contracts) folded into entry 3** as the producer direction of the same lesson: callers consume a boundary; inputs produce one. One lesson, two directions.
- **Aug 26 L8 (advisories are hypotheses; adjudicate against the tree) stays rejected** for the third time — it is this process's documented operating method, exercised again on three advisories with three different verdicts (one correct, one stale, one judgment call). Its transferable kernel remains inside entry 4.
- **Aug 26 L1/L2 kept as two entries (15, 16) rather than one:** the probe (15) is a pre-merge verification default; the guard (16) is a code-shape rule with its own anti-pattern (quarantine-as-error-handler). Each stands alone.
- **Entry 1 retained despite resolution:** the lesson is the diagnostic (a compensating prefix indicts the environment), not the incident. Its resolution note doubles as evidence for the backlog framing — deferred mechanical fixes get applied by disasters, not by prose.
- **Rejected: "hold frontend work until the design spec lands."** The pinned-subset-with-bounded-churn-surface approach shipped a testable surface without preempting the spec; total freeze answers a scoping question with a stop-work order.

---

## Source provenance

| Union entry | Origin | Aug 26 relation |
|---|---|---|
| 1 | Aug 23 A1 | resolved (venv rebuilt); lesson retained |
| 2 | Aug 23 A2 | reconfirmed by lazy `dialogue.py` import |
| 3 | Aug 23 A3 | refined: producer direction (L3) |
| 4 | Aug 23 A4 | unchanged; still the strongest historical item |
| 5 | Aug 23 A5 | reconfirmed (PR #18: Vercel-only signal) |
| 6 | Aug 23 A6 | unchanged |
| 7 | Aug 23 A7 | third recurrence, cost grew |
| 8–14 | Aug 25 C1–C10 (merged per Aug 25 union) | 8's shape reused by v5→v6; 14 reused by dialogue progress |
| 15 | Aug 26 L1 | new |
| 16 | Aug 26 L2 | new |
| 17 | Aug 26 L4 | new |
| 18 | Aug 26 L5 | new |
| 19 | Aug 26 L6 | new |
| 20 | Aug 26 L7 | new |

**Counts.** 20 accepted: 7 carried from Aug 23 (1 resolved-and-retained, 2 refined), 7 from Aug 25, 6 new from Aug 26. Backlog: 9 tracked — 2 applied (S1, S5), 1 worsened (S6), 1 new (S9); plus the Aug 23 carried-forward list.

**Verification.** Every Aug 26 code pointer was verified against the working tree at `main = 3ace411`. Line counts, `pyproject.toml` gate absence, `.github/` absence, and the `run-e2e.mjs` spawn call were re-checked on 2026-08-26. Production claims (health 200, auth 401, PGRST205, two v5 rows) come from live probes run minutes after the PR #18 merge.
