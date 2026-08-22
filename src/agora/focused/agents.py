"""LLM and deterministic agents for abstract-grounded facet deliberation.

The study protocol has four stable facets—scope, explanation, approach, and
significance. Users activate one or two facets per round; the moderator records
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
    ChatReply,
    ClusterNaming,
    ClusterNamings,
    DeliberationPoint,
    ExpPaper,
    Facet,
    FacetEvidence,
    FacetExtraction,
    FacetVerdict,
    FacetVerdicts,
    FramingPosition,
    HypothesisDev,
    HypothesisSteps,
    ParticipantReflection,
    Perspective,
    QuerySuggestions,
    QuestionAssessment,
    QuestionEvidence,
    QuestionPlan,
    QuestionRecommendations,
    RecommendedQuestion,
    ReflectionDraft,
    RoundResolution,
    Statement,
    SuggestedQuery,
    SupportPassage,
    SupportSearch,
)

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


async def _structured(
    provider: FocusedProvider | None,
    system: str,
    user: str,
    schema: type[T],
    temperature: float | None = None,
    max_output_tokens: int | None = None,
) -> T | None:
    """Demo/no-provider → None (caller falls back). Live calls raise typed errors."""
    if provider is None:
        return None
    try:
        result = await provider.generate_structured(
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
        push(q, "Taken directly from your research questions.")
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


async def suggest_queries(
    problem: str,
    questions: list[str],
    *,
    provider: FocusedProvider | None = None,
    count: int = 5,
) -> list[SuggestedQuery]:
    parsed = await _structured(
        provider,
        "You write literature-search queries for a research tool. Queries must "
        "reach DIFFERENT parts of the literature rather than overlapping: a term "
        "that would hit most papers separates nothing. Return exactly "
        f"{count} queries.",
        f"## RESEARCH PROBLEM\n{problem}\n\n## RESEARCH QUESTIONS\n"
        + "\n".join(f"- {q}" for q in questions),
        QuerySuggestions,
        temperature=0.4,
    )
    if parsed and parsed.queries:
        return parsed.queries[:count]
    return _fallback_queries(problem, questions, count)


# ---------------------------------------------------------------------------
# Question-specific reach: own terms → answering papers → literature terms
# ---------------------------------------------------------------------------

QUESTION_PLAN_SYSTEM = """\
You plan a literature search for one research question. Preserve the
question's own scientific terms. Return the form of an answer, two to four
candidate answers, and two concise search queries aimed at those candidates.
Do not silently replace a key term with a neighboring concept."""

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
paper. Also report vocabulary the literature uses differently and up to two
follow-up searches using that observed vocabulary."""

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
                "queries": [query for query in parsed.queries if query.query.strip()][
                    :2
                ],
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
    want_round2: bool = True,
) -> QuestionAssessment:
    if not papers:
        return QuestionAssessment()
    parsed = await _structured(
        provider,
        QUESTION_ASSESS_SYSTEM
        + (
            "\nReturn no follow-up searches; leave round2 empty."
            if not want_round2
            else ""
        ),
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
        temperature=0.1,
        max_output_tokens=2_000,
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
        round2=(
            [query for query in parsed.round2 if query.query.strip()][:2]
            if want_round2
            else []
        ),
    )


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
            fallback = fallback.model_copy(
                update={"blurb": candidate.blurb.strip()}
            )
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


def _pattern_facets(papers: list[ExpPaper]) -> list[FacetEvidence]:
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
        temperature=0.1,
    )
    if parsed and parsed.facets:
        by_id = {paper.id: paper for paper in papers}
        return [
            map_facet_to_sentence(by_id[evidence.paper_id], evidence)
            if evidence.paper_id in by_id
            else evidence
            for evidence in parsed.facets
        ]
    return _pattern_facets(papers)


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


def _fallback_framing(perspective: Perspective) -> FramingPosition:
    scope = _display(_facet_text(perspective, "scope"))
    explanation = _display(_facet_text(perspective, "explanation"))
    approach = _display(_facet_text(perspective, "approach"))
    significance = _display(_facet_text(perspective, "significance"))
    return FramingPosition(
        framing=(
            f"This perspective frames the question within {scope} and explains "
            f"the phenomenon through {explanation}."
        ),
        position=(
            f"It would establish the claim through {approach}; the result matters "
            f"because {significance}."
        ),
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
    )
    if parsed and parsed.framing and parsed.position:
        return parsed
    return _fallback_framing(perspective)


# ---------------------------------------------------------------------------
# Facet-directed panel discussion
# ---------------------------------------------------------------------------


async def open_statement(
    perspective: Perspective,
    facet: Facet,
    *,
    provider: FocusedProvider | None = None,
    round_turns: list[str] | None = None,
) -> Statement:
    evidence = perspective.facets.get(facet)
    value = evidence.text if evidence else "not established"
    context = ""
    if round_turns:
        context = "\n\n## RECENT ROUND CONTEXT\n" + "\n".join(round_turns[-6:])
    parsed = await _structured(
        provider,
        "You are the lead research perspective in a focused deliberation. "
        "Open only on the selected facet, using your own abstract-grounded "
        "facet and papers. State a clear interpretation and its boundary in "
        "one to three sentences. Cite supporting paper IDs. Do not manufacture "
        "opposition.",
        f"## YOUR FACETS\n{_facets_block(perspective)}\n\n"
        f"## ACTIVE FACET\n{facet}: {value}{context}",
        Statement,
    )
    if parsed and parsed.text:
        return parsed
    citations = [evidence.paper_id] if evidence and evidence.paper_id else []
    return Statement(
        text=(
            f"On {facet}, this perspective starts from {_display(value)}. "
            "That is the boundary the panel should test against the other evidence."
        ),
        citations=_citations_for(perspective, citations),
    )


async def answer_statement(
    perspective: Perspective,
    facet: Facet,
    lead_label: str,
    lead_text: str,
    *,
    provider: FocusedProvider | None = None,
) -> Statement:
    evidence = perspective.facets.get(facet)
    value = evidence.text if evidence else "not established"
    parsed = await _structured(
        provider,
        "Answer a lead perspective using only your own abstract-grounded "
        "evidence for the selected facet. Identify whether your evidence "
        "supports, qualifies, or genuinely conflicts with the lead. Difference "
        "alone is not disagreement. Use one to three sentences and cite paper IDs.",
        f"## YOUR FACETS\n{_facets_block(perspective)}\n\n"
        f"## ACTIVE FACET\n{facet}: {value}\n\n"
        f"## LEAD\n{lead_label}: {lead_text}",
        Statement,
    )
    if parsed and parsed.text:
        return parsed
    citations = [evidence.paper_id] if evidence and evidence.paper_id else []
    return Statement(
        text=(
            f"This perspective adds {_display(value)} to {lead_label}'s account. "
            "The panel still needs to establish whether those boundaries support "
            "one conclusion or leave an open evidentiary question."
        ),
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


async def judge_facet(
    lead: Perspective,
    others: list[Perspective],
    facet: Facet,
    turns_for_facet: list[str],
    *,
    provider: FocusedProvider | None = None,
    shared_ground: str | None = None,
) -> FacetVerdict:
    lead_text = _facet_text(lead, facet)
    if provider is not None and turns_for_facet:
        parsed = await _structured(
            provider,
            "Judge one facet discussion. CONSENSUS means the panel established "
            "a shared answer. DISAGREEMENT requires genuinely incompatible "
            "claims or decisions; different emphases are not enough. UNSETTLED "
            "means evidence, boundaries, or a causal question remain open without "
            "clear opposition. Never force disagreement. Return one verdict.",
            f"## LEAD\n{lead.name}: {lead_text}\n\n## OTHER FACETS\n"
            + "\n".join(f"- {item.name}: {_facet_text(item, facet)}" for item in others)
            + "\n\n## DISCUSSION\n"
            + "\n".join(turns_for_facet),
            FacetVerdicts,
            temperature=0.1,
        )
        if parsed and parsed.verdicts:
            verdict = parsed.verdicts[0]
            return FacetVerdict(
                **verdict.model_dump(
                    exclude={"facet", "consensus", "disagreement", "unsettled"}
                ),
                facet=facet,
                consensus=verdict.consensus if verdict.status == "consensus" else "",
                disagreement=(
                    verdict.disagreement if verdict.status == "disagreement" else ""
                ),
                unsettled=verdict.unsettled if verdict.status == "unsettled" else "",
            )

    if shared_ground:
        return FacetVerdict(
            facet=facet,
            status="consensus",
            summary=f"The panel established shared {facet} ground.",
            consensus=shared_ground,
            supporting=[item.name for item in others],
        )

    other_values = [_facet_text(item, facet) for item in others]
    same = all(_norm(value) == _norm(lead_text) for value in other_values)
    transcript = " ".join(turns_for_facet).lower()
    explicit_conflict = bool(
        re.search(
            r"\b(disagree|incompatible|contradicts?|cannot both|rather than)\b",
            transcript,
        )
    )
    if same:
        return FacetVerdict(
            facet=facet,
            status="consensus",
            summary=f"The panel shares the same {facet} account.",
            consensus=lead_text,
            supporting=[item.name for item in others],
        )
    if explicit_conflict:
        return FacetVerdict(
            facet=facet,
            status="disagreement",
            summary=f"The panel states incompatible {facet} accounts.",
            disagreement=(
                f"Whether {lead_text} or the alternative facet accounts should "
                "govern the hypothesis."
            ),
            contested_by=[item.name for item in others],
        )
    return FacetVerdict(
        facet=facet,
        status="unsettled",
        summary=f"The panel adds distinct {facet} evidence without resolving it.",
        unsettled=(
            f"How the {facet} boundaries represented by the panel fit together "
            "remains unestablished."
        ),
    )


def _point_from_verdict(
    verdict: FacetVerdict,
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
        facet=verdict.facet,
        text=text,
        rationale=verdict.summary,
        perspective_names=names,
        citations=citations,
    )


async def summarize_round(
    facets: list[Facet],
    verdicts: list[FacetVerdict],
    turns: list[str],
    *,
    provider: FocusedProvider | None = None,
) -> RoundResolution:
    evidence_by_facet: dict[Facet, list[str]] = {
        verdict.facet: list(
            dict.fromkeys(
                citation
                for citations in verdict.evidence.values()
                for citation in citations
            )
        )
        for verdict in verdicts
    }
    parsed = await _structured(
        provider,
        "Resolve a focused multi-perspective discussion. Summarize what the "
        "dialogue established, then separate consensus, genuine disagreement, "
        "and unsettled evidence or boundaries. Never invent conflict. If no "
        "disagreement exists, identify at least one open point genuinely left "
        "unestablished by the dialogue so the investigation can continue.",
        "## ACTIVE FACETS\n"
        + ", ".join(facets)
        + "\n\n## MODERATOR VERDICTS\n"
        + "\n".join(
            f"- {verdict.facet} [{verdict.status}]: {verdict.summary}"
            + (
                " | canonical evidence IDs: "
                + ", ".join(evidence_by_facet[verdict.facet])
                if evidence_by_facet[verdict.facet]
                else " | canonical evidence IDs: none"
            )
            for verdict in verdicts
        )
        + "\n\n## DIALOGUE\n"
        + "\n".join(turns),
        RoundResolution,
        temperature=0.1,
    )
    if parsed and parsed.summary:
        active = set(facets)
        parsed.consensus_points = [
            point for point in parsed.consensus_points if point.facet in active
        ]
        parsed.disagreement_points = [
            point for point in parsed.disagreement_points if point.facet in active
        ]
        parsed.unsettled_points = [
            point for point in parsed.unsettled_points if point.facet in active
        ]
        all_points = [
            *parsed.consensus_points,
            *parsed.disagreement_points,
            *parsed.unsettled_points,
        ]
        for point in all_points:
            point.citations = list(evidence_by_facet.get(point.facet, []))
        if not parsed.disagreement_points and not parsed.unsettled_points:
            facet = facets[0]
            parsed.unsettled_points.append(
                DeliberationPoint(
                    facet=facet,
                    text=(
                        f"The dialogue did not establish how far its shared "
                        f"{facet} account generalizes."
                    ),
                    rationale="Consensus did not resolve its evidentiary boundary.",
                )
            )
        for point in parsed.unsettled_points:
            point.citations = list(evidence_by_facet.get(point.facet, []))
        return parsed

    consensus = [
        _point_from_verdict(verdict, kind="consensus")
        for verdict in verdicts
        if verdict.status == "consensus"
    ]
    disagreements = [
        _point_from_verdict(verdict, kind="disagreement")
        for verdict in verdicts
        if verdict.status == "disagreement"
    ]
    unsettled = [
        _point_from_verdict(verdict, kind="unsettled")
        for verdict in verdicts
        if verdict.status == "unsettled"
    ]
    if not disagreements and not unsettled:
        facet = facets[0]
        unsettled.append(
            DeliberationPoint(
                facet=facet,
                text=(
                    f"The shared {facet} account has not been tested outside "
                    "the evidence represented in this panel."
                ),
                rationale="The dialogue reached agreement but left its boundary open.",
                citations=list(evidence_by_facet.get(facet, [])),
            )
        )
    summary = " ".join(verdict.summary for verdict in verdicts).strip()
    return RoundResolution(
        summary=summary or "The panel completed a focused facet discussion.",
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
) -> tuple[ParticipantReflection, dict[Facet, FacetEvidence]]:
    parsed = await _structured(
        provider,
        "Reflect as one research perspective after deliberation. Revise only "
        "an active facet when the exchange supplied a defensible reason; do not "
        "change merely to manufacture agreement. Keep unsupported facets "
        "unchanged. A revision is a concise new facet statement.",
        f"## YOUR CURRENT FACETS\n{_facets_block(perspective)}\n\n"
        f"## ACTIVE FACETS\n{', '.join(facets)}\n\n"
        f"## RESOLUTION\n{resolution.model_dump_json()}",
        ReflectionDraft,
        temperature=0.1,
    )
    current = {
        facet: evidence.model_copy(deep=True)
        for facet, evidence in perspective.facets.items()
    }
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

    revisions = [
        revision
        for revision in parsed.revisions
        if revision.facet in facets and revision.text.strip()
    ]
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
    scope = _display(_facet_text(perspective, "scope"))
    explanation = _display(_facet_text(perspective, "explanation"))
    approach = _display(_facet_text(perspective, "approach"))
    significance = _display(_facet_text(perspective, "significance"))
    return HypothesisDev(
        problem=f"The phenomenon to explain is bounded by {scope}.",
        previous_work=f"The represented literature explains it through {explanation}.",
        reasoning=f"The claim can be tested or established through {approach}.",
        hypothesis=(
            f"Within {scope}, evidence for {explanation} measured through "
            f"{approach} will predict outcomes consequential to {significance}."
        ),
    )


async def develop_hypothesis(
    perspective: Perspective,
    *,
    provider: FocusedProvider | None = None,
) -> HypothesisDev:
    parsed = await _structured(
        provider,
        "Develop one testable hypothesis from all four perspective facets. "
        "Return four inspectable parts: problem, previous_work, reasoning, and "
        "hypothesis. Preserve the facet boundaries and do not claim more than "
        "the abstract-grounded evidence supports.",
        f"## PERSPECTIVE: {perspective.name}\n## FACETS\n{_facets_block(perspective)}",
        HypothesisSteps,
    )
    if parsed and parsed.steps:
        return parsed.steps
    return _fallback_hypothesis(perspective)


_NOT_ESTABLISHED = "Not established yet."


def _fallback_consensus_hypothesis(
    resolution: RoundResolution,
    current: HypothesisDev | None = None,
) -> HypothesisDev:
    base = current or HypothesisDev(
        problem=_NOT_ESTABLISHED,
        previous_work=_NOT_ESTABLISHED,
        reasoning=_NOT_ESTABLISHED,
        hypothesis=_NOT_ESTABLISHED,
    )
    by_facet = {
        point.facet: point.text
        for point in resolution.consensus_points
        if point.text.strip()
    }
    shared = "; ".join(
        point.text.strip().rstrip(".")
        for point in resolution.consensus_points
        if point.text.strip()
    )
    updates: dict[str, str] = {}

    if scope := by_facet.get("scope"):
        updates["problem"] = f"The supported scope is {scope}."

    if shared:
        addition = f"Shared evidence added: {shared}."
        updates["previous_work"] = (
            addition
            if base.previous_work == _NOT_ESTABLISHED
            else (
                base.previous_work
                if shared in base.previous_work
                else f"{base.previous_work} {addition}"
            )
        )

    reasoning_points = [
        by_facet[facet].strip().rstrip(".")
        for facet in ("explanation", "approach")
        if facet in by_facet
    ]
    if reasoning_points:
        addition = "New shared reasoning: " + "; ".join(reasoning_points) + "."
        updates["reasoning"] = (
            addition
            if base.reasoning == _NOT_ESTABLISHED
            else (
                base.reasoning
                if all(point in base.reasoning for point in reasoning_points)
                else f"{base.reasoning} {addition}"
            )
        )

    scope_for_hypothesis = by_facet.get("scope")
    if scope_for_hypothesis is None and base.problem.startswith(
        "The supported scope is "
    ):
        scope_for_hypothesis = base.problem.removeprefix(
            "The supported scope is "
        ).removesuffix(".")
    explanation = by_facet.get("explanation")
    if base.hypothesis == _NOT_ESTABLISHED and scope_for_hypothesis and explanation:
        claim = explanation[0].lower() + explanation[1:]
        updates["hypothesis"] = f"Within {scope_for_hypothesis}, {claim}"

    return base.model_copy(update=updates)


async def develop_hypothesis_from_consensus(
    resolution: RoundResolution,
    *,
    current: HypothesisDev | None = None,
    provider: FocusedProvider | None = None,
) -> HypothesisDev:
    """Build a working hypothesis from supported shared ground only."""
    if not resolution.consensus_points:
        raise ValueError("consensus points are required")
    current_block = (
        current.model_dump_json(indent=2)
        if current is not None
        else "No working hypothesis has been established yet."
    )
    parsed = await _structured(
        provider,
        "Revise a four-part working hypothesis using ONLY the supplied consensus "
        "points and their cited evidence. Preserve every current part that the "
        "new shared ground does not directly change. Never use disagreement or "
        "unsettled points to fill a hypothesis part. A part may remain 'Not "
        "established yet.' Return problem, previous_work, reasoning, and "
        "hypothesis.",
        f"## CURRENT WORKING HYPOTHESIS\n{current_block}\n\n"
        "## NEW SUPPORTED SHARED GROUND\n"
        + "\n".join(
            f"- {point.facet}: {point.text}"
            + (f" [evidence: {', '.join(point.citations)}]" if point.citations else "")
            for point in resolution.consensus_points
        ),
        HypothesisSteps,
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

    templates: dict[Facet, str] = {
        "scope": "Under which populations, settings, or conditions does this boundary hold: {point}?",
        "explanation": "What evidence would distinguish the competing or incomplete explanation in this point: {point}?",
        "approach": "Which study design could resolve the methodological uncertainty in this point: {point}?",
        "significance": "When does the consequence in this point become large enough to change a scientific or practical decision: {point}?",
    }
    return [
        RecommendedQuestion(
            question=templates[point.facet].format(point=point.text.rstrip(" .?!")),
            rationale=(
                f"This follows from the round's {source_kind} point on "
                f"{point.facet}: {point.rationale or point.text}"
            ),
            source_kind=source_kind,
            source_point=point.text,
            facets=[point.facet],
        )
        for point in source_points[:3]
    ]


async def reply_to_user(
    perspective: Perspective,
    question: str,
    history: list[str],
    *,
    active_facets: list[Facet] | None = None,
    provider: FocusedProvider | None = None,
) -> Statement:
    facets = active_facets or FACETS
    parsed = await _structured(
        provider,
        "Answer the researcher's question as one evidence-grounded perspective. "
        "Stay within the active facet context when supplied, distinguish a "
        "qualification from disagreement, and cite supporting paper IDs.",
        f"## YOUR FACETS\n{_facets_block(perspective)}\n\n"
        f"## ACTIVE FACETS\n{', '.join(facets)}\n\n"
        f"## RECENT EXCHANGE\n"
        + "\n".join(history[-8:])
        + f"\n\n## RESEARCHER QUESTION\n{question}",
        ChatReply,
    )
    if parsed and parsed.text:
        return Statement(text=parsed.text, citations=parsed.citations)
    focus = "; ".join(
        f"{facet}: {_display(_facet_text(perspective, facet))}" for facet in facets
    )
    return Statement(
        text=f"From the {perspective.name} perspective, {focus}.",
        citations=list(perspective.sources[:2]),
    )
