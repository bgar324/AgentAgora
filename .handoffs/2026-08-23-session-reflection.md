# Reflect — Hypothesis Studio session

**Sources.** `local://judgment-lens.md` (12 findings), `local://tooling-lens.md` (11), `local://divergent-lens.md` (11), adjudicated by `local://handoff-corrections.md`.

The `local://` source artifacts are session-local and are not committed. This
document carries the complete synthesized Accepted, Rejected, and Backlog output
needed for approval; the companion handoff carries project facts.

**Verification.** Every material claim below was re-checked read-only against
the code baseline `/Users/bg/windsurf/hypothesis-studio` at `main` = `09dd11f`,
and against the installed skills in `/Users/bg/.omp/agent/managed-skills/`.
Nothing was edited. No tests, builds, or linters were run by the synthesizer.

**Confirmed by direct read:** HEAD `09dd11f`; commit chain `3302c96` / `da5407f` / `5e16e99` / `575c45d` / `e32100d`; 60 backend tests (21+8+20+1+3+2+5 across `tests/*.py`); `Dockerfile:16` `uvicorn agora.focused_app:app`; `README.md:80` `.venv/bin/fastapi dev src/agora/app.py`; `.venv -> /tmp/agent-agora-github-review/.venv` with `git check-ignore` returning NOT IGNORED and `git status --porcelain` returning `?? .venv`; `.gitignore:10` `.venv/`; `railway.toml` `restartPolicyType = "ON_FAILURE"`, `restartPolicyMaxRetries = 3`, `healthcheckPath = "/api/v1/focused/health"`; `web-ui/playwright.config.ts` `forbidOnly: true`, `workers: 1`, `retries: 0`, `NEXT_DIST_DIR: ".next-e2e"`; `web-ui/scripts/run-e2e.mjs` `spawn(command, ["exec", "playwright", "test"], ...)` with no argv forwarding; `web-ui/eslint.config.mjs` `globalIgnores([".next/**", ".next-*/**", "out/**", ...])`; `web-ui/tsconfig.json` `"exclude": ["node_modules"]`; 20 `.next*` directories totalling 1.1 GB; `tests/test_standalone_api.py` in full; `web-ui/src/store/focused.ts:59-99`; `web-ui/src/hooks/use-focused.ts:82-99`.

---

## Accepted (7)

Each item is a durable cross-project lesson, is not already covered by the target skill, and is not more reliably enforced by a mechanism. Items are ordered strongest first; **A7 is the one to trim** if you want a shorter list.

---

### A1 — A compensating prefix means the environment is the bug

**Durable lesson.** When a command only works with an extra prefix or environment variable, that prefix is the symptom, not the fix. Inspect what the path actually is before promoting the workaround into documentation or a handoff. A command that references `/tmp`, another repository, or a symlink has an expiry date the next reader cannot see.

**Evidence.**
- `.venv` is a **symlink** to `/tmp/agent-agora-github-review/.venv` — a different project's scratch worktree (`ls -ld .venv`, verified).
- The mandatory `PYTHONPATH=/Users/bg/windsurf/hypothesis-studio/src` prefix on every documented Python command exists only to shadow that foreign editable install. Tooling lens F1 read `_editable_impl_agora.pth` → `/private/tmp/agent-agora-github-review/src` and `.venv/bin/pytest` shebang → `#!/private/tmp/agent-agora-github-review/.venv/bin/python`.
- Blast radius is wider than the prefix suggests: `web-ui/playwright.config.ts` resolves uvicorn through the same symlink, so the 14-test E2E suite — the primary proof surface for every UI fix this session — shares the dependency. A macOS `/tmp` sweep breaks both `pytest` and `pnpm test:e2e`.
- Integrity caveat neither the digest nor the judgment lens stated fully: `PYTHONPATH` repairs first-party `agora.*` resolution only. The interpreter is CPython 3.14 (bytecode tags `focused_app.cpython-314.pyc`) while `.python-version` and `Dockerfile:1` are 3.11, and third-party packages come from another project's dependency closure. The reported `60 passed` was validated against a foreign environment.
- Source: judgment J1, tooling F1, divergent F5/F10.

**Routing.** `principle-fix-root-causes`

**Proposed edit.** Append one bullet to the existing **Pattern** list, after `When stuck, instrument. Don't guess (add logging, read the actual error)`:

> - If a command only works with an extra prefix or env var (`PYTHONPATH=`, a hardcoded absolute path, a symlinked venv), the environment is the bug, not the command. Run `ls -ld` / `readlink` on the path before standardizing the workaround, and prefer the project's own documented setup step. A workaround that names `/tmp`, another repository, or a symlink expires silently.

---

### A2 — For memory incidents, suspect the import graph before the request path

**Durable lesson.** Code that never executes still costs resident memory if it is imported at startup. Measure `import <entrypoint>` RSS in a **separate process** for each candidate entrypoint before optimizing anything the request path does. If the delta is most of the container limit, the fix is what gets imported, not what runs.

**Evidence.**
- Separate-process RSS comparison: `import agora.app` ≈ 779.6 MB vs the focused import ≈ 103.4 MB (digest, cited by judgment J3 and tooling). That measurement is what made the entrypoint the answer instead of a request-path optimization.
- The resulting fix, `e32100d`, is a 3-file diff that moved production to `agora.focused_app:app` (`Dockerfile:16`, verified).
- Corroborated by the shape of the two apps: `src/agora/app.py` mounts the legacy router stack; `src/agora/focused_app.py` mounts only `focused_router`. I verified `src/agora/focused/` contains no `from agora.research`, no `import bertopic`, and no top-level `import torch`.
- Per `local://handoff-corrections.md`: import-only RSS ≈ 103 MB, focused + sklearn ≈ 243 MB locally, legacy ≈ 780 MB; current production on `09dd11f` sits at 191.72 MB (18.7% of 1024 MB) over a clean five-minute window.
- Source: judgment J3, tooling "commands worth preserving".

**Routing.** `principle-fix-root-causes`

**Proposed edit.** Add a new bolded subsection immediately after the existing **Restart bugs: suspect state before code** paragraph, matching that section's form:

> **Memory and OOM bugs: suspect the import graph before the request path**
>
> Code that never runs still costs resident memory if it is imported at startup. Before optimizing what a request does, measure what the process loads: run `import <entrypoint>` in a separate process per candidate entrypoint and compare RSS. In-process measurement is contaminated by whatever the harness already imported. If one entrypoint's baseline is most of the container limit, the fix is the import graph, not the hot path.

**Note.** A1 and A2 both land in `principle-fix-root-causes` but in different sections, and neither overlaps the existing bullets (nil-check guards, workaround comments, grep for the pattern, instrument when stuck).

---

### A3 — Docs, dev scripts, and CI are callers too

**Durable lesson.** An entrypoint or process-boundary change is not finished when the deploy config flips. After introducing a new entrypoint, port, start command, or env var, grep the **old** name across README, docs, CI, and dev scripts. If it still appears in a runnable command block, the migration wave is unfinished — and local dev now boots a different process than production, which is the mechanism by which a production-only failure gets reintroduced.

**Evidence.**
- `Dockerfile:16` → `uvicorn agora.focused_app:app`. `README.md:80` → `.venv/bin/fastapi dev src/agora/app.py --port 8000`. Both verified by direct grep.
- A grep for `focused_app` across `README.md` returned **no matches**. The new production entrypoint is undocumented; the legacy one — the exact app the OOM incident was about — is the only one documented.
- The stated invariant ("production must not import `agora.app`") is contradicted by the repo's own setup instructions. A fresh contributor following the README reproduces the incident's precondition locally.
- Source: judgment J2 (primary) and J9, divergent F4.

**Routing.** `principle-migrate-callers-then-delete-legacy-apis`

**Proposed edit.** Append one bullet to the existing **Rule** list, after `Inventory callers, migrate them, and delete the old API immediately`:

> - Callers include documentation, deploy configs, CI, and dev scripts, not just imports. After changing an entrypoint, start command, port, or env var, grep the old name across README, docs, CI, and dev scripts. If it survives in any runnable command block, the wave is unfinished — and local dev now boots a different process than production.

---

### A4 — A regression test must execute the branch that failed, and a name denylist cannot express a budget

**Durable lesson.** Two parts. First, proving an *absence* ("module X is never loaded") requires a fresh subprocess; an in-process assertion is contaminated by the test harness. Second, and more important: if the invariant you actually hold is a **budget**, a module-name denylist is unfalsifiable on the path that matters, because the real path is allowed to load that module by design. State the invariant you hold, then pick an assertion that can fail on the path that broke.

**Evidence — this is the item where two lenses disagreed and the repo settled it.**
- `tests/test_standalone_api.py`, read in full: `test_focused_app_does_not_load_legacy_ml_stack` runs a subprocess asserting `torch`/`sklearn` absent after `import agora.focused_app` — **cold import only**, correctly shaped for an absence proof.
- `test_focused_condition_is_runnable_from_standalone_app` uses `TestClient(app)` — **in-process** — posts `{"demo": True}`, and asserts only `"torch" not in sys.modules`. The judgment lens (J6) described this as "asserted after exercising the lazy path." It is not: the demo branch short-circuits at `service.py:1301-1302` and `:1552-1554`, so `_embedding_clusters` and the lazy `sklearn` imports at `service.py:1333/1385/1391` are never reached.
- `local://handoff-corrections.md` confirms: "it does not exercise `_embedding_clusters` or enforce a numeric memory budget. Do not overstate it."
- Why the assertion cannot simply be strengthened: `sklearn` is legitimately loaded on the live path, so `assert "sklearn" not in sys.modules` after a real search would correctly fail. The denylist is unfalsifiable exactly where the failure lives. Divergent F3 also notes `src/agora/research/model.py` imports `bertopic`/`sklearn` at module top level, so one added import reintroduces the stack with nothing in the suite to catch it.
- Source: divergent F3 (correct), judgment J6 (overstated), divergent F9.

**Routing.** `principle-prove-it-works`

**Proposed edit.** Add a short paragraph at the end of the existing **## Script the check when you can** section:

> **Prove the absence in a subprocess, and check the assertion can fail.** Proving something never happens (a module is not imported, a dependency is not pulled in, an endpoint is not reachable) needs a fresh subprocess; an in-process assertion is contaminated by the harness. Then ask what invariant you actually hold. If it is a budget, a name denylist cannot express it — the real path is usually allowed to load the thing you banned, so the guard passes on the demo path and is silent on the one that broke. A regression test that does not execute the branch that failed is a placeholder; say so rather than letting it stand in.

---

### A5 — On multi-provider deploys, green on the fast provider proves nothing about the slow one

**Durable lesson.** Three verification defaults for split deployments. Readiness is the slowest component, not the first green check — wait for the backend's startup line before exercising a frontend mutation. During a rollout, any per-container resource gauge sums the draining and incoming containers, so take the steady-state reading after drain **and** after a real request. Where a restart policy is configured, a passing healthcheck is not evidence the crash is gone; check for the absence of the kill line.

**Evidence.**
- `railway.toml`, verified: `healthcheckPath = "/api/v1/focused/health"`, `healthcheckTimeout = 30`, `restartPolicyType = "ON_FAILURE"`, `restartPolicyMaxRetries = 3`. A repeat OOM presents as a service that recovers — green health, no user-visible error. Only the absence of a `Killed` line distinguishes "fixed" from "still crashing but restarting fast enough."
- The health handler returns a bare `{"status": "ok"}` (`src/agora/api/focused.py:39-41`, per divergent F11 and tooling F9) — it carries no commit SHA and no process information, so it cannot answer which build is serving.
- Digest, preserved by both lenses: Vercel production becomes ready before Railway; memory metrics briefly summed containers to 1911 MB during overlap, against a steady state of 286.19 MB (27.9%) after drain and a real 20-paper search. Reading the transient as steady state, or the steady state at idle, both give the wrong answer.
- Source: judgment J11, tooling F8/F9.

**Routing.** `principle-prove-it-works`

**Proposed edit.** Append three bullets to the existing **Check the real thing, not a proxy:** list:

> - On multi-service or multi-provider deploys, readiness is the slowest component, not the first green check. Wait for the slow side's startup line before exercising the fast side.
> - During a rollout, resource gauges may sum draining and incoming instances. A transient over-limit reading is not steady state — measure after drain and after a real request, not at idle.
> - Where a restart policy is configured, a green healthcheck is not evidence a crash is fixed. It is evidence the process restarted fast enough. Check for the absence of the kill.

**Note.** A4 and A5 both land in `principle-prove-it-works`, in different sections. Combined they add roughly 120 words to a 350-word skill; if that feels heavy, A5's three bullets are the more broadly applicable half.

---

### A6 — Exempt the one independent action; key staleness on domain identity, not a revision counter

**Durable lesson.** When one action must run concurrently inside an otherwise serialized system, exempt that single action rather than relaxing the lock, and give it an explicit merge rule (preserve pending work, reject responses that drop already-confirmed items). Key the staleness test on **domain identity** — the item's natural key — not on a server revision counter. Hermetic and stub backends routinely pin such counters, so a revision-only guard passes locally and fails in exactly one environment.

**Evidence.**
- `web-ui/src/hooks/use-focused.ts:82-84` states the scope of the exemption in a docstring: "Most mutations are exclusive. Perspective generation may run concurrently; its response merge preserves pending work and rejects older add snapshots." `exclusive()` at `:99-101` still throws for everything else. The lock was not relaxed globally.
- `web-ui/src/store/focused.ts:59-99`, read line by line: the monotonicity test builds `representedOrigins` from `view.active.perspectives.map(p => p.origin)` and rejects a response missing an already-confirmed non-optimistic `origin`; `revision` is used only for the coarse same-workspace check at `:65-71`; pending `optimistic:` cards absent from the response are re-appended.
- The corrective detail is the transferable part: the first guard relied on server revision, and the hermetic backend holds revision 0 (digest; divergent F9 makes the general point that the test double *caused* a bug rather than catching one).
- Source: judgment J5, divergent F9.

**Routing.** `principle-separate-before-serializing-shared-state`

**Proposed edit.** Add a step 4 to the existing **Pattern** numbered list:

> 4. **When one action must run concurrently inside an already-serialized system, exempt that action — do not relax the lock.** Give the exempt action its own merge rule: preserve pending local work, and reject a response that drops an already-confirmed item. Key that staleness test on domain identity (the item's natural key), not on a server revision counter. Stub and hermetic backends often pin such counters at a constant, so a revision-only guard passes every local test and fails only in production.

---

### A7 — A wrapper that swallows arguments gets bypassed, and the bypass is the unsafe path *(weakest; trim first)*

**Durable lesson.** When you wrap a tool to add a safety guarantee, forward the tool's arguments. A wrapper that cannot be narrowed forces anyone iterating to call the raw tool directly — which is precisely the invocation the wrapper existed to make safe. A half-built lever is worse than none, because it creates a safe path nobody can use during the work and an unsafe path everybody uses.

**Evidence.**
- `web-ui/scripts/run-e2e.mjs`: `spawn(command, ["exec", "playwright", "test"], {...})` — verified, no `...process.argv.slice(2)`. `pnpm test:e2e -g "..."` silently runs the whole suite.
- `web-ui/playwright.config.ts`: `forbidOnly: true`, `workers: 1`, `retries: 0` (verified) — `test.only` is banned by config and the suite is serial, so there is no in-file escape hatch either.
- The only way to run one of the 14 tests is `pnpm exec playwright test <file> -g <name>`, which bypasses the wrapper's `finally` block that restores tracked `next-env.d.ts` and `tsconfig.json` (`run-e2e.mjs:22`, verified). The safety guarantee is lost at exactly the moment of iteration.
- Source: tooling F3.

**Routing.** `principle-build-the-lever`

**Proposed edit.** Append one bullet to the existing **Pattern** list, after `Make the lever safe to rerun. A reviewer will.`:

> - If the lever wraps a tool, forward the tool's arguments. A wrapper that cannot be narrowed to one case forces everyone iterating onto the raw command — which is the exact invocation the wrapper existed to make safe. Check that the safe path is usable during the work, not only at the end of it.

---

## Rejected (9)

| # | Tempting finding | Source | Why rejected |
|---|---|---|---|
| R1 | "A 'prefer command A, and if you use B, clean up X' note means X is un-ignored — add the ignore rule, then delete the note." Proposed for `principle-encode-lessons-in-structure`. | J7, tooling F2, divergent F7 | **Already covered.** That skill's **Corollary** already reads "Don't paper over symptoms. If the fix is structural, ONLY use the structural fix. The instruction IS the symptom." This is an instance of the existing rule, not a new one. The three concrete config fixes are real → **Backlog B3, B4, B6.** |
| R2 | "Apply blast-radius when a small diff changes a process boundary (entrypoint, port, env var, build step)." Proposed for `blast-radius`. | J9 | **Duplicate of A3.** Same underlying lesson, better homed in `principle-migrate-callers-then-delete-legacy-apis`, which owns "who are the callers." Two skills carrying one lesson is the bloat this pass exists to avoid. J9 itself rates the counterfactual Medium confidence. |
| R3 | "Split a control that carries both navigation and mutation semantics; guard only the mutation." Proposed for `principle-model-the-domain`. | J4 | **No well-fitting home, single occurrence.** `principle-model-the-domain` is explicitly scoped to data structures (state machines, typed objects, registries, reducers); `principle-experience-first` (read) is scoped to feature count and polish. Forcing a control-semantics lesson into either dilutes it. Per `principle-encode-lessons-in-structure`'s own routing, a one-off is a note, not a skill edit. **Top re-promotion candidate if it recurs.** The instance is correctly persisted in `web-ui/src/features/focused/DESIGN.md:44-48` and locked by an E2E test. |
| R4 | "If the repo has a design doc but no `AGENTS.md`, create `AGENTS.md` for runtime invariants rather than appending them to the design doc." Proposed for `remember`. | J8 | **Mostly covered, and the real fix is a file.** `remember` step 2 already routes cross-cutting patterns to the root memory file and step 3 says read the target first. The actionable half is creating the missing file → **Backlog B9.** |
| R5 | "Scope expansion is legitimate when a live user report or production signal produced it; illegitimate when an adjacent idea did." Proposed for `principle-outcome-oriented-execution`. | J10 | **Poor fit and weak evidence.** That skill is scoped to planned rewrites with explicit phase boundaries; scope-legitimacy is a different topic. J10 rates itself Medium and concedes "whether it was re-contracted with the user is not observable from the digest or repo." |
| R6 | "Explicit paths defeat gitignore filtering in search; allowlist search roots in repos with vendored venvs or many build dirs." Proposed for `principle-guard-the-context-window`. | Tooling F7 | **Harness-tool behavior that will rot,** and the durable half is better solved at source. Removing the 1.1 GB of stale build output and relocating the venv (**Backlog B2, B5, B7**) shrinks the accidental search surface permanently, rather than asking every future reader to remember a tool quirk. |
| R7 | "Context pressure is a sensor for response-shape defects — check whether an oversized payload is also wrong for the product." Proposed for `principle-guard-the-context-window`. | Divergent F1 | **Real insight, but the skill already says "Don't read what you won't use" and "Isolate large payloads."** The genuinely new claim is a project defect (`specter_v2` vectors crossing the wire to a client whose type does not declare the field) → **Backlog B8**, which is where the value is. |
| R8 | Add `metrics --memory --since 5m --json`, the explicit `-p/-s/-e` UUID form over `link`, the Vercel-before-Railway gate, and the `agora.focused_app:app` invariant to `hypothesis-studio-deployment`; point `agent-agora-tmux-dev` at the `pnpm test:e2e` wrapper. | Tooling F4, F8, F9 | **Project-scoped, not cross-project.** Both are project skills, so these are not durable global lessons. Correct and worth doing → **Backlog B15, B16.** The generalizable half of F9 is already Accepted as **A5**. |
| R9 | Provider query-tuning rules (2–6 term academic phrases, preserve acronyms and hyphen-number compounds); zero-paper search must raise before `_save_state`; cap `OMP/OPENBLAS/MKL_NUM_THREADS` at 1; explicit-Chrome-path `--headless=new` spawn; workspace and Railway UUIDs; specific memory figures. | J-rejects 1–6, tooling rejects | **Project-specific by construction.** Per the batch constraint, these stay in the handoff and project follow-ups. The `_save_state` ordering rule's generalizable kernel (validate before you commit) is already covered by `principle-boundary-discipline`. The Chrome-path invocation is harness- and version-specific and will rot. |

---

## Backlog — structurally enforceable (18)

Moved out of Accepted per Reflect step 4: each is enforced more reliably by a mechanism than by prose. Grouped by owner.

### Repository config — one-line or few-line fixes

| # | Item | Stronger mechanism | Where | Source |
|---|---|---|---|---|
| B1 | The `PYTHONPATH=` ritual on every Python command | `[tool.pytest.ini_options]` with `pythonpath = ["src"]`, `testpaths = ["tests"]` — pytest then resolves from any cwd with no env var to forget | `pyproject.toml` (verified: no `[tool.pytest.ini_options]` block exists) | Tooling F1 |
| B2 | `.venv` is a symlink into another project's `/tmp` worktree, on CPython 3.14 against a 3.11 production image | Rebuild a real in-repo venv from `.python-version` — resolves the foreign dependency closure, the interpreter skew, and the `/tmp` purge risk at once | `.venv/` | Tooling F1, divergent F5/F10 |
| B3 | `.venv` shows as untracked despite being named in `.gitignore` | Change `.venv/` → `.venv`. A trailing slash matches directories only, and git classifies a symlink as a file. **Verified:** `git check-ignore -v .venv` → NOT IGNORED; `git status --porcelain` → `?? .venv` | `.gitignore:10` | Divergent F5, J7 |
| B4 | ESLint walks Playwright output because flat config does not consult `.gitignore` | Add `"playwright-report/**"` and `"test-results/**"` to the existing `globalIgnores` array | `web-ui/eslint.config.mjs:8` | Tooling F2, divergent F7, J7 |
| B5 | 63 of 80 files in the typecheck scope are generated residue | Add `.next*` to `exclude`; the explicit `.next/types/**` and `.next/dev/types/**` include entries still bring in what Next needs. **Verified:** `"exclude": ["node_modules"]` only, and an explicit `exclude` replaces TypeScript's defaults | `web-ui/tsconfig.json:38-40` | Tooling F5 |
| B6 | No supported way to run one E2E test (A7's repo half) | Forward `...process.argv.slice(2)` in the wrapper's `spawn` call | `web-ui/scripts/run-e2e.mjs:16` | Tooling F3 |
| B7 | 20 `.next*` directories, **1.1 GB, measured** — one permanent name minted per verification pass | Nest verification builds under one reclaimable parent (`NEXT_DIST_DIR=.next-tmp/<label>`) so a single ignore rule and one `rm -rf` reclaim all of it; or reuse one `.next-verify` label | convention + `.gitignore` | Divergent F6, tooling F5 |

### Application code and tests

| # | Item | Stronger mechanism | Where | Source |
|---|---|---|---|---|
| B8 | Every SPECTERv2 vector crosses the wire on every mutation response to a client that never declares the field | `response_model_exclude={"active": {"papers": {"__all__": {"specter_v2"}}}}` on the API layer. **Do not use `Field(exclude=True)`** — `persistence.py` serializes the same models via `model_dump_json()`, so a model-level exclude silently drops vectors from storage and degrades re-clustering to the TF-IDF fallback. `local://handoff-corrections.md` states the same constraint independently | `src/agora/api/focused.py`, ~25 `-> WorkspaceView` endpoints | Divergent F1, tooling F6 |
| B9 | Runtime invariants live only in a code comment and an ephemeral digest; no repo memory file exists | Create `AGENTS.md` at the repo root covering the `agora.focused_app:app` entrypoint invariant, canonical ports, verification commands, the pending-Perspective guards, and the pre-`_save_state` error ordering | repo root (absent) | J8, tooling F1 |
| B10 | The OOM guard cannot fail on the path that caused the OOM (A4's repo half) | A subprocess test that runs a live-shaped clustering call and asserts peak RSS under a threshold plus a heavy-module allowlist, replacing `assert "torch" not in sys.modules` | `tests/test_standalone_api.py` | Divergent F3 |
| B11 | The production entrypoint is enforced by one Dockerfile string | A test that parses the Dockerfile `CMD` and asserts it targets `focused_app`, or a startup assertion in `focused_app.py` that fails fast if `agora.api.router` is in `sys.modules` | `Dockerfile:16`, `src/agora/focused_app.py` | Divergent F4 |
| B12 | Deploy ordering is a manual cross-reference because the health endpoint cannot answer which build is serving | Return `{"status", "commit", "rss_mb", "heavy_modules"}` from the existing handler. Collapses A5's manual ritual into one request and would have made the OOM diagnosis a single call | `src/agora/api/focused.py:39-41` | Divergent F11, tooling F9 |
| B13 | All 14 E2E tests run against a hermetic backend that already diverged from production once (revision pinned at 0, which produced a wrong guard) | Contract tests pinning hermetic responses to production invariants (monotonic revision), plus recorded-fixture tests for the live S2 query / 422 / 503 branches that PR #6 was entirely about | `tests/e2e_server.py`, `web-ui/e2e/` | Divergent F9 |
| B14 | Full-snapshot replacement is one root cause behind three separately-patched symptoms; rejection granularity is the whole world, so correctness rests on hand-placed UI guards a refactor can delete silently | Narrow domain commands returning affected aggregates, or a store reducer merging per-collection with per-entity versioning. **Largest item here — design work, not a fix** | `src/agora/focused/models.py`, `web-ui/src/store/focused.ts` | Divergent F2 |

### Project skills and harness

| # | Item | Stronger mechanism | Where | Source |
|---|---|---|---|---|
| B15 | The deployment skill lacks the two facts PR #7 existed to establish, and the single most valuable tool of the incident | Add `metrics --memory --since 5m --json`, the stateless `-p/-s/-e` UUID form (prefer over `link`, which writes local state bound to whatever directory it ran in), the Vercel-before-Railway gate, and the `agora.focused_app:app` invariant | `hypothesis-studio-deployment/SKILL.md` | Tooling F8, F9 |
| B16 | A prose warning asks a human to manually restore `next-env.d.ts` after a Next dev run, though a script already does it | Replace the warning with the `pnpm test:e2e` wrapper and the `.next-e2e` dist-dir isolation fact (E2E does not contend with a long-lived `pnpm dev` lock) | `agent-agora-tmux-dev/SKILL.md` | Tooling F4 |
| B17 | Subagent cwd drift: a reviewer inspected the wrong repository because ambient context named it. **This reproduces right now** — my own cwd is `/Users/bg/windsurf/mars`, the session artifact root is `…/-windsurf-mars/…`, and `memory://root/memory_summary.md` opens "User works in /Users/bg/windsurf/mars", while all work targeted `hypothesis-studio` | A required `repo_root` field in the fan-out brief plus a cheap first-call identity probe (read a file only the intended repo has; report BLOCKED if absent). Structural beats prose: the existing rule ("name the path in every prompt") is prose and already failed once. **Fallback if the harness field is unavailable:** add "absolute repo root" to the `swarm` skill's stands-alone brief list ("Include the goal, scope, exact slice or race arm, how to verify, and what to report") and the same to `handoff` | harness; `swarm/SKILL.md`, `handoff/SKILL.md` | Tooling F10, J12, divergent open question 3 |
| B18 | Server fields the client ignores are structurally invisible to review — `web-ui/src/types/focused.ts` hand-mirrors `models.py` with no generator (grep for `openapi\|codegen\|orval\|openapi-typescript` finds nothing) | OpenAPI-generated client types, so an unused server field shows up as a diff | `web-ui/package.json` | Divergent F1 secondary |

### Project follow-ups — no mechanism, just work (not counted above)

- **README is stale in at least four places** and reproduces two of the session's three worst traps: `:80` boots `src/agora/app.py`; `:201` gives `.venv/bin/pytest -q` with no `PYTHONPATH`; `:202` gives `ruff check src tests` while the handoff narrows it to `src/agora/focused_app.py src/agora/focused tests` with no stated reason; `:210-218` still describes pre-PR-#8 E2E coverage (export failure/retry). Per `local://handoff-corrections.md`, treat README as a follow-up, not current authority. Branch copy also still says `Continue` instead of Back/Add.
- **Ruff scope.** `local://handoff-corrections.md`: Ruff was run on affected Python files, not a complete `ruff check src tests`. Whether the wider scope passes is **unknown** — it was not run in this pass either.
- **Handoff identifier correction.** The first synthesis dropped one `b2` pair from the affected workspace id. Live browser/API operations and Railway logs used the 32-character id `520e8e6cf6464a8fa2b2b2b19e02f385`; the companion handoff now carries that corrected value. This is still historical archaeology, not a current endpoint contract.
- **Remaining `exclusive` surfaces.** Every non-exempt mutation still answers a mistimed click with a thrown error string (`use-focused.ts:99-101`, verified) rather than a disabled control. For a study UI with first-time participants, the remaining surface has not been enumerated (divergent F8).
- **Backend export is intentional.** Only participant-facing export UI and the frontend download code were removed. Do not "finish" the removal.
- **Open architecture questions the session raised and did not answer:** `src/agora/focused/service.py` is 2600 lines and `agents.py` 1546 — is the focused service still one coherent unit, or the default landing site? And `pyproject.toml` has one flat dependency list with no optional groups, so the image cannot be slimmed without an extras split.

---

## Cross-lens contradictions adjudicated

Three places where the lenses disagreed. Each was settled against the live repo, not by majority.

1. **Does the OOM regression test exercise the failing path?** Judgment J6 said yes ("assert it a second time after exercising the lazy path"). Divergent F3 said no. **Divergent is correct** — `test_focused_condition_is_runnable_from_standalone_app` uses in-process `TestClient` with `demo: True`, and the demo branch never reaches `_embedding_clusters`. `local://handoff-corrections.md` agrees. J6's proposed edit rested on a false premise; **A4 carries the corrected, stronger lesson instead.**
2. **Is `.venv` gitignored?** Tooling's "stale digest claims" list asserts it is, and calls the follow-up "half-wrong" on that basis. Divergent F5 and judgment J7 say it is not. **Divergent and judgment are correct** — `git check-ignore -v .venv` returns NOT IGNORED and `git status --porcelain` returns `?? .venv`, because `.gitignore:10` is `.venv/` and a trailing slash cannot match a symlink. `local://handoff-corrections.md` states the same. → **B3.**
3. **Should the E2E wrapper delete Playwright reports?** Judgment J7 says yes (add deletion to the existing `finally`). Tooling F2 says no. **Tooling is correct** — `trace` and `video` are `retain-on-failure` precisely so a failed run can be diagnosed; auto-deleting destroys the only evidence at the moment it is needed. The correct owner is the linter. → **B4, not deletion.**

---

## Summary

| | Count | Lands in |
|---|---|---|
| **Accepted** | 7 | `principle-fix-root-causes` (A1, A2), `principle-prove-it-works` (A4, A5), `principle-migrate-callers-then-delete-legacy-apis` (A3), `principle-separate-before-serializing-shared-state` (A6), `principle-build-the-lever` (A7) |
| **Rejected** | 9 | — |
| **Backlog** | 18 + 6 follow-ups | repo config (7), app code and tests (7), project skills and harness (4) |

No new skills proposed. All 7 edits are additions to existing sections of existing skills; none rewrites or contradicts current content. **Nothing has been applied.**

If you want a shorter list: drop **A7** first (lowest blast radius), then **A6** (most specialized). **A1–A5** are the ones that map to failures this session actually paid for.