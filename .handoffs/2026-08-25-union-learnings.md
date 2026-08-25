# 8/25-union-learnings

**What this is.** One deduplicated set of durable cross-project lessons from the August 23 and August 25 Hypothesis Studio sessions. It is self-contained: every entry states its own lesson and evidence, so neither source document needs to be open to use it.
**Sources.** `.handoffs/2026-08-23-session-reflection.md` and
`.handoffs/2026-08-25-session-learnings.md`.

**Tags.** `[Aug 23]` originated on August 23 and is unchanged. `[Aug 25]` originated on August 25. `[Both]` originated on August 23 and was refined in place by August 25 evidence. A refinement is folded into its parent entry and never counted twice.

**Baselines.** August 23 evidence was verified against `main = 09dd11f`. August 25 evidence was verified against `main = 984af54`, after PR #15.

---

## Accepted (14)

### 1. A compensating prefix means the environment is the bug `[Both]`

When a command only works with an extra prefix or environment variable, that prefix is the symptom. Inspect what the path actually is before promoting the workaround into documentation. A command that names `/tmp`, another repository, or a symlink has an expiry date the next reader cannot see.

`.venv` is a symlink to `/tmp/agent-agora-github-review/.venv`, a different project's scratch worktree, and the mandatory `PYTHONPATH=.../src` prefix exists only to shadow that foreign editable install. `PYTHONPATH` repairs first-party resolution only: the interpreter is CPython 3.14 against a 3.11 production image, and third-party packages come from another project's dependency closure. Both the `60 passed` of August 23 and the `103 passed` of August 25 were validated against a foreign environment.

**Refined by August 25.** Once a checked-in config hardcodes the broken path, you can no longer route around it. `web-ui/playwright.config.ts:22-33` builds its server command from `${repositoryRoot}/.venv/bin/uvicorn`, so the session created a clean `/tmp/hypothesis-studio-venv` for pytest and still had to plant a `uvicorn` symlink inside the foreign venv. The workaround deepened the dependency it was meant to escape and left a mutation in another project's tree. Never repair a shared or foreign environment in place.

### 2. For memory incidents, suspect the import graph before the request path `[Aug 23]`

Code that never executes still costs resident memory if it is imported at startup. Measure `import <entrypoint>` RSS in a separate process for each candidate entrypoint before optimizing anything the request path does. In-process measurement is contaminated by whatever the harness already imported. If one entrypoint's baseline is most of the container limit, the fix is the import graph, not the hot path.

Separate-process comparison: `import agora.app` was about 779.6 MB against about 103.4 MB for the focused import. The resulting fix was a three-file diff that moved production to `agora.focused_app:app` in `Dockerfile:16`.

### 3. Docs, dev scripts, CI, and tests are callers. When a caller cannot satisfy the new invariant, migrate the caller `[Both]`

An entrypoint or process-boundary change is not finished when the deploy config flips. After introducing a new entrypoint, port, start command, or env var, grep the old name across README, docs, CI, and dev scripts. If it survives in a runnable command block, the wave is unfinished, and local dev now boots a different process than production, which is how a production-only failure gets reintroduced.

August 23 evidence: `Dockerfile:16` targets `agora.focused_app:app` while the README still boots `src/agora/app.py`, the exact app the OOM incident was about, and a grep for `focused_app` across the README returned no matches. A fresh contributor following the README reproduces the incident's precondition.

**Refined by August 25.** Tests are a caller class with a hazard the others lack: they can push a shipped contract back open. A temporary change restored the 1-2 facet range in the service and API so existing tests would pass, contradicted the four-round four-facet process, and was removed; the fixtures were migrated instead. A compatibility window is legitimate only when the old and new shapes can both be correct. When the old shape is invalid under the new domain rule, a shim is a second contradictory source of truth and every future reader treats it as permission. Ask whether a value the shim admits could ever be right under the new rule. If not, the shim is the bug. Both layers now hold the invariant independently: `src/agora/api/focused.py:129-148` pins `min_length=1, max_length=1`, and `src/agora/focused/service.py:2894-2913` independently rejects anything else.

### 4. A regression test must execute the branch that failed, a denylist cannot express a budget, and historical fixtures must come from the predecessor `[Both]`

Proving an absence, such as "module X is never loaded", requires a fresh subprocess, because an in-process assertion is contaminated by the harness. Then state the invariant you actually hold. If it is a budget, a module-name denylist is unfalsifiable on the path that matters, because the real path is allowed to load that module by design.

August 23 evidence: `test_focused_condition_is_runnable_from_standalone_app` uses in-process `TestClient`, posts `{"demo": True}`, and asserts `"torch" not in sys.modules`, but the demo branch short-circuits before `_embedding_clusters`, so the lazy `sklearn` imports are never reached. The assertion cannot simply be strengthened, because `sklearn` is legitimately loaded on the live path. The guard is silent exactly where the failure lives.

**Refined by August 25.** The same principle governs what a migration test is seeded with. A full gate was green before the two highest-value regressions were found: 103 backend tests, changed-file Ruff, ESLint, `tsc --noEmit`, a Next production build, and 18 Playwright tests. An outside reviewer then produced two P1 findings, and both were invisible for one reason. The legacy fixtures were hand-built, so they encoded the author's post-change model rather than what the prior UI wrote. A hand-built legacy cycle has one consistent lead; the rotating-lead UI never produced one. A migration's gate is not "do my legacy fixtures pass" but "does a record the old system actually produced survive". The corrected fixture at `tests/test_focused_lineage.py:91-128` now encodes rotating leads and two facets per round; it still builds the cycle by direct attribute assignment, so the drift risk remains.

### 5. Green on the fast provider proves nothing about the slow one, and a check that never ran is not a check that passed `[Both]`

Three verification defaults for split deployments. Readiness is the slowest component, not the first green check, so wait for the backend's startup line before exercising a frontend mutation. During a rollout, per-container resource gauges sum draining and incoming containers, so take the steady-state reading after drain and after a real request. Where a restart policy is configured, a passing healthcheck is not evidence a crash is gone; check for the absence of the kill line.

August 23 evidence: `railway.toml` sets `restartPolicyType = "ON_FAILURE"` with `restartPolicyMaxRetries = 3`, so a repeat OOM presents as a service that recovers. Memory metrics briefly summed containers to 1911 MB during overlap against a steady state of 286.19 MB after drain and a real 20-paper search.

**Refined by August 25.** Establishing that a signal fired is the step before interpreting it. No GitHub Actions workflow ran for PR #15, Vercel preview reported Ready, and production after merge was not inspected. The repo has no `.github` directory, so a Vercel build was the only automated signal on a merge to `main` carrying 121 tests. A deploy preview reporting Ready is a build signal, not a test signal, and both render green. In repos that do have CI, path filters, skipped jobs, and fork-PR restrictions produce the same silent absence of red. The health handler still returns a bare `{"status": "ok"}` (`src/agora/api/focused.py:41-43`), so "which build is serving" stays unanswerable.

### 6. Exempt the one independent action, key staleness on domain identity, and prune client sets where they are derived `[Both]`

When one action must run concurrently inside an otherwise serialized system, exempt that single action rather than relaxing the lock, and give it an explicit merge rule that preserves pending work and rejects responses dropping already-confirmed items. Key the staleness test on domain identity, the item's natural key, not on a server revision counter. Hermetic and stub backends routinely pin such counters, so a revision-only guard passes locally and fails in exactly one environment.

August 23 evidence: `web-ui/src/hooks/use-focused.ts` documents the exemption scope in a docstring while `exclusive()` still throws for everything else, and the monotonicity test in `web-ui/src/store/focused.ts` builds `representedOrigins` from perspective `origin` values rather than `revision`. The first guard relied on server revision, and the hermetic backend holds revision 0.

**Refined by August 25.** The mirror direction is client-held identities the server has since invalidated. `stage-deliberation.tsx:1758-1780` seeds `selectedQuestionIds` from a lazy initializer that never re-derives, while the modal renders only open questions. An archived selection disappeared from the modal, so the user could neither see nor deselect it, but it still shipped, and the server returns 404 for non-open ids. The diagnostic tell for the whole class is an error the UI offers no way to clear. Prune where the state is derived or stored, not at each consumer: the fix at `:2231-2235` is a filter at one submit site, which is invisible to a reader of the state declaration and is exactly the hand-placed guard a refactor deletes silently.

### 7. A wrapper that swallows arguments gets bypassed, and the bypass is the unsafe path `[Aug 23]`

When you wrap a tool to add a safety guarantee, forward the tool's arguments. A wrapper that cannot be narrowed forces anyone iterating to call the raw tool directly, which is precisely the invocation the wrapper existed to make safe. A half-built lever is worse than none, because it creates a safe path nobody can use during the work and an unsafe path everybody uses.

`web-ui/scripts/run-e2e.mjs:16` is `spawn(command, ["exec", "playwright", "test"], ...)` with no `...process.argv.slice(2)`, so `pnpm test:e2e -g "..."` silently runs the whole suite. `forbidOnly: true`, `workers: 1`, and `retries: 0` remove every in-file escape hatch, and the only narrow path bypasses the `finally` block that restores tracked `next-env.d.ts` and `tsconfig.json`. August 25 note: the suite grew from 14 to 18 tests in two days, so the cost of deferring the one-line fix is monotonically increasing.

### 8. Archive state written under a superseded invariant. Do not synthesize it, and do not retro-validate it `[Aug 25]`

When a redesign changes an invariant, already-persisted records admit three treatments and two are traps. Synthesizing the missing fields on load claims setup the user never performed and corrupts the audit record. Retro-validating deadlocks real records, because the old system wrote states that can never satisfy the new rule. Detect the legacy shape structurally and archive it at a boundary the user explicitly creates. Answer "can old data satisfy the new rule?" against records the old system actually wrote, never against a fixture you built to be satisfiable.

`src/agora/focused/service.py:2654-2703`: `initialize_deliberation` keys legacy detection on `lead_perspective_id is None and baseline_hypothesis is None`, raises "The lead cannot change after round 1." for non-legacy rounds, and otherwise rebuilds the roster and calls `_restart_deliberation`. The branch runs only after the researcher selects a lead, so the migration is an action the user took rather than something that happened to their data. Both dead ends were attempted first and backed out.

### 9. Store a stabilized role as an identity. Its null state becomes the migration detector `[Aug 25]`

When a role, owner, or selection stabilizes, store its identity rather than recomputing it from position, and let the null state carry the "not yet established" meaning that migrations and audits will later depend on. A derived value cannot distinguish "never established" from "happened to compute to this", and that distinction is exactly what a later migration needs.

`src/agora/focused/models.py:304-355` declares `lead_perspective_id: str | None = None` on both the archived `DeliberationCompletion` and the live `DeliberationState`. Its null state is half the legacy predicate in entry 8, which is why that migration was detectable at all. Read these two entries together.

### 10. Scope a generator's input to the constraint plus the current value, not the source entity `[Aug 25]`

When the operation is "revise X under constraint C", the generator's inputs are C and X, never the object X was originally derived from. A matching output type is not evidence of a matching contract. It is the trap that makes the wrong reuse look correct.

The first implementation called `develop_hypothesis(revised)`, plausible because the return type was exactly right. That generator takes a whole `Perspective` (`src/agora/focused/agents.py:1475-1478`) and can rewrite unrelated non-empty fields the round never discussed. The shipped call at `src/agora/focused/service.py:3194-3218` passes the round's consensus resolution plus the value being revised, through `develop_hypothesis_from_consensus(resolution, *, current=...)` at `agents.py:1567-1572`. Unchanged parts survive, and disagreement or unsettled content is excluded by construction rather than by prompt instruction.

### 11. An audit field answers one question at one layer. A later action gets its own record `[Aug 25]`

Before writing an existing audit field from a new code path, state in one sentence the question that field answers. If the new action answers a different question, it needs its own record. Field reuse driven by type compatibility is how provenance data quietly stops being evidence, and unlike a crash, nothing surfaces the loss.

`DeliberationRound.hypothesis_decision` (`src/agora/focused/models.py:264-274`) records how the researcher resolved that round's pending proposal and nothing else. In `src/agora/focused/service.py:3414-3463`, `reject_pending` writes `"rejected"`, `apply_pending` writes `"accepted"` or `"edited"` by comparing against `latest_round.hypothesis_proposal`, and the `edit_applied` branch sets only `source_kind = "edit"`. A later manual edit is a different event at a different layer; writing the same field would overwrite whether the round's proposal had been accepted or rejected, silently rewriting history that downstream analysis treats as immutable.

### 12. Render an editable set from the canonical enum, and materialize missing entries as blanks `[Aug 25]`

When a server array is an instance of a closed contract, iterate the contract, not the instance. The array is data; the enum is the contract. If a UI iterates a server-supplied array to render editable controls, a partial array deletes the very control the user needs to fill the gap, while the server still rejects the incomplete record. The failure stays hidden until partial data exists, so it will not appear in the run where you choose the pattern.

`web-ui/src/features/focused/stage-extraction.tsx:1029-1040` maps the canonical `FACETS` and falls through `edits[facet] ?? clusterFacets.get(facet) ?? { facet, text: "", ... }`; `stage-deliberation.tsx:2564-2566` does the same for agent facets. The canonical list is declared once at `web-ui/src/types/focused.ts:1-8`.

### 13. Lint the changed surface, and test the whole system `[Aug 25]`

Lint and test gates need opposite scopes. Lint carries pre-existing debt, so whole-repo lint on a feature branch produces findings the change did not cause and cannot gate on. Scope it to changed files. Tests assert a whole-system invariant, so scope them to everything. Never let unrelated pre-existing findings become the gate, and never let a narrowed lint scope go unrecorded.

Whole-repo Ruff surfaced 15 unrelated pre-existing findings; the valid gate was Ruff on changed Python files followed by the full 103-test suite. This answers the August 23 follow-up that recorded whether the wider Ruff scope passes as unknown. It was run, and it does not pass. Neither scope is pinned: `pyproject.toml` has no `[tool.pytest.ini_options]` and no `[tool.ruff]` block.

### 14. One response is authoritative. Progress reporting is advisory `[Aug 25]`

Adding a second transport for progress creates a second source of truth, and tests drift toward asserting on the cheap observable instead of the real one. Exactly one terminal response should be authoritative, and that is what assertions must target.

The session reused the existing generation and cursor channel instead of adding SSE, keeping the final round response authoritative. Both polling sites in `web-ui/src/hooks/use-focused.ts:246-259` and `:431-444` use the same `search-progress?generation=...&after=<cursor>` protocol, and the hook contains no `EventSource` and no `text/event-stream`.

---

## The strongest five

**4, 3, 8, 10, 6.** Each one caused or prevented a concrete defect, each is domain-agnostic, and none can be discharged by a config line, which is what makes prose the right carrier.

- **4** is the strongest single item in the set. Two P1 regressions escaped a fully green five-gate suite, and what found them was an outside reviewer modeling what the previous release actually wrote.
- **3** has recurred across both sessions in two forms, a stale README and a compatibility shim, so it has the best evidence of being a repeated failure rather than an incident.
- **8** cost the most time on August 25: two migration designs were built and backed out before the archive boundary landed.
- **10** transfers furthest outside this codebase. Any generator, codegen step, or model call has the same trap, where a matching return type disguises a mismatched contract.
- **6** hit twice inside a single PR and once on August 23, in both directions of the client and server relationship.

Entries **1** and **7** are deliberately not in this list, and the reason is itself a finding. Both recurred and both got more expensive, but the real fix for each is a config line sitting unapplied in the backlog. Prose already failed to hold them twice.

---

## Consolidated structural backlog

Each of these is enforced more reliably by a mechanism than by prose. Of the August 23 backlog, only the two items that needed no judgment were applied, both in commit `39f054a`: `.gitignore` `.venv/` became `.venv`, and the ESLint `globalIgnores` gained `playwright-report/**` and `test-results/**`. Every item needing a judgment call stayed unapplied and was re-paid two days later. Apply the mechanical ones in the same pass as the reflection; they are the only ones that survive to the next session.

| # | Item | Mechanism | Where |
|---|---|---|---|
| S1 | `.venv` points into another project's `/tmp` worktree on CPython 3.14 against a 3.11 image, and a checked-in config hardcodes it | Rebuild a real in-repo venv from `.python-version`; resolve the E2E server command from PATH or an env var | `.venv/`, `web-ui/playwright.config.ts:22-33` |
| S2 | No supported way to run one E2E test, and the suite keeps growing | Forward `...process.argv.slice(2)` in the `spawn` call | `web-ui/scripts/run-e2e.mjs:16` |
| S3 | No CI at all | A GitHub Actions workflow plus a required status check | `.github` (absent) |
| S4 | Both gate scopes are CLI arguments re-derived from memory, and the narrowed lint scope is unrecorded | `[tool.pytest.ini_options]` with `pythonpath` and `testpaths`; a Ruff scope or per-file baseline | `pyproject.toml` |
| S5 | The schema version is on the export envelope, not the persisted store, so migrations infer legacy shape from field emptiness and then rewrite the field they inferred from | Add `schema_version` to persisted state and key migrations on it | `src/agora/focused/service.py:3607-3611`, `:2175-2203` |
| S6 | A closed enum has two hand-maintained definitions, and both sides now gate finalization on the full set, so drift produces an unfinishable workflow | Generate the TS enum from the OpenAPI schema, or assert list equality in a test | `web-ui/src/types/focused.ts:1-8`, `src/agora/focused/models.py:16` |
| S7 | An unanswered "should this be split" question makes the file the default landing site. In two days `service.py` went 2600 to 3615 and `agents.py` 1546 to 1706; new UI work landed in a 2827-line `stage-deliberation.tsx` | Answer it, or attach a module line budget that fails | `src/agora/focused/`, `web-ui/src/features/focused/` |
| S8 | Runtime invariants live only in ephemeral digests | Create `AGENTS.md` covering the entrypoint invariant, verification commands, the 8011/3011 E2E port reservation and the 8012/3012 dev band | repo root (absent) |

**Carried forward, unapplied since August 23:** `tsconfig.json` exclude for `.next*`; the 21 accumulated `.next*` directories; `specter_v2` vectors crossing the wire on every mutation response (use `response_model_exclude` at the API layer, never `Field(exclude=True)`, because persistence serializes the same models); an OOM budget test replacing the module-name denylist; an entrypoint enforcement test; a health payload carrying commit and RSS; hermetic-backend contract tests; the full-snapshot replacement redesign, whose predicted failure mode recurred as entry 6; subagent cwd drift; and the two project skill updates.

---

## Dedup notes

- **Three lenses independently found the fixture-provenance lesson.** The judgment lens framed it as a gate definition, tooling as predecessor-shaped seeding, and divergent as the fixture inheriting the author's new invariant. All three are one lesson, merged into entry 4 as a refinement of the existing regression-test rule rather than a new entry.
- **Two findings covered stale client state from opposite directions.** Server responses dropping confirmed items (August 23) and client-held ids the server has invalidated (August 25) are the same relationship, so both live in entry 6. The August 25 half also carries the "prune at the derivation site" correction, which the original one-site fix does not satisfy.
- **Two findings covered contract widening.** "Migrate the caller" and "tests are a caller class that can reopen a contract" are one lesson, merged into entry 3.
- **The two gate-scope findings were split rather than merged.** Choosing the right lint and test scopes (entry 13) is a judgment call with no mechanism. Confirming a check ran (folded into entry 5) belongs with the other signal-interpretation defaults. Both have config companions in S3 and S4.
- **Rejected: "automated advisories contradicted tool output, so discount automated review."** The same session record shows the adversarial reviewer produced the two highest-value regressions. The distinguishing property of a finding is whether it names a reproducible path, not its origin.
- **Rejected: promoting "adjudicate advisories against live code" to its own entry.** It is the documented method of this process, and its transferable kernel is already in entry 4.
- **Rejected: "never add a temporary compatibility shim."** The absolute form is wrong; a shim is legitimate when both shapes can be correct. The conditional form is in entry 3.
- **Rejected: the `PYTHONPATH` masking caveat as a new lesson.** It is a verbatim restatement of entry 1's integrity caveat with a different test count attached.
- **Rejected: restating entries 1, 3, and 5 because they recurred.** Recurrence is an escalation signal. A finding whose thesis is that prose does not survive the next session cannot be discharged by adding prose; it became the framing note on the backlog above.
- **Nine of eleven August 25 lens findings routed to backlog were mechanical.** Venv rebuilding, E2E argv forwarding, CI, gate scope pinning, persistence schema versioning, enum codegen, module budgets, and repo memory are all edits, not judgment calls, so none of them earned a prose entry.

---

## Source provenance

| Union entry | Origin | August 25 lens sources | Relationship |
|---|---|---|---|
| 1 | Aug 23 A1 | tooling T8 | refined in place, hardcoded-path escalation |
| 2 | Aug 23 A2 | none | unchanged |
| 3 | Aug 23 A3 | judgment J3, tooling T2 | refined in place, tests as a caller class |
| 4 | Aug 23 A4 | judgment J5, tooling T1, divergent D3 | refined in place, three lenses merged |
| 5 | Aug 23 A5 | tooling T5 | refined in place, gate absence |
| 6 | Aug 23 A6 | judgment J6, divergent D7 | refined in place, two lenses merged |
| 7 | Aug 23 A7 | divergent D2 | unchanged, cost trend noted |
| 8 | Aug 25 | judgment J1 | new |
| 9 | Aug 25 | judgment J7 | new, precondition for 8 |
| 10 | Aug 25 | judgment J2 | new |
| 11 | Aug 25 | judgment J4 | new |
| 12 | Aug 25 | judgment J8 | new |
| 13 | Aug 25 | tooling T4 | new, answers an August 23 open follow-up |
| 14 | Aug 25 | tooling T6 | new |

**Counts.** 14 accepted: 3 unchanged from August 23, 4 refined in place, 7 new. 5 rejected. 8 structural backlog items, plus 10 carried forward unapplied.

**Verification.** Every August 25 code pointer was re-read in the working tree at `main = 984af54`. Nothing was edited, and no test, linter, or build ran. Two claims are attributed rather than reproduced: the 15 pre-existing whole-repo Ruff findings, and the applied state of the two August 23 backlog items in commit `39f054a`. Nothing here has been applied.
