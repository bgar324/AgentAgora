from enum import StrEnum
from types import MappingProxyType
from typing import Final


class FocusedModelRole(StrEnum):
    corpus = "corpus"
    query = "query"
    reasoning = "reasoning"


class FocusedTask(StrEnum):
    suggest_queries = "suggest_queries"
    derive_research_questions = "derive_research_questions"
    plan_question_search = "plan_question_search"
    expand_question_search = "expand_question_search"
    assess_question_papers = "assess_question_papers"
    name_clusters = "name_clusters"
    extract_cluster_facets = "extract_cluster_facets"
    derive_framing = "derive_framing"
    reply_to_user = "reply_to_user"
    review_draft_element = "review_draft_element"
    compare_draft_feedback = "compare_draft_feedback"
    summarize_notepad = "summarize_notepad"


TASK_ROLES: Final = MappingProxyType(
    {
        FocusedTask.suggest_queries: FocusedModelRole.query,
        FocusedTask.derive_research_questions: FocusedModelRole.query,
        FocusedTask.plan_question_search: FocusedModelRole.query,
        FocusedTask.expand_question_search: FocusedModelRole.query,
        FocusedTask.assess_question_papers: FocusedModelRole.corpus,
        FocusedTask.name_clusters: FocusedModelRole.corpus,
        FocusedTask.extract_cluster_facets: FocusedModelRole.corpus,
        FocusedTask.derive_framing: FocusedModelRole.reasoning,
        FocusedTask.reply_to_user: FocusedModelRole.reasoning,
        FocusedTask.review_draft_element: FocusedModelRole.reasoning,
        FocusedTask.compare_draft_feedback: FocusedModelRole.reasoning,
        FocusedTask.summarize_notepad: FocusedModelRole.reasoning,
    }
)

if set(TASK_ROLES) != set(FocusedTask):
    raise RuntimeError("every focused task must route to one model role")
