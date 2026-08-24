from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from agora.focused.clustering import density_partition
from agora.focused.models import ExpPaper


def papers(count: int) -> list[ExpPaper]:
    result = []
    for index in range(count):
        group = index // max(count // 2, 1)
        vector = np.zeros(8, dtype=float)
        vector[group % 2] = 1.0
        vector[2 + index % 6] = 0.05 + index * 0.001
        result.append(
            ExpPaper(
                id=f"p{index}",
                title=f"Paper {index}",
                abstract=f"Grounded abstract sentence for paper {index}.",
                specter_v2=vector.tolist(),
            )
        )
    return result


def test_density_partition_keeps_noise_explicit_and_selects_five(
    monkeypatch,
) -> None:
    labels = np.asarray([0] * 7 + [1] * 7 + [-1] * 2, dtype=np.int64)

    def fake_partition(*_args, **_kwargs):
        return SimpleNamespace(labels=labels, relative_validity=0.5)

    monkeypatch.setattr("agora.research.cluster.fit_partition", fake_partition)

    result = density_partition(papers(16), requested_clusters=2)

    assert result is not None
    assert [len(group) for group in result.groups] == [7, 7]
    assert len(result.unassigned) == 2
    assert all(len(selected) == 5 for selected in result.representatives)
    for group, selected in zip(result.groups, result.representatives, strict=True):
        assert {paper.id for paper in selected} <= {paper.id for paper in group}


def test_density_partition_merges_extra_clusters_without_losing_members(
    monkeypatch,
) -> None:
    labels = np.asarray([0] * 5 + [1] * 5 + [2] * 5 + [-1], dtype=np.int64)

    def fake_partition(*_args, **_kwargs):
        return SimpleNamespace(labels=labels, relative_validity=0.4)

    monkeypatch.setattr("agora.research.cluster.fit_partition", fake_partition)

    result = density_partition(papers(16), requested_clusters=2)

    assert result is not None
    assert len(result.groups) == 2
    assert sum(len(group) for group in result.groups) == 15
    assert len(result.unassigned) == 1


def test_density_partition_requires_complete_embeddings() -> None:
    corpus = papers(10)
    corpus[-1].specter_v2 = None

    assert density_partition(corpus, requested_clusters=2) is None

def test_density_partition_runs_lightweight_hdbscan_end_to_end() -> None:
    rng = np.random.default_rng(42)
    corpus: list[ExpPaper] = []
    for group in range(3):
        center = np.zeros(12)
        center[group] = 1.0
        for offset in range(20):
            vector = center + rng.normal(0.0, 0.015, size=12)
            corpus.append(
                ExpPaper(
                    id=f"g{group}-{offset}",
                    title=f"Group {group} paper {offset}",
                    abstract="A complete grounded abstract.",
                    specter_v2=vector.tolist(),
                )
            )

    result = density_partition(corpus, requested_clusters=3)

    assert result is not None
    assert len(result.groups) == 3
    assert all(len(selected) == 5 for selected in result.representatives)
