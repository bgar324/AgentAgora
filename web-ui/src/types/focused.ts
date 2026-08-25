export const FACETS = [
  "scope",
  "explanation",
  "approach",
  "significance",
] as const

export type Facet = (typeof FACETS)[number]
export type RetrievalTier = "answer" | "problem" | "candidate"

export interface ExpPaper {
  id: string
  title: string
  abstract: string | null
  abstract_sentences: string[]
  year: number | null
  venue: string | null
  authors: string[]
  source_query: string | null
  retrieval_tier: RetrievalTier | null
}

export interface FacetEvidence {
  facet: Facet
  text: string
  paper_id: string | null
  sentence_index: number | null
  sentence: string | null
  edited: boolean
}

export interface ClusterCard {
  id: string
  name: string
  blurb: string
  facets: FacetEvidence[]
  paper_ids: string[]
  representative_paper_ids: string[]
}

export interface FramingPosition {
  framing: string
  position: string
}

export interface Perspective {
  id: string
  name: string
  color: string
  facets: Partial<Record<Facet, FacetEvidence>>
  sources: string[]
  framing: FramingPosition | null
  summary: string
  evolved: boolean
  origin: string
  source_question_id: string | null
  panel_cycle: number
}

export interface HypothesisDev {
  problem: string
  previous_work: string
  reasoning: string
  hypothesis: string
}

export type HypothesisPart = keyof HypothesisDev
export type HypothesisConfirmationMode =
  | "apply_pending"
  | "edit_applied"
  | "reject_pending"
export type HypothesisDecision = "accepted" | "edited" | "rejected"

export interface HypothesisVersion {
  id: string
  workspace_id: string
  investigation_id: string
  parent_ids: string[]
  steps: HypothesisDev
  step_sources: Record<HypothesisPart, string>
  source_kind: "applied" | "edit" | "merge"
  source_deliberation_id: string | null
  source_round: number | null
  archived: boolean
  created_at: string
}

export type TurnKind = "open" | "answer" | "support" | "user" | "system"

export interface Turn {
  id: number
  agent_iid: number | null
  agent_label: string
  role: "lead" | "other" | "user" | "system"
  kind: TurnKind
  facet: Facet | null
  text: string
  citations: string[]
}

export interface FacetVerdict {
  facet: Facet
  status: "consensus" | "disagreement" | "unsettled"
  summary: string
  consensus: string
  disagreement: string
  unsettled: string
  supporting: string[]
  contested_by: string[]
  positions: Record<string, string>
  evidence: Record<string, string[]>
}

export interface DeliberationPoint {
  facet: Facet
  text: string
  rationale: string
  perspective_names: string[]
  citations: string[]
}

export interface RoundResolution {
  summary: string
  consensus_points: DeliberationPoint[]
  disagreement_points: DeliberationPoint[]
  unsettled_points: DeliberationPoint[]
}

export interface FacetDistance {
  facet: Facet
  distance: number
  participant_count: number
}

export interface RoundMetrics {
  method: string
  before: FacetDistance[]
  after: FacetDistance[]
  overall_before: number | null
  overall_after: number | null
  delta: number | null
  direction: "convergent" | "divergent" | "stable" | "insufficient"
}

export interface FacetRevision {
  facet: Facet
  text: string
}

export interface ParticipantReflection {
  agent_iid: number
  perspective_name: string
  decision: "unchanged" | "revised"
  reason: string
  revisions: FacetRevision[]
}

export interface DeliberationRating {
  divergent: number
  convergent: number
  note: string
  submitted_at: string
}

export interface DeliberationCompletion {
  archived_at: string
  reason: "completed" | "restarted"
  completed_at: string | null
  final_hypothesis_version_id: string | null
  round_count: number
  chat_count: number
  agent_iids: number[]
  question_ids: string[]
  lead_perspective_id: string | null
  baseline_hypothesis: HypothesisDev | null
  selected_question_ids: string[]
  rating: DeliberationRating | null
  rounds: DeliberationRound[]
  recommended_questions: RecommendedQuestion[]
  chat: Turn[]
  revised_perspective: Perspective | null
  hypothesis: HypothesisDev | null
  applied_hypothesis_version_id: string | null
  applied_hypothesis: HypothesisDev | null
  hypothesis_confirmed: boolean
  no_agreement: boolean
}

export interface DeliberationRound {
  n: number
  lead_iid: number
  participant_iids: number[]
  facets: Facet[]
  turns: Turn[]
  verdicts: FacetVerdict[]
  resolution: RoundResolution | null
  reflections: ParticipantReflection[]
  metrics: RoundMetrics | null
  completed: boolean
  hypothesis_before: HypothesisDev | null
  hypothesis_proposal: HypothesisDev | null
  hypothesis_decision: HypothesisDecision | null
}

export type QuestionStatus =
  | "open"
  | "investigating"
  | "addressed"
  | "archived"


export interface RecommendedQuestion {
  id: string
  question: string
  rationale: string
  source_kind: "disagreement" | "unsettled"
  source_point: string
  facets: Facet[]
  source_round: number | null
  status: QuestionStatus
  child_investigation_id: string | null
  selected_for_followup: boolean
}

export interface DeliberationState {
  id: string
  agent_iids: number[]
  lead_perspective_id: string | null
  baseline_hypothesis: HypothesisDev | null
  selected_question_ids: string[]
  rounds: DeliberationRound[]
  revised_perspective: Perspective | null
  hypothesis: HypothesisDev | null
  applied_hypothesis: HypothesisDev | null
  hypothesis_confirmed: boolean
  working_hypothesis_source_kind: "applied" | "edit" | null
  working_hypothesis_source_round: number | null
  no_agreement: boolean
  recommended_questions: RecommendedQuestion[]
  questions_generated: boolean
  chat: Turn[]
  completed_at: string | null
  final_hypothesis_version_id: string | null
  rating: DeliberationRating | null
  completion_history: DeliberationCompletion[]
}

export interface AgentState {
  iid: number
  perspective_id: string
  label: string
  facets: Partial<Record<Facet, FacetEvidence>>
  facet_version: number
  hypothesis: HypothesisDev | null
}

export interface SuggestedQuery {
  query: string
  rationale: string
  kind: "problem" | "question"
  question_index: number | null
  round: 1 | 2
}
export type SearchProgressKind =
  | "query_started"
  | "query_completed"
  | "query_failed"
  | "retrieval_completed"
  | "clustering_started"
  | "clustering_completed"
  | "round_stage"
  | "round_turn"

export interface SearchProgressItem {
  stage?: string
  step?: number
  total_steps?: number
  agent_label?: string
  text?: string
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


export interface QuestionEvidence {
  paper_id: string
  candidate_index: number | null
  bears: "supports" | "opposes" | "conditions"
  evidence: string
}

export interface VocabularyPair {
  ours: string
  theirs: string
}

export interface QuestionReach {
  question: string
  form: string
  candidates: string[]
  queries_r1: string[]
  queries_r2: string[]
  retrieved: number
  selected: QuestionEvidence[]
  vocabulary: VocabularyPair[]
  reached: boolean
}

export interface ClusteringDiagnostics {
  method:
    | "position_llm"
    | "specter_hdbscan_dpp"
    | "specter_kmeans"
    | "tfidf_kmeans"
    | "demo_seeds"
    | "single_group"
    | "balanced_fallback"
  embedded: number
  total: number
  requested_clusters: number
  cluster_sizes: number[]
  silhouette: number | null
  retrieval_tier_counts: Partial<Record<RetrievalTier, number>>
}

export interface SessionState {
  id: string
  workspace_id: string
  created_at: string
  demo: boolean
  problem: string
  research_questions: string[]
  parent_investigation_id: string | null
  origin_question_id: string | null
  origin_question: string | null
  integrated_into_parent_at: string | null
  applied_hypothesis: HypothesisDev | null
  applied_hypothesis_version_id: string | null
  suggested_queries: SuggestedQuery[]
  searched_queries: string[]
  question_reach: QuestionReach[]
  papers: ExpPaper[]
  clusters: ClusterCard[]
  unassigned_paper_ids: string[]
  perspectives: Perspective[]
  agents: AgentState[]
  deliberations: DeliberationState[]
  searched: boolean
  clustering: ClusteringDiagnostics | null
}

export interface InvestigationSummary {
  id: string
  parent_investigation_id: string | null
  origin_question_id: string | null
  origin_question: string | null
  created_at: string
  searched: boolean
  paper_count: number
  perspective_count: number
  completed_rounds: number
  open_question_count: number
  applied_hypothesis_version_id: string | null
}

export interface WorkspaceState {
  revision: number
  id: string
  created_at: string
  problem: string
  root_investigation_id: string
  active_investigation_id: string
  investigation_ids: string[]
  promoted_hypothesis_version_id: string | null
  hypothesis_versions: HypothesisVersion[]
}

export interface WorkspaceView {
  workspace: WorkspaceState
  investigations: InvestigationSummary[]
  active: SessionState
}

export interface PaperDetail {
  paper: ExpPaper
  facet_hits: {
    facet: Facet
    text: string
    sentence_index: number
  }[]
}

