# Handoff — Hypothesis Studio, `main@09dd11f`

**Written:** 2026-08-23, ~12:45 PDT (UTC−07:00).
**Repository this document is about:** `/Users/bg/windsurf/hypothesis-studio` → `github.com/bgar324/hypothesis-studio`.
**Not** `/Users/bg/windsurf/mars`. The harness session that produced this work was rooted in `/Users/bg/windsurf/mars`, and that has already misled one reviewer into auditing the wrong repository. Name the absolute path in every subagent prompt.

**Code baseline:** `09dd11f`. The commit that adds this hidden documentation is
expected to be a docs-only descendant, so future `HEAD` may be newer without any
product-code drift. Verify with `git diff --stat 09dd11f..HEAD`.

## Evidence tags used throughout

| Tag | Meaning |
|---|---|
| `[V]` | Verified by direct read/command during this synthesis, 2026-08-23 12:41–12:45 PDT. |
| `[AUDIT]` | Read-only source audit at `09dd11f` (backend / frontend / deployment audits). Line citations spot-checked and held. |
| `[LIVE 08-23]` | Live platform observation on 2026-08-23. Point-in-time; **will drift**. Re-measure, never restate. |
| `[HIST]` | Historical session evidence (a fix, a smoke test, a log line). True then, not a current-state claim. |
| `[INF]` | Inference from verified facts, not observed. |

Anything not tagged is structural description carried from the audits.

---

## 1. Mission

The user's asks, in their words, over the session that produced `09dd11f`:

1. A live (non-demo) Semantic Scholar search "returned no papers" and **sealed the Investigation** — fix it.
2. Perspective generation used one global loading state, so a second `Add to matrix` was impossible — fix it.
3. A child Research Problem branch could not get back to an unfinished parent panel; `Continue` attempted a blocked integration — fix it.
4. The resulting red action-error banner **could not be dismissed** — fix it.
5. Railway reported a **production OOM** — diagnose and fix.
6. `Export workspace` and the caret dropdown made the participant header noisy — "the single button is cleaner" — remove them.
7. Finally: produce a comprehensive hidden handoff (this document) plus a separate reflection artifact.

**All six code asks are delivered, merged, and deployed; the seventh ask is
fulfilled by this handoff and its companion reflection.** Acceptance criteria
outstanding: **none.** There is no unfinished code task or partially applied
patch. Everything in §4 is a *follow-up*, explicitly not a blocker.

If you were handed this document without a new instruction, your job is to *not* start work. Read §20, confirm state, and wait for a request.

## 2. State

### Git code baseline `[V]`

```
code baseline  09dd11fef44993caacde32cd0f7fa9f96b9b1f13
authoring      docs/session-handoff   (cut from 09dd11f; no upstream yet)
origin/main    09dd11fef44993caacde32cd0f7fa9f96b9b1f13
pre-commit     ## docs/session-handoff
               ?? .handoffs/                              # these two documents
               ?? .venv
baseline authored 2026-08-23T12:16:23-07:00  "Merge pull request #8 from bgar324/fix/simplify-header-actions"
```

Once `.handoffs/` is committed and merged, expect `main` and `origin/main` to
match at a docs-only descendant of `09dd11f`, with `?? .venv` as the only status
entry. No worktree or stash is relied upon; there are no uncommitted source
changes.

### The `.venv` hazard — the single most important local fact `[V]`

```
/Users/bg/windsurf/hypothesis-studio/.venv
    → symlink → /tmp/agent-agora-github-review/.venv        (macOS resolves /private/tmp/...)
    pyvenv.cfg: version 3.14.6, home /opt/homebrew/opt/python@3.14/bin
    bin/pytest shebang: #!/private/tmp/agent-agora-github-review/.venv/bin/python
    site-packages/_editable_impl_agora.pth: /private/tmp/agent-agora-github-review/src
git check-ignore -v .venv  →  exit 1     (NOT ignored)
```

**There is no local virtualenv.** Four consequences, all live:

1. **Wrong source tree by default.** The `.pth` puts `/private/tmp/agent-agora-github-review/src` on `sys.path`, and that stale checkout exists right now. `.venv/bin/pytest` without `PYTHONPATH` imports `agora` from `/tmp` and fails on symbols that do not exist in this repo. `PYTHONPATH` wins because its entries precede `.pth` additions — that is *why* the prefix is mandatory rather than merely advisable.
2. **Interpreter mismatch with production.** Local Python **3.14.6**; the image is **3.11** (`Dockerfile`, `.python-version`, `requires-python = ">=3.11"`). Green local pytest is necessary but not sufficient evidence about production runtime behavior.
3. **One `/tmp` purge breaks the Playwright suite too.** `web-ui/playwright.config.ts` hard-codes `<repoRoot>/.venv/bin/uvicorn` for its API webServer. When macOS clears `/tmp`, `pnpm test:e2e` fails at webServer startup with an error that *reads like a frontend problem*. This dependency is documented nowhere in the repo.
4. **`git add -A` would commit the symlink.** `.gitignore:10` is `.venv/` — a trailing-slash pattern matches **directories only**, and git classifies a symlink as a file. **Operative rule: never `git add -A` in this repo; stage explicit paths.** (Correction: an earlier review claimed `.venv` is gitignored. It is not — `git check-ignore` exits 1 and `git status` reports `?? .venv`. `[V]`)

### Local processes and ports, 2026-08-23 12:41 PDT `[V]`

Nothing here is required by the repo; all of it is session residue you may safely stop.

| PID | What | Port | cwd | Note |
|---|---|---|---|---|
| 23178 | `/tmp/agent-agora-github-review/.venv/bin/uvicorn e2e_server:app --app-dir tests` | `127.0.0.1:8000` | **`/Users/bg/windsurf/hypothesis-studio`** | Up 2h14m. `GET /api/v1/focused/health` → `{"status":"ok"}`. **This is the hermetic in-memory E2E app squatting on the canonical API port** — not the real focused app. Its state resets on restart and workspace `revision` stays 0. |
| 71543 | `.venv/bin/uvicorn agora.app:app` | `127.0.0.1:8001` | `/private/tmp/agent-agora-github-review` | Up 1d11h. The **legacy** OOM-class entrypoint, from the stale `/tmp` checkout. Health returns 200, which is exactly why the README's wrong local command is silent (§19). |
| 17291 + 58571 | `pnpm dev -p 3002` + `next-server 16.2.6` | 3002 | `/private/tmp/agent-agora-github-review/web-ui` | Frontend from the stale `/tmp` checkout. |
| 31787 | `next-server 16.1.6` | `*:3001` | `iterations/log-it` | **A different project (Logit).** Do not touch. |

- **Port 3000 has zero listeners.** No Hypothesis Studio web dev server is running. `[V]`
- Canonical local pair for anything user-facing is **UI 3000 / API 8000**. Port 8000 is currently occupied by the hermetic app (row 1); stop it before starting the real focused app there.
- Ports 3011/8011 belong to Playwright, are `reuseExistingServer:false`, and are E2E-internal and transient. **Never present a temporary numbered port as the product URL.**

### Disk `[V]`

`web-ui/` holds **20** `.next*` directories totalling **~1.1 GB** (`.next`, `.next-e2e`, and 18 labeled `NEXT_DIST_DIR` builds from verification runs: `.next-pr3-demo`, `.next-pi-verify`, `.next-scoring-verify`, `.next-simple-header`, …). `playwright-report/` and `test-results/` do **not** currently exist; the tree is clean of them.

### Credentials

No secret value was read or printed during this synthesis, and none appears in this document. Variable **names** only:

- **Railway:** `AGORA_PERSISTENCE`, `SUPABASE_URL`, `SUPABASE_SECRET_KEY`, `AGORA_PROXY_TOKEN`, `OPENAI_API_KEY`, `OPENROUTER_API_KEY`, `SEMANTIC_SCHOLAR_API_KEY`, `AGORA_CORS_ORIGINS`.
- **Vercel:** `API_URL`, `AGORA_PROXY_TOKEN` — never `NEXT_PUBLIC_`-prefixed.
- `npx @railway/cli variables` prints values. **Never run it into a transcript.**

## 3. Done so far

Three PRs, all merged to `main` and deployed. Commit chronology and diffstats in §17.

### PR #6 — live literature search recovery · merge `349c2f5` · source `30dd480`

Four independent root causes, each fixed:

- raw textarea newlines split wrapped research questions into separate stored questions → `parseResearchQuestions` (`web-ui/src/hooks/use-focused.ts`) joins likely continuations while preserving capitalized one-per-line entries;
- LLM output sent long prose, quotes, Boolean syntax, and notation to Semantic Scholar → search prompts demand 2–6 academic terms, and `agents.compact_search_query` (`src/agora/focused/agents.py:113-130`) rewrites unsafe queries while **preserving acronyms and hyphen-number compounds** (`GPT-4`, `LLM`, `RAG`, `QA`, `COVID-19`);
- zero-paper results persisted `searched=true`, creating a permanently sealed empty state → a successful-but-empty search raises **422 before** `state.searched = True`, so the mutation decorator rolls back and the Investigation stays editable and retryable;
- retrieval failure and true zero-match were indistinguishable → 422 for zero match with a healthy provider, **503** only when every attempted query failed.

`[HIST]` Live proof on workspace `b17856580abf494cada7ece0cb192ac1`: 6 question fragments repaired to 4, generated queries short, a 3-query **live** search returned 10 papers and 6 clusters. That workspace was later deleted by the user.

### PR #7 — Perspective concurrency, branch return, and the Railway OOM · merge `da5407f` · sources `e32100d`, `575c45d`, `5e16e99`

**Perspective concurrency (frontend property).** `generatePerspective` is the one mutation that does not go through the global `exclusive()` wrapper. Each cluster inserts its own optimistic card `optimistic:${sessionId}:${clusterId}` and owns its own rollback; other clusters stay addable. `perspectiveViewSet` is **addition-monotonic**: it preserves optimistic cards absent from a response and rejects any response missing an already-confirmed Perspective `origin`.

**Branch navigation.** `Back to panel` (pure navigation, `switchInvestigation(parent)`) was split from `Add to panel` (the mutating integration). Integration errors now say to return to the parent and end its deliberation. The action-error banner is scoped to the active Investigation and carries a `Dismiss error` control.

**OOM.** `[HIST]` Railway logs showed `Killed`, a restart, and 1007 MB of the 1024 MB limit. Local separate-process RSS: `import agora.app` ≈ **779.6 MB** and pulled in Torch/sklearn because the legacy DSPy `Runner` API initialized eagerly; a focused-only import ≈ **103.4 MB**. Fix: new `src/agora/focused_app.py` (87 lines) composing only focused auth/CORS, Supabase-or-SQLite persistence, the OpenRouter provider, Semantic Scholar, and OpenAI embeddings; `Dockerfile` CMD switched to `uvicorn agora.focused_app:app` and `OMP_NUM_THREADS` / `OPENBLAS_NUM_THREADS` / `MKL_NUM_THREADS` capped at 1. Legacy code stays in the repo but is not the entrypoint.

`[HIST]` Production proof: focused app booted, loaded Supabase state, drained to ~176 MB; a temporary 20-paper/5-cluster production demo search settled at **286.2 MB (27.9%)** with no `Killed` line and no restart; the temporary workspace was cleaned up. The affected user workspace `520e8e6cf6464a8fa2b2b2b19e02f385` was recovered: its child `89119d5c45fa4f10a33d4ecdb05d8b89` exposed both `Back to panel` and `Add to panel`, and `Add to panel` succeeded once the parent was ready, leaving the workspace on parent root `ea05af4f97014ad489205ba903233d2f`.

### PR #8 — header simplification · merge `09dd11f` · source `3302c96`

Frontend-only (4 files, +53/−151, all under `web-ui/`). Removed participant-facing `Export workspace`, the frontend download code, the caret, divider, dropdown, backdrop, and `menuOpen` state. Replaced the split control with **one ordinary `Button`** whose label is `Continue` / `Add to panel` / `Continued` / `Extraction` / `Open current Investigation`. `Start over` is now directly visible on desktop and mobile. **The backend export service and route were deliberately kept** — research tests and external study data use them. `[V]` grep over `web-ui/src` finds no `Export workspace`, `Workspace menu`, `menuOpen`, or download code.

### Verification actually performed `[HIST]`

- `PYTHONPATH=…/src AGORA_PROXY_TOKEN= .venv/bin/pytest` → **60 passed**, one Starlette/httpx deprecation warning.
- `pnpm test:e2e` → **14 passed**.
- `pnpm exec tsc --noEmit`, `pnpm lint`, `pnpm build` → passed.
- Ruff was run on **affected files only** (`src/agora/focused_app.py src/agora/focused tests`), not a full `ruff check src tests`.
- PR #8 additionally: desktop browser smoke, mobile browser smoke, Vercel production smoke, Railway redeploy.

`[V]` I independently recounted both suites at `09dd11f`: **60** backend test functions (`test_focused.py` 21, `test_focused_lineage.py` 20, `test_focused_hermetic.py` 8, `test_supabase_persistence.py` 5, `test_proxy_auth.py` 3, `test_standalone_api.py` 2, `test_openrouter_schema.py` 1; no `parametrize`, so functions == cases) and **14** Playwright tests. The reported numbers are not stale. (One audit table understated `test_focused.py` as 15; 21 is correct.)

## 4. Open threads

**Nothing here blocks anything. No code task is half-done.** Ordered by risk × cheapness. Each entry names the exact next action.

| # | Follow-up | Next action | Why it matters |
|---|---|---|---|
| 1 | **Backend deps are unpinned in the image.** `uv.lock` exists but is never copied into the image; `pip install .` resolves `pyproject.toml` ranges live. Only `numpy>=2.0,<2.4` is upper-bounded; `dspy`, `pandas`, `scikit-learn`, `bertopic`, `umap-learn`, `hdbscan`, `supabase`, `fastapi[standard]`, `openai` are open-ended. | Copy and honor `uv.lock` (or emit a pinned requirements file) in `Dockerfile`. | A rebuild of an **unchanged commit** can produce a different, broken image — and it makes "redeploy an older commit" not reproducible. Highest untracked deploy risk found. |
| 2 | **ESLint does not ignore Playwright artifacts.** `web-ui/eslint.config.mjs` `globalIgnores` = `.next/**`, `.next-*/**`, `out/**`, `build/**`, `next-env.d.ts`. Flat config does not read `.gitignore`. `[V]` | Add `"playwright-report/**"` and `"test-results/**"`. | One line retires a recurring manual-cleanup instruction, and it protects the *direct* `playwright test` path the wrapper cannot guard. |
| 3 | **`README.md:80` tells you to boot the OOM entrypoint** (`fastapi dev src/agora/app.py`). `[V]` | Change to `uvicorn agora.focused_app:app --port 8000`; add the `PYTHONPATH` / `AGORA_PROXY_TOKEN=` prefixes to `:201`; refresh the E2E coverage list at `:210-218`. | A doc line that hands a new contributor a ~780 MB local process and masks any re-import regression. |
| 4 | **`.gitignore` entry `.venv/` → `.venv`.** `[V]` | One character. | Removes the `git add -A` symlink hazard permanently. |
| 5 | **Rebuild `.venv` in-repo on Python 3.11.** | Needs the **user's go-ahead** — it is user-owned environment state and was deliberately left untouched. | Retires the `PYTHONPATH` ritual, aligns the interpreter with production, and removes the latent Playwright failure (§2). |
| 6 | **`specter_v2` vectors ship in every `WorkspaceView`.** `ExpPaper.specter_v2` is serialized in responses although frontend types never declare or use it — an 8,000-line JSON for one workspace. | `response_model_exclude` at the route layer. **Not** `Field(exclude=True)` — persistence serializes the same models and `persistence.py:377` needs the field. | Real payload defect, not an agent reading problem. |
| 7 | **Split focused vs legacy dependency extras.** `pyproject.toml` has one flat `dependencies` list, no optional groups. | Extras split, then a slim image. | Build time and image size only. **Runtime memory is already fixed**; do not re-litigate this as a memory issue. |
| 8 | **Reorder `Dockerfile`** so deps install before `COPY src`. | Move `COPY src` after `pip install`. | Every backend commit currently re-downloads the ML wheels. |
| 9 | **`railway.toml` Config-as-Code deprecation**, migrate before 2026-12-01. `[LIVE-ONLY]` — the file carries no marker. | Confirm in the Railway dashboard. | Platform-side deadline. |
| 10 | **`pnpm test:e2e` swallows CLI args.** `run-e2e.mjs` spawns `["exec","playwright","test"]` with no `process.argv.slice(2)`, so `pnpm test:e2e -g "…"` silently runs the whole suite — which pushes agents onto the unsafe direct path. | Forward `process.argv.slice(2)`. | Makes the safe path usable for single-test runs. |
| 11 | **~1.1 GB of stale `.next-*` builds** `[V]`, from a *good* practice (`NEXT_DIST_DIR` isolation) with no reclamation step. | `rm -rf` the labeled ones, or adopt `.next-tmp/<label>` with cleanup. | Also inflates typecheck/grep scope. |
| 12 | **Consider a debug/health endpoint exposing process RSS and loaded heavy modules.** | Open design question, not decided. | Would have reduced the OOM diagnosis from RSS archaeology to one authenticated request. Also: `/health` returning a bare `{"status":"ok"}` is why deploy ordering (§13) is manual. |

Backend export staying live is **intentional**, not a follow-up.

## 5. Decisions and constraints — do not relitigate

### Product

1. **One Hypothesis Studio product.** Participant language is "panel" and Perspective **names**. Never internal agent ids (`A1`/`A2`) or mentor jargon. Enforced upstream: `service.py:1646` sets `AgentState.label = perspective.name`, so `Turn.agent_label` is always a Perspective name. Hypothesis version ids (`H1`, `H2`) *are* intentionally visible — they are workspace artifacts, not agent ids.
2. **One fixed panel per Investigation.** Child Investigations use fresh literature and Perspectives and inherit the last applied hypothesis checkpoint.
3. **Child branches are explicit, never automatic.** Code-level expression: `open → investigating` is *not* in the question transition table; it happens only as a side effect of `create_child_investigation`.
4. **`Back to panel` is navigation. `Add to panel` is a separate mutation** that imports a ready branch only after the parent deliberation has ended. **Do not recombine them** — this is user correction #3/#4 and no error-copy change substitutes for it.
5. **Navigation model:** one high-level Investigation map + one detailed Investigation. **No header Investigation picker** (E2E pins `combobox "Switch Investigation"` at count 0).
6. Perspective cards and messages use neutral restrained styling — no decorative pills, dots, tinted rails, or false affordances.
7. Working-hypothesis steps are **read-only cards** until an explicit `Edit hypothesis`.
8. **`Apply shared ground` always shows a field-level Before/Proposed diff and requires a distinct second confirmation.** `Cancel` is always available and non-mutating.
9. **`Start over` stays directly visible. `Export workspace` is not participant-facing. One primary action, no caret menu.**
10. **`Add to matrix` is optimistic and immediate, but loading belongs only to that Perspective's card and button.** Other clusters stay addable.
11. **A zero-paper search never seals the Investigation.** The empty state stays editable and retryable.
12. **Moderator output is explicitly labelled and rendered below agent turns** (E2E compares bounding boxes).
13. **No per-round result nodes on the canvas.** Only final Hypothesis and Research Problem outputs appear after `End deliberation`.
14. **Imported agents never attach to the root problem** — they attach to their `research-<questionId>` node.
15. Saved Hypothesis nodes use the restrained green success surface; E2E pins the computed background to `rgb(236, 253, 243)`.
16. Full bibliographic titles as dotted clickable links; internal paper ids never render.
17. Copy rules: sentence case, no uppercase eyebrows, no arrows or emojis, "panel" in participant copy, exactly `End deliberation` as the terminal action, empty states are one actionable line, busy = spinner inside the triggering button.
18. **One rating per deliberation, never per round** (E2E asserts `rounds[0]` has no `rating`).
19. **Rejected in-session:** reserving one problem-angle search query. Query-ranking redesign was an explicit non-goal.

### Engineering

20. **Production must not import `agora.app`.** Doing so reloads the legacy DSPy/Torch stack and recreates the OOM. The one automated guard is `tests/test_standalone_api.py`.
21. Zero-paper search errors must be raised **before** `_save_state` so the serialized-mutation decorator restores the prior state.
22. Search provider failures degrade **per query**; only a total outage across every attempted query becomes 503.
23. `workspaceViewSet` handles ordinary authoritative responses; `perspectiveViewSet` is addition-monotonic and has exactly one caller.
24. **Do not remove the pending-Perspective guards** from header transitions, the removal control, or `Back to panel`. A late child response can otherwise switch the active Investigation back under the user.
25. **Most mutations remain globally exclusive.** Only `generatePerspective` bypasses `exclusive()` — and that is a *frontend* property (§11).
26. **Single Railway replica is a correctness constraint, not a cost choice** (§11).

## 6. Landmines

Ranked. Each has an exact site. None is currently on fire.

### Backend

**L1 — An integrated "read-only" branch is still fully mutable through the deliberation surface.** `integrated_into_parent_at` is checked in exactly three places: `integrate_child_investigation` (`service.py:719`), `generate_perspective` (`:1672`), `remove_perspective` (`:1763`). It is **not** checked in `create_deliberation`, `run_round`, `confirm_deliberation_hypothesis`, `save_deliberation_hypothesis`, `complete_deliberation`, `rate_deliberation`, `chat`, `suggest_queries`, `run_search`, or `update_brief`. Activating an already-continued child and running a deliberation there mints real `HypothesisVersion`s attributed to a branch the product presents as provenance-only. The "integrated branch is read-only" decision is enforced in the **frontend and three service methods**, not in the domain.

**L2 — `addressed → investigating` can create a permanently un-continuable branch.** `set_question_status` allows it (`service.py:903`). If that question's child was already integrated, `integrate_child_investigation` refuses (409, `:719-723`) and `create_child_investigation` refuses (status ≠ `open`, `:676-680`). The question sits in `investigating` with no reachable terminal action.

**L3 — Retrieval 429 aborts the entire multi-query search.** `service.py:1264-1271` raises 503 on the *first* 429 across any variant of any query, discarding papers already gathered. The one search failure mode that is **not** per-query degradation, contradicting the spirit of constraint #22.

**L4 — Blocking persistence I/O on the event loop.** `_persist_workspace` is synchronous, called from async handlers; both backends block (SQLite `persistence.py:389-427`; synchronous `postgrest .execute()` `supabase_persistence.py:161-172`), each additionally serialized by a `threading.Lock`. Every mutation stalls the uvicorn worker for one Supabase round trip. Fine at single-replica study scale; first thing to bite under load.

**L5 — "Concurrent" Perspective adds are backend-serialized with an LLM call inside the lock.** `generate_perspective` holds the workspace lock across `await agents.derive_framing(…)` (`service.py:1740`). The concurrency win is a **frontend optimistic-UI** property; on the backend two adds queue, and while either runs, every other mutation in that workspace either waits or returns 409 from `_ensure_workspace_idle`. Read the digest's "only Perspective generation bypasses `exclusive`" as a statement about `web-ui/src/hooks/use-focused.ts`, not about `service.py`.

**L6 — Boot-time hard failure on a doubly-owned investigation.** `persistence.py:283-290` raises `ValueError` (not quarantine) when one investigation id is referenced by two workspaces. Every other corruption is survivable; this one takes the whole service down at startup, healthy workspaces included.

**L7 — `deliberations[0]` vs `deliberations[-1]` inconsistency.** `integrate_child_investigation` (`:728`) and `generate_perspective` (`:1735`) use `[0]`; `merge_hypotheses` (`:959-961`) uses `[-1]`. Identical today only because `create_deliberation` caps the list at one (`:1882`). A future "second panel" breaks three call sites silently.

**L8 — Any new state field must survive `_validated_workspace_state`.** A validator that rejects existing rows will **quarantine live production workspaces on the next boot** (`persistence.py:191-230`, `supabase_persistence.py:126-131`). Migrations must be additive-with-defaults or paired with a payload rewrite.

**L9 — Never add an `await` to an undecorated mutation** (list in §11) without converting it to a decorated one. `_ensure_workspace_idle` only protects code with no suspension points.

**L10 — Stale comment lies about the concurrency model.** `service.py:1745-1747` says "two racing requests can both pass the pre-check above, but only one survives this synchronous window." `generate_perspective` is decorated and holds the workspace lock across the whole call, so no in-process race exists; cross-process racing is caught by the revision CAS. Harmless, actively misleading.

**L11 — Dead and dormant fields.** `ExpPaper.open_access_pdf_url` is never populated by any path (`retrieval.py:35-45`, `client/s2.py:28-41,88-125`). `QuestionReach.queries_r2` / `QuestionAssessment.round2` are modeled but never requested (`run_search` passes `want_round2=False`; `queries_r2` is reset to `[]`) — intentionally dormant, not broken. `_embed_metric_texts`'s `provider.embed_batch` fallback (`:1957-1959`) is test-only; `FocusedProvider` has no such method.

### Frontend

**L12 — Truthiness bug in `ClusterRow`.** `stage-extraction.tsx:608`: `const integrated = session?.integrated_into_parent_at !== null`. With a null session this evaluates **true** (`undefined !== null`), hard-disabling every facet edit and `Add to matrix`. `[V]` Masked today only because `ClusterRow` renders under a non-null session. The top-level `StageExtraction` copy at `:60` is correct because it runs after `if (!session) return null` (`:59`).

**L13 — `"optimistic:"` is an untyped magic string in 8 places** and `hasPendingPerspectives` is independently re-derived three times. `[V]` Sites: `store/focused.ts:81,90`; `index.tsx:105-106,109`; `stage-extraction.tsx:62-63,521,620`; `use-focused.ts:266`. A rename, or a fourth surface that forgets the guard, silently reintroduces user corrections #2/#3. **The strongest candidate for a structurally-enforced fix** — an `isPendingPerspective(p)` predicate plus a `selectHasPendingPerspectives` selector — not another prose rule.

**L14 — Navigation paths that bypass the pending guard.** Only three surfaces block on `hasPendingPerspectives`: the header (`Start over`, `Open current Investigation`, primary action), `Back to panel`, and the per-Perspective remove `✕`. `[V]` `ResearchProblemNode.onOpen` (canvas), and `Open Investigation` / `Start paper search` (drawer) gate on `busy` only. Safe today by modal serialization, **not by design**.

**L15 — Two counts, two rules.** `Perspective matrix (N)` uses `session.perspectives.length` (**includes** optimistic cards, by design — E2E test 2 asserts "Perspective matrix (2)" mid-flight) while `canDeliberate` uses `matrixCount` (**excludes** them). Do not "unify" them without rewriting that test.

**L16 — 409 recovery bypasses the monotonic merge.** `requestView`'s catch applies the refetched view through `workspaceViewSet`, not the caller's `applyView`. During a concurrent Perspective add this can drop a sibling's optimistic card, which `generatePerspective`'s catch then tries to remove again.

**L17 — Duplicated cycle math.** `questionIdsForCompletion`, `questionCycle`, `completionAgentIids` and the `targetCycle` precedence chain are written **twice** in `stage-deliberation.tsx` — once in the `nodes` memo and once in the `edges` memo. They must stay equivalent or React Flow emits "Couldn't create edge", which E2E test 4 asserts never happens.

**L18 — Smaller ones.** `RefitOnNodes` leaks a `window.setTimeout` with no cleanup (fires after unmount during fast navigation). `workspaceScreen` is never reset, so a workspace collapsing to one Investigation leaves the store on `"map"`. The drawer auto-closes whenever `!session || !active`, so any transient state that nulls `deliberations[0]` dismisses it. `sendChat` hardcodes `proactivity: "med"` with no UI. Design tokens live in `dangerouslySetInnerHTML` (`app/focused/layout.tsx`) and are duplicated as prose in `DESIGN.md` — two unlinted places to keep in sync. The Vercel proxy drops `retry-after`/`set-cookie` and re-encodes path segments. `ListRow` (`ui.tsx:341`) is dead code.

### Tooling and workflow dead ends already paid for

- **Never run `pnpm exec playwright test` directly.** It mutates tracked `web-ui/next-env.d.ts` and `web-ui/tsconfig.json` and leaves `playwright-report/` + `test-results/`, which then make `pnpm lint` scan thousands of generated findings. `scripts/run-e2e.mjs` snapshots and restores the two config files in a `finally` — but **does not** delete the reports. Recovery: `git checkout -- web-ui/next-env.d.ts web-ui/tsconfig.json && rm -rf web-ui/playwright-report web-ui/test-results`.
- **A stray listener on 3011 or 8011 fails the whole E2E suite outright** (`reuseExistingServer:false`).
- **Browser device without an explicit Chrome path fails** with `cmux browser.open_split did not return a surface_id`. Working path: spawn `/Applications/Google Chrome.app/Contents/MacOS/Google Chrome` with `--headless=new`.
- **Reading a whole production workspace JSON after a search yields 8,000+ lines** because every SPECTER vector serializes. Query summary fields via `tab.evaluate` or a narrow JSON selector. (Root cause is follow-up #6, not a reading habit.)
- **`grep` with an explicit path into a gitignored directory bypasses the `gitignore:true` default** — naming `.venv/lib/.../site-packages` returns pages of Cython sources. Scope searches to `src/`, `tests/`, `web-ui/src`, `web-ui/e2e`.
- **`gh pr merge --delete-branch` switches the local checkout to `main` and fast-forwards it.** Re-check branch and status immediately after any merge.
- **Vercel goes ready before Railway.** Do not exercise a new frontend mutation until the matching Railway deployment is `SUCCESS` *and* its logs show `Application startup complete`.
- **Railway memory metrics briefly sum old and new containers during a rollout.** A transient reading above the limit during overlap is **not** the steady state. Wait for drain, then measure after a real request.
- **Cross-project contamination is real.** Agent memory carries ExPerspect/MARS-era rules (e.g. "the panel drawer is 760px/96vw"). In *this* repo the drawer is `w-[min(1180px,96vw)]`. Do not apply MARS conventions here, and always name `/Users/bg/windsurf/hypothesis-studio` explicitly in subagent prompts.

---

# Deep reference

## 7. Product and domain model

A participant runs an **Investigation** inside a **Workspace**: retrieve abstract-grounded literature → cluster it → turn clusters into named **Perspectives** → deliberate in one **panel** → converge on a four-part **Hypothesis** → checkpoint it as an immutable version → spin child Investigations off open questions and integrate them back.

**Aggregate shape** (`src/agora/focused/models.py`). `WorkspaceState` is the transactional aggregate root; `SessionState` is one Investigation and a member of it. `WorkspaceView = {workspace, investigations: [InvestigationSummary], active: SessionState}` is the response body of nearly every route (`models.py:477-480`).

```
WorkspaceState
└── SessionState  (one Investigation)              N
    └── DeliberationState  (at most 1, forever)    N in type, 1 in practice
        └── DeliberationRound
            ├── Turn / FacetVerdict
            ├── RoundResolution
            ├── ParticipantReflection
            └── RoundMetrics
cross-cutting:  ExpPaper → ClusterCard → Perspective → AgentState (1:1) → round participant
```

**Fixed vocabularies.** `Facet = 'scope' | 'explanation' | 'approach' | 'significance'`, stable order in `FACETS` (`models.py:14-19`) — a Perspective always carries all four; a round activates 1–2. `QuestionStatus = 'open' | 'investigating' | 'addressed' | 'archived'` (`:262`). `HypothesisPart` = the four steps; `HypothesisConfirmationMode = 'apply_pending' | 'edit_applied'` (`:115`). `PERSONA_COLORS` — 6 colors assigned `len(perspectives) % 6` (`:17-24`); a 7th Perspective repeats a color **by design**.

**The five pydantic validators are the real specification.** They fail closed on every save:

| Validator | Site | Enforces |
|---|---|---|
| `HypothesisVersion.validate_ancestry` | `models.py:133-139` | unique parents; no self-parent |
| `RecommendedQuestion.validate_status` | `:276-285` | `open` ⇒ no child; `investigating`/`addressed` ⇒ child required |
| `DeliberationState.validate_hypothesis_state` | `:307-336` | rating/final version require `completed_at`; completed requires a final version; `hypothesis_confirmed` ⇒ `hypothesis == applied_hypothesis`; working-hypothesis provenance all-or-nothing |
| `SessionState.validate_lineage` | `:401-421` | applied hypothesis + version id co-present; root has no origin question; child requires both origin fields; only a child may be integrated |
| `WorkspaceState.validate_graph` | `:447-475` | unique investigation ids; root/active in workspace; unique version ids; every version's workspace, investigation, parents and step-sources resolve inside the workspace; promoted version exists and is not archived |

`_validated_workspace_state` (`service.py:368-379`) round-trips `model_dump()` → `model_validate()` on **every** persist, so a service bug that corrupts the graph raises *before* it is written and the mutation rolls back. **Read `models.py` first.** The service is largely ordered guards around these validators.

**The grounding rule (the study's core constraint).** Facet evidence may come **only** from abstract sentences, enforced at the service boundary rather than in prompts:

- `_validate_facet_source` (`service.py:1420-1458`): `edited=True` strips provenance; unknown `paper_id` blanks the text; a valid `sentence_index` is re-materialized from `paper.abstract_sentences`; otherwise `agents.map_facet_to_sentence` must find a mapping or the facet text is **erased**.
- `FocusedSemanticScholar.search` drops any paper without a non-empty abstract (`retrieval.py:47`).
- `_canonical_citations` (`:1912-1928`) filters every model-emitted citation against that speaker's own source allow-list.
- `generate_perspective` refuses unless all four facets survive with non-empty text (`:1714-1719`).

## 8. Architecture map

### Two entrypoints, one router

| Entrypoint | File | Extra imports | Role |
|---|---|---|---|
| **Focused (production)** | `src/agora/focused_app.py` (87 lines) | — | **The** Railway entrypoint |
| **Legacy (not deployed)** | `src/agora/app.py` (98 lines) | `dspy`, `agora.api.router`, `agora.db.store`, `agora.workflow.run.Runner` | in repo, must never run in production |

`app.py:4-5,25` imports `numpy` then `dspy` at module scope and constructs `Runner` in lifespan (`:53-59`). Both apps mount the **same** `focused_router` at `/api/v1`, so the HTTP contract is identical — only the import graph differs. That is exactly why the README's wrong local command is silent.

### Layering — strictly downward, no cycles

```
focused_app.py       composition root: settings → persistence → provider → s2 → service
  └── api/focused.py            HTTP shell: request schemas, error translation, view projection
        └── focused/service.py  all domain behavior + concurrency + persistence orchestration
              ├── focused/models.py                authoritative pydantic domain + wire contracts
              ├── focused/agents.py                prompts, structured calls, query compaction, sentence mapping
              ├── focused/demo_data.py             deterministic no-provider corpus
              ├── focused/retrieval.py             Semantic Scholar adapter, abstract-only
              ├── focused/provider.py              thin OpenRouter structured-output adapter
              ├── focused/persistence.py           Protocol + SQLite impl + shared validators
              ├── focused/supabase_persistence.py  JSONB aggregate impl, reuses SQLite validators
              └── focused/importer.py              SQLite → Supabase migration
```

**Composition root** (`focused_app.py:26-84`): persistence chosen by `settings.server.persistence_backend` (Supabase or `sqlite3.connect(data_dir/'agora.db')`); `AsyncOpenAI` supplies the `embed` closure over `agora.db.vector.embed_texts` (`text-embedding-3-small`, `db/vector.py:14`); `FocusedProvider` is constructed **only if** `settings.openrouter.api_key` is set, otherwise `None` and every session is forced into demo mode (`service.py:603-607` — a keyless deployment silently serves demo content). Middleware: `ProxyTokenMiddleware` then CORS.

**Where state lives.** `FocusedPanelService` is an **in-process authoritative cache**, not a repository facade (`service.py:229-258`): `_sessions` (every Investigation of every workspace), `_workspaces`, `_workspace_locks`, `_durable_snapshots`. The constructor eagerly `persistence.load()`s **all** workspaces at boot.

**Import weight, precisely.** `focused_app` imports `numpy` (via `service.py` and `db/vector.py`) but **not** `torch`/`dspy`. `sklearn` **is** imported lazily at first use — `_kmeans_clusters` (`:1307-1308`), `_embedding_clusters` (`:1333-1334`), `_clustering_diagnostics` (`:1385,1391`), `_round_metrics` (`:1999`) — so **sklearn is a real production runtime dependency of the focused app**; only Torch/DSPy are avoided. `[INF]` the "103 MB at import → 286 MB after a real search" delta is largely sklearn plus the numpy working set and SPECTER vectors. Also: `db/vector.py:11-12` drags `agora.schemas.panel` and `agora.schemas.research` into the focused image — pydantic-only, but the focused import graph is not fully independent of legacy schemas.

## 9. Backend runtime flows

**Workspace creation → literature.**
1. `POST /focused/workspaces` → `create_workspace` (`service.py:614-656`). Synchronous, **undecorated**. Registers session + workspace + lock, then `persistence.create`; on any exception it pops all four maps (`:650-655`), so creation is atomic. `demo = demo or self._provider is None`.
2. `POST /sessions/{id}/suggest-queries` → `suggest_queries` (`:1143-1235`). Live path: one `agents.suggest_queries` problem-angle call plus one `agents.plan_question_search` per research question, building `QuestionReach` rows. Deduped, whitespace-normalized, capped at `MAX_SUGGESTED_QUERIES = 5` (`:67`); the request schema enforces the same cap (`api/focused.py:107-108`).
3. `POST /sessions/{id}/search` → `run_search` (`:1460-1623`). Splits selections into problem-angle and per-question round-1 queries, retrieves each set, asks `agents.assess_question_papers` which retrieved papers bear on each question, then clusters, names, and extracts facets.

**Clustering ladder.** `_embedding_clusters` (SPECTERv2 + KMeans; needs ≥4 papers and **full** embedding coverage) → `_kmeans_clusters` (TF-IDF, ≥4 papers) → single group; demo uses keyword seeds (`:1552-1565`). `ClusteringDiagnostics` records method, embedded/total, sizes, and a cosine silhouette computed **in SPECTER space** whenever coverage is full, explicitly so scores stay comparable across methods (`:1362-1405`). Diagnostics never fail a search (broad `except` → `silhouette=None`).

**Deliberation lifecycle.**
- `create_deliberation` (`:1877-1901`) is **idempotent and single-instance** — appends only `if not state.deliberations`, seeding with the Investigation's inherited `applied_hypothesis` marked confirmed. One Investigation therefore has at most one deliberation, forever.
- `run_round` (`:2064-2358`) preconditions: deliberation open; 1–2 unique valid facets; ≥2 agents; lead wired; **no unconfirmed pending hypothesis**. Discards a trailing incomplete round (`:2104-2105`), then per facet: lead open statement → each other agent answers → if *nobody* cited anything, one `retrieve_support` rescue that may append a paper to the corpus → `judge_facet`. Then a resolution, per-agent reflections (revisions bump `facet_version`), semantic metrics, an evolved lead perspective, a hypothesis proposal, and question recommendation.
- **No-agreement is code-enforced:** a hypothesis is proposed only `if resolution.consensus_points`, else `no_agreement = True` (`:2320-2340`).
- **Semantically-unchanged proposals stay confirmed:** `_same_hypothesis` (`:1857-1870`) normalizes whitespace and treats the literal `"Not established yet."` as empty, so a no-op proposal never creates a false pending update.
- **Question dedup:** recommendations are skipped when an `open`/`investigating` question already has the same casefolded, whitespace-normalized text; ids are `{delib}-r{n}-q{i}` (`:2342-2356`).

**Hypothesis versioning — three distinct verbs.**

| Verb | Route | Service | Effect |
|---|---|---|---|
| **Apply / edit** | `PUT …/deliberations/{id}/hypothesis` | `confirm_deliberation_hypothesis` (`:2420-2480`) | mutates the **working** hypothesis only; records `working_hypothesis_source_kind/_round`; **creates no version** |
| **Save (checkpoint)** | `POST …/hypothesis/checkpoint` | `save_deliberation_hypothesis` (`:2483-2520`) | creates the immutable `HypothesisVersion` |
| **Merge** | `POST /workspaces/{id}/hypotheses/merge` | `merge_hypotheses` (`:944-1025`) | two-parent version with per-step `step_sources` |

`_record_hypothesis` (`:501-575`) is the single version factory: id `H{n+1}` by count; parents default to the current applied version; per-step provenance carries forward when a step's text is unchanged; the first-ever version auto-promotes. `archive_hypothesis` only sets `archived=True` and never deletes, so `H{n}` ids stay unique. Guards: promote requires the version be an Investigation's *current* checkpoint (`:930-936`); merge is blocked while a pending panel update exists (`:963-974`); archive is blocked for the promoted version and for any Investigation's current checkpoint (`:1035-1050`). `_address_contributing_questions` (`:576-601`) walks the promoted version's ancestry and marks every contributing child Investigation's origin question `addressed`.

**Question state machine** — explicit allow-table (`:900-914`):

```
open          → archived
investigating → addressed | archived
addressed     → investigating | archived
archived      → open                        (only if no child)
              → investigating | addressed   (if a child exists)
```

`open → investigating` is deliberately absent; it happens only via `create_child_investigation` (`:699-700`).

**Branch and integrate.**

*Branch* — `create_child_investigation` (`:659-701`): requires `status == 'open'`. The child inherits `workspace.problem`, carries exactly `[question.question]` as its research questions, copies the parent's applied hypothesis **and its version id**, and becomes active.

*Integrate ("Continue")* — `integrate_child_investigation` (`:704-881`), the most intricate routine in the backend. Ordered preconditions: (1) child's parent matches; (2) not already integrated; (3) child has ≥1 Perspective; (4) parent has a deliberation; (5) **parent deliberation is completed with a final version** — "Return to the parent panel and end its current deliberation before adding this research branch."; (6) child has an origin question; (7) the origin question still points at this child. It then *reopens* the parent deliberation:

- pushes a `DeliberationCompletion` (round count, agent iids, question ids, rating) onto `completion_history`, with a back-compat path reconstructing `question_ids` for older completions from `source_round` (`:797-816`);
- clears `completed_at`, `final_hypothesis_version_id`, `rating`;
- imports papers with content-fingerprint dedup `(title.casefold(), abstract)` and `{child_id[:8]}-{id}` collision prefixes; imports clusters with remapped paper ids; imports Perspectives with fresh parent-scoped ids, recycled colors, remapped origins/sources/facets, `source_question_id = child.origin_question_id`, and `panel_cycle = len(completion_history)`;
- calls `_ensure_perspective_agent` per imported Perspective, which also wires the new agent into every open deliberation (`:1651-1659`);
- unions `searched_queries`, marks the source question `addressed`, stamps `child.integrated_into_parent_at`, activates the parent.

`complete_deliberation` then requires a **new** round beyond the last completion (`:2378-2386`) — the "continued panel needs a fresh round before ending again" rule.

**Failure semantics (exact HTTP contract).** Translation in `api/focused.py:46-83`: `SessionError.status` passes through verbatim; `FocusedAgentError` → **503**; anything else is an unhandled 500.

| Condition | Status | Site |
|---|---|---|
| unknown session / workspace / question / version / paper / agent / cluster | 404 | `service.py:263,272,484,494,1630,1910` |
| default domain refusal | 400 | `:71-73` |
| **zero papers matched, provider healthy** | **422** | `:1546-1550` (state rolled back) |
| **every attempted query failed** | **503** | `:1542-1545` |
| S2 returned 429 on any variant | 503 | `:1267-1271` — **aborts the whole search** (L3) |
| live LLM call failed | 503 | `agents.py:_structured` → `FocusedAgentError` |
| stale revision / deleted workspace | 409 | `:76-81` |
| workspace busy | 409 | `:358-366` |
| illegal question transition / already-integrated branch / cluster already in matrix / archived-version ops | 409 | `:915-918, 719-723, 1748-1752, 1032-1034` |
| missing proxy token | 401 | `api/proxy_auth.py:27-32` |

**Per-query degradation** (`_live_retrieve`, `:1249-1293`): each query is tried as-is then as a `relaxed_search_query` (last 3 content terms); non-429 failures `continue` and only flip `search_succeeded` when some variant returns. Caps: 8 per query, 30 papers total.

**Query safety** (`agents.compact_search_query`, `agents.py:113-130`): a query is "unsafe" if it contains `?` / `？` / `"`, a bare `AND|OR|NOT`, or more than 6 content terms; unsafe queries reduce to deduped non-filler terms. `_search_query_words` keeps hyphen-number compounds and 2-character tokens — that is what preserves acronyms.

**Metric failure never fails a round.** `_embed_metric_texts` returns `method='unavailable:no-semantic-embedder' | 'unavailable:embedding-failed' | 'unavailable:invalid-embedding-batch'` (`:1947-1971`); the round completes with an explicit `RoundMetrics(method=…)` and `direction='insufficient'`.

## 10. Frontend runtime flows

**Routing.** `app/page.tsx` → `redirect("/focused")`. One participant route. `app/focused/layout.tsx` sets metadata `study-condition: focused`, wraps in `<div className="focused min-h-screen">`, and injects the whole token stylesheet through `<style dangerouslySetInnerHTML>`.

**Surfaces inside `FocusedWorkspace`** (`features/focused/index.tsx`):

| Surface | Condition |
|---|---|
| "Opening workspace…" spinner | `!session && busy === "Opening workspace"` |
| `RestoreErrorScreen` | `!session && restoreError` |
| `StartScreen` | `!session` |
| `WorkspaceMap` | `investigations.length > 1 && workspaceScreen === "map"` |
| `StageExtraction` | `stage === "extraction"` |
| `StageDeliberation` | `stage === "deliberation"` |
| `PaperModal` (always mounted) | `openPaperId !== null` |
| `ResetDialog` | `resetOpen` |

`activeScreen = hasInvestigationBranches ? workspaceScreen : "detail"`, where `hasInvestigationBranches = investigations.length > 1`.

**URL / storage lifecycle.** Restore keys off `?workspace=` then `localStorage["focused-workspace"]`. `ApiError` 404/410 → clear both silently and fall to `StartScreen`; any other failure → `RestoreErrorScreen` that **keeps** the pointer. A persist effect writes localStorage + `history.replaceState` on every workspace change. `loadWorkspace` retries at delays `[0, 500, 1500, 2500]`, aborting early only for status `< 500` other than 429.

**API proxy** — `app/api/focused/[...path]/route.ts`: `runtime="nodejs"`, `dynamic="force-dynamic"`, `maxDuration=300`. One `proxy` function exported as GET/POST/PUT/PATCH/DELETE (no HEAD/OPTIONS). Target `${API_URL ?? "http://127.0.0.1:8000"}/api/v1/focused/${path.map(encodeURIComponent).join("/")}`; query string copied verbatim. On Vercel with `API_URL` or `AGORA_PROXY_TOKEN` missing → 503 `{"detail":"The production API proxy is not configured."}`, upstream never called. Fetch throw → 502 `{"detail":"The API is unavailable."}`. Forwards request headers `accept`, `content-type`, `x-agora-proxy-token`; preserves response headers `cache-control`, `content-disposition`, `content-type`. `cache:"no-store"`, `redirect:"manual"`. **Every user-visible API error string is authored server-side**; `api()` in `hooks/use-focused.ts` reads `(await res.json()).detail`.

**Header.** Sticky, `z-40`, `min-h-12`, wraps below `sm`. Left→right: brand (`hidden sm:block`) · Investigation-map entry (**only** when `investigations.length > 1`; label `Map` below `sm`; on mobile `order-last w-full` beneath a hairline) · progress trail `Search / Perspectives / Panel` (`aria-label="Progress"`, `hidden lg:flex`, detail screen only) · `demo` pill · spacer · `Start over` (ghost) · exactly one primary action.

| Screen / state | Label | Handler |
|---|---|---|
| map screen | `Open current Investigation` | `workspaceScreenSet("detail")` |
| extraction, root | `Continue` | `createDeliberation()` → `stageSet("deliberation")` |
| extraction, research branch | `Add to panel` | `integrateChildInvestigation()` → `stageSet("deliberation")` |
| branch already integrated | `Continued` (disabled) | — |
| deliberation | `Extraction` | `stageSet("extraction")` — pure local, no request |
| busy `"Setting up the panel"` | spinner + `Continuing panel…` | — |
| busy `"Adding research branch to panel"` | spinner + `Adding to panel…` | — |

Disabled predicate: `busy !== null || hasPendingPerspectives || (stage === "extraction" && !canDeliberate)`, with a `title` naming the gate that fired. Gate arithmetic: `matrixCount` counts only **confirmed** Perspectives; `isResearchBranch = parent_investigation_id !== null && origin_question_id !== null`; `canDeliberate = !branchIntegrated && matrixCount >= (isResearchBranch ? 1 : 2)`.

Action-error banner: `role="alert"`, rendered only when `actionError.sessionId === session.id`, dismissible via `aria-label="Dismiss error"`. `Start over` → `ResetDialog` → `deleteWorkspace()` → clear localStorage + URL param → `reset()`.

**Extraction** (`stage-extraction.tsx`). Research-branch banner when `parent_investigation_id` — not integrated: *Started from "<origin_question>". Search fresh literature and add new Perspectives. Back to panel returns without changing this branch. Add to panel imports it after the current parent deliberation ends.* plus either *This branch begins from <version id>.* or *No hypothesis checkpoint had been applied yet.*; integrated: *This research branch has already been added to the parent Canvas and is now read-only.* Brief card: pencil edit appears only when `!session.searched || session.papers.length === 0`; in edit mode the Problem textarea is `disabled` for child investigations; Save requires `problem.trim().length >= 3`; `updateBrief` clears picked queries. Query selection: `suggestQueries()` → `Load demo queries` / `Generate search queries`; top-5 render as `aria-pressed` toggles with an optional `For: <research question>` line; primary `Search papers (N queries)`. Post-search `<section aria-label="Queries searched">` lists `session.searched_queries` verbatim. Zero-result recovery: "No papers matched those searches." + "Retry generates shorter academic queries automatically." + `Retry search` = `updateBrief(same)` → `suggestQueries()` → `runSearch(all refreshed)`. `ClusterRow`: collapsible; per-facet inline edit commits on blur, strips `paper_id`/`sentence_index`/`sentence`, marks `edited`, surfaces "Researcher edited · source link removed"; one primary `Add to matrix` with `aria-live="polite"` states `Adding to matrix…` / `✓ Added to matrix` / `Complete all four areas` / `Add to matrix`, disabled on `integrated || inMatrix || !complete || busy !== null`.

**Deliberation canvas** (`stage-deliberation.tsx`, 2241 lines — also contains `PanelDrawer` at `:619`). `NODE_TYPES`: `epProblem`, `epAgent`, `epPanel`, `epHypothesis`, `epResearchProblem`. Topology, computed in two `useMemo` blocks that duplicate the same cycle math (L17):

- Coordinates: `panelX(c)=720+c*1060`, `artifactX(c)=panelX(c)+360`, `branchAgentX(c)=panelX(c)+700`; cycle-0 agents at `x=330`; agents stack `index*175 − (n−1)*87.5`; artifacts at `(i − (n−1)/2) * 165`.
- `targetCycleForAgent` precedence: `perspective.panel_cycle > 0` (clamped to `history.length`) → `source_question_id` via `questionCycle` + 1 → first `completion_history` entry containing the iid → `history.length`.
- Edge precedence: agent with a known `source_question_id` attaches to `research-<questionId>`; cycle-0 agent attaches to `problem`; otherwise to the **previous completed panel**.
- `questionIdsForCompletion` falls back to `source_round` windowing when `completion.question_ids` is empty (legacy tolerance). `renderedVersionIds` dedupes hypothesis nodes across cycles. Artifacts emit only for completed cycles, and for the current panel once `completed_at !== null`.
- Panel status strings: `Ended after N round(s)` / `N completed round(s)` / `Ready for a focused round` / `Needs two Perspectives`; button `Review` when ended else `Join`; `canJoin = agent_iids.length >= 2`.
- **Canvas Add Perspective**: React Flow `<Panel position="top-left">`, rendered only when `deliberations[0].completed_at === null && availableClusters.length > 0`. The dialog keeps its **own** serialized `addingPerspective` flag; `ModalShell` covers the canvas until the add resolves, so this path is single-flight even though `generatePerspective` is concurrency-capable.

**Panel drawer.** `fixed inset-0 z-40`, backdrop `rgba(16,24,40,0.32)` + `backdrop-blur-[2px]`, aside `w-[min(1180px,96vw)]`, `role="dialog" aria-modal="true"` labelled "Focused panel". Accessibility is centralised in `useDialogSurface` (`ui.tsx`): a module-level `DIALOG_STACK` so Escape closes only the topmost surface, Tab trap, `[data-autofocus]`, `document.body.style.overflow` lock, prior-focus restore. Two-pane body: left `data-testid="panel-conversation-scroll"`, right `data-testid="working-hypothesis-sidebar"` (`lg:w-[380px] lg:overflow-y-auto lg:border-l`) — independent scrolling is an E2E contract. `ResolutionCard` = `<section aria-label="Moderator summary">` with an explicit **Moderator** label and **Round summary** caption, strictly **below** agent turns; groups Shared ground / Disagreement / Still unsettled, "None recorded" when empty. Round setup card renders only when `completed_at === null && (hypothesis === null || hypothesis_confirmed)`; facet picker allows at most 2; `Start round` needs ≥2 agents and ≥1 facet; opener rotates `agents[active.rounds.length % agents.length]`. Chat bar appears only when `completed_at === null` and ≥1 round completed.

**Hypothesis confirmation** (`WorkingHypothesisPanel`). `pending = value !== null && !hypothesis_confirmed`; `unsaved = hypothesis_confirmed && applied_hypothesis !== null && (no savedHypothesis || any part differs)`; `reviewingChanges = pending || editing`; `baseline = applied_hypothesis`. `changedParts` uses `normalizedHypothesisPart()`, which trims and maps `"Not established yet."` to empty — **the meaningful-diff rule**; whitespace-only and placeholder-only differences never count. Status ladder: `Update ready` (amber) → `Applied, not saved` (amber) → `Saved <versionId>` (green) / `Applied`. Each part renders `data-hypothesis-part="problem|previous_work|reasoning|hypothesis"` as a read-only card until `Edit hypothesis`. **Two-step apply:** `Apply shared ground` / `Apply edits`, both disabled at `changedParts.length === 0`, open `ModalShell title="Apply hypothesis changes?"` listing `data-testid="changed-hypothesis-part-<key>"` articles with Before/Proposed and requiring a distinct `Apply changes` press. `confirmDraft` refuses empty fields and picks `edit_applied` when already confirmed else `apply_pending`. Then `Save hypothesis` creates the checkpoint.

**Open questions.** Per-question card with source ("From disagreement" / "From an unsettled point") + rationale. Status `select` appears only once a child exists. For `status === "open"`: `Archive` always, and `Start paper search` **only when the deliberation is completed** — otherwise "Its Research Problem node appears when you end the deliberation." Archived-without-child offers `Reopen`; any question with a child offers `Open Investigation`.

**End block.** `needsNewRound = completion_history.at(-1) !== undefined && rounds.length <= previousCompletion.round_count` → "Complete a round with the added Perspectives before ending again." `End deliberation` disabled on `busy || rounds.length === 0 || needsNewRound || pending || unsaved || editing || savedVersionId === null`. After completion: "Deliberation ended" + `Rate deliberation` / `Update scores`. `DeliberationScoringDialog` opens automatically via `onEnded`: "Rate this deliberation", two fieldsets ("Divergent thinking", "Convergent thinking"), each a 1–7 radio row anchored "Not at all" / "Very much".

**Busy labels are load-bearing strings.** Components match them literally: `Opening workspace, Deleting workspace, Starting Investigation, Saving brief, Generating queries, Searching literature, Removing, Setting up the panel, Running focused round, Ending deliberation, Saving deliberation scores, Applying hypothesis, Saving hypothesis checkpoint, Starting child Investigation, Adding research branch to panel, Opening Investigation, Updating question, Promoting hypothesis, Merging hypotheses, Archiving hypothesis, Restoring hypothesis, Deliberating`. **Renaming any one silently drops a spinner or a disabled state.**

## 11. Concurrency invariants

### Backend — two decorators

- `_serialized_session_mutation` (`service.py:84-106`): resolve session → take `workspace_lock` → re-resolve session → take `session.lock` → snapshot the **whole workspace** → run → on any `BaseException` except `WorkspaceConflict`, restore the snapshot and re-raise.
- `_serialized_parent_mutation` (`:109-142`): same, keyed on `(workspace_id, parent_investigation_id)`, with a membership check returning 404 for a foreign Investigation.

`WorkspaceConflict` is deliberately excluded from rollback because `_persist_workspace` has already replaced in-memory state with the authoritative reload; restoring the entry snapshot would undo that.

**Decorated (async, serialized):** `suggest_queries`, `run_search`, `generate_perspective`, `remove_perspective`, `develop_agent_hypothesis`, `create_deliberation`, `run_round`, `complete_deliberation`, `rate_deliberation`, `confirm_deliberation_hypothesis`, `save_deliberation_hypothesis`, `chat`, `create_child_investigation`, `integrate_child_investigation`.

**Undecorated (sync, guarded by `_ensure_workspace_idle`):** `activate_investigation`, `set_question_status`, `promote_hypothesis`, `merge_hypotheses`, `archive_hypothesis`, `restore_hypothesis`, `delete_workspace`, `update_brief`, `export_workspace`. `_ensure_workspace_idle` (`:358-366`) returns **409 "Wait for the current workspace action to finish."** when the workspace lock or any session lock is held. These are safe without a lock **only because they contain no `await`** and cannot interleave on the event loop — except for the blocking persistence call inside them (L4). See L9.

**Three rollback layers.**
1. **Decorator snapshot** — deep copy of `WorkspaceState` plus every member `SessionState` *and* its four id sequence counters (`_turn_seq/_persp_seq/_agent_seq/_delib_seq`, `:183-203`). Restoring also **removes sessions created during the failed mutation** (`:311-317`) — this is what makes a failed `create_child_investigation` leave no orphan.
2. **Durable snapshot** — `_durable_snapshots` holds the last successfully persisted image; `_restore_durable` is the rollback for undecorated mutations and for validation failures in the no-persistence configuration (`:381-395`).
3. **Revision CAS** — §12.

**The ordering rule that makes zero-paper search safe.** `run_search` raises 503/422 at `:1542-1550`, **before** `state.papers = papers` / `state.searched = True` (`:1568-1570`) and before `_save_state` (`:1623`). With the decorator, the Investigation is restored to its pre-search state and stays editable and retryable.

**Single replica is a correctness constraint.** `_workspace_locks` are per-process `asyncio.Lock`s (`:266-267`) and every instance eagerly loads **all** workspaces at boot (`:246-258`). A second replica gets no mutual exclusion and diverges until a CAS failure forces a reload. The README's "Keep the service at one replica" is load-bearing.

### Frontend — `store/focused.ts` (165 lines)

`workspaceViewPatch(state, view, monotonicPerspectives = false)` is the single merge point:

1. **Revision guard** — drop when `sameWorkspace && currentWorkspace.revision > view.workspace.revision`. **Strict `>`**, so equal revisions always apply. This is why the hermetic E2E backend (revision permanently 0) works.
2. `activeChanged = state.sessionId !== view.active.id`; `currentSession` is consulted only when the workspace matches and the active Investigation did not change.
3. **Addition-monotonic rejection** (monotonic mode only): if any **confirmed** current Perspective's `origin` is absent from the response's origins, discard the whole view. **The real stale-response defence is origin-set-based, not revision-based** — state it that way; the digest's "rejects stale add snapshots … where revision remains 0" is accurate but imprecise.
4. **Pending preservation:** optimistic Perspectives with an unrepresented `origin` are re-appended.
5. On `activeChanged`: `stage` → `deliberation` when `active.deliberations.length > 0` else `extraction`; `pickedQueries`, `openClusterId`, `openPaperId` reset.

`workspaceViewSet` = plain merge; `perspectiveViewSet` = monotonic, exactly one caller (`generatePerspective`). `optimisticPerspectiveAdd` refuses a duplicate when a Perspective with the same `origin` and `!evolved` exists. `optimisticPerspectiveRemove` removes by id only.

### Frontend — `hooks/use-focused.ts` (565 lines)

- `exclusive(label, op)` throws `"Wait for the current action to finish."` when `busy !== null`. **Every mutation except `generatePerspective` goes through it.**
- `requestView(path, init, applyView = workspaceViewSet)` catches `ApiError 409`, refetches `workspaces/<id>`, applies it through `workspaceViewSet`, then rethrows. (L16: it does not use the caller's `applyView`.)
- `generatePerspective` is the only concurrent mutation. It still refuses to start while `busy !== null`; validates the cluster and that no non-evolved Perspective owns that origin; builds `optimistic:${session.id}:${clusterId}` with `color "#98a2b3"`, deduped+sorted `sources`, `panel_cycle = deliberations[0]?.completion_history.length ?? 0`; on failure removes **only** its own card.
- `parseResearchQuestions`: strips `-`/`*`/`•`/`1.`/`1)`; a blank line flushes; a line joins the previous when the previous ends in `WRAPPED_LINE_END` (`[,;:]` or a trailing function word from `a|an|and|as|between|by|for|from|in|of|on|or|than|that|the|to|which|who|whose|with|without`) **or** the new line starts lowercase; a trailing `?`/`？` (with optional closing bracket/quote) force-flushes.

**Pending-perspective guards are exhaustive at three sites** (`[V]`): header (`Start over`, `Open current Investigation`, primary action), `Back to panel`, and the per-Perspective remove `✕`. Everything else gates on `busy` only — safe today by emergent modal serialization, not by design (L14).

## 12. Persistence and security

**Contract.** `WorkspacePersistence` Protocol (`focused/persistence.py:25-41`): `load()`, `create(ws, invs)`, `save(ws, invs, *, expected_revision)`, `delete(id, *, expected_revision)`. Both implementations persist the **complete workspace aggregate**, never a partial write.

**Revision protocol** (`_persist_workspace`, `service.py:381-410`):

```
expected = workspace.revision
workspace.revision += 1
validate (pydantic round-trip of workspace + every investigation)
persistence.save(..., expected_revision=expected)
  ├─ PersistenceConflict → revision rolled back, _reload_workspace(), raise WorkspaceConflict (HTTP 409)
  ├─ other Exception     → revision rolled back, _restore_durable(), re-raise
  └─ success             → _remember_durable()
```

Both backends refuse a save whose revision does not advance exactly once (`persistence.py:394-395`, `supabase_persistence.py:163-164`) and both compare-and-set on `(workspace_id, revision)`, so a stale process can neither overwrite nor resurrect (`persistence.py:404-419,428-441`, `supabase_persistence.py:160-183`). `_reload_workspace` (`service.py:332-356`) re-loads **all** workspaces, drops every in-memory session of the conflicted workspace and rebuilds it; if the workspace vanished it evicts workspace, locks and durable snapshot. Every `WorkspaceConflict` response therefore reflects the durable winner, not the losing in-memory mutation.

**SQLite backend.** Three tables created at construction: `focused_workspaces(workspace_id pk, revision, payload)`, `focused_investigations(investigation_id pk, workspace_id, payload)` + index, `focused_quarantine(kind, record_id) pk` (`:49-77`). In-place migration adds a missing `revision` column with `alter table … default 0` (`:78-88`). `pragma busy_timeout = 5000`; writes use `begin immediate` with explicit rollback. `_write_investigations` upserts each member, **deletes members no longer in the set** (`:361-386`), and refuses to steal an id owned by another workspace. **Quarantine on load** (`:172-330`) moves a malformed record to `focused_quarantine` and deletes it rather than crashing boot — triggers: payload fails validation, row id ≠ payload id, row revision ≠ payload revision, workspace references missing or foreign investigations, lineage errors, or an investigation unreachable from a valid workspace. `_lineage_error` (`:141-170`) rejects a root with a parent, a parentless child, a self-parent, an out-of-workspace parent, and **cycles**. Exception: a doubly-owned investigation raises `ValueError` at boot instead (L6).

**Supabase backend.** One JSONB row per workspace: `focused_workspace_snapshots(workspace_id pk, revision, payload{workspace, investigations[]})`. It **reuses the SQLite class's static validators** — `FocusedPersistence._validate_membership`, `._lineage_error`, `._reason` (`supabase_persistence.py:51,84-85,101`) — so one implementation enforces lineage for both backends. CAS is `.eq('workspace_id',…).eq('revision', expected)` with `ReturnMethod.representation` and a strict `len(response.data) != 1` check. Client uses `auto_refresh_token=False, persist_session=False` (`:38-44`).

**Migration** `supabase/migrations/20260822180000_focused_workspace_snapshots.sql`: both tables, an `updated_at` trigger with `set search_path = ''`, RLS **enabled** on both, all privileges revoked from `anon`/`authenticated` and granted to `service_role` only. There are deliberately **no RLS policies** — with RLS on and no policy, only `service_role` (which bypasses RLS) can read or write. That is the intended posture for a server-key-only service. **Do not "fix" the missing policies.**

SQLite → Supabase path: `scripts/import_focused_sqlite_to_supabase.py` → `agora.focused.importer.import_snapshots`, with `--dry-run` and created/skipped reporting.

**Auth.** `src/agora/api/proxy_auth.py`: `PUBLIC_PATHS = frozenset({"/api/v1/focused/health"})`; header `x-agora-proxy-token`; `secrets.compare_digest`; the gate applies **only when a token is configured** and **only to paths starting `/api/v1/`**. With `AGORA_PROXY_TOKEN` unset the whole API is open — deliberate for local dev (`tests/test_proxy_auth.py:47` asserts it), and the reason local commands pass `AGORA_PROXY_TOKEN=`. Guardrail: `load_settings()` (`src/agora/config/settings.py:130-152`) **raises `ConfigurationError` at import** when `AGORA_PERSISTENCE=supabase` and any of `SUPABASE_URL` / `SUPABASE_SECRET_KEY` / `AGORA_PROXY_TOKEN` is missing, so Supabase mode cannot boot unauthenticated (covered by `tests/test_supabase_persistence.py:182,191`).

**Export.** `export_workspace` (`service.py:2587-2600`) emits `schema: 'agora-hypothesis-workspace'`, `schema_version: 5`, the workspace, and every Investigation in full. `GET /workspaces/{id}/export` (`api/focused.py:488`) is **still live**; PR #8 removed only the participant-facing UI action. It calls `_ensure_workspace_idle`, so an export can 409 during a mutation.

## 13. Deployment topology

```
Browser
  → Vercel Next.js  (project root = web-ui)
      → /api/focused/[...path]      server-only route, Node runtime
         attaches header x-agora-proxy-token
  → Railway FastAPI  Docker, uvicorn agora.focused_app:app
      ProxyTokenMiddleware gate on /api/v1/*
  → Supabase   AGORA_PERSISTENCE=supabase, service-key writes
```

- **Docker** `[V]`: `FROM python:3.11-slim`; `ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1`; `COPY pyproject.toml README.md ./` then `COPY src ./src`; `pip install .`; `CMD ["sh","-c","uvicorn agora.focused_app:app --host 0.0.0.0 --port ${PORT:-8000}"]`.
- **`README.md` is a build input.** `pyproject.toml` declares `readme = "README.md"` and hatchling reads it. Renaming or deleting the README breaks the **image build**, not just docs.
- **`railway.toml`** `[V]`: `builder = "DOCKERFILE"`, `healthcheckPath = "/api/v1/focused/health"`, `healthcheckTimeout = 30`, `restartPolicyType = "ON_FAILURE"`, `restartPolicyMaxRetries = 3`.
- **`.dockerignore`** excludes `web-ui`, `.venv`, `.git`, `artifacts`, `.cache`, `node_modules`, `.env*` (keeps `.env.example`).
- **Vercel** (`web-ui/vercel.json`): `framework: nextjs`, `installCommand: pnpm install --frozen-lockfile`, `buildCommand: pnpm build`. `--frozen-lockfile` means **any `web-ui/package.json` edit without a regenerated `pnpm-lock.yaml` fails the Vercel install step.** Frontend deps *are* reproducible; backend deps are **not** (follow-up #1). `next.config.ts` sets `distDir: process.env.NEXT_DIST_DIR ?? ".next"` — the hook that keeps the Playwright build out of `.next`. `pnpm-workspace.yaml` declares `allowBuilds: msw, sharp, unrs-resolver`; a new dependency with a postinstall script needs an entry there or pnpm silently skips its build. `maxDuration = 300` exceeds Hobby-plan limits; the successful `09dd11f` deploy implies the tier permits it — **do not lower it casually**, live searches and panel rounds are long-running.
- **Deploy-ordering rule.** Both platforms build on every push, but only a diff touching `Dockerfile`, `pyproject.toml`, `railway.toml`, or `src/**` requires Railway green *before* you exercise the UI. A `web-ui/**`-only change (the #8 class) is satisfied by Vercel alone. **Vercel becomes ready before Railway**; do not exercise a new frontend mutation until the matching Railway deployment is `SUCCESS` *and* its logs show `Application startup complete`. The `/health` endpoint returns a bare `{"status":"ok"}` with no commit or readiness detail, which is precisely why this gate is manual (follow-up #12).
- **Railway resource ids** (non-secret): project `4fe1b638-9ab6-4cc3-b0bf-0a7f856ef4bc`, service `dc9febe4-a590-46e4-8329-05f2d8dd2c56`, production environment `fc8fd145-0890-45aa-9485-6cb66fc31790`. `[LIVE-ONLY]` — no Railway or Vercel identifier appears anywhere in the tree; confirm via CLI before relying on them.
- **Production frontend:** `https://hypothesis-studio.vercel.app`. `[LIVE-ONLY]`

### Triage table

| Symptom | First diagnostic | Cause / action |
|---|---|---|
| Healthcheck fails within 30 s; container restarts ≤3× then stops | `logs --deployment` | Almost always `load_settings()` raising `ConfigurationError` **at module import** (`focused_app.py` calls it at module scope, before `lifespan`) — i.e. `AGORA_PERSISTENCE=supabase` with a missing `SUPABASE_URL` / `SUPABASE_SECRET_KEY` / `AGORA_PROXY_TOKEN`. Fix the variable, redeploy. |
| `Killed` in logs, memory near 1024 MB | `metrics --memory` after drain | Verify `Dockerfile` CMD is still `agora.focused_app:app` and the thread-cap `ENV` block survives; run `tests/test_standalone_api.py`. A regression here means something re-imported the legacy stack. |
| Browser sees 503 `"The production API proxy is not configured."` | Vercel project env | `API_URL` or `AGORA_PROXY_TOKEN` missing/renamed. Env changes need a redeploy to take effect. |
| Browser sees 502 `"The API is unavailable."` | Railway status | Backend down or domain changed. |
| Browser sees 401 | token pair | `AGORA_PROXY_TOKEN` differs between Vercel and Railway. Re-sync; never echo the value. |
| CORS error in console | `AGORA_CORS_ORIGINS` | Default when unset is `["http://localhost:3000"]`. Production must list the Vercel origin. The browser normally talks only to Vercel, so a CORS failure implies something is calling Railway directly. |
| Bad **backend** release | — | Prefer Railway's *redeploy this previous deployment*, which reuses the built image. Because backend deps are unpinned, **rebuilding an older commit is not guaranteed to reproduce what originally ran there.** `git revert` of the merge commit is the source-level fallback. |
| Bad **frontend** release | — | Vercel *Promote to Production* on the prior deployment — instant and image-exact. |

## 14. Live evidence — all dated, all will drift

| When | Fact | Tag |
|---|---|---|
| 2026-08-23 12:16:23 −07:00 | `main` = `09dd11f` = `origin/main`, merge of PR #8. Re-verified 12:41. | `[V]` |
| 2026-08-23 | Railway deployment for `09dd11f` is **SUCCESS**. | `[LIVE 08-23]` |
| 2026-08-23 | Railway memory over a clean five-minute window: **191.72 MB (18.7% of 1024 MB)** idle on `09dd11f`. | `[LIVE 08-23]` |
| 2026-08-23 | Railway memory **286.19 MB (27.9%)** after a real 20-paper / 5-cluster production demo smoke on `da5407f`. No `Killed`, no restart. | `[LIVE 08-23]` |
| 2026-08-23 | Post-rollout idle before the smoke: ~176 MB. | `[HIST]` |
| pre-PR #7 | Legacy OOM era: **1007 MB of 1024 MB** (98.4% current, 1911 MB overlap max), `Killed` + restart in logs. | `[HIST]` |
| 2026-08-23 | Local separate-process RSS: `import agora.app` ≈ **780 MB**; focused import-only ≈ **103 MB**; focused + sklearn ≈ **243 MB**. Measured on CPython 3.14, not 3.11. | `[HIST]` |
| 2026-08-23 | Vercel and Railway both deployed `09dd11f` successfully. | `[LIVE 08-23]` |
| 2026-08-23 | Production header showed Investigation map, `Start over`, and the single primary action; `Workspace menu` and `Export workspace` absent. | `[HIST]` browser smoke |
| 2026-08-23 12:41 | Local: hermetic E2E API on `127.0.0.1:8000` (health 200), legacy `agora.app` on 8001 from the `/tmp` checkout, stale-checkout web on 3002, unrelated Logit on 3001, **port 3000 free**. | `[V]` |
| 2026-08-23 12:42 | `web-ui/`: 20 `.next*` dirs, ~1.1 GB; no `playwright-report/` or `test-results/`. | `[V]` |

**Rules for these numbers.** Do not restate a memory figure as current. Re-measure with §16. Railway metrics briefly sum old and new containers during a rollout, so a transient reading above the limit during overlap is not the steady state — wait for drain, run one real request, then measure.

**Historical workspace ids** (`[HIST]`, for archaeology only): `b17856580abf494cada7ece0cb192ac1` (PR #6 repair, later deleted by the user); `520e8e6cf6464a8fa2b2b2b19e02f385` (affected user workspace) with child `89119d5c45fa4f10a33d4ecdb05d8b89` and parent root `ea05af4f97014ad489205ba903233d2f`.

## 15. Verification matrix

### Backend — 60 tests across 7 test files `[V]`

| File | Tests | Defends |
|---|---|---|
| `tests/test_focused.py` | 21 | query compaction/relaxation incl. acronyms and `COVID-19` (`:105`); Perspectives join an open deliberation without reset and end once (`:145`); demo search reaches every default question (`:261`); sealed-literature refusal (`:292`); exactly four abstract-grounded facets (`:312`); facets map only to abstract sentences (`:333`); framing/position coupling (`:353`); difference ≠ disagreement (`:364`); unsettled fallback without forced conflict (`:400`); round-summary normalization (`:439`); consensus-only hypothesis (`:473`); typed live-provider failure (`:508`); full round records resolution/metrics/rating/child branch (`:520`); **child research continues existing deliberation** (`:612`); hypothesis progress across rounds (`:765`); unchanged consensus creates no pending update (`:803`); 1–2 facet enforcement (`:849`); semantic metric direction (`:877`); consensus round evolves working hypothesis (`:914`); edited facets not misrepresented as abstract provenance (`:987`) |
| `tests/test_focused_lineage.py` | 20 | branch from last applied checkpoint while an update is pending (`:100`); checkpoint-vs-applied distinction (`:196,247,276`); `edit_applied` provenance (`:314`); promote/merge/archive + question closure (`:384,496`); merge blocked by pending update (`:463`); duplicate open questions suppressed (`:529`); **concurrency and rollback** (`:562,623,698`); >3 agents (`:734`); SQLite reload (`:753`); quarantine of malformed/orphan/cyclic records (`:789,824,963`); revision CAS for overwrite and delete (`:870,909`); persistence-less validation rollback (`:945`) |
| `tests/test_focused_hermetic.py` | 8 | question reach/miss (`:234`); relaxed retry on a zero-result prose query (`:285`); provider failure surfaced (`:303`); **empty live search rolls back and can retry** (`:323`); ungrounded facet blanked (`:367`); metric explicitly unavailable (`:411`); citation allow-list (`:436`); one full-paper search per query (`:458`) |
| `tests/test_supabase_persistence.py` | 5 | snapshot round-trip + revision conflict (`:104`); quarantine of malformed rows (`:136`); idempotent SQLite import (`:157`); credential and proxy-token config gating (`:182,191`) |
| `tests/test_proxy_auth.py` | 3 | 401 without token (`:22`); public health path (`:41`); disabled locally (`:47`) |
| `tests/test_standalone_api.py` | 2 | `:15` **subprocess** import of `agora.focused_app` asserts `torch` **and** `sklearn` absent; `:33` in-process demo create → suggest-queries → search, then re-asserts **`torch`** absent after the search |
| `tests/test_openrouter_schema.py` | 1 | strict JSON-schema structured outputs (`:19`) |
| `tests/e2e_server.py` | 0 | Not a test file. ~10-line hermetic ASGI app: `FastAPI()` + `app.state.focused = FocusedPanelService()` + `include_router(focused_router, prefix="/api/v1")`. **No persistence argument ⇒ purely in-memory ⇒ demo data resets on restart and workspace `revision` stays 0.** Both properties are load-bearing. |

**Be precise about the OOM guard.** The **subprocess** test is import-only and asserts both `torch` and `sklearn` absent. The **post-search** assertion is in-process and asserts only `torch` — correctly, because **sklearn does load during a search**. Neither test exercises `_embedding_clusters` and neither enforces a numeric memory budget. Do not describe it as a memory-budget test.

### Frontend — 14 Playwright tests, `web-ui/e2e/investigation-lineage.spec.ts` `[V]`

| # | Line | Title |
|---|---|---|
| 1 | 178 | joins wrapped lines into complete research questions |
| 2 | 210 | **keeps other matrix additions available while one loads** |
| 3 | 275 | **returns from a blocked research branch to its parent panel** |
| 4 | 360 | **continues an open question on the existing canvas** |
| 5 | 747 | promotes and merges versioned hypotheses through the workspace map |
| 6 | 833 | edits an applied hypothesis without reusing pending-update semantics |
| 7 | 868 | restores a workspace from its URL and deletes it on reset |
| 8 | 904 | automatically recovers from a brief API restart |
| 9 | 929 | preserves a workspace pointer across transient restore failures |
| 10 | 968 | **uses one primary header action without an export menu** |
| 11 | 985 | reloads the authoritative workspace after a revision conflict |
| 12 | 1035 | keeps repeated research problems from separate rounds |
| 13 | 1094 | allows a focused panel with more than three Perspectives |
| 14 | 1126 | keeps detail and branched map surfaces inside a mobile viewport |

Notable mechanics: **test 2** routes `POST …/perspectives`, holds response #1, proves the second `Add to matrix` is enabled and completes first, then releases #1 **out of order**, asserting both Remove buttons and "Perspective matrix (2)". **Test 3** asserts `Back to panel` disabled during an in-flight add and re-enabled after, the `Add to panel` error "Return to the parent panel and end its current deliberation" dismissible via `Dismiss error`, and `integrated_into_parent_at` still null. **Test 4** is the long one: paper-modal 503 + Retry; `Continue` with no panel-selection dialog; moderator ordering by bounding box; a "2 of 4 parts changed" diff modal with Cancel then Apply; `Saved H1`; canvas Add Perspective preserving rounds; `End deliberation` → scoring 6/5; `Review` → `Start paper search` from the drawer; child branch; `Add to panel`; 2 panel nodes, 4 agent nodes, `H2` background `rgb(236, 253, 243)`, imported agent `x` right of the Research Problem node; "Complete a round with the added Perspectives before ending again." with `End deliberation` disabled; sidebar `borderLeftWidth 1px` / `overflowY auto`; independent sidebar scroll; nested paper-modal Escape ordering; zero React Flow / duplicate-key console warnings.

**Playwright config** (`web-ui/playwright.config.ts`): baseURL `http://localhost:3011`; `fullyParallel:false`, `workers:1`, `retries:0`, `forbidOnly:true`, timeout 90 s, expect timeout 10 s. Two webServers, both `reuseExistingServer:false`:
1. `<repo>/.venv/bin/uvicorn e2e_server:app --app-dir tests --host 127.0.0.1 --port 8011`, cwd = repo root, `PYTHONPATH=<repo>/src` injected **by the config itself** — so the `PYTHONPATH` landmine applies to `pytest`, not to E2E. But the `.venv` symlink dependency does apply (§2).
2. `pnpm dev -p 3011`, cwd `web-ui`, env `API_URL=http://127.0.0.1:8011`, `NEXT_DIST_DIR=.next-e2e`.

**Stable selector inventory.** `data-testid`: `panel-conversation-scroll`, `panel-chat-bar`, `working-hypothesis-sidebar`, `round-<n>-discussion`, `round-<n>-summary`, `changed-hypothesis-part-<key>`, `root-research-problem-node`, `agent-node-<iid>`, `panel-node-<id>`, `saved-hypothesis-node-<versionId>`, `research-problem-node-<questionId>`, `investigation-node-<id>`, `hypothesis-version-<id>`. Attribute: `[data-hypothesis-part="problem|previous_work|reasoning|hypothesis"]`. Named regions: `Queries searched`, `Investigation lineage`, `Hypothesis lineage`, `Moderator summary`, `Progress`. Named dialogs: `Focused panel`, `Apply hypothesis changes?`, `Rate this deliberation`, `Add a Perspective`, `Start over?`, `Remove Perspective?`, `Archive H2?`, `Abstract evidence`, `Compare H1 with H2`.

**Negative contracts that must stay at count 0:** `[data-testid^="round-result-node-"]`, `spinbutton "Panel size"`, `dialog "Choose the focused panel"`, `combobox "Switch Investigation"`, `button "Workspace menu"`, `button "Export workspace"`, text `Perspective matrix (0)`, text `None yet — generate one from a cluster.`, the `Investigation map` button when only one Investigation exists, and `Initial Investigation` on the detail screen.

**Highest-value regression targets if the frontend changes:** tests 2 and 3 (concurrency), test 4 (canvas topology — the only test asserting imported-agent placement, panel-node count, the green node colour, and the zero-console-warning contract), test 10 (header shape), test 14 (responsive).

**All 14 tests run against the hermetic backend**, and that test double has already diverged from production semantics once (revision permanently 0). Treat green E2E as evidence about the frontend contract, not about live provider behavior.

## 16. Command cookbook

### Read-only state checks — zero side effects

```sh
cd /Users/bg/windsurf/hypothesis-studio
git status --porcelain=v1 -b            # pre-merge: docs/session-handoff + .handoffs/.venv; post-merge: main + .venv
git rev-parse HEAD origin/main          # must print the same SHA twice
git log --oneline --decorate -5
git show --stat --oneline HEAD
git check-ignore -v .venv               # exits 1 — the symlink is NOT ignored
```

**Never `git add -A`.** Stage explicit paths.

### Backend verification — both env prefixes are mandatory

```sh
cd /Users/bg/windsurf/hypothesis-studio
PYTHONPATH=/Users/bg/windsurf/hypothesis-studio/src AGORA_PROXY_TOKEN= .venv/bin/pytest
.venv/bin/ruff check src/agora/focused_app.py src/agora/focused tests
```

`PYTHONPATH` overrides the `/tmp` editable path. `AGORA_PROXY_TOKEN=` clears any inherited token so the open-API assertion at `tests/test_proxy_auth.py:47` holds. Omitting either is the documented route to confusing failures. Expect **60 passed** plus one Starlette/httpx deprecation warning. `README.md:202` suggests the broader `ruff check src tests`, which also sweeps legacy `src/agora/workflow` and `src/agora/api/router.py`; the narrower form above is what recent PRs actually used.

### Frontend verification

```sh
cd /Users/bg/windsurf/hypothesis-studio/web-ui
pnpm exec tsc --noEmit     # there is NO "typecheck" script — this form is correct
pnpm lint
pnpm build
pnpm test:e2e              # 14 tests, via scripts/run-e2e.mjs
```

A fresh machine additionally needs `pnpm exec playwright install chromium` once. **Never run `pnpm exec playwright test` directly.** If it already happened:

```sh
git checkout -- web-ui/next-env.d.ts web-ui/tsconfig.json
rm -rf web-ui/playwright-report web-ui/test-results
```

Note `pnpm test:e2e` currently swallows CLI arguments, so there is no supported single-test run (follow-up #10).

### Canonical local run — UI 3000 / API 8000

```sh
# stop whatever holds 8000 first (today: the hermetic E2E app, PID 23178)
cd /Users/bg/windsurf/hypothesis-studio
PYTHONPATH=/Users/bg/windsurf/hypothesis-studio/src \
  .venv/bin/uvicorn agora.focused_app:app --port 8000     # focused entrypoint, NOT src/agora/app.py

cd web-ui && pnpm dev                                     # 3000
```

Health <http://localhost:8000/api/v1/focused/health> → `{"status":"ok"}`. UI <http://localhost:3000> redirects to `/focused`. **Only 3000/8000 may be presented as project URLs.** Any other port is temporary, must be labeled as such, and must be stopped before delivery. If you demo from `tests/e2e_server.py` because no keys are available, **disclose that its state is in memory and resets on restart.**

### Deployment status — read-only

```sh
RW="-p 4fe1b638-9ab6-4cc3-b0bf-0a7f856ef4bc -s dc9febe4-a590-46e4-8329-05f2d8dd2c56 -e fc8fd145-0890-45aa-9485-6cb66fc31790"

npx -y @railway/cli deployment list $RW --limit 2 --json          # status + commit SHA
npx -y @railway/cli logs <deployment-id> $RW --deployment -n 200  # startup / Killed lines
npx -y @railway/cli metrics $RW --memory --since 5m --json        # steady-state RSS
```

Use `metrics` for memory, not logs. **Never pipe `railway variables` into a transcript — it prints secret values.**

### Production smoke — read-only HTTP

```sh
curl -s https://<railway-domain>/api/v1/focused/health                        # {"status":"ok"}
curl -i https://<railway-domain>/api/v1/focused/workspaces/example            # MUST be 401
curl -i https://hypothesis-studio.vercel.app/api/focused/workspaces/example   # expect 404
```

The 401 proves the proxy gate is live — **a 200 there is a security regression** (token unset on Railway). The 404 through Vercel proves the token pair matches and traffic reaches FastAPI. 503 ⇒ Vercel env vars missing; 502 ⇒ Railway unreachable.

### Deploy checklist

**Before:** identical `HEAD`/`origin/main`; clean tree apart from `?? .venv`; classify the diff (touches `Dockerfile` / `pyproject.toml` / `railway.toml` / `src/**` ⇒ Railway rebuild mandatory); if `web-ui/package.json` changed, confirm `pnpm-lock.yaml` was regenerated; run backend **and** frontend verification in full, not a narrowed subset; if startup imports could be affected, confirm `tests/test_standalone_api.py` passes; confirm nothing in `focused_app`'s import closure newly reaches `agora.app`, `agora.workflow`, `agora.api.router`, `dspy`, `torch`, or `sklearn` **at import time**.

**After (ordering is load-bearing):** wait for Railway `SUCCESS` **and** `Application startup complete` before exercising a new frontend mutation; confirm the deployment's commit SHA; health check; auth check (401 direct, 404 proxied); wait for the old container to drain, run one **real** request, then measure memory; confirm no `Killed` and no restart; browser-check production for any UI change and **delete any temporary production workspace in a `finally`**.

### Browser automation that works

Spawn `/Applications/Google Chrome.app/Contents/MacOS/Google Chrome` with `--headless=new` and an explicit path. Without the explicit path the browser device fails with `cmux browser.open_split did not return a surface_id`. Use `tab.evaluate` to extract compact JSON summaries rather than reading whole workspace payloads.

## 17. Recent PR chronology

| PR | Merge | Authored (−07:00) | Sources | Files, diffstat | Scope |
|---|---|---|---|---|---|
| #8 | `09dd11f` | 2026-08-23 12:16:23 | `3302c96` (12:15:28) | 4 files, **+53 / −151** | **Frontend only.** `features/focused/index.tsx`, `hooks/use-focused.ts`, `e2e/investigation-lineage.spec.ts`, `features/focused/DESIGN.md`. Vercel alone gates it. |
| #7 | `da5407f` | 2026-08-23 11:53:52 | `e32100d` (11:48:30), `575c45d` (11:48:38), `5e16e99` (11:53:02) | 11 files, **+512 / −118** | **Backend + Docker.** New `src/agora/focused_app.py` (+87), `Dockerfile`, `src/agora/focused/service.py`, `tests/test_standalone_api.py`, `web-ui/src/hooks/use-focused.ts`, `web-ui/src/store/focused.ts`. Railway rebuild required. |
| #6 | `349c2f5` | 2026-08-23 | `30dd480` | 9 files, **+406 / −74** | Backend + frontend. `stage-extraction.tsx`, `hooks/use-focused.ts`, service/agents. |
| #5 | `c63d17d` | earlier | `b8bfd18` … `5ed260d` | 12 files, **+1436 / −352** | PI canvas refinements — the cumulative-Canvas continuation contract. |

PR #4 was closed; its README refresh was carried into PR #5.

## 18. Files and symbol index

### Backend `[V]` line counts

| File | Lines | Role |
|---|---|---|
| `src/agora/focused/service.py` | **2600** | All domain behavior, concurrency, persistence orchestration. 98 KB — the place every feature currently lands. |
| `src/agora/focused/agents.py` | **1546** | Prompts, structured calls, query compaction (`:113-130`), sentence mapping. |
| `src/agora/focused/models.py` | **577** | **Read this first.** Authoritative domain + wire contracts + the five validators. |
| `src/agora/api/focused.py` | 508 | HTTP shell; error translation `:46-83`; health `:39-41`; export route `:488`. |
| `src/agora/focused/persistence.py` | 442 | Protocol `:25-41`; SQLite impl; quarantine `:172-330`; lineage `:141-170`; shared static validators. |
| `src/agora/focused_app.py` | **87** | Production composition root. |
| `src/agora/app.py` | 98 | **Legacy. Never run in production.** |
| also | — | `focused/supabase_persistence.py`, `focused/demo_data.py`, `focused/retrieval.py`, `focused/provider.py`, `focused/importer.py`, `api/proxy_auth.py`, `api/dependencies.py`, `api/router.py` (legacy), `config/settings.py:130-152`, `db/vector.py`, `scripts/import_focused_sqlite_to_supabase.py`, `supabase/migrations/20260822180000_focused_workspace_snapshots.sql` |

**Key service symbols** (`service.py`, `[V]`): `SessionError` `:70`, `WorkspaceConflict` `:76`, `_serialized_session_mutation` `:84`, `_serialized_parent_mutation` `:109`, `_Session` `:145` (`snapshot` `:183`, `restore` `:192`), `FocusedPanelService` `:221`, `_ensure_workspace_idle` `:358`, `_validated_workspace_state` `:368`, `_persist_workspace` `:381`, `_record_hypothesis` `:501`, `_address_contributing_questions` `:576`, `create_workspace` `:614`, `create_child_investigation` `:659`, `integrate_child_investigation` `:704`, `set_question_status` `:883`, `promote_hypothesis` `:921`, `merge_hypotheses` `:944`, `archive_hypothesis` `:1027`, `update_brief` `:1095`, `suggest_queries` `:1143`, `_live_retrieve` `:1249`, `_kmeans_clusters` `:1306`, `_embedding_clusters` `:1326`, `_clustering_diagnostics` `:1362`, `_validate_facet_source` `:1420`, `run_search` `:1460`, `_ensure_perspective_agent` `:1632`, `generate_perspective` `:1662`, `remove_perspective` `:1758`, `_same_hypothesis` `:1857`, `create_deliberation` `:1877`, `_canonical_citations` `:1912`, `_embed_metric_texts` `:1947`, `_round_metrics` `:1972`, `run_round` `:2064`, `complete_deliberation` `:2361`, `rate_deliberation` `:2402`, `confirm_deliberation_hypothesis` `:2420`, `save_deliberation_hypothesis` `:2483`, `chat` `:2523`, `export_workspace` `:2587`.

### Frontend — the whole participant surface is 13 files `[V]`

| File | Lines | Role |
|---|---|---|
| `web-ui/src/features/focused/stage-deliberation.tsx` | **2241** | Canvas, node types, topology memos, **and `PanelDrawer` at `:619`**. There is no `panel-drawer.tsx`. |
| `web-ui/src/features/focused/stage-extraction.tsx` | 819 | Brief, queries, clusters, matrix. `ClusterRow` `integrated` at `:608` (L12). |
| `web-ui/src/features/focused/index.tsx` | 627 | `FocusedWorkspace`, header, one-primary-action matrix, gates at `:105-116`. |
| `web-ui/src/hooks/use-focused.ts` | 565 | `api()`, `exclusive()`, `requestView()`, every mutation, `parseResearchQuestions`, optimistic id at `:266`. |
| `web-ui/src/features/focused/workspace-map.tsx` | 531 | Investigation map, hypothesis lineage. |
| `web-ui/src/features/focused/ui.tsx` | 397 | `ModalShell`, `Button`, `Spinner`, **`useDialogSurface`** (focus trap / Escape stack / scroll lock), dead `ListRow` at `:341`. |
| `web-ui/src/store/focused.ts` | **165** | `workspaceViewPatch` and the three merge modes. Small and load-bearing — read it in full. |
| plus | — | `types/focused.ts`, `app/api/focused/[...path]/route.ts`, `app/focused/{layout,page}.tsx`, `app/{layout,page}.tsx` |

Other: `web-ui/e2e/investigation-lineage.spec.ts`, `web-ui/scripts/run-e2e.mjs`, `web-ui/playwright.config.ts`, `web-ui/next.config.ts`, `web-ui/vercel.json`, `web-ui/eslint.config.mjs`, `web-ui/pnpm-workspace.yaml`, `web-ui/src/features/focused/DESIGN.md`.

**Before this handoff, tracked markdown was exactly two files** `[V]`:
`README.md` and `web-ui/src/features/focused/DESIGN.md`. This hidden handoff and
its companion reflection add two more. The older two both have stale sections
(§19).

## 19. Stale docs and contradictions — resolved

Order of authority: **current repo code and git history > audits > session digest > agent memory > README/DESIGN.**

### `README.md`

1. **`:80` instructs `.venv/bin/fastapi dev src/agora/app.py --port 8000`** `[V]` — the legacy module that eagerly imports `dspy` and `Runner`. This directly contradicts the invariant "production must not import `agora.app`", produces a ~780 MB local process, and **masks any regression that re-imports the ML stack**. It is silent because the health URL resolves under **both** apps — and in fact a process matching this command is running right now on port 8001 (§2). **The single most misleading line in the repo.** Correct: `uvicorn agora.focused_app:app --port 8000`.
2. **`:201` `.venv/bin/pytest -q` omits both required env prefixes** `[V]`, so it imports `agora` from `/tmp` and can inherit a stray token.
3. **`:202` `ruff check src tests`** is broader than what recent PRs ran; it sweeps legacy `src/agora/workflow` and `src/agora/api/router.py`.
4. **`:210-218` Playwright coverage list is PR #5-era** — it claims "export failure and retry", "archive confirmation and restore", "destructive reset", "keyboard dialog behavior", and never mentions the four contracts added by PRs #6–#8. The suite now includes `"uses one primary header action without an export menu"`, the **opposite** of an export-retry test.
5. **§Verification omits `pnpm exec tsc --noEmit`**, which every recent PR actually ran.
6. **Naming drift.** The package is still `agora` / `agent-agora-study-ui`, and the README describes `OPENAI_API_KEY` as "Agent Agora's evidence index" while the product is Hypothesis Studio. Harmless, confusing.
7. **`README.md` is a Docker build input** (`pyproject.toml` `readme = "README.md"`). Rewriting the content is safe; renaming or deleting the file breaks the image build.

### `web-ui/src/features/focused/DESIGN.md`

1. **The type scale is factually wrong.** DESIGN.md claims "11 micro/meta, 12 labels/body-sm, 13 body/default, 14 emphasis, 16 modal titles, 22 hero. **No other sizes.**" The tree has about 60 noncanonical size occurrences, including 9, 9.5, 10, 10.5, 11.5, 12.5, 15 and 17 px — e.g. `workspace-map.tsx:181` `text-[17px]`, `:214` `text-[15px]`, `:266` `text-[9px]`, `:429-449` `text-[9.5px]`; `stage-deliberation.tsx:838/856` `text-[15px]`, many `text-[10.5px]`, `TurnBubble` body `text-[12.5px]`; `stage-extraction.tsx:686` `text-[10.5px]`. A fresh agent will trust this doc and act on it. Either the doc or the code must move.
2. **`ModalShell` widths** — documented as "640px/92vw" only; `ui.tsx` also has a `wide` variant `w-[min(760px,92vw)]` used by `PaperModal`.
3. **`ListRow` is documented (`:114`) and exported (`ui.tsx:341`) but referenced nowhere.** Dead code.
4. **`useDialogSurface` is undocumented** despite being the load-bearing focus-trap / Escape-stack / scroll-lock primitive behind every modal and the drawer.
5. **"Every list row has exactly one affordance, visible without hover" is false.** `ClusterRow` exposes four facet-edit buttons, three paper buttons, per-facet "View abstract evidence", and `Add to matrix`.
6. **The header description is incomplete** — it omits the `Open current Investigation` primary on the map screen and the `Continued` / `Extraction` labels.
7. **Accurate and worth keeping:** the 1180px drawer, the "no second Investigation picker" rule, the persisted `Queries searched` record, the 36–45 ms list stagger (code uses 36/42/45 ms), `h-7`/`h-8` control heights (`btn-sm 28px` / `btn-md 32px` in `app/focused/layout.tsx`), and the full `prefers-reduced-motion` escape hatch.

### Corrections to the session digest

| Digest claim | Verdict |
|---|---|
| Code baseline `09dd11f`, then-current tree clean except untracked `.venv`; merge/source commits; "60 passed"; "14 passed"; Docker entrypoint; health path | **Accurate**, all independently re-verified `[V]`. A docs-only descendant may now be `HEAD`. |
| "`.venv` executables resolve packages from `/private/tmp/…`" | **Understated.** `.venv` is a **symlink into `/tmp`**, not a local venv. Adds: Python 3.14.6 vs prod 3.11; a `/tmp` purge breaks the **Playwright suite** too; and `git check-ignore` confirms the symlink is **not** ignored, so `git add -A` would commit it. `[V]` |
| "`.venv` should eventually be ignored" | Half-wrong in both directions: it is *not* currently ignored, and the real defect is the foreign wrong-interpreter venv, not the ignore rule. Fix both (follow-ups #4, #5). |
| "post-search subprocess test asserts Torch stays unloaded" | **Mislabeled.** The subprocess test is import-only (asserts torch **and** sklearn); the post-search assertion is in-process and asserts **only** torch. `[V]` |
| "focused import … did not import Torch/sklearn" | **True only at import time.** sklearn is a real production runtime dependency, imported lazily in clustering and metrics. |
| "Only independent Perspective generation bypasses `exclusive`" | **Frontend-only claim.** Nothing in `service.py` relaxes serialization; two adds queue on the workspace lock with an LLM call inside it (L5). |
| "`perspectiveViewSet` rejects stale add snapshots, including … revision 0" | Accurate but imprecise. The revision guard is strict `>` so it never fires at revision 0; the actual rejection is the **origin-set comparison** in the monotonic branch. |
| "header transitions, removals, and Back to panel remain blocked while optimistic cards exist" | Accurate and **exhaustive** — those are the *only* three guards. Canvas and drawer navigation are safe today by emergent modal serialization (L14). |
| "Export workspace is not participant-facing" | Accurate, and **≠ removed.** `GET /api/v1/focused/workspaces/{id}/export` is live at `api/focused.py:488`. |
| Memory figures 176 / 286.2 / 1007 MB | **Historical.** Point-in-time; re-measure, do not restate. |
| Railway project/service/environment UUIDs; `hypothesis-studio.vercel.app` | **`[LIVE-ONLY]`.** No Railway or Vercel identifier appears anywhere in the tree. Confirm via CLI. |
| "`railway.toml` Config as Code deprecated, migrate before 2026-12-01" | **`[LIVE-ONLY]`.** The file carries no marker. Platform-side claim only. |
| Zero-paper rollback ordering; revision CAS; Docker entrypoint + thread caps; Supabase credential/proxy gating | **No contradiction found.** All hold at HEAD. |
| One audit table listing `test_focused.py` as 15 tests | **Wrong; it has 21.** Total is 60 either way. `[V]` |
| An earlier review claiming `.venv` **is** gitignored | **Wrong.** `git check-ignore -v .venv` exits 1. `[V]` |

### Agent-memory contamination

Memory carries ExPerspect/MARS-era rules from `github.com/katjpg/mars`. Two that will actively mislead you here: **"the panel drawer is 760px/96vw"** (in *this* repo it is `w-[min(1180px,96vw)]`), and MARS-specific participant-copy conventions. Confirmed-good memory: the focused entrypoint requirement, PR #8's single primary action, and the canonical 3000/8000 ports.

## 20. First fifteen minutes

1. `cd /Users/bg/windsurf/hypothesis-studio` — **not** `mars`. Confirm `git rev-parse HEAD origin/main` prints the same SHA twice. Before this handoff is merged, `git status` shows branch `docs/session-handoff` plus `?? .handoffs/` and `?? .venv`; afterward it should show `main...origin/main` plus only `?? .venv`. Use `git diff --stat 09dd11f..HEAD` to distinguish the docs-only successor from product-code drift.
2. Read §2 in full. Understand that `.venv` is a `/tmp` symlink on Python 3.14 and that **`PYTHONPATH=…/src` is mandatory for `pytest`**. Never `git add -A`.
3. Read `src/agora/focused/models.py` end to end (577 lines). The five `model_validator`s are the real specification.
4. Read `service.py:84-142` (the two decorators) and `:368-410` (`_validated_workspace_state`, `_persist_workspace`). Every mutation's atomicity and every 409 comes from those ~90 lines.
5. Read `integrate_child_investigation` (`service.py:704-881`) — the only place two Investigations mutate together, and the source of most subtle behavior.
6. Read `web-ui/src/store/focused.ts` in full (165 lines) and `hooks/use-focused.ts:96-99` (`exclusive`) plus `:250-300` (`generatePerspective`). That is the whole concurrency story on the client.
7. Skim the 14 E2E titles (§15). They are the executable statement of the product contract; treat them as the spec, not the DESIGN.md prose.
8. Before any local run: check what holds 8000. Today it is the **hermetic in-memory** E2E app (PID 23178). Stop it before starting the real focused app there, and never demo hermetic state without disclosing that it resets.
9. Do **not** trust `README.md:80`. The correct local backend command is `uvicorn agora.focused_app:app --port 8000` with `PYTHONPATH`.
10. If you touch anything in `src/**`, `Dockerfile`, `pyproject.toml`, or `railway.toml`, re-read §13's deploy-ordering rule before exercising the UI.
11. Before claiming any memory or deployment number, **re-measure** with §16. Every figure in §14 is dated and will drift.
12. Before declaring anything done: run the full verification pair in §16 — not a narrowed subset — and verify UI changes in a real browser.

## 21. Skills the next session should use

| Skill | When |
|---|---|
| `blast-radius` | Before touching `service.py`, `models.py`, or `store/focused.ts`. The one skill whose absence is visible in this session's result: several fixes had adjacent surfaces (L1, L14, L16) that a blast-radius pass would have surfaced. |
| `principle-prove-it-works` | Any claim about memory, deployment, or provider behavior. The recurring failure mode here is a green demo-path assertion standing in for the branch that actually failed. |
| `principle-encode-lessons-in-structure` | Follow-ups #2, #4, #10 and landmine L13 are each a one-line config or one-predicate fix that would retire a prose rule permanently. Prefer the edit over another paragraph. |
| `principle-guard-the-context-window` | Before reading any workspace payload (follow-up #6) or grepping near `.venv`/`.next-*`. |
| `tdd` | Only for a bug with an obvious cheap local target — the backend suite is fast and hermetic, so regression tests there are genuinely cheap. |
| `adversarial-review` | Before opening any PR that touches concurrency, lineage validators, or canvas topology. |
| `technical-writing` | If you take follow-up #3 (README) or the DESIGN.md type-scale contradiction. |
| `push-notification` | Long Railway rollouts and live searches; the user is often not watching the terminal. |

Do **not** reach for heavy process skills for a single UI correction. The live-correction loop — reproduce on the real surface, trace to root cause from persisted state and platform metrics *before* writing code, fix, verify in the browser — outperformed them in this session and is the pattern the user responds to.