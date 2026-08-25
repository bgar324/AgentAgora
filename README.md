# Hypothesis Studio

A standalone FastAPI and Next.js application for literature-grounded
Perspective panels and four-step scientific hypothesis development. It includes
demo fixtures, tests, local startup configuration, and Vercel, Railway, and
Supabase deployment support.

## Focused study flow

Each workspace begins with one research problem and one root Investigation.
The exact queries submitted for retrieval remain visible beside the resulting
literature clusters and are included in workspace exports.
Perspectives contain four abstract-grounded areas: Scope, Explanation,
Approach, and Significance. Before round 1, the researcher chooses one lead
Perspective and generates its baseline hypothesis. The same lead opens every
round, and each round examines exactly one area. The panel must complete at
least one round for each area before it can end.

The drawer reports round progress and shows agent turns as they arrive. The
moderator summary follows the conversation. Each proposal shows Before and
Proposed values for changed hypothesis parts. The researcher can accept, edit,
or reject the proposal. Questions can be submitted before or between rounds. A
question submitted during a round waits until the round finishes.

Saving creates an immutable checkpoint. Review and end shows the final
hypothesis and lets the researcher select open questions. Confirm and end closes
the deliberation and opens one dialog for separate 1–7 divergent-thinking and
convergent-thinking scores.

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
a branch, preserve alternatives, merge selected Problem / Previous work /
Reasoning / Hypothesis steps with per-step provenance, archive a superseded
checkpoint, and restore it later. A panel requires at least two Perspectives but
has no product-level maximum. Every matrix Perspective automatically becomes an
agent on the canvas. The Canvas Add Perspective action appends another
literature-grounded agent to the same open deliberation; prior rounds, questions,
and hypothesis checkpoints remain unchanged. Open questions move through Open,
Investigating, Addressed, and Archived states.

Focused workspaces use revision-checked aggregate snapshots in local SQLite or
production Supabase. Concurrent stale writers receive a conflict instead of
overwriting newer work, malformed rows are quarantined without taking down
healthy workspaces, and failed in-process mutations roll back before another
request can observe them.

The app has no actor accounts or tenant authorization. Production deploys gate
the FastAPI service behind the Vercel server proxy token.

Computed semantic cosine distances remain export-only study measurements; they
are never rendered to participants.

## Required keys

Copy the template and fill the keys:

```bash
cp .env.example .env
```

- `OPENAI_API_KEY`: `text-embedding-3-small` embeddings and Agent Agora's evidence index.
- `OPENROUTER_API_KEY`: structured model calls for live extraction and panel responses.
- `SEMANTIC_SCHOLAR_API_KEY`: optional, but recommended for paper-search throughput.

Demo sessions use the bundled abstract corpus and deterministic panel output.
Focused demo rounds still embed the four facet profiles with OpenAI for the
hidden study-analysis metric; they never display that metric to participants.

## Run locally

Backend, from the repository root:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/python -m pip install pytest ruff
.venv/bin/fastapi dev src/agora/app.py --port 8000
```

Frontend, in another terminal:

```bash
cd web-ui
pnpm install
pnpm dev
```

Open:

- Benjamin’s focused Hypothesis Studio: <http://localhost:3000> (redirects to
  `/focused`)
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

Create a Supabase project, then run
`supabase/migrations/20260822180000_focused_workspace_snapshots.sql` in its SQL
editor. Copy the project URL and secret key after the migration succeeds.

To import existing local workspaces, run:

```bash
.venv/bin/python scripts/import_focused_sqlite_to_supabase.py --dry-run
.venv/bin/python scripts/import_focused_sqlite_to_supabase.py
```

The importer skips identical workspaces on repeated runs and stops instead of
overwriting a workspace that differs.

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
continue directly to the canvas, complete a round, save the hypothesis, and end
the deliberation. Submit the final scores, refresh the page, and confirm that
Supabase restores the workspace and final canvas nodes.

## Verification

```bash
.venv/bin/pytest -q
.venv/bin/ruff check src tests
cd web-ui
pnpm lint
pnpm build
pnpm exec playwright install chromium  # first run only
pnpm test:e2e
```

The Playwright suite starts an isolated API and frontend. It covers persistent
search-query history, automatic agent placement, later-Perspective state
preservation, terminal deliberation completion and scoring, final artifact
reveal, open-question branching and status transitions, fresh child state,
Investigation-map navigation, UI hypothesis application, promotion,
provenance-preserving merge, archive confirmation and restore, URL restoration,
transient restore failure, export failure and retry, abstract loading failure
and retry, destructive reset, keyboard dialog behavior, and mobile overflow.

Workspace exports include every Investigation, submitted search queries,
abstract provenance, selected areas, each round’s participant roster, turns,
moderator evidence references, participant reflections, hidden semantic-distance
metrics, deliberation completion and final scores, open-question status, and
hypothesis lineage.

## Credits

Developed by [Benjamin Garcia](https://github.com/bgar324) in collaboration with
[@katjpg](https://github.com/katjpg), who contributed the architecture and
backend foundation.
