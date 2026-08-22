create table if not exists public.focused_workspace_snapshots (
  workspace_id text primary key,
  revision bigint not null check (revision >= 0),
  payload jsonb not null check (jsonb_typeof(payload) = 'object'),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.focused_workspace_quarantine (
  workspace_id text primary key,
  revision bigint,
  payload jsonb not null,
  reason text not null,
  quarantined_at timestamptz not null default now()
);

create index if not exists focused_workspace_snapshots_updated_at_idx
  on public.focused_workspace_snapshots(updated_at);

create or replace function public.set_focused_workspace_updated_at()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists set_focused_workspace_updated_at
  on public.focused_workspace_snapshots;
create trigger set_focused_workspace_updated_at
before update on public.focused_workspace_snapshots
for each row execute function public.set_focused_workspace_updated_at();

alter table public.focused_workspace_snapshots enable row level security;
alter table public.focused_workspace_quarantine enable row level security;

revoke all on table public.focused_workspace_snapshots from anon, authenticated;
revoke all on table public.focused_workspace_quarantine from anon, authenticated;
grant all on table public.focused_workspace_snapshots to service_role;
grant all on table public.focused_workspace_quarantine to service_role;
