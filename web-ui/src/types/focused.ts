export const MAX_PERSPECTIVES = 6

export type NotepadPart = "framing" | "prior" | "method" | "expected"

export const NOTEPAD_PARTS: NotepadPart[] = [
  "framing",
  "prior",
  "method",
  "expected",
]

export const NOTEPAD_LABELS: Record<NotepadPart, string> = {
  framing: "Framing",
  prior: "Previous work",
  method: "Methodology",
  expected: "Expected results",
}

export interface NotepadDoc {
  framing: string
  prior: string
  method: string
  expected: string
}

export interface ExpPaper {
  id: string
  title: string
  abstract: string | null
  abstract_sentences: string[]
  year: number | null
  venue: string | null
  authors: string[]
  tldr: string | null
  open_access_pdf_url: string | null
}

export interface SuggestedQuery {
  query: string
  rationale: string
}

export interface Perspective {
  id: string
  name: string
  color: string
  summary: string
  anchor_paper_id: string | null
  related_paper_count: number
}

export type SearchProgressKind =
  | "query_started"
  | "query_completed"
  | "query_failed"
  | "retrieval_completed"
  | "clustering_started"
  | "clustering_completed"

export interface SearchProgressItem {
  generation: number
  sequence: number
  kind: SearchProgressKind
  message: string
  query?: string
  retrieved?: number
  query_run_id?: number | null
  reason?: "rate_limited" | "unavailable"
  retained?: number
  query_count?: number
  papers?: number
  requested_clusters?: number
  clusters?: number
  unassigned?: number
  method?: string
}

export type NotepadAgendaPhase = "feedback" | "comparison" | "complete"

export interface NotepadAgenda {
  review_n: number
  part: NotepadPart
  phase: NotepadAgendaPhase
  subject_text: string
  participant_ids: string[]
  feedback_done_ids: string[]
  comparison_done_ids: string[]
  comparison_cycle: number
  turn_budget: number
  turns_emitted: number
  completed_at: string | null
}

export interface NotepadVersion {
  id: string
  name: string
  doc: NotepadDoc
  agenda: NotepadAgenda
  visible_turn_start: number
  created_from: string | null
  created_at: string
}

export interface DiscussionTopic {
  id: string
  perspective_id: string
  title: string
  question: string
  hypothesis: string
  rationale: string
  citations: string[]
  created_at: string
}

export interface NotepadTurn {
  id: string
  version_id: string
  kind:
    | "feedback"
    | "comparison"
    | "researcher"
    | "direct_reply"
    | "summary"
    | "system"
  role: "researcher" | "perspective" | "system" | "summary"
  author_id: string | null
  author_label: string
  text: string
  citations: string[]
  review_n: number | null
  part: NotepadPart | null
  comparison_cycle: number | null
  reply_to_turn_id: string | null
  topic_id: string | null
  created_at: string
}

export interface NotepadFinalSnapshot {
  versions: NotepadVersion[]
  finished_at: string
}

export interface NotepadState {
  id: string
  versions: NotepadVersion[]
  active_version_id: string | null
  turns: NotepadTurn[]
  topics: DiscussionTopic[]
  in_chat: string[]
  final_snapshot: NotepadFinalSnapshot | null
}

export interface SessionState {
  id: string
  workspace_id: string
  created_at: string
  problem: string
  suggested_queries: SuggestedQuery[]
  searched_queries: string[]
  papers: ExpPaper[]
  perspectives: Perspective[]
  notepad: NotepadState | null
  position: NotepadDoc
  searched: boolean
}

export interface WorkspaceState {
  revision: number
  id: string
  created_at: string
  problem: string
}

export interface WorkspaceView {
  workspace: WorkspaceState
  active: SessionState
}

export interface PaperDetail {
  paper: ExpPaper
}
