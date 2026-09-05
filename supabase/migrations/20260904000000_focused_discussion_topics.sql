-- Extend existing study logs without rewriting append-only history.
alter table public.focused_interaction_events
  drop constraint focused_interaction_events_action_check,
  add constraint focused_interaction_events_action_check check (action in (
    'workspace.create',
    'workspace.delete',
    'queries.suggest',
    'papers.search',
    'paper.view',
    'perspective.create',
    'perspective.remove',
    'discussion.start',
    'topics.generate',
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
  drop constraint focused_interaction_events_details_check,
  add constraint focused_interaction_events_details_check check (
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
      'message_characters',
      'topic_id'
    ]::text[] = '{}'::jsonb
  );
