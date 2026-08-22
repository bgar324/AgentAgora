import asyncio
import re

import dspy

from agora.config.research import DiscoveryConfig
from agora.research.search import LiteratureSearch
from agora.schemas.research import (
    AcademicField,
    ResearchDirection,
    ResearchIdea,
    ResearchQuestion,
    RetrievalSeed,
    SearchPlan,
    Snippet,
)


def normalize_query(query: str) -> str:
    return " ".join(part for part in re.split(r"\W+", query.casefold()) if part)


def distinct_fields(
    fields: list[AcademicField],
    *,
    max_fields: int,
) -> list[AcademicField]:
    return list(dict.fromkeys(fields))[:max_fields]


def distinct_seeds(seeds: list[RetrievalSeed], *, n: int) -> list[RetrievalSeed]:
    selected: list[RetrievalSeed] = []
    seen: set[str] = set()

    for seed in seeds:
        query = " ".join(seed.query.split())
        intent = " ".join(seed.intent.split())
        key = normalize_query(query)

        if not query or not intent:
            continue
        if key in seen:
            continue

        seen.add(key)
        selected.append(RetrievalSeed(query=query, intent=intent))

        if len(selected) == n:
            return selected

    raise ValueError(f"Expected {n} distinct Retrieval Seeds")


def distinct_directions(
    directions: list[ResearchDirection],
    *,
    seeds: list[RetrievalSeed],
    n: int,
) -> list[ResearchDirection]:
    selected: list[ResearchDirection] = []
    seen = {normalize_query(seed.query) for seed in seeds}

    for direction in directions:
        topic = " ".join(direction.topic.split())
        query = " ".join(direction.query.split())
        intent = " ".join(direction.intent.split())
        key = normalize_query(query)

        if not topic or not query or not intent:
            continue
        if key in seen:
            continue

        seen.add(key)
        selected.append(ResearchDirection(topic=topic, query=query, intent=intent))

        if len(selected) == n:
            return selected

    raise ValueError(f"Expected {n} distinct Research Directions")


class DefineResearchQuestion(dspy.Signature):
    """
    You are defining a focused research question from an initial research
    idea.

    Write a concise title and one main question that preserve the central
    concern of the idea and can guide subsequent research. If the idea is
    broad, narrow its scope without introducing assumptions that the idea
    does not support.
    """

    idea: ResearchIdea = dspy.InputField()

    research_question: ResearchQuestion = dspy.OutputField()


class SelectFieldsOfStudy(dspy.Signature):
    """
    You are choosing fields of study for a literature search.

    Select the smallest set of fields that contains the literature required
    by the research question. Use more than one field only when each field
    contributes a necessary body of research.

    If a field restriction could exclude a central part of the question,
    return an empty list. Do not return more than the requested number.
    """

    research_question: ResearchQuestion = dspy.InputField()
    max_fields: int = dspy.InputField()

    fields_of_study: list[AcademicField] = dspy.OutputField()


class GenerateRetrievalSeeds(dspy.Signature):
    """
    You are writing the initial literature-search queries for a research
    question.

    Use compact noun phrases in terminology likely to occur in paper titles
    and abstracts. Preserve the central constructs of the question and give
    each query a different point of entry into the literature.

    Write exactly the requested number of neutral search queries. Use concise
    search phrases, normally five to ten words, rather than complete questions
    or hypothetical claims.
    """

    research_question: ResearchQuestion = dspy.InputField()
    n: int = dspy.InputField()

    retrieval_seeds: list[RetrievalSeed] = dspy.OutputField()


class ProposeResearchDirections(dspy.Signature):
    """
    You are proposing complementary research directions after reviewing
    passages returned by the initial literature searches.

    Use the research question, Retrieval Seeds, and passages to identify
    different explanations, methods, populations, conditions, settings, or
    consequences that warrant further search. Each direction should remain
    within the investigation while extending beyond the literature emphasized
    by the initial queries.

    Write exactly the requested number of directions. Give each direction a
    topic of two to four words that labels the line of inquiry, a compact
    literature-search query, and an intent that explains why that literature
    is relevant.

    If no passages are available, form the directions from the research
    question and Retrieval Seeds.
    """

    research_question: ResearchQuestion = dspy.InputField()
    retrieval_seeds: list[RetrievalSeed] = dspy.InputField()
    passages: list[Snippet] = dspy.InputField()
    n: int = dspy.InputField()

    research_directions: list[ResearchDirection] = dspy.OutputField()


class ResearchDiscovery(dspy.Module):
    def __init__(
        self,
        literature_search: LiteratureSearch,
        config: DiscoveryConfig | None = None,
    ):
        super().__init__()

        self.define_research_question = dspy.Predict(DefineResearchQuestion)
        self.select_fields_of_study = dspy.Predict(SelectFieldsOfStudy)
        self.generate_retrieval_seeds = dspy.Predict(GenerateRetrievalSeeds)
        self.propose_research_directions = dspy.Predict(ProposeResearchDirections)

        self.literature_search = literature_search
        self.config = config or DiscoveryConfig()

    async def aforward(self, idea: ResearchIdea, n: int = 3):
        if not 1 <= n <= 5:
            raise ValueError("n must be between 1 and 5")
        if not 1 <= self.config.n_seeds <= 3:
            raise ValueError("n_seeds must be between 1 and 3")
        if not 0 <= self.config.max_fields <= 2:
            raise ValueError("max_fields must be between 0 and 2")
        if self.config.passage_limit < 1:
            raise ValueError("passage_limit must be positive")

        prediction = await self.define_research_question.acall(idea=idea)

        research_question = ResearchQuestion(
            title=" ".join(prediction.research_question.title.split()),
            main_question=" ".join(
                prediction.research_question.main_question.split()
            ),
        )

        if not research_question.title or not research_question.main_question:
            raise ValueError("ResearchQuestion is incomplete")

        seeds_call = self.generate_retrieval_seeds.acall(
            research_question=research_question,
            n=self.config.n_seeds,
        )

        if self.config.max_fields:
            fields_prediction, seeds_prediction = await asyncio.gather(
                self.select_fields_of_study.acall(
                    research_question=research_question,
                    max_fields=self.config.max_fields,
                ),
                seeds_call,
            )
            fields_of_study = distinct_fields(
                fields_prediction.fields_of_study,
                max_fields=self.config.max_fields,
            )
        else:
            fields_of_study = []
            seeds_prediction = await seeds_call

        retrieval_seeds = distinct_seeds(
            seeds_prediction.retrieval_seeds,
            n=self.config.n_seeds,
        )

        searches, passages = await self.literature_search.search_seeds(
            retrieval_seeds,
            fields_of_study,
            limit=self.config.passage_limit,
        )

        prediction = await self.propose_research_directions.acall(
            research_question=research_question,
            retrieval_seeds=retrieval_seeds,
            passages=passages,
            n=n,
        )

        research_directions = distinct_directions(
            prediction.research_directions,
            seeds=retrieval_seeds,
            n=n,
        )

        search_plan = SearchPlan(
            idea=idea,
            research_question=research_question,
            fields_of_study=fields_of_study,
            retrieval_seeds=retrieval_seeds,
            research_directions=research_directions,
        )

        return dspy.Prediction(
            search_plan=search_plan,
            searches=searches,
            passages=passages,
        )
