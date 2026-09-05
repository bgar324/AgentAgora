# AgentAgora

AgentAgora is a multi-agent research panel that deliberates literature-grounded
Perspectives to develop, refine, and version scientific hypotheses. It is a
standalone FastAPI and Next.js application with demo fixtures, tests, local
startup configuration, and Vercel, Railway, and Supabase deployment support.

## Focused study flow

Each workspace begins with one research problem and one root Investigation.
The exact queries submitted for retrieval remain visible beside the resulting
literature clusters and are included in workspace exports.
Perspectives carry four abstract-grounded facets — Scope, Explanation,
Approach, and Significance — the representation and traceability layer of the
panel: they surface where Perspectives differ and record what changed after
each discussion, without setting the agenda.

The researcher chooses one lead Perspective, which drafts the baseline
hypothesis (one scalar "possible solution"). The panel then identifies
Threads: the scientific issues, disagreements, and open questions worth
deliberating. Each discussion centers one Thread. The lead answers the
Thread's question; the other Perspectives challenge, reply, and cite
evidence; exchanges continue automatically until every Perspective accepts
the moderator's proposed shared ground, with a moderator check after each
exchange.

A completed Thread records its finding, the moderator's resolution, a
Perspective delta for every panelist, and the working-hypothesis delta. The
researcher reviews each resolution — accept it, edit it in their own words,
or keep the Thread open for another discussion — and separately accepts,
edits, or rejects the hypothesis proposal. A resolution's open questions
re-enter the picker as suggested Threads. Questions to the panel can be
submitted at any point; one sent during a Thread waits until it finishes.

Saving creates an immutable checkpoint. Review and end shows the final
hypothesis and lets the researcher select open questions. Confirm and end
synthesizes the final Document — each resolved Thread becomes a research
section stating the hypothesis it supports and why, with unresolved issues
kept as numbered open questions — then closes the deliberation and opens one
dialog for separate 1–7 divergent-thinking and convergent-thinking scores.

An open question starts a research branch with fresh literature and Perspectives
while inheriting the parent's last applied hypothesis checkpoint. Continue
imports the branch evidence and agents into the parent and starts a fresh panel
cycle on the existing Canvas. The prior rounds, chat, questions, hypothesis,
completion, and score remain in completion history. The workspace map retains
the question-labeled research branch for provenance.
On the Canvas, imported agents branch from the Research Problem that initiated
their literature search and feed the continued panel. The earlier panel,
Hypothesis, and Research Problem outputs remain visible as the prior checkpoint.

Hypothesis checkpoints form an immutable version graph. Researchers can promote
a branch, preserve alternatives, merge checkpoints with provenance, archive a
superseded checkpoint, and restore it later. A panel requires at least two
Perspectives but has no product-level maximum. Every matrix Perspective
automatically becomes an agent on the canvas. The Canvas Add Perspective action
archives the current cycle into Panel history and starts a new deliberation
with the enlarged panel; hypothesis checkpoints remain. Open questions
move through Open, Investigating, Addressed, and Archived states.

Focused workspaces use revision-checked aggregate snapshots in local SQLite or
production Supabase. Concurrent stale writers receive a conflict instead of
overwriting newer work, malformed rows are quarantined without taking down
healthy workspaces, and failed in-process mutations roll back before another
request can observe them.

Each new workspace also gets an immutable pseudonymous study assignment.
Meaningful server interactions, including paper opens, append one terminal
success or failure event with duration, revisions, and content-free metadata.
Successful snapshot and event writes are atomic. A process exit before the
terminal write leaves no event. Start over removes the working snapshot but
retains assignment and interaction history. Each repeated (`participant_id`,
`condition`) pair starts another workspace attempt. Use `assigned_at` to order
the attempts.

Discussion topic generation records `topics.generate`. A successful topic-linked
`question.send` records `details.topic_id`, while failed requests omit topic IDs.
Neither topic text nor message contents enter the study log.

The app has no actor accounts or tenant authorization. Production deploys gate
the FastAPI service behind the Vercel server proxy token.

Computed semantic cosine distances remain export-only study measurements; they
are never rendered to participants.

## Live-mode keys

For live sessions, copy the template and fill the keys:

```bash
cp .env.example .env
```

- `OPENAI_API_KEY`: `text-embedding-3-small` embeddings and AgentAgora's evidence index.
- `OPENROUTER_API_KEY`: structured model calls for live extraction and panel responses.
- `SEMANTIC_SCHOLAR_API_KEY`: optional, but recommended for paper-search throughput.

Demo sessions use the bundled corpus and deterministic panel output without
external API keys. Without OpenAI, the hidden study-analysis metric is recorded
as unavailable and is never displayed to participants.

## Run locally

Backend, from the repository root:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/python -m pip install pytest ruff
.venv/bin/fastapi dev src/agora/focused_app.py --port 8000
```

Frontend, in another terminal:

```bash
cd web-ui
pnpm install
pnpm dev
```

Open:

- AgentAgora: <http://localhost:3000> (redirects to `/focused`)
- API health: <http://localhost:8000/api/v1/focused/health>

The frontend route `/api/focused/*` forwards requests to
`<API_URL>/api/v1/focused/*`. Override the backend host when needed:

```bash
API_URL=http://127.0.0.1:8000 pnpm dev
```


## Deploy with Vercel, Railway, and Supabase

The production topology is:

```text
Vercel Next.js frontend
  -> authenticated server-side proxy
Railway FastAPI service
  -> service-key requests
Supabase workspace snapshots
```

The browser never receives the Supabase secret or the API proxy token.

### 1. Create the Supabase tables

Create a Supabase project, then run every file in `supabase/migrations/` in
filename order. The migrations create workspace snapshots and archives, then
the study assignment and append-only interaction tables. Copy the project URL
and secret key after the migrations succeed.

For an existing Supabase deployment, apply pending migrations before deploying.
`20260904000000_focused_discussion_topics.sql` extends the event constraints for
topic generation and topic-linked questions.

To import existing local workspaces, run:

```bash
.venv/bin/python scripts/import_focused_sqlite_to_supabase.py --dry-run
.venv/bin/python scripts/import_focused_sqlite_to_supabase.py
```

The importer skips identical workspaces on repeated runs and stops instead of
overwriting a workspace that differs.

Export assignment and interaction records only from a trusted operator
environment. Supabase uses the configured service credentials; local SQLite
accepts an explicit database path. Files are written with owner-only
permissions.

```bash
.venv/bin/python -m agora.focused.study_export --output study-events.ndjson
.venv/bin/python -m agora.focused.study_export \
  --sqlite artifacts/agora.db \
  --output study-events.ndjson
```

### 2. Deploy FastAPI to Railway

Create one Railway service from this repository. Railway uses the root
`Dockerfile` and `railway.toml`. Keep the service at one replica.

Set these Railway variables:

```text
AGORA_PERSISTENCE=supabase
SUPABASE_URL=https://<project-ref>.supabase.co
SUPABASE_SECRET_KEY=<secret key>
AGORA_PROXY_TOKEN=<random 64-character value>
OPENAI_API_KEY=<key>
OPENROUTER_API_KEY=<key>
SEMANTIC_SCHOLAR_API_KEY=<key>
AGORA_CORS_ORIGINS=https://<vercel-domain>
```

Generate the proxy token locally:

```bash
openssl rand -hex 32
```

Create a Railway public domain after the health check passes. The public health
path is `/api/v1/focused/health`. Every other `/api/v1/*` request requires the
proxy token.

### 3. Deploy Next.js to Vercel

Import the same repository into Vercel with `web-ui` as the project root. Set:

```text
API_URL=https://<railway-domain>
AGORA_PROXY_TOKEN=<same Railway value>
```

Do not prefix either variable with `NEXT_PUBLIC_`. The route at
`/api/focused/*` reads them only on the Vercel server and forwards the shared
token to Railway.

Keep Vercel Deployment Protection enabled for preview deployments. Keep the
production URL accessible to study participants, then redeploy the frontend.

### 4. Verify production

Check the API and the protected proxy:

```bash
curl https://<railway-domain>/api/v1/focused/health
curl -i https://<railway-domain>/api/v1/focused/workspaces/example
curl -i https://<vercel-domain>/api/focused/workspaces/example
```

The direct Railway workspace request must return `401`. The Vercel request
should reach FastAPI and return `404` for the example ID.

In the browser, create an Investigation and run a demo search. Confirm that the
submitted queries remain visible after the clusters load. Add two Perspectives,
continue directly to the canvas, complete a Thread, accept its resolution,
save the hypothesis, and end the deliberation. Submit the final scores,
refresh the page, and confirm that Supabase restores the workspace and final
canvas nodes.

## Verification

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check src tests
cd web-ui
pnpm lint
pnpm build
pnpm exec playwright install chromium  # first run only
pnpm test:e2e
```

The Playwright suite starts an isolated API and frontend. It covers wrapped
research-question parsing, the search-to-clustering timeline, sibling searches
surviving a stopped query, unassigned-paper inspection, concurrent matrix
additions, Thread selection and the auto-continuing exchange loop, resolution
review, suggested Threads from open questions, the final Document, hypothesis
application and editing, promotion and provenance-preserving merge, archive
and restore, open-question branching and continuation, panel restart on Add
Perspective, URL restoration, transient restore failure, API restart recovery,
revision-conflict reload, repeated-question dedup, panels beyond three
Perspectives, destructive reset, and mobile overflow.

Workspace exports include every Investigation, submitted search queries,
abstract provenance, identified Threads, each Thread's participant roster,
turns, moderator checks and evidence references, participant reflections for
every panelist, resolution decisions, the final Document, hidden
semantic-distance metrics, deliberation completion and final scores,
open-question status, and hypothesis lineage.

## Credits

Developed by [Benjamin Garcia](https://github.com/bgar324) in collaboration with
[@katjpg](https://github.com/katjpg), who contributed the architecture and
backend foundation.
