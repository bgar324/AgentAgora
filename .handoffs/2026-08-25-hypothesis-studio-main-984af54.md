# Handoff: Hypothesis Studio after PR #15

**Written:** 2026-08-25.
**Repository:** `/Users/bg/windsurf/hypothesis-studio`.
**Remote:** `github.com/bgar324/hypothesis-studio`.
**Product-code baseline:** `main@984af54`.

This handoff records the product state after PRs #10 through #15. The documentation PR that adds this file is a docs-only successor to `984af54`.

## 1. Mission

The session's work moved through six linked asks:

1. Compare the Professor and Kat retrieval pipelines fairly, without cache replay or incomparable metrics, and choose the smallest production pipeline supported by the evidence.
2. Implement the selected retrieval path, expose progress and cluster evidence, and merge it.
3. Broaden the retained literature corpus before clustering and make query and clustering progress visible.
4. Reduce deliberation latency, route focused model work through GPT-5.6 Luna, show direct panel replies, and run independent literature searches concurrently without violating Semantic Scholar pacing.
5. Redesign deliberation around an explicit lead, a lead baseline, one facet per round, four-facet coverage, hypothesis proposal decisions, questions at any point, open-question carry-forward, and final confirmation.
6. Preserve the session in three hidden documents: this handoff, a current learnings document, and a deduplicated union with the August 23 learning document.

The product work is complete and merged. Once the documentation PR containing this file is merged, no requested implementation remains open.

## 2. State

### Git

- `main` and `origin/main` were clean and identical at `984af54` before the docs branch.
- PR #15 is merged: <https://github.com/bgar324/hypothesis-studio/pull/15>.
- GitHub Actions reported no workflow run for the PR #15 SHA. Do not describe CI as green. Local verification and the Vercel preview are the available evidence.
- The `.handoffs/` directory is already tracked. No `.handoffs` rule exists in `.gitignore` or `.git/info/exclude`; there was no ignore line to remove.

### Python environment

The repository `.venv` is not a trustworthy project environment:

```text
/Users/bg/windsurf/hypothesis-studio/.venv
  -> /private/tmp/agent-agora-github-review/.venv
```

It uses a foreign editable install and Python 3.14, while the repository declares Python 3.11. This session created `/tmp/hypothesis-studio-venv` and installed the repository there for backend verification. A temporary `uvicorn` symlink was added under the foreign `.venv/bin` because Playwright's server command is fixed to that path.

Do not standardize `PYTHONPATH=` or the temporary venv path as the setup. Rebuild a real repository environment from `.python-version` instead.

### Running local processes

These `hub` processes were live when this handoff was written:

| Name | Command | State |
|---|---|---|
| `hypothesis-api` | `.venv/bin/uvicorn agora.focused_app:app --host 127.0.0.1 --port 8012` | ready |
| `hypothesis-ui` | `pnpm dev -p 3012` in `web-ui/` | ready |
| `omp.browser.headless` | managed headless Chromium | ready |
| `focused-api` | prior service attempt | exited after restart failures |

The API and UI processes are session residue, not repository requirements.

### Credentials and deployment

No secret value was printed or copied into these documents. PR #15's Vercel preview reported Ready. Production deployment after the merge was not inspected. Use the `hypothesis-studio-deployment` skill before making a production claim.

## 3. Done so far

### Recent merged work

| PR | Main commit | Delivered |
|---|---|---|
| [#10](https://github.com/bgar324/hypothesis-studio/pull/10) | `39f054a` | Fair, cache-independent Professor-versus-Kat evaluation; evidence-selected production retrieval; fresh deliberation restart; model routing; cluster and unassigned-paper inspection. |
| [#11](https://github.com/bgar324/hypothesis-studio/pull/11) | `266b418` | Retained question-search candidates, answer/problem/candidate retrieval tiers, a 90-paper target, bounded gap queries, and at least three usable clusters. |
| [#12](https://github.com/bgar324/hypothesis-studio/pull/12) | `732fc1c` | Typed query/retrieval/clustering checkpoints and the persistent centered retrieval timeline. |
| [#13](https://github.com/bgar324/hypothesis-studio/pull/13) | `6a3ba66` | Concurrent independent deliberation calls, a shorter model-call critical path, GPT-5.6 Luna routing, and direct agent replies. |
| [#14](https://github.com/bgar324/hypothesis-studio/pull/14) | `8196dfd` | Concurrent Semantic Scholar queries with the pacing lock retained, partial-429 recovery, active-row spinners, optimistic Markdown chat, facet history, and question-search concurrency. |
| [#15](https://github.com/bgar324/hypothesis-studio/pull/15) | `984af54` | Persistent lead and baseline, one facet per round, at least four rounds plus complete facet coverage, lead-only consensus revision, accept/edit/reject proposals, queued in-round questions, selected open questions, seven-stage progress, and canonical missing-facet editors. |

### PR #15 behavior

The current panel protocol is enforced at both the API and service boundaries:

1. The researcher chooses one lead Perspective.
2. `initialize_deliberation` generates the lead baseline before round 1.
3. Every new round uses the same lead and exactly one of Scope, Explanation, Approach, or Significance.
4. Other Perspectives answer concurrently. Only the lead reflects, and only on consensus points.
5. `develop_hypothesis_from_consensus` generates the proposal from the current applied hypothesis. Do not replace it with the full-Perspective `develop_hypothesis` generator.
6. The researcher accepts, edits, or rejects the pending proposal before another round.
7. Questions work before and between rounds. One question submitted during a round waits and sends when the round mutation ends.
8. Completion requires at least four completed rounds and coverage of all four facets.
9. Final review submits only ids that are still open. It records the selected ids and `selected_for_followup` flags.

Old open cycles created by the prior rotating-lead UI cannot satisfy the new invariant. When their lead is explicitly selected, the service archives the old cycle to `completion_history`, creates fresh panel agents, and starts a zero-round cycle with the selected lead. The setup card warns the researcher. The old rounds, chat, questions, and hypotheses remain in Panel history.

### Verification actually performed

- Full backend suite: **103 passed**, with the existing Starlette/httpx deprecation warning and UMAP `n_jobs` warning.
- Changed Python files: Ruff passed.
- Frontend: ESLint passed.
- Frontend: `tsc --noEmit` passed.
- Frontend: Next production build passed.
- Full browser suite: **18 passed**.
- The final targeted browser journey passed after it added: pre-round question, queued in-round question, 7/7 round progress, four rounds, final question selection, cancel/archive/reopen stale-selection pruning, and completion.
- Independent adversarial review initially found two P1 regressions: persisted rotating-lead cycles could deadlock, and an archived selected question could remain in the final payload. Both were fixed and the targeted re-review approved the result.

## 4. Open threads

Nothing blocks the merged product. These are follow-ups, ordered by risk.

1. **Confirm production after `984af54`.** Use `hypothesis-studio-deployment`. Check both Railway startup and Vercel production, then exercise one real request. The PR preview alone does not prove production.
2. **Replace the foreign `.venv`.** Create a Python 3.11 environment owned by this repository. Remove the `/tmp` dependency before it disappears and breaks both pytest and Playwright startup.
3. **Fix the documented backend entrypoint.** `README.md` still runs `src/agora/app.py`, while production and the lightweight application use `agora.focused_app:app`. This is the same import-graph hazard documented on August 23.
4. **Forward arguments through `web-ui/scripts/run-e2e.mjs`.** The safe wrapper cannot run one test. Raw targeted Playwright runs mutate tracked Next config files and require manual restoration.
5. **Define the repository-wide Ruff baseline.** `ruff check src tests` currently reports 15 unrelated pre-existing findings. Changed-file Ruff is the evidence for PR #15, not a whole-repository pass.
6. **Add CI if remote gating is expected.** GitHub reported no Actions run for PR #15.

Exact first action for a new product session: run `git status --short --branch`, resolve `.venv` to its real path, and decide whether the task needs production evidence or code work before starting a service.

## 5. Decisions and constraints

### Product

1. Use participant language: **panel**, **Perspective**, and Perspective names. Do not expose internal agent ids.
2. A Perspective always has the canonical four areas in this order: Scope, Explanation, Approach, Significance.
3. A new deliberation cycle has one explicit lead. The client must not derive the lead from round count.
4. One round means one facet. Do not restore a one-or-two facet compatibility path.
5. Four-facet coverage and four completed rounds are separate completion facts. Check both.
6. Only supported consensus changes the lead and the working hypothesis. Disagreement and unsettled points generate questions, not hypothesis text.
7. A proposal decision is an audit fact. Pending edits use `apply_pending` and record `edited`. A later `edit_applied` operation must not overwrite whether the round proposal was accepted or rejected.
8. Open-question selection is live domain state. Validate status on the server and filter stale client selections at submit time.
9. The sixth-cluster fix is structural: render from `FACETS`, fill missing entries with editable blanks, and send all four. Do not special-case cluster index 6.
10. Backend workspace export is intentional. Prior work removed participant-facing export UI, not the export service.

### Engineering

11. Production must use `agora.focused_app:app`. Importing the legacy `agora.app` pulls in the large DSPy/Torch stack.
12. Workspace mutations are aggregate transactions. `_serialized_session_mutation` and `_serialized_parent_mutation` snapshot the whole workspace and restore it on failure.
13. Reuse of the search-progress generation/cursor channel for rounds is deliberate. The progress stream is advisory; the final `WorkspaceView` response is authoritative.
14. Keep independent model calls concurrent, but preserve transcript order and mutation order after `TaskGroup` completion.
15. Keep the Semantic Scholar pacing lock even when query pipelines run concurrently. Concurrent orchestration does not mean concurrent request starts.
16. An incompatible historical state gets an archive boundary. Do not fabricate new semantic fields on load, and do not deadlock old data behind an invariant it predates.
17. Clean cutovers still need persisted-data handling. Compatibility means preserving user history, not preserving the old request shape.

## 6. Landmines

1. **Raw Playwright mutates tracked files.** `pnpm exec playwright test ...` rewrites `web-ui/next-env.d.ts` and `web-ui/tsconfig.json`. Use `pnpm test:e2e` for the full suite. After any raw targeted run, restore both files before staging.
2. **The safe E2E wrapper drops arguments.** `pnpm test:e2e -- --grep ...` does not narrow the run. Until the wrapper forwards arguments, targeted execution and safe cleanup are separate paths.
3. **E2E ports are fixed.** The suite starts API 8011 and UI 3011 with `reuseExistingServer: false`. A stray listener fails the entire suite.
4. **The repository venv can lie convincingly.** `PYTHONPATH=src` fixes first-party imports but third-party dependencies and the interpreter still come from the foreign environment.
5. **Whole-repository Ruff is not green.** Do not claim it is. The last whole-tree attempt found 15 existing findings before frontend checks could run.
6. **`develop_hypothesis` and `develop_hypothesis_from_consensus` are not interchangeable.** The first builds a fresh four-part baseline from a full Perspective. The second preserves unaffected parts and accepts only supported shared ground.
7. **Legacy rotation is real production state.** Tests must reproduce lead A in round 1 and lead B in round 2. A fixture that gives one lead every old round cannot defend the migration.
8. **React selection state can outlive the options that created it.** If an option can disappear, intersect cached ids with current valid ids at the mutation boundary.
9. **Effect-driven queue flushes can duplicate requests.** `flushingQueuedChatRef` is the guard. Removing it can resend when the authoritative chat response replaces `active` before `finally` clears local state.
10. **No production claim follows from a Vercel preview.** Railway, Vercel production, and the real mutation path must all be checked.

## Skills for the next session

- `hypothesis-studio-deployment`: production verification or deployment changes.
- `adversarial-review`: any non-trivial PR, especially migrations or stateful UI.
- `blast-radius`: small changes to aggregate persistence, progress transport, or panel lifecycle.
- `principle-model-the-domain`: new deliberation state or question-status behavior.
- `principle-prove-it-works`: every final claim; use the real UI for user-visible behavior.
- `push-notification`: notify the user after a long verification or merge finishes.
