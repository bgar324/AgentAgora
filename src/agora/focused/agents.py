"""LLM and deterministic agents for abstract-grounded facet deliberation.

The study protocol has four stable facets: scope, explanation, approach, and
significance. Each round activates exactly one facet. The moderator records
consensus, genuine disagreement, and unresolved questions without forcing
opposition.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from typing import TYPE_CHECKING, Any, TypeVar

from pydantic import BaseModel

from agora.focused.models import (
    FACETS,
    NOTEPAD_LABELS,
    NOTEPAD_PARTS,
    ChatReply,
    ClusterNaming,
    ClusterNamings,
    DeliberationDocument,
    DeliberationPoint,
    DeliberationRound,
    DeliberationThread,
    DeliberationThreadDraft,
    DeliberationThreads,
    DerivedQuestions,
    DocumentDraft,
    DocumentSection,
    ExpPaper,
    Facet,
    FacetEvidence,
    FacetExtraction,
    FacetRevision,
    FramingPosition,
    HypothesisDev,
    HypothesisSteps,
    NotepadDoc,
    ParticipantReflection,
    Perspective,
    QuerySuggestions,
    QuestionAssessment,
    QuestionEvidence,
    QuestionExpansion,
    QuestionPlan,
    QuestionRecommendations,
    RecommendedQuestion,
    ReflectionDraft,
    RoundResolution,
    SharedGroundAssentDraft,
    Statement,
    SuggestedQuery,
    SupportPassage,
    SupportSearch,
    ThreadPerspectiveLink,
    ThreadVerdict,
    ThreadVerdictOutput,
    VocabularyPair,
)
from agora.focused.routing import FocusedTask

if TYPE_CHECKING:
    from agora.focused.provider import FocusedProvider


logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class FocusedAgentError(RuntimeError):
    """A live focused-panel model call failed. Demo sessions never raise this."""


STOPWORDS = frozenset(
    "the a an and or of to for in on at is are be been being should would could "  # noqa: SIM905
    "i you we my me it its that this these those with without against off both "
    "no not can how what why when does do doing done their there our your from "
    "as by they them then than also into about over under more most some any "
    "which who whom whose will may might must shall question questions research "
    "paper papers study studies work".split()
)

_FACET_DISPLAY: dict[Facet, str] = {
    "scope": "the phenomena, settings, populations, tasks, and conditions",
    "explanation": "how the phenomenon is understood",
    "approach": "how the claim is investigated or established",
    "significance": "why the claim is consequential",
}


def _display(value: str) -> str:
    v = (value or "").strip().rstrip(".")
    return v[0].lower() + v[1:] if v and not v[:2].isupper() else v


def _content_words(text: str) -> list[str]:
    return [
        w for w in re.findall(r"[a-z][a-z-]{3,}", text.lower()) if w not in STOPWORDS
    ]


def _search_query_words(text: str) -> list[str]:
    words = re.findall(r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*", text)
    return [
        word.lower()
        for word in words
        if len(word) > 1 and word.lower() not in STOPWORDS
    ]


SEARCH_QUERY_FILLER = frozenset(
    {
        "ability",
        "cases",
        "determine",
        "different",
        "identify",
        "provide",
        "relevant",
        "reliably",
        "request",
        "various",
    }
)


def compact_search_query(query: str, *, max_terms: int = 6) -> str:
    text = " ".join(query.split())
    content = _search_query_words(text)
    unsafe = (
        "?" in text
        or "？" in text
        or '"' in text
        or re.search(r"\b(?:AND|OR|NOT)\b", text) is not None
        or len(content) > max_terms
    )
    if not unsafe:
        return text
    terms = list(
        dict.fromkeys(word for word in content if word not in SEARCH_QUERY_FILLER)
    )
    if len(terms) < 2:
        terms = list(dict.fromkeys(content))
    return " ".join(terms[:max_terms]) or text.rstrip("?？")


def relaxed_search_query(query: str, *, terms: int = 3) -> str:
    content = list(
        dict.fromkeys(
            word
            for word in _search_query_words(query)
            if word not in SEARCH_QUERY_FILLER
        )
    )
    if not content:
        return ""
    return " ".join(content[-terms:])


async def _structured(
    provider: FocusedProvider | None,
    system: str,
    user: str,
    schema: type[T],
    temperature: float | None = None,
    max_output_tokens: int | None = None,
    *,
    task: FocusedTask,
) -> T | None:
    """Demo/no-provider → None (caller falls back). Live calls raise typed errors."""
    if provider is None:
        return None
    try:
        result = await provider.generate_structured(
            task=task,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            schema=schema,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
        )
        return result.parsed
    except Exception as exc:
        logger.exception("Live LLM call failed for %s", schema.__name__)
        raise FocusedAgentError(
            f"live LLM call failed ({schema.__name__}): {exc}"
        ) from exc


def split_sentences(text: str | None) -> list[str]:
    if not text:
        return []
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z(])", text.strip())
    return [p.strip() for p in parts if p.strip()]


# ---------------------------------------------------------------------------
# [1] five diversified search queries
# ---------------------------------------------------------------------------


def _fallback_queries(
    problem: str, questions: list[str], count: int
) -> list[SuggestedQuery]:
    out: list[SuggestedQuery] = []
    seen: set[str] = set()

    def push(q: str, rationale: str) -> None:
        q = " ".join(q.split())
        key = q.lower().rstrip("?")
        if len(q) > 12 and key not in seen:
            seen.add(key)
            out.append(SuggestedQuery(query=q, rationale=rationale))

    words = _content_words(problem)
    freq = [w for w, _ in Counter(words).most_common(6)]
    if freq:
        push(
            " ".join(freq[:4]) + " evidence",
            "Core constructs of the problem statement.",
        )
    for q in questions:
        push(compact_search_query(q), "Taken directly from your research questions.")
    if len(freq) >= 4:
        push(
            f"{freq[0]} versus {freq[min(2, len(freq) - 1)]}",
            "Opposes two constructs to reach the debate literature.",
        )
        push(
            f"mechanisms of {freq[0]} and {freq[1]}", "Reaches mechanism-oriented work."
        )
    i = 0
    while len(out) < count and freq:
        pair = f"{freq[i % len(freq)]} {freq[(i + 2) % len(freq)]} review"
        push(pair, "Broad review literature for coverage.")
        i += 1
        if i > count * 3:
            break
    return out[:count]


def _position_block(position: NotepadDoc | None) -> str:
    """The researcher's own four-part position, when they wrote one.

    Youngseung's baseline draws queries from the problem *and* these parts,
    so a stated methodology or expected result steers retrieval instead of
    sitting unused on the input screen.
    """
    if position is None:
        return ""
    parts = [
        (NOTEPAD_LABELS[part], " ".join(getattr(position, part).split()))
        for part in NOTEPAD_PARTS
    ]
    written = [f"### {label}\n{text}" for label, text in parts if text]
    if not written:
        return ""
    return "\n\n## RESEARCHER POSITION\n" + "\n".join(written)


async def suggest_queries(
    problem: str,
    questions: list[str],
    *,
    position: NotepadDoc | None = None,
    provider: FocusedProvider | None = None,
    count: int = 5,
) -> list[SuggestedQuery]:
    parsed = await _structured(
        provider,
        "You write literature-search queries for Semantic Scholar. Queries must "
        "reach DIFFERENT parts of the literature rather than overlapping. Use "
        "two to six unquoted academic keywords or a short noun phrase in "
        "established literature vocabulary. Do not write questions, Boolean "
        "expressions, prose sentences, or notation such as Pₓ. Return exactly "
        f"{count} queries.",
        f"## RESEARCH PROBLEM\n{problem}\n\n## RESEARCH QUESTIONS\n"
        + "\n".join(f"- {q}" for q in questions)
        + _position_block(position),
        QuerySuggestions,
        task=FocusedTask.suggest_queries,
        temperature=0.4,
    )
    if parsed and parsed.queries:
        return [
            query.model_copy(update={"query": compact_search_query(query.query)})
            for query in parsed.queries[:count]
        ]
    return _fallback_queries(problem, questions, count)


async def derive_research_questions(
    problem: str,
    *,
    position: NotepadDoc | None = None,
    provider: FocusedProvider | None = None,
    count: int = 3,
) -> list[str]:
    """Derive the research questions a user no longer types.

    The questions power answer-tier retrieval (question planning, paper
    assessment, coverage ranking). Returns [] when the model yields
    nothing usable, which degrades retrieval to problem-angle queries.
    """
    parsed = await _structured(
        provider,
        "You turn one research problem into the questions a literature "
        "search must answer. Write two or three answerable research "
        "questions, each probing a DIFFERENT empirical uncertainty already "
        "present in the problem statement. Preserve the problem's own "
        "concepts; do not introduce neighboring topics. One sentence each, "
        f"ending in a question mark. Return at most {count} questions.",
        f"## RESEARCH PROBLEM\n{problem}" + _position_block(position),
        DerivedQuestions,
        task=FocusedTask.derive_research_questions,
        temperature=0.3,
    )
    if parsed is None:
        return []
    questions = []
    for question in parsed.questions:
        text = " ".join(question.split()).strip()
        if len(text) > 11 and text not in questions:
            questions.append(text)
    return questions[:count]


# ---------------------------------------------------------------------------
# Question-specific reach: own terms → answering papers → literature terms
# ---------------------------------------------------------------------------

QUESTION_PLAN_SYSTEM = """\
You plan a Semantic Scholar literature search for one research question.
Preserve the question's scientific concepts. Return the form of an answer,
two to four candidate answers, and two search queries aimed at those
candidates. Each query must contain two to six unquoted academic keywords or
a short noun phrase in established literature vocabulary. Do not write
questions, Boolean expressions, prose sentences, or notation such as Pₓ.
Do not silently replace a key concept with a neighboring concept."""

QUESTION_PLAN_USER = """\
Research problem (context only):
{problem}

Research question:
{question}
"""

QUESTION_ASSESS_SYSTEM = """\
You identify papers that actually answer a research question. A paper counts
only when its supplied abstract or passage supports, opposes, or conditions a
candidate answer. Return one verbatim evidence sentence for every selected
paper. Also report vocabulary the literature uses differently."""

QUESTION_ASSESS_USER = """\
Question:
{question}

Candidate answers:
{candidates}

Retrieved papers:
{papers}
"""


async def plan_question_search(
    problem: str,
    question: str,
    *,
    provider: FocusedProvider | None = None,
) -> QuestionPlan:
    parsed = await _structured(
        provider,
        QUESTION_PLAN_SYSTEM,
        QUESTION_PLAN_USER.format(problem=problem, question=question),
        QuestionPlan,
        task=FocusedTask.plan_question_search,
        temperature=0.2,
    )
    if parsed is not None:
        return parsed.model_copy(
            update={
                "candidates": [
                    candidate.strip()
                    for candidate in parsed.candidates
                    if candidate.strip()
                ],
                "queries": [
                    query.model_copy(
                        update={"query": compact_search_query(query.query)}
                    )
                    for query in parsed.queries
                    if compact_search_query(query.query)
                ][:2],
            }
        )
    terms = _content_words(question)
    query = " ".join(terms[:7]) or question.strip().rstrip("?")
    return QuestionPlan(
        form="",
        candidates=[question.strip()],
        queries=[
            SuggestedQuery(
                query=query,
                rationale="Searches in the research question's own terms.",
                kind="question",
            )
        ],
    )


def _evidence_is_verbatim(paper: ExpPaper, evidence: str) -> bool:
    needle = " ".join(evidence.split()).casefold()
    if not needle:
        return False
    haystacks = [paper.abstract or "", *paper.abstract_sentences]
    return any(needle in " ".join(text.split()).casefold() for text in haystacks)


async def assess_question_papers(
    question: str,
    candidates: list[str],
    papers: list[ExpPaper],
    *,
    provider: FocusedProvider | None = None,
) -> QuestionAssessment:
    if not papers:
        return QuestionAssessment()
    parsed = await _structured(
        provider,
        QUESTION_ASSESS_SYSTEM,
        QUESTION_ASSESS_USER.format(
            question=question,
            candidates="\n".join(
                f"{index}. {candidate}" for index, candidate in enumerate(candidates, 1)
            )
            or "(none)",
            papers="\n\n".join(
                f"[{paper.id}] {paper.title}\n{paper.abstract or ''}"
                for paper in papers
            ),
        ),
        QuestionAssessment,
        task=FocusedTask.assess_question_papers,
        temperature=0.1,
        max_output_tokens=None,
    )
    if parsed is None:
        target_terms = set(_content_words(" ".join([question, *candidates])))
        threshold = 1 if len(target_terms) < 4 else 2
        selected = []
        for paper in papers:
            sentences = paper.abstract_sentences or split_sentences(paper.abstract)
            ranked = [
                (
                    len(target_terms & set(_content_words(sentence))),
                    sentence,
                )
                for sentence in sentences
                if sentence.strip()
            ]
            score, evidence = max(ranked, default=(0, ""))
            if score >= threshold:
                selected.append(
                    QuestionEvidence(
                        paper_id=paper.id,
                        candidate_index=1 if candidates else None,
                        bears="conditions",
                        evidence=evidence,
                    )
                )
        return QuestionAssessment(selected=selected)

    by_id = {paper.id: paper for paper in papers}
    selected: list[QuestionEvidence] = []
    seen: set[str] = set()
    for item in parsed.selected:
        paper = by_id.get(item.paper_id)
        candidate_ok = item.candidate_index is None or 1 <= item.candidate_index <= len(
            candidates
        )
        if (
            paper is not None
            and item.paper_id not in seen
            and candidate_ok
            and _evidence_is_verbatim(paper, item.evidence)
        ):
            seen.add(item.paper_id)
            selected.append(item)
    return QuestionAssessment(
        selected=selected,
        vocabulary=[
            pair
            for pair in parsed.vocabulary
            if pair.ours.strip() and pair.theirs.strip()
        ],
    )


QUESTION_EXPAND_SYSTEM = """\
You write follow-up Semantic Scholar queries after a first retrieval pass.
Use the vocabulary observed in the selected literature to reach additional
papers that answer the same research question. Return at most two compact
queries of three to eight words. Do not use Boolean operators, quotation marks,
questions, or prose sentences."""


async def expand_question_search(
    question: str,
    candidates: list[str],
    vocabulary: list[VocabularyPair],
    papers: list[ExpPaper],
    *,
    provider: FocusedProvider | None = None,
) -> list[SuggestedQuery]:
    if not papers:
        return []
    parsed = await _structured(
        provider,
        QUESTION_EXPAND_SYSTEM,
        "\n".join(
            [
                f"Research question: {question}",
                "Candidate answers:",
                *[f"- {candidate}" for candidate in candidates],
                "Observed vocabulary:",
                *[f"- {pair.ours} -> {pair.theirs}" for pair in vocabulary],
                "Selected literature:",
                *[
                    f"- [{paper.id}] {paper.title}: {(paper.abstract or '')[:500]}"
                    for paper in papers[:12]
                ],
            ]
        ),
        QuestionExpansion,
        task=FocusedTask.expand_question_search,
        temperature=0.2,
    )
    if parsed is not None:
        queries = [
            query.model_copy(
                update={
                    "query": compact_search_query(query.query),
                    "kind": "question",
                    "round": 2,
                }
            )
            for query in parsed.queries
            if compact_search_query(query.query)
        ]
        return queries[:2]
    terms = list(
        dict.fromkeys(
            [
                *(
                    term
                    for pair in vocabulary
                    for term in _search_query_words(pair.theirs)
                ),
                *(
                    term
                    for paper in papers[:5]
                    for term in _search_query_words(paper.title)
                ),
            ]
        )
    )
    query = " ".join(terms[:6])
    return (
        [
            SuggestedQuery(
                query=query,
                rationale="Uses vocabulary observed in answering papers.",
                kind="question",
                round=2,
            )
        ]
        if query
        else []
    )


CORPUS_EXPAND_SYSTEM = """\
You expand an underfilled scientific-paper corpus for clustering.
Write complementary Semantic Scholar queries that cover populations, methods,
mechanisms, outcomes, and counterpositions underrepresented by the prior
queries. Use compact title-and-abstract terminology. Do not repeat a prior
query, write prose questions, or use Boolean operators or quotation marks.
Return at most four queries of three to eight words."""


async def expand_corpus_search(
    problem: str,
    questions: list[str],
    prior_queries: list[str],
    vocabulary: list[VocabularyPair],
    *,
    current_papers: int,
    target_papers: int,
    provider: FocusedProvider | None = None,
) -> list[SuggestedQuery]:
    parsed = await _structured(
        provider,
        CORPUS_EXPAND_SYSTEM,
        "\n".join(
            [
                f"Research problem: {problem}",
                "Research questions:",
                *[f"- {question}" for question in questions],
                f"Current unique papers: {current_papers}",
                f"Target unique papers: {target_papers}",
                "Prior queries:",
                *[f"- {query}" for query in prior_queries],
                "Observed vocabulary:",
                *[f"- {pair.ours} -> {pair.theirs}" for pair in vocabulary],
            ]
        ),
        QuerySuggestions,
        task=FocusedTask.expand_question_search,
        temperature=0.2,
    )
    if parsed is None:
        return []
    prior = {" ".join(query.casefold().split()) for query in prior_queries}
    selected: list[SuggestedQuery] = []
    seen = set(prior)
    for suggestion in parsed.queries:
        query = compact_search_query(suggestion.query)
        key = " ".join(query.casefold().split())
        if not query or key in seen:
            continue
        seen.add(key)
        selected.append(
            suggestion.model_copy(
                update={"query": query, "kind": "problem", "round": 2}
            )
        )
        if len(selected) == 4:
            break
    return selected


# ---------------------------------------------------------------------------
# [2] cluster name + blurb
# ---------------------------------------------------------------------------


def _cluster_terms(papers: list[ExpPaper]) -> Counter[str]:
    terms: Counter[str] = Counter()
    for paper in papers:
        terms.update(_content_words(paper.title))
        if paper.abstract:
            terms.update(set(_content_words(paper.abstract[:400])))
    return terms


def _cluster_names_too_similar(
    candidate: str,
    existing: list[ClusterNaming],
) -> bool:
    candidate_terms = set(_content_words(candidate))
    if not candidate_terms:
        return True
    for naming in existing:
        if candidate.casefold().strip() == naming.name.casefold().strip():
            return True
        existing_terms = set(_content_words(naming.name))
        if existing_terms and (
            len(candidate_terms & existing_terms) * 3
            >= min(len(candidate_terms), len(existing_terms)) * 2
        ):
            return True
    return False


def _fallback_cluster_name(
    papers: list[ExpPaper],
    *,
    comparison: list[ExpPaper] | None = None,
    blocked_names: list[str] | None = None,
) -> ClusterNaming:
    local = _cluster_terms(papers)
    outside = _cluster_terms(comparison or [])
    blocked = set(_content_words(" ".join(blocked_names or [])))
    ranked = sorted(
        local,
        key=lambda word: (
            local[word] / (1 + outside[word]),
            local[word],
            -outside[word],
            len(word),
        ),
        reverse=True,
    )
    top = [word for word in ranked if len(word) > 3 and word not in blocked][:2]
    if not top:
        top = [word for word in ranked if len(word) > 3][:2]
    name = " ".join(word.title() for word in top) or "Mixed Literature"
    subject = " and ".join(word.replace("-", " ") for word in top)
    blurb = (
        f"Papers centered on {subject}."
        if subject
        else f"A cluster of {len(papers)} related papers."
    )
    return ClusterNaming(name=name, blurb=blurb)


async def name_clusters(
    groups: list[list[ExpPaper]],
    *,
    provider: FocusedProvider | None = None,
) -> list[ClusterNaming]:
    if not groups:
        return []
    sections = []
    for index, papers in enumerate(groups, 1):
        corpus = "\n".join(
            f"- {paper.title}"
            + (f" — {paper.abstract[:280]}" if paper.abstract else "")
            for paper in papers[:12]
        )
        sections.append(f"## CLUSTER {index}\n{corpus}")
    parsed = await _structured(
        provider,
        "Name all scientific-paper clusters in one comparative pass. Return "
        "exactly one entry per numbered cluster, in the same order. Each name "
        "must be 2-4 words and identify what distinguishes that cluster from "
        "its siblings: a population, outcome, mechanism, method, intervention "
        "contrast, or practical concern. Names must be mutually distinct. Do "
        "not use the corpus-wide topic as a complete name. Do not create "
        "cosmetic variants by adding words such as Effects, Studies, or "
        "Evidence. Spell out abbreviations; do not introduce acronyms. Each "
        "blurb is one sentence describing the distinction.",
        "\n\n".join(sections),
        ClusterNamings,
        task=FocusedTask.name_clusters,
        temperature=0.1,
        max_output_tokens=1_600,
    )
    candidates = parsed.clusters if parsed is not None else []
    named: list[ClusterNaming] = []
    all_papers = [paper for group in groups for paper in group]
    for index, papers in enumerate(groups):
        candidate = candidates[index] if index < len(candidates) else None
        if (
            candidate is not None
            and candidate.name.strip()
            and not _cluster_names_too_similar(candidate.name, named)
        ):
            named.append(
                candidate.model_copy(
                    update={
                        "name": candidate.name.strip(),
                        "blurb": candidate.blurb.strip(),
                    }
                )
            )
            continue
        comparison = [paper for paper in all_papers if paper not in papers]
        fallback = _fallback_cluster_name(
            papers,
            comparison=comparison,
            blocked_names=[item.name for item in named],
        )
        if candidate is not None and candidate.blurb.strip():
            fallback = fallback.model_copy(update={"blurb": candidate.blurb.strip()})
        named.append(fallback)
    return named


# ---------------------------------------------------------------------------
# Four abstract-grounded perspective facets
# ---------------------------------------------------------------------------

_FACET_PATTERNS: dict[Facet, list[str]] = {
    "scope": [
        r"\b(?:covers|examines|focuses on|includes|among|patients|population|setting)\b",
    ],
    "explanation": [
        r"\b(?:because|explains?|drives?|leads? to|associated with|predicts?|mechanism)\b",
    ],
    "approach": [
        r"\b(?:cohort|trial|model|analysis|experiment|sequencing|survey|validated|compares?)\b",
    ],
    "significance": [
        r"\b(?:matters?|consequential|supports?|implies?|risk|benefit|cost|mortality|harm)\b",
    ],
}


def _abstract_sentences(paper: ExpPaper) -> list[str]:
    return paper.abstract_sentences or split_sentences(paper.abstract)


def _compress(sentence: str, limit: int = 180) -> str:
    text = sentence.strip().rstrip(".")
    text = re.sub(
        r"^(However|Moreover|Furthermore|In addition)[, ]\s*",
        "",
        text,
        flags=re.IGNORECASE,
    )
    if len(text) <= limit:
        return text
    cut = text[:limit]
    comma = cut.rfind(", ")
    return (cut[:comma] if comma > limit * 0.5 else cut).strip()


def fallback_cluster_facets(papers: list[ExpPaper]) -> list[FacetEvidence]:
    """Deterministic extraction over abstracts only."""
    available = [
        (paper, index, sentence)
        for paper in papers
        for index, sentence in enumerate(_abstract_sentences(paper))
        if sentence.strip()
    ]
    if not available:
        return []

    out: list[FacetEvidence] = []
    for facet_index, facet in enumerate(FACETS):
        selected = next(
            (
                item
                for item in available
                if any(
                    re.search(pattern, item[2].lower())
                    for pattern in _FACET_PATTERNS[facet]
                )
            ),
            available[facet_index % len(available)],
        )
        paper, sentence_index, sentence = selected
        out.append(
            FacetEvidence(
                facet=facet,
                text=_compress(sentence),
                paper_id=paper.id,
                sentence_index=sentence_index,
                sentence=sentence,
            )
        )
    return out


def _tally_facets(demo_facets: list[list[FacetEvidence]]) -> list[FacetEvidence]:
    """Select the most recurrent grounded facet value in a demo cluster."""
    out: list[FacetEvidence] = []
    for facet in FACETS:
        tally: Counter[str] = Counter()
        by_text: dict[str, FacetEvidence] = {}
        for facets in demo_facets:
            for evidence in facets:
                if evidence.facet == facet:
                    tally[evidence.text] += 1
                    by_text.setdefault(evidence.text, evidence)
        if tally:
            text = tally.most_common(1)[0][0]
            out.append(by_text[text].model_copy(deep=True))
    return out


async def extract_cluster_facets(
    papers: list[ExpPaper],
    *,
    provider: FocusedProvider | None = None,
    demo_facets: list[list[FacetEvidence]] | None = None,
) -> list[FacetEvidence]:
    if demo_facets is not None:
        return _tally_facets(demo_facets)

    corpus = "\n\n".join(
        f"### {paper.id}: {paper.title}\n"
        + "\n".join(
            f"{index}. {sentence}"
            for index, sentence in enumerate(_abstract_sentences(paper))
        )
        for paper in papers[:8]
    )
    parsed = await _structured(
        provider,
        "Extract exactly four facets that characterize this body of work. "
        "SCOPE names the phenomena, settings, populations, tasks, or conditions "
        "covered. EXPLANATION states how the phenomenon is understood. APPROACH "
        "states how claims are investigated or established. SIGNIFICANCE states "
        "why the work is consequential. Use only the supplied abstracts. Each "
        "facet must be a short quote or tight paraphrase with the paper_id and "
        "zero-based sentence_index of its supporting abstract sentence.",
        f"## ABSTRACTS\n{corpus}",
        FacetExtraction,
        task=FocusedTask.extract_cluster_facets,
        temperature=0.1,
    )
    if parsed and parsed.facets:
        by_id = {paper.id: paper for paper in papers}
        candidates = [
            FacetEvidence.model_validate(evidence.model_dump())
            for evidence in parsed.facets
        ]
        return [
            map_facet_to_sentence(by_id[evidence.paper_id], evidence)
            if evidence.paper_id in by_id
            else evidence
            for evidence in candidates
        ]
    return fallback_cluster_facets(papers)


def map_facet_to_sentence(paper: ExpPaper, evidence: FacetEvidence) -> FacetEvidence:
    """Ground a facet in the exact abstract sentence it came from."""
    sentences = _abstract_sentences(paper)
    value = evidence.text.strip().lower()
    for index, sentence in enumerate(sentences):
        normalized = sentence.lower()
        if value and (value in normalized or normalized in value):
            return evidence.model_copy(
                update={
                    "paper_id": paper.id,
                    "sentence_index": index,
                    "sentence": sentence,
                }
            )

    words = set(_content_words(evidence.text))
    best_index: int | None = None
    best_score = 0.0
    for index, sentence in enumerate(sentences):
        score = len(words & set(_content_words(sentence))) / max(len(words), 1)
        if score > best_score:
            best_index, best_score = index, score
    if best_index is not None and best_score >= 0.5:
        return evidence.model_copy(
            update={
                "paper_id": paper.id,
                "sentence_index": best_index,
                "sentence": sentences[best_index],
            }
        )
    return evidence


def _facets_block(perspective: Perspective) -> str:
    return "\n".join(
        f"- {facet}: {perspective.facets[facet].text}"
        for facet in FACETS
        if facet in perspective.facets
    )


def _facet_text(perspective: Perspective, facet: Facet) -> str:
    evidence = perspective.facets.get(facet)
    return evidence.text if evidence and evidence.text.strip() else "not established"


def _sentence(value: str) -> str:
    """A facet's evidence as a standalone sentence."""
    text = " ".join((value or "").split())
    if not text:
        return ""
    text = text[0].upper() + text[1:]
    return text if text.endswith((".", "?", "!")) else f"{text}."


def _fallback_framing(perspective: Perspective) -> FramingPosition:
    # Facet evidence is already whole sentences, so state them as prose.
    # Embedding them in subordinate clauses ("...through A birth cohort
    # links...") reads as a broken template wherever this path runs.
    scope = _sentence(_facet_text(perspective, "scope"))
    explanation = _sentence(_facet_text(perspective, "explanation"))
    approach = _sentence(_facet_text(perspective, "approach"))
    significance = _sentence(_facet_text(perspective, "significance"))
    return FramingPosition(
        framing=" ".join(part for part in (scope, explanation) if part),
        position=" ".join(part for part in (approach, significance) if part),
    )


async def derive_framing(
    perspective: Perspective,
    *,
    provider: FocusedProvider | None = None,
) -> FramingPosition:
    parsed = await _structured(
        provider,
        "Synthesize two coupled descriptions from all four perspective facets. "
        "FRAMING states how scope and explanation orient the question. POSITION "
        "states what approach the perspective trusts and why its significance "
        "matters. These are descriptors, not sequential deliberation rounds.",
        f"## PERSPECTIVE: {perspective.name}\n## FACETS\n{_facets_block(perspective)}",
        FramingPosition,
        task=FocusedTask.derive_framing,
    )
    if parsed and parsed.framing and parsed.position:
        return parsed
    return _fallback_framing(perspective)


# ---------------------------------------------------------------------------
async def suggest_deliberation_threads(
    perspectives: list[Perspective],
    hypothesis: HypothesisDev,
    *,
    provider: FocusedProvider | None = None,
    demo: bool = False,
) -> list[DeliberationThreadDraft]:
    names = [perspective.name for perspective in perspectives]
    parsed = await _structured(
        provider,
        "Propose two to five focused scientific Threads for the next discussion. "
        "Each Thread must address one distinct scientific issue, disagreement, or "
        "open question: a difference in explanation, a measurement problem, a "
        "boundary condition, a disputed assumption, or an evidence gap. Give each "
        "Thread a concise title, a neutral question, and context stating what it "
        "would clarify. Facets only describe where Perspectives differ: report "
        "them per Perspective under `related` as traceability, never as the topic "
        "itself. Reference exact excerpts from the current hypothesis when "
        "relevant.",
        "## CURRENT HYPOTHESIS\n"
        + hypothesis.hypothesis
        + "\n\n## PERSPECTIVES\n"
        + "\n\n".join(
            f"### {perspective.name}\n{_facets_block(perspective)}"
            for perspective in perspectives
        ),
        DeliberationThreads,
        task=FocusedTask.suggest_deliberation_threads,
        temperature=0.1,
    )
    if parsed and parsed.threads:
        known_names = set(names)
        out: list[DeliberationThreadDraft] = []
        for thread in parsed.threads[:5]:
            if not thread.title.strip() or not thread.question.strip():
                continue
            related = [
                link.model_copy(update={"facets": list(dict.fromkeys(link.facets))})
                for link in thread.related
                if link.perspective_name in known_names
            ]
            facets = list(
                dict.fromkeys(
                    [
                        *thread.facets,
                        *(facet for link in related for facet in link.facets),
                    ]
                )
            )
            linked_names = [link.perspective_name for link in related]
            out.append(
                thread.model_copy(
                    update={
                        "title": thread.title.strip(),
                        "question": thread.question.strip(),
                        "context": thread.context.strip(),
                        "related": related,
                        "facets": facets,
                        "perspective_names": list(
                            dict.fromkeys(
                                [
                                    *linked_names,
                                    *(
                                        name
                                        for name in thread.perspective_names
                                        if name in known_names
                                    ),
                                ]
                            )
                        ),
                        "hypothesis_fragments": [
                            fragment
                            for fragment in thread.hypothesis_fragments
                            if fragment and fragment in hypothesis.hypothesis
                        ],
                    }
                )
            )
        if out:
            return out

    pairs = (
        [
            (
                "Acute benefit versus ecological harm",
                "When does faster broad coverage justify resistance selection and microbiome harm?",
                "The Perspectives disagree about which patients benefit enough to justify downstream ecological costs.",
                ["scope", "significance"],
            ),
            (
                "Mechanism of downstream harm",
                "How much of the downstream harm follows from resistance selection versus microbiome disruption?",
                "The candidate depends on causal mechanisms that the Perspectives weight differently.",
                ["explanation"],
            ),
            (
                "Targeting without delayed cure",
                "Can rapid diagnosis and de-escalation preserve acute cure while reducing broad exposure?",
                "The Perspectives propose competing approaches for reducing exposure without compromising immediate treatment.",
                ["approach", "significance"],
            ),
        ]
        if demo
        else [
            (
                "Boundary of the proposed solution",
                "Which populations and conditions should bound this solution candidate?",
                "The Perspectives describe different boundary conditions for the candidate.",
                ["scope"],
            ),
            (
                "Competing causal assumptions",
                "Which explanation best justifies the proposed solution, and what finding could overturn it?",
                "The Perspectives rely on different causal assumptions.",
                ["explanation"],
            ),
            (
                "Evidence needed to choose an approach",
                "Which study design and outcome would distinguish the competing approaches?",
                "The Perspectives disagree about the most informative intervention and outcome.",
                ["approach", "significance"],
            ),
        ]
    )
    return [
        DeliberationThreadDraft(
            title=title,
            question=question,
            context=context,
            related=[
                ThreadPerspectiveLink(perspective_name=name, facets=facets)
                for name in names
            ],
            facets=facets,
            perspective_names=names,
            hypothesis_fragments=[hypothesis.hypothesis],
        )
        for title, question, context, facets in pairs
    ]


# Thread-directed panel discussion. The Thread question defines the topic;
# facets supply supporting context and traceability only.
# ---------------------------------------------------------------------------


def _thread_evidence(
    perspective: Perspective,
    thread: DeliberationThread,
) -> FacetEvidence | None:
    """Pick this Perspective's supporting evidence for a Thread.

    Preference order: the Perspective's own related fragments, the Thread's
    traceability facets, then scope. Selection never narrows the topic; the
    Thread question does that.
    """
    linked = next(
        (
            link.facets
            for link in thread.related
            if link.perspective_name == perspective.name
        ),
        [],
    )
    seen: list[Facet] = []
    for facet in [*linked, *thread.facets, "scope"]:
        if facet in seen:
            continue
        seen.append(facet)
        evidence = perspective.facets.get(facet)
        if evidence and evidence.text.strip():
            return evidence
    return None


async def open_statement(
    perspective: Perspective,
    thread: DeliberationThread,
    *,
    provider: FocusedProvider | None = None,
    round_turns: list[str] | None = None,
    moderator_feedback: str | None = None,
    current_hypothesis: HypothesisDev | None = None,
) -> Statement:
    evidence = _thread_evidence(perspective, thread)
    value = evidence.text if evidence else "not established"
    continuing = bool(round_turns)
    hypothesis_text = (
        current_hypothesis.hypothesis if current_hypothesis is not None else ""
    )
    context = ""
    if round_turns:
        context += "\n\n## PRIOR EXCHANGES\n" + "\n".join(round_turns[-12:])
    if moderator_feedback:
        context += "\n\n## MODERATOR'S LAST CHECK\n" + moderator_feedback
    parsed = await _structured(
        provider,
        (
            "Respond as the lead to the named challenge from the prior exchange. "
            "Explain which assumption produced your position and revise or defend it. "
            if continuing
            else "Answer the Thread's opening question with one evidence-grounded "
            "position. State the assumption that connects the findings to the answer. "
        )
        + "The Thread question defines the topic; your facets are supporting "
        "context, not the agenda. Reference exact excerpts from the current "
        "hypothesis when relevant. Use one to three sentences, cite paper IDs, "
        "and do not manufacture agreement.",
        f"## THREAD\n{thread.model_dump_json()}\n\n"
        f"## YOUR PERSPECTIVE\n{_facets_block(perspective)}\n\n"
        f"## CURRENT HYPOTHESIS\n{hypothesis_text or 'Not established yet.'}{context}",
        Statement,
        task=FocusedTask.open_statement,
    )
    if parsed and parsed.text:
        return parsed
    citations = [evidence.paper_id] if evidence and evidence.paper_id else []
    if continuing:
        return Statement(
            text=(
                f"I hold my answer to “{thread.question}” because "
                f"{_display(value)}. That is the assumption behind my earlier claim."
            ),
            assumption=value,
            relation="reply",
            hypothesis_fragments=[hypothesis_text] if hypothesis_text else [],
            citations=_citations_for(perspective, citations),
        )
    return Statement(
        text=(
            f"On “{thread.question}”, this perspective's answer starts from "
            f"{_display(value)}. That is the position the panel should test "
            "against the other evidence."
        ),
        assumption=value,
        relation="answer",
        hypothesis_fragments=[hypothesis_text] if hypothesis_text else [],
        citations=_citations_for(perspective, citations),
    )


async def answer_statement(
    perspective: Perspective,
    thread: DeliberationThread,
    lead_label: str,
    lead_text: str,
    *,
    provider: FocusedProvider | None = None,
    round_turns: list[str] | None = None,
    moderator_feedback: str | None = None,
    current_hypothesis: HypothesisDev | None = None,
) -> Statement:
    evidence = _thread_evidence(perspective, thread)
    value = evidence.text if evidence else "not established"
    hypothesis_text = (
        current_hypothesis.hypothesis if current_hypothesis is not None else ""
    )
    context = ""
    if round_turns:
        context += "\n\n## PRIOR EXCHANGES\n" + "\n".join(round_turns[-12:])
    if moderator_feedback:
        context += "\n\n## MODERATOR'S LAST CHECK\n" + moderator_feedback
    parsed = await _structured(
        provider,
        "Respond directly to the lead's claim on the Thread question. Identify "
        "the assumption behind it, then support, qualify, or challenge that "
        "assumption using your own abstract-grounded evidence. Your facets are "
        "supporting context, not the agenda. Reference exact excerpts from the "
        "current hypothesis when relevant. Use one to three sentences and cite "
        "paper IDs.",
        f"## THREAD\n{thread.model_dump_json()}\n\n"
        f"## YOUR PERSPECTIVE\n{_facets_block(perspective)}\n\n"
        f"## CURRENT HYPOTHESIS\n{hypothesis_text or 'Not established yet.'}\n\n"
        f"## LEAD\n{lead_label}: {lead_text}{context}",
        Statement,
        task=FocusedTask.answer_statement,
    )
    if parsed and parsed.text:
        return parsed
    citations = [evidence.paper_id] if evidence and evidence.paper_id else []
    if not round_turns:
        return Statement(
            text=(
                f"Did you reach that conclusion because you assume {lead_text.rstrip('.')}? "
                f"I find it difficult to agree without accounting for {_display(value)}."
            ),
            assumption=value,
            relation="challenge",
            hypothesis_fragments=[hypothesis_text] if hypothesis_text else [],
            citations=_citations_for(perspective, citations),
        )
    return Statement(
        text=(
            f"The explanation addresses part of the challenge. This perspective "
            f"still qualifies it with {_display(value)}."
        ),
        assumption=value,
        relation="reply",
        hypothesis_fragments=[hypothesis_text] if hypothesis_text else [],
        citations=_citations_for(perspective, citations),
    )


def _citations_for(perspective: Perspective, paper_ids: list[str | None]) -> list[str]:
    out: list[str] = []
    for paper_id in paper_ids:
        if paper_id and paper_id not in out:
            out.append(paper_id)
    return out or list(perspective.sources[:1])


async def retrieve_support(
    statement_text: str,
    perspective: Perspective,
    *,
    provider: FocusedProvider | None = None,
    s2: Any | None = None,
    corpus: list[ExpPaper] | None = None,
) -> tuple[Statement, ExpPaper] | None:
    """Retrieve one checkable abstract passage for an unsupported claim."""
    parsed = await _structured(
        provider,
        "Write one precise literature-search query for the claim.",
        f"## CLAIM\n{statement_text}",
        SupportSearch,
        task=FocusedTask.find_support_query,
    )
    query = parsed.query if parsed else " ".join(_content_words(statement_text)[:6])

    paper: ExpPaper | None = None
    passage = ""
    if s2 is not None:
        try:
            results = await s2.search(query, limit=5)
            if results:
                result = results[0]
                sentences = split_sentences(result.abstract)
                paper = ExpPaper(
                    id=result.id,
                    title=result.title,
                    abstract=result.abstract,
                    abstract_sentences=sentences,
                    year=result.year,
                    venue=result.venue,
                    authors=[author.name for author in result.authors[:4]],
                    source_query=query,
                    tldr=result.tldr,
                    open_access_pdf_url=result.open_access_pdf_url,
                    specter_v2=result.specter_v2,
                )
                passage = sentences[0] if sentences else result.title
        except Exception as exc:  # noqa: BLE001
            logger.warning("focused-panel support retrieval failed: %s", exc)
            return None

    if paper is None and s2 is None and corpus:
        query_words = set(_content_words(query))
        ranked = [
            (
                len(
                    query_words
                    & set(_content_words(item.title + " " + (item.abstract or "")))
                ),
                item,
            )
            for item in corpus
        ]
        score, candidate = max(ranked, default=(0, None), key=lambda item: item[0])
        if candidate is not None and score > 0:
            paper = candidate
            sentences = _abstract_sentences(paper)
            passage = next(
                (
                    sentence
                    for sentence in sentences
                    if query_words & set(_content_words(sentence))
                ),
                sentences[0] if sentences else paper.title,
            )

    if paper is None:
        return None

    selected = passage
    if provider is not None:
        selection = await _structured(
            provider,
            "Select the verbatim abstract passage that best supports the claim "
            "and state why it supports it.",
            f"## CLAIM\n{statement_text}\n\n## ABSTRACT\n"
            f"{paper.title}\n{paper.abstract or ''}",
            SupportPassage,
            task=FocusedTask.select_support_passage,
        )
        if selection and _evidence_is_verbatim(paper, selection.passage):
            selected = selection.passage

    return (
        Statement(
            text=f"Supporting literature — {paper.title}: “{selected.strip()}”",
            citations=[paper.id],
        ),
        paper,
    )


def _norm(value: str) -> str:
    return " ".join(_content_words(value)).strip().lower()


async def judge_thread(
    lead: Perspective,
    others: list[Perspective],
    thread: DeliberationThread,
    turns: list[str],
    *,
    provider: FocusedProvider | None = None,
    shared_ground: str | None = None,
) -> ThreadVerdict:
    facets = list(thread.facets)
    if provider is not None and turns:
        parsed = await _structured(
            provider,
            "Judge one scientific Thread as a whole. CONSENSUS means the panel "
            "established a shared answer to the Thread question. DISAGREEMENT "
            "requires genuinely incompatible claims or decisions; different "
            "emphases are not enough. UNSETTLED means a comparison, boundary, or "
            "causal question remains open without clear opposition. Propose the "
            "narrowest concrete shared-ground statement every Perspective could "
            "accept, or leave it empty. Do not issue separate facet verdicts.",
            f"## THREAD\n{thread.model_dump_json()}\n\n"
            f"## LEAD PERSPECTIVE\n{lead.name}\n{_facets_block(lead)}\n\n"
            "## OTHER PERSPECTIVES\n"
            + "\n\n".join(
                f"### {perspective.name}\n{_facets_block(perspective)}"
                for perspective in others
            )
            + "\n\n## LABELED DISCUSSION\n"
            + "\n".join(turns),
            ThreadVerdictOutput,
            task=FocusedTask.judge_thread,
            temperature=0.1,
        )
        if parsed:
            verdict = parsed.verdict
            return ThreadVerdict(
                **verdict.model_dump(
                    exclude={"consensus", "disagreement", "unsettled"}
                ),
                facets=facets,
                consensus=verdict.consensus if verdict.status == "consensus" else "",
                disagreement=(
                    verdict.disagreement if verdict.status == "disagreement" else ""
                ),
                unsettled=verdict.unsettled if verdict.status == "unsettled" else "",
            )

    participants = [lead, *others]
    if shared_ground:
        return ThreadVerdict(
            facets=facets,
            status="consensus",
            summary=f"The panel established shared ground for {thread.title}.",
            proposed_shared_ground=shared_ground,
            consensus=shared_ground,
            supporting=[perspective.name for perspective in participants],
        )

    comparison_facets: list[Facet] = facets or FACETS
    lead_values = tuple(_norm(_facet_text(lead, facet)) for facet in comparison_facets)
    same = all(
        tuple(_norm(_facet_text(perspective, facet)) for facet in comparison_facets)
        == lead_values
        for perspective in others
    )
    transcript = " ".join(turns).lower()
    explicit_conflict = bool(
        re.search(
            r"\b(disagree|incompatible|contradicts?|cannot both|rather than)\b",
            transcript,
        )
    )
    lead_ground = "; ".join(_facet_text(lead, facet) for facet in comparison_facets)
    if same:
        return ThreadVerdict(
            facets=facets,
            status="consensus",
            summary=f"The panel shares an answer to {thread.question}",
            proposed_shared_ground=lead_ground,
            consensus=lead_ground,
            supporting=[perspective.name for perspective in participants],
        )
    if explicit_conflict:
        return ThreadVerdict(
            facets=facets,
            status="disagreement",
            summary=f"The panel states incompatible answers to {thread.question}",
            disagreement=thread.question,
            contested_by=[perspective.name for perspective in others],
        )
    return ThreadVerdict(
        facets=facets,
        status="unsettled",
        summary=f"The Thread remains open: {thread.question}",
        unsettled=thread.question,
    )


async def assent_to_shared_ground(
    perspective: Perspective,
    thread: DeliberationThread,
    proposed_shared_ground: str,
    turns: list[str],
    *,
    provider: FocusedProvider | None = None,
    demo: bool = False,
    exchange_n: int = 1,
    challenge_turn_id: int | None = None,
) -> SharedGroundAssentDraft:
    if not proposed_shared_ground.strip():
        return SharedGroundAssentDraft(
            decision="reject",
            reason="The moderator did not identify substantive shared ground.",
        )
    if demo and exchange_n == 1:
        return SharedGroundAssentDraft(
            decision="qualify",
            reason="The lead must explain the assumption behind the proposed boundary.",
            challenge_turn_id=challenge_turn_id,
            challenge="Why does that assumption justify the proposed boundary?",
        )
    if demo:
        return SharedGroundAssentDraft(
            decision="accept",
            reason="The response addressed the qualification with grounded evidence.",
        )
    parsed = await _structured(
        provider,
        "Assess one proposed shared-ground statement as this research Perspective. "
        "ACCEPT only when the exact statement is supported without changes. QUALIFY "
        "or REJECT when a narrower claim is needed, and identify one supplied turn "
        "whose assumption should be challenged. Do not accept merely to end.",
        f"## YOUR PERSPECTIVE\n{_facets_block(perspective)}\n\n"
        f"## THREAD\n{thread.model_dump_json()}\n\n"
        "## DISCUSSION\n"
        + "\n".join(turns[-12:])
        + f"\n\n## PROPOSED SHARED GROUND\n{proposed_shared_ground}",
        SharedGroundAssentDraft,
        task=FocusedTask.assent_shared_ground,
        temperature=0.1,
    )
    return parsed or SharedGroundAssentDraft(
        decision="reject",
        reason="No explicit assent was returned.",
    )


def _point_from_verdict(
    verdict: ThreadVerdict,
    *,
    kind: str,
) -> DeliberationPoint:
    if kind == "consensus":
        text = verdict.consensus or verdict.summary
        names = verdict.supporting
    elif kind == "disagreement":
        text = verdict.disagreement or verdict.summary
        names = verdict.contested_by
    else:
        text = verdict.unsettled or verdict.summary
        names = list(verdict.positions)
    citations = list(
        dict.fromkeys(
            citation for evidence in verdict.evidence.values() for citation in evidence
        )
    )
    return DeliberationPoint(
        facets=list(verdict.facets),
        text=text,
        rationale=verdict.summary,
        perspective_names=names,
        citations=citations,
    )


def _normalize_thread_summary(
    summary: str,
    thread: DeliberationThread,
    turns: list[str],
    verdict: ThreadVerdict,
) -> str:
    sentences = split_sentences(summary)
    process_markers = (
        "compared",
        "challenged",
        "reinforced",
        "discussion",
        "dialogue",
        "responded",
    )
    has_process = bool(sentences) and any(
        marker in sentences[0].casefold() for marker in process_markers
    )
    if has_process and len(sentences) >= 2:
        return " ".join(sentences[:3])
    process = (
        sentences[0]
        if has_process
        else (
            f"The panel compared {len(turns)} contributions in the "
            f"“{thread.title}” Thread before the moderator classified the result."
        )
    )
    conclusions = (
        split_sentences(verdict.summary)
        if has_process
        else sentences or [verdict.summary]
    )
    return " ".join([process, *conclusions[:2]])


async def summarize_thread(
    thread: DeliberationThread,
    verdict: ThreadVerdict,
    turns: list[str],
    *,
    provider: FocusedProvider | None = None,
) -> RoundResolution:
    evidence_ids = list(
        dict.fromkeys(
            citation
            for citations in verdict.evidence.values()
            for citation in citations
        )
    )
    parsed = await _structured(
        provider,
        "Summarize one scientific Thread in 2-3 sentences. First explain how "
        "the Perspectives challenged, replied to, or refined the relevant "
        "assumptions and what findings moved the discussion; then state the "
        "moderator's conclusion. The supplied Thread verdict is authoritative. "
        "Do not reclassify it or invent conflict.",
        f"## THREAD\n{thread.model_dump_json()}\n\n"
        f"## AUTHORITATIVE VERDICT\n{verdict.model_dump_json()}\n\n"
        "## CANONICAL EVIDENCE IDS\n"
        + (", ".join(evidence_ids) if evidence_ids else "none")
        + "\n\n## LABELED DIALOGUE\n"
        + "\n".join(turns),
        RoundResolution,
        task=FocusedTask.summarize_thread,
        temperature=0.1,
    )
    consensus = (
        [_point_from_verdict(verdict, kind="consensus")]
        if verdict.consensus.strip()
        else []
    )
    disagreements = (
        [_point_from_verdict(verdict, kind="disagreement")]
        if verdict.disagreement.strip()
        else []
    )
    unsettled = (
        [_point_from_verdict(verdict, kind="unsettled")]
        if verdict.unsettled.strip()
        else []
    )
    if not disagreements and not unsettled:
        unsettled.append(
            DeliberationPoint(
                facets=list(thread.facets),
                text=thread.question,
                rationale=(
                    "The Thread reached agreement but did not test that agreement "
                    "outside the represented findings."
                ),
                citations=evidence_ids,
            )
        )
    summary = parsed.summary if parsed and parsed.summary else verdict.summary
    return RoundResolution(
        summary=_normalize_thread_summary(summary, thread, turns, verdict),
        consensus_points=consensus,
        disagreement_points=disagreements,
        unsettled_points=unsettled,
    )


async def reflect_on_round(
    agent_iid: int,
    perspective: Perspective,
    facets: list[Facet],
    resolution: RoundResolution,
    *,
    provider: FocusedProvider | None = None,
    demo: bool = False,
) -> tuple[ParticipantReflection, dict[Facet, FacetEvidence]]:
    parsed = await _structured(
        provider,
        "Reflect as one research perspective after deliberation. Revise any "
        "facet of your Perspective for which the challenge-response exchange "
        "supplied a defensible reason to change. The Thread facets are "
        "traceability hints, not a restriction. Keep unsupported facets "
        "unchanged.",
        f"## YOUR CURRENT FACETS\n{_facets_block(perspective)}\n\n"
        f"## THREAD FACETS (traceability)\n{', '.join(facets) or 'none'}\n\n"
        f"## RESOLUTION\n{resolution.model_dump_json()}",
        ReflectionDraft,
        task=FocusedTask.reflect_on_round,
        temperature=0.1,
    )
    current = {
        facet: evidence.model_copy(deep=True)
        for facet, evidence in perspective.facets.items()
    }
    if parsed is None and demo and resolution.consensus_points:
        revisions: list[FacetRevision] = []
        for point in resolution.consensus_points:
            segments = [
                segment.strip() for segment in point.text.split(";") if segment.strip()
            ]
            aligned = len(segments) == len(point.facets)
            for index, facet in enumerate(point.facets):
                text = segments[index] if aligned else point.text.strip()
                if text and _norm(text) != _norm(_facet_text(perspective, facet)):
                    revisions.append(FacetRevision(facet=facet, text=text))
        parsed = ReflectionDraft(
            decision="revised" if revisions else "unchanged",
            reason=(
                "The lead incorporated the panel's accepted qualification."
                if revisions
                else "The accepted shared ground restates this Perspective."
            ),
            revisions=revisions,
        )
    if parsed is None or parsed.decision == "unchanged":
        reason = parsed.reason if parsed else "No supported revision emerged."
        return (
            ParticipantReflection(
                agent_iid=agent_iid,
                perspective_name=perspective.name,
                decision="unchanged",
                reason=reason,
            ),
            current,
        )
    revisions = [revision for revision in parsed.revisions if revision.text.strip()]
    for revision in revisions:
        current[revision.facet] = FacetEvidence(
            facet=revision.facet,
            text=revision.text.strip(),
            edited=True,
        )
    decision = "revised" if revisions else "unchanged"
    return (
        ParticipantReflection(
            agent_iid=agent_iid,
            perspective_name=perspective.name,
            decision=decision,
            reason=parsed.reason,
            revisions=revisions,
        ),
        current,
    )


# ---------------------------------------------------------------------------
# Hypothesis and recursive next-question generation
# ---------------------------------------------------------------------------


def _fallback_hypothesis(perspective: Perspective) -> HypothesisDev:
    scope = _facet_text(perspective, "scope").strip().rstrip(".")
    approach = _facet_text(perspective, "approach").strip().rstrip(".")
    explanation = _display(_facet_text(perspective, "explanation"))
    significance = _display(_facet_text(perspective, "significance"))
    return HypothesisDev(
        hypothesis=(
            f"{scope}. {approach}. This should clarify whether "
            f"{explanation}, because {significance}."
        )
    )


async def develop_hypothesis(
    perspective: Perspective,
    *,
    provider: FocusedProvider | None = None,
) -> HypothesisDev:
    parsed = await _structured(
        provider,
        "Propose one direct, testable solution candidate for the research problem "
        "from the Perspective's four evidence-grounded facets. Return only the "
        "hypothesis. Do not repeat the problem statement, literature summary, or "
        "reasoning as separate fields.",
        f"## PERSPECTIVE: {perspective.name}\n## FACETS\n{_facets_block(perspective)}",
        HypothesisSteps,
        task=FocusedTask.develop_hypothesis,
    )
    if parsed and parsed.steps:
        return parsed.steps
    return _fallback_hypothesis(perspective)


_NOT_ESTABLISHED = "Not established yet."


def _fallback_consensus_hypothesis(
    resolution: RoundResolution,
    current: HypothesisDev | None = None,
) -> HypothesisDev:
    segments = list(
        dict.fromkeys(
            segment.strip().rstrip(".")
            for point in resolution.consensus_points
            for segment in point.text.split(";")
            if segment.strip()
        )
    )
    if not segments:
        return current or HypothesisDev(hypothesis=_NOT_ESTABLISHED)
    base = current.hypothesis.strip() if current is not None else ""
    if current is None or not base or base == _NOT_ESTABLISHED:
        return HypothesisDev(
            hypothesis=f"A viable solution should account for {'; '.join(segments)}."
        )
    novel = [
        segment for segment in segments if segment.casefold() not in base.casefold()
    ]
    if not novel:
        return current
    return HypothesisDev(
        hypothesis=(
            f"{base.rstrip('.')}. It should also account for {'; '.join(novel)}."
        )
    )


async def develop_hypothesis_from_consensus(
    resolution: RoundResolution,
    *,
    current: HypothesisDev | None = None,
    provider: FocusedProvider | None = None,
) -> HypothesisDev:
    """Revise one solution candidate from unanimously accepted shared ground."""
    if not resolution.consensus_points:
        raise ValueError("consensus points are required")
    current_text = (
        current.hypothesis
        if current is not None
        else "No working hypothesis has been established yet."
    )
    parsed = await _structured(
        provider,
        "Revise the current hypothesis using ONLY the supplied consensus points "
        "and cited evidence. Return one direct, testable solution candidate. "
        "Preserve the current hypothesis when the new shared ground does not "
        "justify a change. Never use disagreement or unsettled points.",
        f"## CURRENT HYPOTHESIS\n{current_text}\n\n"
        "## NEW SUPPORTED SHARED GROUND\n"
        + "\n".join(
            f"- {', '.join(point.facets)}: {point.text}"
            + (f" [evidence: {', '.join(point.citations)}]" if point.citations else "")
            for point in resolution.consensus_points
        ),
        HypothesisSteps,
        task=FocusedTask.develop_hypothesis_from_consensus,
        temperature=0.1,
    )
    if parsed and parsed.steps:
        return parsed.steps
    return _fallback_consensus_hypothesis(resolution, current)


async def recommend_questions(
    resolution: RoundResolution,
    perspective: Perspective,
    *,
    provider: FocusedProvider | None = None,
) -> list[RecommendedQuestion]:
    source_kind = "disagreement" if resolution.disagreement_points else "unsettled"
    source_points = (
        resolution.disagreement_points
        if resolution.disagreement_points
        else resolution.unsettled_points
    )
    if not source_points:
        return []

    parsed = await _structured(
        provider,
        "Recommend one to three answerable research questions for the next "
        "investigation cycle. If genuine disagreement points exist, ground the "
        "questions in those points. Otherwise use unsettled points. Every "
        "question must include a rationale that explains exactly why it follows "
        "from the named source point. Do not invent disagreement.",
        f"## CURRENT PERSPECTIVE\n{_facets_block(perspective)}\n\n"
        f"## ROUND RESOLUTION\n{resolution.model_dump_json()}",
        QuestionRecommendations,
        task=FocusedTask.recommend_questions,
        temperature=0.2,
    )
    if parsed and parsed.questions:
        allowed = {point.text for point in source_points}
        out = []
        for question in parsed.questions[:3]:
            if not question.question.strip() or not question.rationale.strip():
                continue
            source_point = (
                question.source_point
                if question.source_point in allowed
                else source_points[min(len(out), len(source_points) - 1)].text
            )
            out.append(
                question.model_copy(
                    update={
                        "source_kind": source_kind,
                        "source_point": source_point,
                    }
                )
            )
        if out:
            return out

    templates = {
        "disagreement": (
            "Which finding would decide between the incompatible positions "
            "in this point: {point}?"
        ),
        "unsettled": (
            "What evidence would settle the open issue in this point: {point}?"
        ),
    }
    return [
        RecommendedQuestion(
            question=templates[source_kind].format(point=point.text.rstrip(" .?!")),
            rationale=(
                f"This follows from the Thread's {source_kind} point: "
                f"{point.rationale or point.text}"
            ),
            source_kind=source_kind,
            source_point=point.text,
            facets=list(point.facets),
        )
        for point in source_points[:3]
    ]


# ---------------------------------------------------------------------------
# Final Document: the researcher-approved outcome of deliberation
# ---------------------------------------------------------------------------


def _fallback_document(
    problem: str,
    threads: list[DeliberationThread],
    rounds: list[DeliberationRound],
    open_questions: list[str],
) -> DeliberationDocument:
    threads_by_id = {thread.id: thread for thread in threads}
    sections: list[DocumentSection] = []
    for round_state in rounds:
        if not round_state.completed:
            continue
        if round_state.resolution_decision not in {"accepted", "edited"}:
            continue
        hypothesis = round_state.hypothesis_proposal or round_state.hypothesis_before
        if hypothesis is None or not hypothesis.hypothesis.strip():
            continue
        thread = threads_by_id.get(round_state.thread_id or "")
        if round_state.thread_id is not None:
            # A re-discussed Thread supersedes its earlier section.
            sections = [
                section
                for section in sections
                if section.thread_id != round_state.thread_id
            ]
        sections.append(
            DocumentSection(
                thread_id=round_state.thread_id,
                title=thread.title if thread else f"Thread {round_state.n}",
                hypothesis=hypothesis.hypothesis,
                explanation=(
                    round_state.resolution.summary if round_state.resolution else ""
                ),
            )
        )
    return DeliberationDocument(
        title=problem,
        sections=sections,
        open_questions=[question for question in open_questions if question.strip()],
    )


async def synthesize_document(
    problem: str,
    threads: list[DeliberationThread],
    rounds: list[DeliberationRound],
    open_questions: list[str],
    *,
    provider: FocusedProvider | None = None,
) -> DeliberationDocument:
    """Moderator synthesis of resolved Threads into the final Document."""
    fallback = _fallback_document(problem, threads, rounds, open_questions)
    if provider is None or not fallback.sections:
        return fallback
    resolved_by_title = {section.title: section for section in fallback.sections}
    parsed = await _structured(
        provider,
        "Synthesize the researcher-approved outcome of this deliberation as a "
        "final Document. Each resolved Thread becomes a substantive research "
        "section titled by its topic: state the hypothesis it supports and "
        "explain why it is warranted, incorporating the reasoning, "
        "qualifications, and Perspective differences that survived deliberation "
        "without reproducing the transcript. Keep unresolved scientific issues "
        "as open questions. Do not invent Threads or hypotheses.",
        "## INVESTIGATION PROBLEM\n"
        + problem
        + "\n\n## RESOLVED THREADS\n"
        + "\n\n".join(
            f"### {section.title}\nHypothesis: {section.hypothesis}\n"
            f"Resolution: {section.explanation}"
            for section in fallback.sections
        )
        + "\n\n## OPEN QUESTIONS\n"
        + ("\n".join(f"- {question}" for question in open_questions) or "none"),
        DocumentDraft,
        task=FocusedTask.synthesize_document,
        temperature=0.1,
    )
    if not parsed or not parsed.sections:
        return fallback
    sections: list[DocumentSection] = []
    for draft in parsed.sections:
        base = resolved_by_title.get(draft.thread_title.strip())
        if base is None or not draft.hypothesis.strip():
            continue
        sections.append(
            DocumentSection(
                thread_id=base.thread_id,
                title=base.title,
                hypothesis=draft.hypothesis.strip()[:4000],
                explanation=draft.explanation.strip()[:4000] or base.explanation,
            )
        )
    if len(sections) != len(fallback.sections):
        return fallback
    open_qs = [
        question.strip() for question in parsed.open_questions if question.strip()
    ]
    return DeliberationDocument(
        title=problem,
        sections=sections,
        open_questions=open_qs or fallback.open_questions,
    )


async def reply_to_user(
    perspective: Perspective,
    question: str,
    history: list[str],
    *,
    active_facets: list[Facet] | None = None,
    round_context: str = "",
    working_hypothesis: HypothesisDev | None = None,
    provider: FocusedProvider | None = None,
) -> Statement:
    facets = active_facets or FACETS
    hypothesis_context = (
        working_hypothesis.model_dump_json(indent=2)
        if working_hypothesis is not None
        else "No working hypothesis is available."
    )
    parsed = await _structured(
        provider,
        "Answer the researcher's question as one evidence-grounded perspective. "
        "Use the supplied round record when present, stay within the active facet, "
        "distinguish a qualification from disagreement, and cite paper IDs. Explain "
        "the recorded discussion; do not claim that this answer changes panel state.",
        f"## YOUR FACETS\n{_facets_block(perspective)}\n\n"
        f"## ACTIVE FACETS\n{', '.join(facets)}\n\n"
        f"## LATEST COMPLETED ROUND\n{round_context or 'No completed round yet.'}\n\n"
        f"## WORKING HYPOTHESIS\n{hypothesis_context}\n\n"
        "## RECENT FOLLOW-UP CONVERSATION\n"
        + "\n".join(history[-8:])
        + f"\n\n## RESEARCHER QUESTION\n{question}",
        ChatReply,
        task=FocusedTask.reply_to_user,
    )
    if parsed and parsed.text:
        return Statement(text=parsed.text, citations=parsed.citations)
    focus = "; ".join(
        f"{facet}: {_display(_facet_text(perspective, facet))}" for facet in facets
    )
    round_summary = (
        round_context.split("Moderator resolution:", 1)[-1].strip()
        if round_context
        else "No completed round has been recorded yet."
    )
    hypothesis_text = (
        working_hypothesis.hypothesis if working_hypothesis is not None else ""
    )
    return Statement(
        text=(
            f"Regarding “{question.strip()}”, {perspective.name} reads the active "
            f"evidence as {focus}. The latest panel record says {round_summary[:500]}"
        ),
        relation="reply",
        hypothesis_fragments=[hypothesis_text] if hypothesis_text else [],
        citations=list(perspective.sources[:2]),
    )
