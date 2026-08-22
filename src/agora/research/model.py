import hashlib
import re
from collections.abc import Sequence

import numpy as np
from bertopic import BERTopic
from bertopic.cluster import BaseCluster
from bertopic.dimensionality import BaseDimensionalityReduction
from bertopic.vectorizers import ClassTfidfTransformer
from sklearn.base import clone
from sklearn.feature_extraction.text import CountVectorizer

from agora.config.literature import LiteratureConfig, TopicConfig
from agora.research.cluster import fit_partition
from agora.research.corpus import build_corpus
from agora.research.selection import select_representatives
from agora.schemas.research import (
    ClusteredLiterature,
    LiteratureCluster,
    Paper,
    RepresentativePaper,
    TopicRepresentation,
)

NOISE = -1


def cluster_id(source_ids: Sequence[str]) -> str:
    value = "\x1f".join(sorted(source_ids))
    digest = hashlib.sha256(value.encode()).hexdigest()[:16]
    return f"cluster_{digest}"


def _clean_text(documents: Sequence[str]) -> list[str]:
    return [
        re.sub(
            r"[^A-Za-z0-9 ]+",
            "",
            document.replace("\n", " ").replace("\t", " "),
        )
        or "emptydoc"
        for document in documents
    ]


def _vectorizer(
    documents: Sequence[str],
    *,
    config: TopicConfig,
) -> CountVectorizer:
    if not documents:
        raise ValueError("documents must not be empty")

    low, high = config.ngram_range

    if not 1 <= low <= high:
        raise ValueError("ngram_range must contain positive ordered bounds")

    if config.min_papers < 1:
        raise ValueError("min_papers must be positive")

    if config.n_terms < 1:
        raise ValueError("n_terms must be positive")

    vocabulary = (
        CountVectorizer(
            ngram_range=config.ngram_range,
            min_df=config.min_papers,
            stop_words=config.stop_words,
        )
        .fit(_clean_text(documents))
        .get_feature_names_out()
    )

    return CountVectorizer(
        ngram_range=config.ngram_range,
        vocabulary=vocabulary,
        stop_words=config.stop_words,
    )


def _fit_topics(
    documents: Sequence[str],
    X: np.ndarray,
    y: np.ndarray,
    *,
    vectorizer: CountVectorizer,
    n_terms: int,
) -> BERTopic:
    model = BERTopic(
        embedding_model=None,
        umap_model=BaseDimensionalityReduction(),
        hdbscan_model=BaseCluster(),
        vectorizer_model=clone(vectorizer),
        ctfidf_model=ClassTfidfTransformer(),
        top_n_words=n_terms,
        calculate_probabilities=False,
    )

    model.fit_transform(list(documents), embeddings=X, y=list(y))

    return model


def _topic_map(model: BERTopic) -> dict[int, int]:
    return {
        int(source): int(target)
        for source, target in model.topic_mapper_.get_mappings().items()
    }


def _topic_representations(
    documents: Sequence[str],
    X: np.ndarray,
    y: np.ndarray,
    *,
    config: TopicConfig,
) -> dict[int, TopicRepresentation]:
    labels = [int(label) for label in np.unique(y) if label != NOISE]

    try:
        vectorizer = _vectorizer(documents, config=config)
    except ValueError:
        return {label: TopicRepresentation() for label in labels}

    model = _fit_topics(
        documents,
        X,
        y,
        vectorizer=vectorizer,
        n_terms=config.n_terms,
    )

    mapping = _topic_map(model)
    representations = {}

    for label in labels:
        topic_id = mapping[label]
        ranked = model.get_topic(topic_id) or []

        terms = [term for term, _ in ranked[: config.n_terms]]

        representations[label] = TopicRepresentation(
            label=" · ".join(terms[:2]) if terms else None,
            terms=terms,
        )

    return representations


class LiteratureModel:
    def __init__(self, config: LiteratureConfig | None = None):
        self.config = config or LiteratureConfig()

    def fit(self, papers: Sequence[Paper]) -> ClusteredLiterature:
        corpus = build_corpus(papers)
        cluster = self.config.cluster
        representatives = self.config.representatives

        partition = fit_partition(
            corpus.X,
            min_cluster_size=cluster.min_cluster_size,
            min_samples=cluster.min_samples,
            cluster_selection_method=cluster.cluster_selection_method,
            n_neighbors=cluster.n_neighbors,
            n_components=cluster.n_components,
            min_dist=cluster.min_dist,
            random_state=cluster.random_state,
        )

        y = partition.labels
        assigned = set(y.tolist()) - {NOISE}

        if not assigned:
            raise ValueError("The partition contains no assigned clusters")

        topics = _topic_representations(
            corpus.documents,
            corpus.X,
            y,
            config=self.config.topic,
        )

        selected = select_representatives(
            corpus.X,
            y,
            n_central=representatives.n_central,
            n_diverse=representatives.n_diverse,
        )

        clusters: list[LiteratureCluster] = []

        for label in sorted(selected):
            member_indices = np.flatnonzero(y == label)

            source_ids = [corpus.source_ids[i] for i in member_indices]

            papers_selected = [
                RepresentativePaper(
                    source_id=corpus.source_ids[item.index],
                    title=corpus.papers[item.index].title,
                    abstract=corpus.papers[item.index].abstract or "",
                    role=item.role,
                    rank=item.rank,
                )
                for item in selected[label]
            ]

            clusters.append(
                LiteratureCluster(
                    id=cluster_id(source_ids),
                    source_ids=source_ids,
                    representatives=papers_selected,
                    topic=topics.get(label),
                )
            )

        clusters.sort(key=lambda item: (-item.size, item.id))

        unassigned_source_ids = [
            corpus.source_ids[i] for i in np.flatnonzero(y == NOISE)
        ]

        return ClusteredLiterature(
            clusters=clusters,
            unassigned_source_ids=unassigned_source_ids,
        )
