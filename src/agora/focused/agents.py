"""LLM and deterministic helpers for baseline retrieval and draft review."""

from __future__ import annotations

import logging
import re
from collections import Counter
from typing import TYPE_CHECKING, TypeVar

from pydantic import BaseModel

from agora.focused.models import (
    FACETS,
    NOTEPAD_LABELS,
    NOTEPAD_PARTS,
    ChatReply,
    ClusterNaming,
    ClusterNamings,
    DerivedQuestions,
    ExpPaper,
    Facet,
    FacetEvidence,
    FacetExtraction,
    FramingPosition,
    NotepadDoc,
    NotepadPart,
    NotepadTurn,
    Perspective,
    QuerySuggestions,
    QuestionAssessment,
    QuestionEvidence,
    QuestionExpansion,
    QuestionPlan,
    Statement,
    SuggestedQuery,
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
        len(text) > 500
        or "?" in text
        or "？" in text
        or '"' in text
        or re.search(r"\b(?:AND|OR|NOT)\b", text) is not None
        or len(content) > max_terms
    )
    if not unsafe:
        compacted = text
    else:
        terms = list(
            dict.fromkeys(word for word in content if word not in SEARCH_QUERY_FILLER)
        )
        if len(terms) < 2:
            terms = list(dict.fromkeys(content))
        compacted = " ".join(terms[:max_terms]) or text.rstrip("?？")
    return compacted[:500].strip()


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
    problem: str,
    questions: list[str],
    position: NotepadDoc | None,
    count: int,
) -> list[SuggestedQuery]:
    out: list[SuggestedQuery] = []
    seen: set[str] = set()

    def push(q: str, rationale: str) -> None:
        q = compact_search_query(q)
        key = q.lower().rstrip("?")
        if q and key not in seen:
            seen.add(key)
            out.append(SuggestedQuery(query=q, rationale=rationale))

    source_texts = [problem]
    push(
        compact_search_query(problem),
        "Drawn from the research problem.",
    )
    if position is not None:
        for part in NOTEPAD_PARTS:
            text = getattr(position, part).strip()
            if not text:
                continue
            source_texts.append(text)
            push(
                compact_search_query(text),
                f"Drawn from your {NOTEPAD_LABELS[part].lower()}.",
            )
    for question in questions:
        source_texts.append(question)
        push(
            compact_search_query(question),
            "Taken directly from your research questions.",
        )

    words = _content_words(" ".join(source_texts))
    freq = [word for word, _ in Counter(words).most_common(6)]
    seed_terms = (
        freq
        or list(dict.fromkeys(_search_query_words(" ".join(source_texts))))[:6]
        or ["research"]
    )
    push(
        " ".join(seed_terms[:4]) + " evidence",
        "Core constructs across the problem and position.",
    )
    if len(freq) >= 4:
        push(
            f"{freq[0]} versus {freq[min(2, len(freq) - 1)]}",
            "Opposes two constructs to reach the debate literature.",
        )
        push(
            f"mechanisms of {freq[0]} and {freq[1]}",
            "Reaches mechanism-oriented work.",
        )
    seed = " ".join(seed_terms[: min(3, len(seed_terms))])
    for suffix, rationale in (
        ("outcomes", "Outcome-oriented literature for coverage."),
        ("mechanisms", "Mechanism-oriented literature for coverage."),
        ("methods", "Methods literature for coverage."),
        ("evidence review", "Broad review literature for coverage."),
    ):
        if len(out) >= count:
            break
        push(f"{seed} {suffix}", rationale)
    index = 0
    while len(out) < count and seed_terms:
        pair = (
            f"{seed_terms[index % len(seed_terms)]} "
            f"{seed_terms[(index + 2) % len(seed_terms)]} review"
        )
        push(pair, "Broad review literature for coverage.")
        index += 1
        if index > count * 3:
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
    fallbacks = _fallback_queries(problem, questions, position, count)
    candidates = [*(parsed.queries if parsed else []), *fallbacks]
    suggestions: list[SuggestedQuery] = []
    seen: set[str] = set()
    for candidate in candidates:
        query = compact_search_query(candidate.query)
        key = query.lower().rstrip("?")
        if not query or key in seen:
            continue
        seen.add(key)
        suggestions.append(candidate.model_copy(update={"query": query}))
        if len(suggestions) == count:
            break
    return suggestions


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


async def extract_cluster_facets(
    papers: list[ExpPaper],
    *,
    provider: FocusedProvider | None = None,
) -> list[FacetEvidence]:

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
    fallback = fallback_cluster_facets(papers)
    if not parsed or not parsed.facets:
        return fallback

    by_id = {paper.id: paper for paper in papers}
    by_facet: dict[Facet, FacetEvidence] = {}
    for candidate in parsed.facets:
        paper = by_id.get(candidate.paper_id)
        if paper is None or candidate.facet in by_facet:
            continue
        evidence = FacetEvidence.model_validate(candidate.model_dump())
        mapped = map_facet_to_sentence(
            paper,
            evidence.model_copy(update={"sentence_index": None, "sentence": None}),
        )
        if mapped.sentence_index is not None:
            by_facet[candidate.facet] = mapped
    for evidence in fallback:
        by_facet.setdefault(evidence.facet, evidence)
    return [by_facet[facet] for facet in FACETS if facet in by_facet]


def map_facet_to_sentence(paper: ExpPaper, evidence: FacetEvidence) -> FacetEvidence:
    """Ground a facet in the exact abstract sentence it came from."""
    sentences = _abstract_sentences(paper)
    value = evidence.text.strip().lower()
    for index, sentence in enumerate(sentences):
        normalized = sentence.lower()
        if value and (value in normalized or normalized in value):
            return evidence.model_copy(
                update={
                    "text": _compress(sentence),
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
                "text": _compress(sentences[best_index]),
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


async def reply_to_user(
    perspective: Perspective,
    question: str,
    history: list[str],
    *,
    provider: FocusedProvider | None = None,
) -> Statement:
    """Answer one directed researcher exchange from one hidden profile."""
    parsed = await _structured(
        provider,
        "Answer the researcher's question as one evidence-grounded scientific "
        "Perspective. Use the complete hidden profile and recent conversation. "
        "Give a direct answer and name an important boundary or tradeoff. Put "
        "supporting paper IDs only in citations; never mention IDs in the answer "
        "text. Do not claim to change the researcher's draft.",
        f"## JOB\n{perspective.name}\n\n"
        f"## ORIENTATION\n{perspective.summary}\n\n"
        f"## YOUR PROFILE\n{_facets_block(perspective)}\n\n"
        f"## FRAMING AND POSITION\n"
        f"{perspective.framing.model_dump_json() if perspective.framing else 'Not synthesized.'}\n\n"
        "## RECENT CONVERSATION\n"
        + "\n".join(history[-8:])
        + f"\n\n## RESEARCHER QUESTION\n{question}",
        ChatReply,
        task=FocusedTask.reply_to_user,
    )
    if parsed and parsed.text:
        return Statement(text=parsed.text, citations=parsed.citations)
    focus = "; ".join(
        f"{facet}: {_display(_facet_text(perspective, facet))}" for facet in FACETS
    )
    return Statement(
        text=(
            f"With “{perspective.summary[:180]}” as its orientation, "
            f"{perspective.name} would answer “{question.strip()}” by weighing "
            f"this evidence: {focus}."
        ),
        relation="reply",
        citations=list(perspective.sources[:2]),
    )


_PART_FACETS: dict[NotepadPart, tuple[Facet, ...]] = {
    "framing": ("scope", "explanation"),
    "prior": ("scope", "explanation", "significance"),
    "method": ("approach",),
    "expected": ("significance",),
}


async def review_draft_element(
    perspective: Perspective,
    part: NotepadPart,
    subject_text: str,
    *,
    provider: FocusedProvider | None = None,
) -> Statement:
    """Give one independent, evidence-grounded review of one draft element."""
    facet_names = _PART_FACETS[part]
    parsed = await _structured(
        provider,
        "Review exactly one element of a researcher's draft as one scientific "
        "Perspective. Give concrete feedback, state what is strong or missing, "
        "and recommend what the researcher should reconsider. Use the hidden "
        "Perspective profile and its evidence. Do not mention other agents or "
        "their feedback. Put paper IDs only in citations; never mention IDs in "
        "the feedback text. Do not rewrite the draft.",
        f"## JOB\n{perspective.name}\n\n"
        f"## ORIENTATION\n{perspective.summary}\n\n"
        f"## DRAFT ELEMENT\n{NOTEPAD_LABELS[part]}: {subject_text or 'Not written.'}\n\n"
        f"## FRAMING AND POSITION\n"
        f"{perspective.framing.model_dump_json() if perspective.framing else 'Not synthesized.'}\n\n"
        f"## RELEVANT FRAGMENTS\n"
        + "\n".join(
            f"- {facet}: {_facet_text(perspective, facet)}" for facet in facet_names
        ),
        ChatReply,
        task=FocusedTask.review_draft_element,
        temperature=0.2,
    )
    if parsed and parsed.text.strip():
        return Statement(text=parsed.text.strip(), citations=parsed.citations)
    evidence = " ".join(
        _sentence(_facet_text(perspective, facet))
        for facet in facet_names
        if _facet_text(perspective, facet).strip()
    ).strip()
    draft = subject_text.strip() or "This element is not written yet."
    return Statement(
        text=(
            f"Working from “{perspective.summary[:180]}”, {perspective.name} "
            f"would test “{draft[:240]}” against this evidence: "
            f"{evidence or 'The profile does not establish this element yet.'} "
            "Clarify the boundary or claim that the evidence does not yet establish."
        ),
        relation="answer",
        citations=list(perspective.sources),
    )


async def compare_draft_feedback(
    perspective: Perspective,
    part: NotepadPart,
    subject_text: str,
    feedback: list[NotepadTurn],
    *,
    provider: FocusedProvider | None = None,
) -> Statement:
    """Compare the complete independent feedback set from one Perspective."""
    transcript = "\n".join(f"- {turn.author_label}: {turn.text}" for turn in feedback)
    parsed = await _structured(
        provider,
        "Compare the independent feedback on one draft element as one "
        "Perspective. Identify a substantive agreement or difference, explain "
        "why it matters for the draft, and say what the researcher should weigh. "
        "Do not rewrite the draft. Put your supporting paper IDs only in citations; "
        "never mention IDs in the feedback text.",
        f"## DRAFT ELEMENT\n{NOTEPAD_LABELS[part]}: {subject_text or 'Not written.'}\n\n"
        f"## JOB\n{perspective.name}\n\n"
        f"## ORIENTATION\n{perspective.summary}\n\n"
        f"## FRAMING AND POSITION\n"
        f"{perspective.framing.model_dump_json() if perspective.framing else 'Not synthesized.'}\n\n"
        f"## YOUR PROFILE\n{_facets_block(perspective)}\n\n"
        f"## INDEPENDENT FEEDBACK\n{transcript}",
        ChatReply,
        task=FocusedTask.compare_draft_feedback,
        temperature=0.2,
    )
    if parsed and parsed.text.strip():
        return Statement(text=parsed.text.strip(), citations=parsed.citations)
    peers = [turn for turn in feedback if turn.author_id != perspective.id]
    peer_text = peers[0].text if peers else "The feedback emphasizes the same boundary."
    return Statement(
        text=(
            f"Working from “{perspective.summary[:180]}”, {perspective.name} "
            f"compares the {NOTEPAD_LABELS[part]} feedback this way: "
            f"{peer_text[:320]} The key decision is which boundary the "
            "researcher wants the draft to defend."
        ),
        relation="reply",
        citations=list(perspective.sources),
    )


async def summarize_notepad_turns(
    turns: list[NotepadTurn],
    *,
    provider: FocusedProvider | None = None,
) -> Statement:
    """Summarize visible baseline feedback without mutating the draft."""
    transcript = "\n".join(
        f"- {turn.author_label}: {turn.text}"
        for turn in turns
        if turn.kind in {"feedback", "comparison", "direct_reply"}
    )
    parsed = await _structured(
        provider,
        "Summarize the feedback the researcher has received. Preserve the main "
        "agreements, differences, and actionable questions. Do not rewrite or "
        "claim to update the draft.",
        f"## FEEDBACK\n{transcript}",
        ChatReply,
        task=FocusedTask.summarize_notepad,
        temperature=0.1,
    )
    if parsed and parsed.text.strip():
        return Statement(text=parsed.text.strip(), citations=parsed.citations)
    recent = [
        f"{turn.author_label}: {turn.text}"
        for turn in turns
        if turn.kind in {"feedback", "comparison", "direct_reply"}
    ][-6:]
    return Statement(
        text="Feedback so far: " + " ".join(recent),
        citations=list(
            dict.fromkeys(citation for turn in turns for citation in turn.citations)
        ),
    )
