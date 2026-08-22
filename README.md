# Hypothesis Studio

A standalone FastAPI and Next.js application for literature-grounded
Perspective panels and four-step scientific hypothesis development. It includes
demo fixtures, tests, local startup configuration, and Vercel, Railway, and
Supabase deployment support.

## Focused study flow

Each workspace begins with one research problem and one root Investigation.
Perspectives contain four abstract-grounded areas—Scope, Explanation,
Approach, and Significance—and the researcher selects one or two areas per
round. Each completed round remains on the canvas with a process-first summary.
Consensus-only updates can be applied to the four-step working hypothesis;
saving creates an immutable Hypothesis node. Disagreement and unsettled points
remain Research Problem nodes that can open child Investigations.

An open question can explicitly start a child Investigation. The child receives
fresh literature, fresh Perspectives, and a fresh fixed panel while inheriting
the parent’s last applied hypothesis checkpoint. A pending parent update never
leaks into the child. The workspace map records question-labeled lineage and
opens one Investigation detail at a time.

Hypothesis checkpoints form an immutable version graph. Researchers can promote
a branch, preserve alternatives, merge selected Problem / Previous work /
Reasoning / Hypothesis steps with per-step provenance, archive a superseded
checkpoint, and restore it later. A focused panel requires at least two
Perspectives but has no product-level maximum; the researcher may seat every
relevant Perspective before the first round locks membership. Open questions
move through Open, Investigating, Addressed, and Archived states.

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

The frontend proxies `/api/*` to `http://127.0.0.1:8000/api/v1/*`. Override the backend host when needed:

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

Enable Vercel Deployment Protection and grant the PI access. Then redeploy the
frontend.

### 4. Verify production

Check the API and the protected proxy:

```bash
curl https://<railway-domain>/api/v1/focused/health
curl -i https://<railway-domain>/api/v1/focused/workspaces/example
curl -i https://<vercel-domain>/api/focused/workspaces/example
```

The direct Railway workspace request must return `401`. The Vercel request
should reach FastAPI and return `404` for the example ID.

In the browser, create an Investigation, run a demo search, add two
Perspectives, refresh the page, and confirm that the workspace restores from
Supabase.

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

The Playwright suite starts an isolated hermetic API and frontend. It covers
open-question branching and status transitions, fresh child state,
Investigation-map navigation, UI hypothesis application, promotion,
provenance-preserving merge, archive confirmation and restore, URL restoration,
transient restore failure, export failure/retry, abstract loading failure/retry,
destructive reset, keyboard dialog behavior, and mobile overflow.

Workspace exports include every Investigation, abstract provenance, selected
areas, turns, moderator evidence references, participant reflections, hidden
semantic-distance metrics, open-question status, and hypothesis lineage.

## Credits

Developed by [Benjamin Garcia](https://github.com/bgar324) in collaboration with
[@katjpg](https://github.com/katjpg), who contributed the architecture and
backend foundation.
