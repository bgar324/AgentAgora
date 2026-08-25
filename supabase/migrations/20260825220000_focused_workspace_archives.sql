create table if not exists public.focused_workspace_archives (
  workspace_id text not null,
  schema_version integer not null,
  revision bigint not null,
  payload jsonb not null,
  archived_at timestamptz not null default now(),
  primary key(workspace_id, schema_version)
);

alter table public.focused_workspace_archives enable row level security;

revoke all on table public.focused_workspace_archives from anon, authenticated;
grant all on table public.focused_workspace_archives to service_role;
