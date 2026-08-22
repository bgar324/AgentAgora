from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import pandas as pd
from numpy.typing import NDArray

from agora.research.semantics import l2_normalize
from agora.schemas.research import Paper

METADATA_COLUMNS = (
    "source_id",
    "paper_id",
    "s2_corpus_id",
    "title",
    "abstract",
    "tldr",
    "year",
    "venue",
    "citation_count",
    "fields_of_study",
)


@dataclass
class Corpus:
    papers: tuple[Paper, ...]
    source_ids: tuple[str, ...]
    documents: tuple[str, ...]
    X: NDArray[np.float64]
    metadata: pd.DataFrame


def build_corpus(
    papers: Sequence[Paper],
    *,
    require_abstract: bool = True,
) -> Corpus:
    seen: set[str] = set()
    selected: list[tuple[Paper, NDArray[np.float64]]] = []

    for paper in papers:
        if not paper.source_id:
            continue
        if paper.source_id in seen:
            continue
        if not paper.title.strip():
            continue
        if require_abstract and not (paper.abstract or "").strip():
            continue
        if not paper.specter_v2:
            continue

        vector = np.asarray(paper.specter_v2, dtype=np.float64)

        if vector.ndim != 1:
            continue
        if not np.isfinite(vector).all():
            continue
        if np.linalg.norm(vector) == 0.0:
            continue

        seen.add(paper.source_id)
        selected.append((paper, vector))

    if not selected:
        raise ValueError(
            "No paper contains a title, abstract, and usable SPECTER2 embedding"
        )

    dimensions = {len(vector) for _, vector in selected}

    if len(dimensions) != 1:
        raise ValueError("The retained embeddings have different dimensions")

    retained = tuple(paper for paper, _ in selected)
    source_ids = tuple(paper.source_id for paper in retained)

    documents = tuple(
        "\n\n".join(
            value.strip()
            for value in (paper.title, paper.abstract)
            if value and value.strip()
        )
        for paper in retained
    )

    X = l2_normalize(np.vstack([vector for _, vector in selected]))

    metadata = pd.DataFrame(
        [
            {
                "source_id": paper.source_id,
                "paper_id": paper.paper_id,
                "s2_corpus_id": paper.s2_corpus_id,
                "title": paper.title,
                "abstract": paper.abstract,
                "tldr": paper.tldr,
                "year": paper.year,
                "venue": paper.venue,
                "citation_count": paper.citation_count,
                "fields_of_study": paper.fields_of_study,
            }
            for paper in retained
        ],
        columns=list(METADATA_COLUMNS),
    )

    return Corpus(
        papers=retained,
        source_ids=source_ids,
        documents=documents,
        X=X,
        metadata=metadata,
    )
