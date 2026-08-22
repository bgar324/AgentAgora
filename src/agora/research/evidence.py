import asyncio
import re
from collections.abc import Sequence

import dspy

from agora.config.deliberation import DeliberationConfig
from agora.db.vector import KnowledgeSearch
from agora.research.annotate import ExtractObservations, observation_id
from agora.schemas.deliberation import EvidenceResult
from agora.schemas.panel import Observation


def merge_observations(
    *groups: Sequence[Observation],
) -> list[Observation]:
    by_id: dict[str, Observation] = {}

    for observations in groups:
        for observation in observations:
            current = by_id.get(observation.id)

            if current is not None and current != observation:
                raise ValueError(
                    f"Observation {observation.id} has conflicting values"
                )

            by_id.setdefault(observation.id, observation)

    return list(by_id.values())


CITATION_MARKS = re.compile(
    r"\s*\[\d+(?:\s*,\s*\d+)*\](?:\s*,?\s*\[\d+(?:\s*,\s*\d+)*\])*"
)
OBSERVATION_MARKS = re.compile(
    r"\s*\(observations?(?:\s+\d+(?:\s*,\s*\d+)*)?\)",
    re.IGNORECASE,
)


def strip_citations(text: str) -> str:
    stripped = CITATION_MARKS.sub("", text)
    stripped = OBSERVATION_MARKS.sub("", stripped)
    return " ".join(stripped.split())


MARKER = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")
REPEATED_MARKS = re.compile(r"(\[(\d+)\])(?:\s*\[\2\])+")


UNRESOLVED_ANNOUNCE = re.compile(
    r"\bwhat remains (unresolved|unsettled|open|unclear) is ([^.!?]+)([.!?])",
    re.IGNORECASE,
)

ANNOUNCE_OPENER = re.compile(
    r"\bthe (remaining disagreement|unresolved question|open question)"
    r" is ([^.!?]+)([.!?])",
    re.IGNORECASE,
)

OPENER_STATES = {
    "remaining disagreement": "disputed",
    "unresolved question": "open",
    "open question": "open",
}


def invert_announcements(text: str) -> str:
    def rewrite(state: str, match: re.Match) -> str:
        subject = match.group(2).strip()
        prefix = text[: match.start()].rstrip()
        sentence_start = not prefix or prefix[-1] in ".!?"

        if sentence_start:
            subject = subject[0].upper() + subject[1:]

        return f"{subject} remains {state}{match.group(3)}"

    text = UNRESOLVED_ANNOUNCE.sub(
        lambda match: rewrite(match.group(1).lower(), match), text
    )
    return ANNOUNCE_OPENER.sub(
        lambda match: rewrite(OPENER_STATES[match.group(1).lower()], match),
        text,
    )


def collapse_repeats(text: str) -> str:
    collapsed = REPEATED_MARKS.sub(r"\1", text)

    while collapsed != text:
        text = collapsed
        collapsed = REPEATED_MARKS.sub(r"\1", text)

    return collapsed


def text_citations(text: str) -> list[int]:
    positions: list[int] = []

    for match in MARKER.finditer(text):
        positions.extend(int(part) for part in match.group(1).split(","))

    return positions


def cited_prose(text: str | None, catalogue_size: int) -> str:
    cleaned = " ".join(str(text or "").split())

    if cleaned.startswith("{"):
        raise ValueError("A prose field contains serialized structure")

    cleaned = OBSERVATION_MARKS.sub("", cleaned)
    cleaned = invert_announcements(cleaned)

    def rewrite(match: re.Match) -> str:
        kept = [
            position
            for position in (
                int(part) for part in match.group(1).split(",")
            )
            if 1 <= position <= catalogue_size
        ]
        return "".join(f"[{position}]" for position in kept)

    rewritten = collapse_repeats(MARKER.sub(rewrite, cleaned))
    rewritten = re.sub(r"\s+([.,;:])", r"\1", rewritten)
    return " ".join(rewritten.split())


SENTENCE_ENDS = re.compile(r"[.!?](?:\s|$)")


def word_count(text: str) -> int:
    return len(text.split())


def sentence_count(text: str) -> int:
    return max(len(SENTENCE_ENDS.findall(text)), 1 if text.strip() else 0)


def prose(text: str | None) -> str:
    cleaned = " ".join(str(text or "").split())

    if cleaned.startswith("{"):
        raise ValueError("A prose field contains serialized structure")

    return strip_citations(cleaned)


def observation_catalogue(
    observations: Sequence[Observation],
) -> list[str]:
    return [
        f"[{position}] {observation.text}"
        for position, observation in enumerate(observations, start=1)
    ]


def cited_observations(
    positions: Sequence[int],
    observations: Sequence[Observation],
) -> list[Observation]:
    selected: dict[str, Observation] = {}

    for position in positions:
        if not 1 <= position <= len(observations):
            raise ValueError(
                f"Citation outside the catalogue: {position}"
            )

        observation = observations[position - 1]
        selected.setdefault(observation.id, observation)

    return list(selected.values())


def observations_by_id(
    observation_ids: Sequence[str],
    observations: Sequence[Observation],
) -> list[Observation]:
    ordered_ids = list(dict.fromkeys(observation_ids))
    by_id = {observation.id: observation for observation in observations}
    missing = [
        observation_id
        for observation_id in ordered_ids
        if observation_id not in by_id
    ]

    if missing:
        raise ValueError(f"Unknown Observation identifiers: {missing}")

    return [by_id[observation_id] for observation_id in ordered_ids]


def limit_observations(
    observations: Sequence[Observation],
    *,
    n: int = 10,
    per_source: int = 2,
) -> list[Observation]:
    if n < 1 or per_source < 1:
        raise ValueError("n and per_source must be positive")

    selected: list[Observation] = []
    source_counts: dict[str, int] = {}

    for observation in observations:
        count = source_counts.get(observation.source_id, 0)

        if count >= per_source:
            continue

        selected.append(observation)
        source_counts[observation.source_id] = count + 1

        if len(selected) == n:
            break

    return selected


class EvidenceSearch(dspy.Module):
    def __init__(
        self,
        search: KnowledgeSearch,
        config: DeliberationConfig | None = None,
    ):
        super().__init__()

        self.extract_observations = dspy.Predict(ExtractObservations)
        self.search = search
        self.config = config or DeliberationConfig()

    async def aforward(
        self,
        *,
        query: str,
        question: str,
        investigation_id: str,
        corpus_id: str,
        source_ids: Sequence[str],
    ):
        query = " ".join(query.split())

        if not query or not source_ids:
            raise ValueError(
                "Evidence search requires a query and source IDs"
            )

        hits = await self.search.search(
            query,
            investigation_id=investigation_id,
            corpus_id=corpus_id,
            source_ids=source_ids,
            method=self.config.search_method,
            limit=self.config.evidence_limit,
            per_source=1,
        )
        stored = [
            observation
            for hit in hits
            for observation in hit.observations
        ]
        pending = [hit for hit in hits if not hit.observations]
        predictions = await asyncio.gather(
            *[
                self.extract_observations.acall(
                    question=question,
                    title=hit.snippet.title,
                    passage=hit.snippet.text,
                )
                for hit in pending
            ]
        )
        new: dict[str, Observation] = {}
        observation_snippets: dict[str, str] = {}

        for hit, prediction in zip(pending, predictions, strict=True):
            for text in prediction.observations:
                text = " ".join(text.split())

                if not text:
                    continue

                identifier = observation_id(
                    hit.snippet.source_id,
                    text,
                    hit.snippet.location,
                )
                new[identifier] = Observation(
                    id=identifier,
                    text=text,
                    source_id=hit.snippet.source_id,
                    location=hit.snippet.location,
                )
                observation_snippets[identifier] = hit.snippet.id

        result = EvidenceResult(
            observations=merge_observations(stored, list(new.values())),
            new_observations=list(new.values()),
            snippet_ids=[hit.snippet.id for hit in hits],
            observation_snippets=observation_snippets,
        )

        return dspy.Prediction(result=result)
