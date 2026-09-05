"""Provider-boundary contracts for proposal-derived discussion topics."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from agora.focused import agents
from agora.focused.agents import FocusedAgentError
from agora.focused.demo_data import DEMO_PAPERS
from agora.focused.models import (
    FACETS,
    DiscussionTopicDraft,
    DiscussionTopicDrafts,
    FacetEvidence,
    Perspective,
)


def _perspective(index: int, name: str) -> Perspective:
    paper = DEMO_PAPERS[index]
    return Perspective(
        id=f"persp-{index}",
        name=name,
        color="#336699",
        facets={
            facet: FacetEvidence(
                facet=facet,
                text=paper.abstract_sentences[slot],
                paper_id=paper.id,
                sentence_index=slot,
                sentence=paper.abstract_sentences[slot],
            )
            for slot, facet in enumerate(FACETS)
        },
        sources=[paper.id],
        anchor_paper_id=paper.id,
    )


PERSPECTIVES = [
    _perspective(0, "Population resistance cost"),
    _perspective(1, "Host microbiome integrity"),
]


class ScriptedProvider:
    def __init__(self, *replies: DiscussionTopicDrafts) -> None:
        self.replies = list(replies)
        self.calls = 0

    async def generate_structured(self, **_):
        self.calls += 1
        return SimpleNamespace(parsed=self.replies.pop(0))


def _drafts(
    perspectives: list[Perspective], *, citation: str | None = None
) -> DiscussionTopicDrafts:
    return DiscussionTopicDrafts(
        topics=[
            DiscussionTopicDraft(
                perspective_id=perspective.id,
                title=f"{perspective.name} boundary",
                question=f"Does {perspective.name.lower()} hold beyond ward {index}?",
                hypothesis=f"If it drives the effect, cohort {index} should weaken.",
                rationale=f"The abstracts report a {perspective.name.lower()} link.",
                citations=[citation or DEMO_PAPERS[index].id],
            )
            for index, perspective in enumerate(perspectives)
        ]
    )


def _generate(provider) -> list[DiscussionTopicDraft]:
    return asyncio.run(
        agents.generate_discussion_topics(
            problem="How should antibiotic breadth be bounded?",
            perspectives=PERSPECTIVES,
            papers=DEMO_PAPERS,
            provider=provider,
        )
    )


def test_one_correction_pass_recovers_a_cited_topic_set() -> None:
    provider = ScriptedProvider(
        _drafts(PERSPECTIVES, citation="p99"), _drafts(PERSPECTIVES)
    )
    topics = _generate(provider)
    assert provider.calls == 2
    assert [topic.perspective_id for topic in topics] == [
        perspective.id for perspective in PERSPECTIVES
    ]
    assert [topic.citations for topic in topics] == [["p1"], ["p2"]]


def test_fabricated_citations_fail_instead_of_reaching_the_notepad() -> None:
    provider = ScriptedProvider(
        _drafts(PERSPECTIVES, citation="p99"),
        _drafts(PERSPECTIVES, citation="p99"),
    )
    with pytest.raises(FocusedAgentError):
        _generate(provider)
    assert provider.calls == 2


def test_incomplete_perspective_coverage_is_rejected() -> None:
    provider = ScriptedProvider(_drafts(PERSPECTIVES[:1]), _drafts(PERSPECTIVES[:1]))
    with pytest.raises(FocusedAgentError, match="Host microbiome integrity"):
        _generate(provider)


def test_duplicate_perspective_topics_are_rejected() -> None:
    doubled = DiscussionTopicDrafts(
        topics=[*_drafts(PERSPECTIVES[:1]).topics, *_drafts(PERSPECTIVES[:1]).topics]
    )
    with pytest.raises(FocusedAgentError):
        _generate(ScriptedProvider(doubled, doubled))


def test_unrelated_corpus_papers_cannot_supply_a_perspectives_topic() -> None:
    perspective = PERSPECTIVES[0].model_copy(
        update={"sources": ["missing"], "anchor_paper_id": "missing", "facets": {}}
    )
    with pytest.raises(FocusedAgentError, match="no abstract evidence"):
        asyncio.run(
            agents.generate_discussion_topics(
                problem="How should antibiotic breadth be bounded?",
                perspectives=[perspective],
                papers=DEMO_PAPERS,
            )
        )


def test_facet_text_without_its_source_abstract_is_not_topic_evidence() -> None:
    paper = DEMO_PAPERS[0].model_copy(
        update={"abstract": None, "abstract_sentences": []}
    )
    with pytest.raises(FocusedAgentError, match="no abstract evidence"):
        asyncio.run(
            agents.generate_discussion_topics(
                problem="How should antibiotic breadth be bounded?",
                perspectives=PERSPECTIVES[:1],
                papers=[paper],
            )
        )


def test_paper_ids_in_a_topic_question_require_correction() -> None:
    invalid = _drafts(PERSPECTIVES)
    invalid.topics[0].question = "[p1]?"
    with pytest.raises(FocusedAgentError, match="paper IDs"):
        _generate(ScriptedProvider(invalid, invalid))


def test_rebuilt_demo_perspective_gets_a_distinct_topic_with_a_long_name() -> None:
    async def go() -> None:
        perspectives = [
            _perspective(index, "R" * 200 if index == 0 else f"Panelist {index}")
            for index in range(6)
        ]
        existing = await agents.generate_discussion_topics(
            problem="How should antibiotic breadth be bounded?",
            perspectives=perspectives,
            papers=DEMO_PAPERS,
        )
        rebuilt = perspectives[0].model_copy(update={"id": "rebuilt-perspective"})
        new = await agents.generate_discussion_topics(
            problem="How should antibiotic breadth be bounded?",
            perspectives=[rebuilt],
            papers=DEMO_PAPERS,
            existing_topics=existing,
        )
        assert new[0].question not in {topic.question for topic in existing}
        assert len(new[0].title) <= 200

    asyncio.run(go())
