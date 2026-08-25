# August 25 session learnings

**Scope.** What the August 25 Hypothesis Studio session taught. Drawn from three lenses over `local://aug25-session-digest.md`, settled against the working tree at `main = 984af54` (PR #15, "Redesign deliberation around a persistent lead").
The digest and lens artifacts are session-local and are not committed. This
document carries the complete Accepted, Rejected, Backlog, and adjudication
output.

**Verification.** I re-read every code pointer below. Nothing was edited, and no test, linter, or build ran. Two claims I could not reproduce read-only are attributed to their source rather than asserted: the 15 pre-existing whole-repo Ruff findings (session digest), and the applied state of August 23 backlog items B3 and B4 in commit `39f054a` (divergent lens, via `git log -p` and `git log -S`).

---

## Accepted (10)

Ten durable cross-project lessons, ordered strongest first. Each cost this session something real, and none is held more reliably by a config line.

### C1. Archive state written under a superseded invariant. Do not synthesize it, and do not retro-validate it

**Lesson.** When a redesign changes an invariant, already-persisted records admit three treatments and two of them are traps. Synthesizing the missing fields on load claims setup the user never performed and corrupts the audit record. Retro-validating deadlocks real records, because the old system wrote states that can never satisfy the new rule. Detect the legacy shape structurally and archive it at a boundary the user explicitly creates. Answer "can old data satisfy the new rule?" against records the old system actually wrote, never against a fixture you built to be satisfiable.

**Evidence.** `src/agora/focused/service.py:2654-2703`. `initialize_deliberation` keys legacy detection on `lead_perspective_id is None and baseline_hypothesis is None`, raises "The lead cannot change after round 1." for non-legacy rounds, and otherwise rebuilds the roster from `agent_iids` and calls `_restart_deliberation`. The branch runs only after the researcher selects a lead, so the migration is an action the user took, not something that happened to their data. Both dead ends are recorded in the digest under "Corrections and dead ends".

**Aug 23 relation.** New. A3 covers migrating callers; no accepted item covered migrating persisted data across an invariant change.

### C2. Store a stabilized role as an identity. Its null state becomes the migration detector

**Lesson.** The lead was previously derived client-side from a round index. Persisting it removes a fragile positional formula, but the larger payoff is that a stored nullable field makes "was a lead ever chosen?" answerable. A derived value cannot distinguish "never established" from "happened to compute to this", and that distinction is exactly what a later migration needs to identify records written under the old invariant. When a role, owner, or selection stabilizes, store its identity and let the null state carry the "not yet established" meaning.

**Evidence.** `src/agora/focused/models.py:304-355` declares `lead_perspective_id: str | None = None` on both the archived `DeliberationCompletion` and the live `DeliberationState`. `service.py:2654-2703` sets it, reads it to make re-initialization idempotent, and uses its null state as half the legacy predicate in C1.

**Aug 23 relation.** New. This is the domain-modeling precondition that made C1's migration boundary detectable at all, so the two belong adjacent.

### C3. When a caller cannot satisfy a new invariant, migrate the caller. Never widen the shipped contract

**Lesson.** A compatibility window is legitimate only when the old and new shapes can both be correct. When the old shape is invalid under the new domain rule, a shim is a second contradictory source of truth, and every future reader treats it as permission. Failing legacy tests are the migration's cost, not evidence the new constraint is too strict. Tests are a caller class with a specific hazard the others lack: they can push a contract back open, which inverts the gate so the suite starts defining the contract. The cheap check is to ask whether a value the shim admits could ever be right under the new rule. If not, the shim is the bug.

**Evidence.** A temporary change restored the 1-2 facet range in the service and API so existing tests would pass, contradicted the four-round four-facet process, and was removed (digest, "Corrections and dead ends"). The fixtures were migrated instead: initialize a lead, hold it fixed, resolve each pending proposal, cover all four areas. Both layers now hold the invariant independently. `src/agora/api/focused.py:129-148` pins `facets: list[Facet] = Field(min_length=1, max_length=1)` on `RoundRequest`; `src/agora/focused/service.py:2894-2913` rejects anything else with "Select exactly one area for this round." and validates membership against `FACETS`.

**Aug 23 relation.** Refines A3 (`.handoffs/2026-08-23-session-reflection.md:66-68`), which answers "who are the callers". This answers the next question, what to do when a caller resists, and adds tests to A3's caller list.

### C4. Build historical fixtures from what the predecessor actually wrote

**Lesson.** The full gate was green before the two highest-value regressions were found: 103 backend tests, changed-file Ruff, ESLint, `tsc --noEmit`, a Next production build, and 18 Playwright tests. An independent adversarial reviewer then produced two P1 findings, and both were invisible to the suite for one reason. The legacy fixtures were hand-built, so they encoded the author's post-change model of prior state rather than what the prior UI wrote. A hand-built legacy cycle has one consistent lead; the rotating-lead UI never produced one. A migration's acceptance gate is not "do my legacy fixtures pass" but "does a record the old system actually produced survive". A suite authored alongside a change cannot falsify that change's own assumptions about history, so green means nothing on exactly the axis a migration is risky.

**Evidence.** `src/agora/focused/service.py:2654-2703` contains the branch a happy-path hand-built fixture never reaches. The corrected fixture at `tests/test_focused_lineage.py:91-128` now encodes predecessor behavior, with `lead_iid=prior_iids[0]` on round 1 and `prior_iids[1]` on round 2, and two facets per round. Residual risk worth naming: that fixture still builds the cycle by direct attribute assignment, bypassing every service method, so it models prior behavior by hand and can drift from it again.

**Aug 23 relation.** Refines A4 (`:84-86`), which covers absence proofs and unfalsifiable denylists. Fixture provenance is the adjacent claim in the same skill: A4 says the assertion must be able to fail, and C4 says the fixture must be able to reach the branch where it would.

### C5. Scope a generator's input to the constraint plus the current value, not the source entity

**Lesson.** When the operation is "revise X under constraint C", the generator's inputs are C and X, never the object X was originally derived from. A matching output type is not evidence of a matching contract. It is the trap that makes the wrong reuse look correct.

**Evidence.** The first proposal implementation called `develop_hypothesis(revised)`, plausible because the return type was exactly right. That generator takes a whole `Perspective` (`src/agora/focused/agents.py:1475-1478`) and can rewrite unrelated non-empty fields the round never discussed. The shipped call at `src/agora/focused/service.py:3194-3218` is `agents.develop_hypothesis_from_consensus(consensus_resolution, current=deliberation.applied_hypothesis, ...)`, defined at `agents.py:1567-1572` with `current` keyword-only and documented as "Build a working hypothesis from supported shared ground only." Unchanged parts survive, and disagreement or unsettled content is excluded by construction rather than by prompt instruction. The broad form survives only for the initial baseline.

**Aug 23 relation.** New. Nothing in the accepted seven addresses generator or model input scoping.

### C6. An audit field answers one question at one layer. A later action gets its own record

**Lesson.** Before writing an existing audit field from a new code path, state in one sentence the question that field answers. If the new action answers a different question, it needs its own record. Field reuse driven by type compatibility is how provenance data quietly stops being evidence, and unlike a crash, nothing surfaces the loss.

**Evidence.** `DeliberationRound.hypothesis_decision` (`src/agora/focused/models.py:264-274`) records how the researcher resolved that round's pending proposal and nothing else. `src/agora/focused/service.py:3414-3463` shows `reject_pending` writing `"rejected"`, `apply_pending` writing `"accepted"` or `"edited"` by comparing the applied value against `latest_round.hypothesis_proposal`, and the `edit_applied` branch setting only `source_kind = "edit"`. A later manual edit to an already-resolved hypothesis is a different event at a different layer. Letting it write the same field would overwrite whether the round's proposal had been accepted or rejected, silently rewriting history that downstream study analysis treats as immutable.

**Aug 23 relation.** New. A6 covers concurrency staleness, not provenance, and audit semantics are absent from the accepted seven.

### C7. Prune a client-held identity set where it is derived, and re-intersect before submitting

**Lesson.** Any client selection set that outlives a refresh of the list it was chosen from must be reconciled with the currently rendered set. The diagnostic tell for this whole bug class is an error the UI offers no way to clear: look for state the user owns but can no longer address. Prune at the derivation or storage site, not at each consumer. A filter at one submit site is invisible to a reader of the state declaration and is exactly the hand-placed guard a refactor deletes silently.

**Evidence.** `web-ui/src/features/focused/stage-deliberation.tsx:1758-1780` seeds `selectedQuestionIds` from a lazy `useState` initializer over `deliberation.recommended_questions` that never re-derives, while the modal renders only `openQuestions`. When a selected question was archived it disappeared from the modal, so the user could neither see nor deselect the id, but it still shipped, and the server rejects ids whose status is not `open` with a 404. The fix at `:2231-2235` builds `openQuestionIds` from the rendered `openQuestions` and passes `selectedQuestionIds.filter((id) => openQuestionIds.has(id))` to `onEnd`; the browser test reproduces check, cancel, archive, reopen, and complete. The same shape appears twice in one PR: the missing-facet blank-editor fallback in C8 is the second instance.

**Aug 23 relation.** Refines A6 (`:125-127`). A6 keys response-merge staleness on domain identity. This is the mirror direction, client-held identities the server has since invalidated, and it completes A6's coverage of stale client state. It is also a direct recurrence of backlog B14, which predicted that correctness resting on hand-placed UI guards would break again.

### C8. Render an editable set from the canonical enum, and materialize missing entries as blanks

**Lesson.** When a server array is an instance of a closed contract, iterate the contract, not the instance. The array is data; the enum is the contract. If a UI iterates a server-supplied array to render editable controls, a partial array deletes the very control the user needs to fill the gap, while the server still rejects the incomplete record. The failure stays hidden until partial data exists, so it will not show up in the run where you chose the pattern.

**Evidence.** `web-ui/src/features/focused/stage-extraction.tsx:1029-1040` maps the canonical `FACETS` and falls through `edits[facet] ?? clusterFacets.get(facet) ?? { facet, text: "", ... }`; `stage-deliberation.tsx:2564-2566` does the same for agent facets; the canonical list is declared once at `web-ui/src/types/focused.ts:1-8`. Server-side, `src/agora/focused/service.py` materializes empty `FacetEvidence` for gaps and rejects a Perspective missing any of Scope, Explanation, Approach, or Significance.

**Aug 23 relation.** New. Its structural companion, the duplicated enum itself, goes to backlog.

### C9. Lint the changed surface, test the whole system, and confirm each gate ran

**Lesson.** Lint and test gates need opposite scopes. Lint carries pre-existing debt, so whole-repo lint on a feature branch produces findings the change did not cause and cannot gate on. Scope it to changed files. Tests assert a whole-system invariant, so scope them to everything. Separately, absence of a red signal is not a green one. Before treating a change as gated, confirm the check executed. A deploy preview reporting Ready is a build signal, not a test signal, and the two are easy to conflate because both render green.

**Evidence.** Whole-repo Ruff surfaced 15 unrelated pre-existing findings (digest); the valid gate was Ruff on changed Python files followed by the full 103-test suite. Neither scope is pinned: `pyproject.toml` has no `[tool.pytest.ini_options]` and no `[tool.ruff]` block, so both are re-derived from memory each session. On the signal half, no GitHub Actions workflow ran for PR #15, Vercel preview reported Ready, and production after the merge was not inspected. The repo has no `.github` directory at all, so a Vercel build was the only automated signal on a change carrying 103 backend tests, 18 Playwright tests, and a merge to `main`. The health handler still returns a bare `{"status": "ok"}` (`src/agora/api/focused.py:41-43`), so "which build is serving" stays unanswerable.

**Aug 23 relation.** The scope half is new, and it answers the August 23 open follow-up that recorded whether wider Ruff passes as unknown. It was run on August 25, and it does not pass. The signal half refines A5 (`:104-127` region), which covers misreading signals that did fire. This covers the prior step, establishing that a signal fired at all. Path filters, skipped jobs, and fork-PR restrictions produce the same silent absence of red in repos that do have CI.

### C10. One response is authoritative. Progress reporting is advisory, and assertions belong on the authority

**Lesson.** Adding a second transport for progress creates a second source of truth, and tests drift toward asserting on the cheap observable instead of the real one. Exactly one terminal response should be authoritative, and that is what assertions must target.

**Evidence.** The session reused the existing generation and cursor progress channel instead of adding SSE, keeping the final round response authoritative (digest decision 8). Confirmed live: both polling sites in `web-ui/src/hooks/use-focused.ts:246-259` and `:431-444` use the same `search-progress?generation=...&after=<cursor>` protocol, and the hook contains no `EventSource` and no `text/event-stream`.

**Aug 23 relation.** Adjacent to A4. A4's OOM guard passed because a `demo: True` short circuit meant the assertion never reached the real path. A parallel progress channel is the same failure shape at the UI layer: it can report motion the authoritative response never confirms.

---

## Rejected (5)

| # | Tempting claim | Source | Why rejected |
|---|---|---|---|
| R1 | Automated advisories contradicted tool output, so discount automated review. | Digest "Corrections and dead ends"; divergent D8 | Contradicted by the same document. The adversarial reviewer produced the two highest-value regressions of the session, real historical lead rotation and stale selected-question ids. The distinguishing property of a finding is whether it names a reproducible path, not its origin. |
| R2 | Promote "adjudicate conflicting advisories against live code and the domain invariant, not by recency" to an accepted lesson. | Tooling T3 | Already the operating method of this process, stated and exercised. `.handoffs/2026-08-23-session-reflection.md:225-227` opens "Three places where the lenses disagreed. Each was settled against the live repo, not by majority", and that pass overturned its own judgment lens on the OOM regression test. The transferable kernel, that an advisory is a hypothesis about code rather than an observation of it, is carried by A4's "check the assertion can fail". |
| R3 | Never add a temporary compatibility shim. | Divergent D9 | The absolute form is wrong. A shim is legitimate when both shapes can be correct. The correct conditional form is accepted as C3, and the general rule already lives in A3's home skill. Adding the absolute form would put one lesson in a third place. |
| R4 | `PYTHONPATH` masks first-party resolution while third-party packages stay wrong. | Tooling T10; digest "Tooling and review evidence" | Verbatim restatement of A1's integrity caveat, which already reads that `PYTHONPATH` repairs first-party `agora.*` resolution only and that third-party packages come from another project's dependency closure. August 25 changes only the number the caveat applies to, from `60 passed` to `103 passed`. Its actionable half is the venv rebuild, already in backlog. |
| R5 | Restate A1, A3, and A5 as new August 25 lessons because they recurred. | Judgment J9; divergent D1 | Recurrence is an escalation signal, not new content. Restating prose that already failed to change behavior is the bloat this pass exists to prevent. Routed to the backlog framing note below, which is where it does work. |

---

## Backlog, structurally enforceable (8)

**Framing.** Of the August 23 backlog, only the two items that needed no judgment were applied, both in commit `39f054a` (divergent lens, verified by `git log -p` and `git log -S`): B3 changed `.gitignore` `.venv/` to `.venv`, and B4 added `playwright-report/**` and `test-results/**` to the ESLint `globalIgnores`. Every item requiring a judgment call stayed unapplied and was re-paid on August 25, then re-discovered as if new. A reflection backlog is a cost forecast, not an archive. Apply the pure mechanical items in the same pass; they are the only ones that survive contact with the next session.

| # | Item | Mechanism | Where | Status |
|---|---|---|---|---|
| S1 | `.venv` resolves to `/private/tmp/agent-agora-github-review/.venv`, and a checked-in config hardcodes that path, so the defect is no longer routable around. This session built `/tmp/hypothesis-studio-venv` for pytest and still had to plant a `uvicorn` symlink inside the foreign venv to satisfy Playwright, deepening the dependency it meant to escape and mutating another project's tree. | Rebuild a real in-repo venv from `.python-version`, and resolve the E2E server command from PATH or an env var. | `.venv/`, `web-ui/playwright.config.ts:22-33` (verified: `${repositoryRoot}/.venv/bin/uvicorn`) | Aug 23 B2, unapplied, cost grew |
| S2 | No supported way to run one E2E test. The safe wrapper cannot forward grep arguments, so targeted runs use raw Playwright, which mutates tracked `next-env.d.ts` and `tsconfig.json` and skips the wrapper's restoring `finally`. Cost is not constant: the suite grew from 14 tests to 18 in two days, and `workers: 1`, `retries: 0`, `forbidOnly: true` leave no in-file escape hatch. | Forward `...process.argv.slice(2)` in the `spawn` call. | `web-ui/scripts/run-e2e.mjs:16` (verified: `spawn(command, ["exec", "playwright", "test"], ...)`) | Aug 23 B6, unapplied, cost grew |
| S3 | No CI. A merge to `main` carrying 103 backend and 18 Playwright tests had a Vercel build as its only automated signal. | Add a GitHub Actions workflow plus a required status check. | `.github` (verified absent) | New, C9 companion |
| S4 | Both gate scopes are CLI arguments re-derived from memory each session, and the narrowed lint scope is unrecorded. | `[tool.pytest.ini_options]` with `pythonpath = ["src"]` and `testpaths = ["tests"]`; a Ruff scope or per-file baseline. | `pyproject.toml` (verified: no `[tool.pytest.ini_options]`, no `[tool.ruff]`) | Aug 23 B1 plus C9 companion |
| S5 | The schema version lives on the export envelope, not on the store that gets migrated. Migrations infer legacy shape from field emptiness, then rewrite the field they inferred from, so the discriminator and the payload are the same data. Correctness depends on the pass completing atomically, and the next schema change must invent another emptiness heuristic. | Add `schema_version` to persisted `SessionState`/`WorkspaceState` and key migrations on it. | `src/agora/focused/service.py:3607-3611` (verified: `"schema_version": 5`, the only occurrence in `src/agora`), `:2175-2203` (`_materialize_completion_history` detects `completion.round_count > 0 and not completion.rounds`, then rewrites `completion.round_count`) | New |
| S6 | A closed enumeration has two hand-maintained definitions across a process boundary, and PR #15 made both sides gate finalization on the full set. Drift now means the client renders and requires four editors while the server refuses to finalize. | Generate the TS enum from the OpenAPI schema, or add a test asserting list equality across both files. | `web-ui/src/types/focused.ts:1-8` and `src/agora/focused/models.py:16` (verified identical today; no generator exists) | Refines Aug 23 B18, stake raised |
| S7 | The August 23 open question "is the focused service still one coherent unit" was left unanswered, which granted the file default-landing-site status. In two days `service.py` went from 2600 to 3615 lines and `agents.py` from 1546 to 1706, and the session's new UI work landed in a single 2827-line `stage-deliberation.tsx`. Leaving a scope question open is not neutral: the split cost grows fastest while the decision is pending. | Answer it, or attach a module line budget that fails. | `src/agora/focused/service.py`, `agents.py`, `web-ui/src/features/focused/stage-deliberation.tsx` (line counts verified) | Aug 23 follow-up, now measured |
| S8 | Runtime invariants live only in ephemeral digests. No repo memory file exists, so each session re-derives the entrypoint invariant, verification commands, and port reservations. | Create `AGENTS.md` at the repo root. Include the 8011/3011 E2E reservation and the 8012/3012 dev band, since `reuseExistingServer: false` turns any stray listener into a startup failure rather than a test failure. | repo root (verified absent); `web-ui/playwright.config.ts:22-42` | Aug 23 B9, unapplied |

**Still unapplied from August 23, unchanged by this session:** B5 (`tsconfig.json` exclude), B7 (`.next*` directories, now 21), B8 (`specter_v2` vectors on every mutation response), B10 (OOM budget test), B11 (entrypoint enforcement test), B12 (health payload carrying commit and RSS, verified still bare at `src/agora/api/focused.py:41-43`), B13 (hermetic backend contract tests), B14 (full-snapshot replacement, whose predicted failure mode recurred as C7), B15 and B16 (project skills), B17 (subagent cwd drift).

---

## Cross-lens contradictions adjudicated (4)

1. **Is "adjudicate advisories against live code" a new lesson?** Tooling accepted it as T3; judgment rejected it as already-covered. **Judgment is correct.** The August 23 document practices it in a named section and commits every material claim to a read-only recheck. Promoting it would add a second copy of what the pipeline already enforces. Recorded as R2.

2. **Is the recurrence of A1, A3, and A5 a lesson or an escalation?** Divergent accepted D1 as prose; judgment classified the same recurrence as backlog. **Judgment is correct, and D1's own content is the argument.** A finding whose thesis is that prose lessons do not survive the next session cannot be discharged by adding prose. Its kernel now frames the backlog section, and its concrete instruction, ship the mechanism, is S1 through S8.

3. **Are the shipped lineage fixtures provenance-safe?** Tooling T1 said the tests now encode predecessor state; divergent D3 said they are still hand-built by direct attribute assignment and therefore still import the author's model. **Both are right about different things, settled by reading `tests/test_focused_lineage.py:91-128`.** The fixture does now encode rotating leads and two facets per round, which is what the old UI produced, so the specific gap is closed. It also still bypasses every service method, so the construction mechanism can drift again. C4 states the lesson about the behavior modeled and keeps D3's warning as a named residual risk.

4. **"Migrate fixtures, never widen the contract" versus "never add a compatibility shim".** Tooling T2 accepted the first; divergent D9 proposed the second and rejected it itself. **They are not the same claim.** The conditional form is accepted as C3, keyed on whether a value the shim admits could ever be right under the new rule. The absolute form is rejected as R3.

---

## Summary

This session's lessons cluster in two places. The first is what to do when new code meets old state, which is C1, C2, C3, and C4, and it is where the session lost the most time: two failed migration designs, a compatibility shim that had to be backed out, and two P1 regressions that a fully green five-gate suite could not see. The second is what counts as evidence, which is C4, C9, and C10.

The uncomfortable result is C4 and C9 read together. Every gate passed, and the gates were not the thing that found the bugs. What found them was an outside reviewer modeling what the previous release actually wrote. That is not an argument against the gates. It is an argument that a suite authored alongside a change is structurally unable to falsify that change's own assumptions about history, which is precisely the axis a migration is risky on.

| | Count |
|---|---|
| Accepted | 10 |
| Rejected | 5 |
| Backlog | 8, plus 10 carried forward unapplied from August 23 |

Nothing has been applied.
