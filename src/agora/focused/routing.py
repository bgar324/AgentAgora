from enum import StrEnum
from types import MappingProxyType
from typing import Final


class FocusedModelRole(StrEnum):
    corpus = "corpus"
    query = "query"
    reasoning = "reasoning"
    evaluation = "evaluation"


class FocusedTask(StrEnum):
    suggest_queries = "suggest_queries"
    plan_question_search = "plan_question_search"
    expand_question_search = "expand_question_search"
    assess_question_papers = "assess_question_papers"
    name_clusters = "name_clusters"
    extract_cluster_facets = "extract_cluster_facets"
    derive_framing = "derive_framing"
    open_statement = "open_statement"
    answer_statement = "answer_statement"
    find_support_query = "find_support_query"
    select_support_passage = "select_support_passage"
    judge_facet = "judge_facet"
    summarize_round = "summarize_round"
    reflect_on_round = "reflect_on_round"
    develop_hypothesis = "develop_hypothesis"
    develop_hypothesis_from_consensus = "develop_hypothesis_from_consensus"
    recommend_questions = "recommend_questions"
    reply_to_user = "reply_to_user"


TASK_ROLES: Final = MappingProxyType(
    {
        FocusedTask.suggest_queries: FocusedModelRole.query,
        FocusedTask.plan_question_search: FocusedModelRole.query,
        FocusedTask.expand_question_search: FocusedModelRole.query,
        FocusedTask.assess_question_papers: FocusedModelRole.corpus,
        FocusedTask.name_clusters: FocusedModelRole.corpus,
        FocusedTask.extract_cluster_facets: FocusedModelRole.corpus,
        FocusedTask.derive_framing: FocusedModelRole.reasoning,
        FocusedTask.open_statement: FocusedModelRole.reasoning,
        FocusedTask.answer_statement: FocusedModelRole.reasoning,
        FocusedTask.find_support_query: FocusedModelRole.query,
        FocusedTask.select_support_passage: FocusedModelRole.corpus,
        FocusedTask.judge_facet: FocusedModelRole.evaluation,
        FocusedTask.summarize_round: FocusedModelRole.evaluation,
        FocusedTask.reflect_on_round: FocusedModelRole.reasoning,
        FocusedTask.develop_hypothesis: FocusedModelRole.reasoning,
        FocusedTask.develop_hypothesis_from_consensus: FocusedModelRole.evaluation,
        FocusedTask.recommend_questions: FocusedModelRole.reasoning,
        FocusedTask.reply_to_user: FocusedModelRole.reasoning,
    }
)

if set(TASK_ROLES) != set(FocusedTask):
    raise RuntimeError("every focused task must route to one model role")
