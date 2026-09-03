create table if not exists public.focused_study_assignments (
  workspace_id text primary key,
  schema_version integer not null default 1 check (schema_version = 1),
  participant_id text,
  condition text not null,
  assigned_at timestamptz not null,
  check (
    participant_id is null
    or participant_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'
  ),
  check (condition ~ '^[a-z0-9][a-z0-9_-]{0,63}$')
);

create table if not exists public.focused_interaction_events (
  event_seq bigint generated always as identity primary key,
  event_id uuid not null unique,
  schema_version integer not null default 1 check (schema_version = 1),
  workspace_id text not null,
  session_id text,
  participant_id text,
  condition text,
  action text not null check (action in (
    'workspace.create',
    'workspace.delete',
    'queries.suggest',
    'papers.search',
    'paper.view',
    'perspective.create',
    'perspective.remove',
    'discussion.start',
    'document.edit',
    'version.create',
    'version.switch',
    'version.delete',
    'chat.clear',
    'discussion.run',
    'question.send',
    'summary.create',
    'review.restart',
    'study.finish'
  )),
  stage text not null check (stage in (
    'lifecycle', 'retrieval', 'perspectives', 'discussion', 'completion'
  )),
  outcome text not null check (outcome in ('success', 'failure')),
  occurred_at timestamptz not null,
  recorded_at timestamptz not null default now(),
  duration_ms bigint not null check (duration_ms >= 0),
  revision_before bigint check (revision_before >= 0),
  revision_after bigint check (revision_after >= 0),
  object_type text check (object_type in ('paper', 'perspective', 'version')),
  object_id text,
  error_code text check (error_code in (
    'invalid_request',
    'not_found',
    'conflict',
    'model_failure',
    'storage_failure',
    'cancelled',
    'internal_error'
  )),
  details jsonb not null default '{}'::jsonb check (
    jsonb_typeof(details) = 'object'
    and details - array[
      'problem_characters',
      'demo',
      'query_count',
      'custom_name',
      'description_characters',
      'part',
      'text_characters',
      'copy_current',
      'turns_requested',
      'message_characters'
    ]::text[] = '{}'::jsonb
  ),
  check ((object_type is null) = (object_id is null)),
  check (
    (outcome = 'success' and error_code is null)
    or (outcome = 'failure' and error_code is not null)
  ),
  check (
    participant_id is null
    or participant_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'
  ),
  check (condition is null or condition ~ '^[a-z0-9][a-z0-9_-]{0,63}$')
);

create index if not exists focused_interaction_events_workspace_idx
  on public.focused_interaction_events(workspace_id, event_seq);
create index if not exists focused_interaction_events_participant_idx
  on public.focused_interaction_events(participant_id, event_seq)
  where participant_id is not null;
create index if not exists focused_interaction_events_condition_idx
  on public.focused_interaction_events(condition, event_seq)
  where condition is not null;

create or replace function public.reject_focused_study_history_mutation()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  raise exception 'focused study history is append-only';
end;
$$;

create or replace function public.insert_focused_interaction_event(p_event jsonb)
returns void
language sql
security definer
set search_path = ''
as $$
  insert into public.focused_interaction_events(
    event_id,
    schema_version,
    workspace_id,
    session_id,
    participant_id,
    condition,
    action,
    stage,
    outcome,
    occurred_at,
    duration_ms,
    revision_before,
    revision_after,
    object_type,
    object_id,
    error_code,
    details
  ) values (
    (p_event ->> 'event_id')::uuid,
    (p_event ->> 'schema_version')::integer,
    p_event ->> 'workspace_id',
    p_event ->> 'session_id',
    p_event ->> 'participant_id',
    p_event ->> 'condition',
    p_event ->> 'action',
    p_event ->> 'stage',
    p_event ->> 'outcome',
    (p_event ->> 'occurred_at')::timestamptz,
    (p_event ->> 'duration_ms')::bigint,
    nullif(p_event ->> 'revision_before', '')::bigint,
    nullif(p_event ->> 'revision_after', '')::bigint,
    p_event ->> 'object_type',
    p_event ->> 'object_id',
    p_event ->> 'error_code',
    coalesce(p_event -> 'details', '{}'::jsonb)
  );
$$;

create or replace function public.create_focused_study_workspace(
  p_workspace_id text,
  p_revision bigint,
  p_payload jsonb,
  p_assignment jsonb,
  p_event jsonb
)
returns void
language plpgsql
security definer
set search_path = ''
as $$
begin
  if p_assignment ->> 'workspace_id' is distinct from p_workspace_id
     or p_event ->> 'workspace_id' is distinct from p_workspace_id then
    raise exception 'focused study workspace IDs do not match';
  end if;

  insert into public.focused_workspace_snapshots(
    workspace_id, revision, payload
  ) values (p_workspace_id, p_revision, p_payload);

  insert into public.focused_study_assignments(
    workspace_id, schema_version, participant_id, condition, assigned_at
  ) values (
    p_workspace_id,
    (p_assignment ->> 'schema_version')::integer,
    p_assignment ->> 'participant_id',
    p_assignment ->> 'condition',
    (p_assignment ->> 'assigned_at')::timestamptz
  );

  perform public.insert_focused_interaction_event(p_event);
end;
$$;

create or replace function public.save_focused_study_workspace(
  p_workspace_id text,
  p_expected_revision bigint,
  p_revision bigint,
  p_payload jsonb,
  p_event jsonb
)
returns boolean
language plpgsql
security definer
set search_path = ''
as $$
begin
  if p_event ->> 'workspace_id' is distinct from p_workspace_id
     or p_revision <> p_expected_revision + 1 then
    raise exception 'invalid focused study save';
  end if;

  update public.focused_workspace_snapshots
  set revision = p_revision, payload = p_payload
  where workspace_id = p_workspace_id and revision = p_expected_revision;

  if not found then
    return false;
  end if;

  perform public.insert_focused_interaction_event(p_event);
  return true;
end;
$$;

create or replace function public.delete_focused_study_workspace(
  p_workspace_id text,
  p_expected_revision bigint,
  p_event jsonb
)
returns boolean
language plpgsql
security definer
set search_path = ''
as $$
begin
  if p_event ->> 'workspace_id' is distinct from p_workspace_id then
    raise exception 'focused study workspace IDs do not match';
  end if;

  delete from public.focused_workspace_snapshots
  where workspace_id = p_workspace_id and revision = p_expected_revision;

  if not found then
    return false;
  end if;

  perform public.insert_focused_interaction_event(p_event);
  return true;
end;
$$;

drop trigger if exists reject_focused_study_assignment_update
  on public.focused_study_assignments;
create trigger reject_focused_study_assignment_update
before update or delete on public.focused_study_assignments
for each row execute function public.reject_focused_study_history_mutation();

drop trigger if exists reject_focused_interaction_event_update
  on public.focused_interaction_events;
create trigger reject_focused_interaction_event_update
before update or delete on public.focused_interaction_events
for each row execute function public.reject_focused_study_history_mutation();

alter table public.focused_study_assignments enable row level security;
alter table public.focused_interaction_events enable row level security;

revoke all on table public.focused_study_assignments from anon, authenticated;
revoke all on table public.focused_interaction_events from anon, authenticated;
grant select, insert on table public.focused_study_assignments to service_role;
grant select, insert on table public.focused_interaction_events to service_role;
grant usage, select on sequence public.focused_interaction_events_event_seq_seq
  to service_role;

revoke all on function public.reject_focused_study_history_mutation()
  from public, anon, authenticated;
revoke all on function public.insert_focused_interaction_event(jsonb)
  from public, anon, authenticated, service_role;
revoke all on function public.create_focused_study_workspace(
  text, bigint, jsonb, jsonb, jsonb
) from public, anon, authenticated;
revoke all on function public.save_focused_study_workspace(
  text, bigint, bigint, jsonb, jsonb
) from public, anon, authenticated;
revoke all on function public.delete_focused_study_workspace(
  text, bigint, jsonb
) from public, anon, authenticated;
grant execute on function public.create_focused_study_workspace(
  text, bigint, jsonb, jsonb, jsonb
) to service_role;
grant execute on function public.save_focused_study_workspace(
  text, bigint, bigint, jsonb, jsonb
) to service_role;
grant execute on function public.delete_focused_study_workspace(
  text, bigint, jsonb
) to service_role;
