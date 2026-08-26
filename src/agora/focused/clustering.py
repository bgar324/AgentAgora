from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from agora.focused.models import ExpPaper

NOISE_LABEL = -1
CENTRAL_REPRESENTATIVES = 3
DIVERSE_REPRESENTATIVES = 2
REPRESENTATIVE_COUNT = CENTRAL_REPRESENTATIVES + DIVERSE_REPRESENTATIVES


@dataclass(frozen=True)
class FocusedPartition:
    groups: list[list[ExpPaper]]
    representatives: list[list[ExpPaper]]
    unassigned: list[ExpPaper]


def _normalize_rows(matrix: np.ndarray) -> np.ndarray:
    values = np.asarray(matrix, dtype=np.float64)
    norms = np.linalg.norm(values, axis=1, keepdims=True)
    if np.any(norms == 0):
        raise ValueError("embedding vectors must be nonzero")
    return values / norms


def _candidate_min_cluster_sizes(paper_count: int, requested: int) -> list[int]:
    target = max(REPRESENTATIVE_COUNT, paper_count // max(requested, 1))
    return list(
        dict.fromkeys(
            [
                min(target, paper_count),
                max(REPRESENTATIVE_COUNT, target * 2 // 3),
                REPRESENTATIVE_COUNT,
            ]
        )
    )


def _merge_extra_clusters(
    matrix: np.ndarray,
    labels: np.ndarray,
    *,
    requested: int,
) -> np.ndarray:
    assigned = [int(label) for label in np.unique(labels) if label != NOISE_LABEL]
    if len(assigned) <= requested:
        return labels
    kept = sorted(
        assigned,
        key=lambda label: (-int(np.sum(labels == label)), label),
    )[:requested]
    centroids = np.asarray(
        [matrix[labels == label].mean(axis=0) for label in kept],
        dtype=np.float64,
    )
    centroids = _normalize_rows(centroids)
    merged = labels.copy()
    for index, label in enumerate(labels):
        if label == NOISE_LABEL or int(label) in kept:
            continue
        merged[index] = kept[int(np.argmax(centroids @ matrix[index]))]
    return merged


def _fallback_representatives(
    matrix: np.ndarray,
    labels: np.ndarray,
    label: int,
) -> list[int]:
    indices = np.flatnonzero(labels == label)
    vectors = matrix[indices]
    centroid = _normalize_rows(vectors.mean(axis=0, keepdims=True))[0]
    order = np.argsort(-(vectors @ centroid), kind="stable")
    return [int(indices[item]) for item in order[:REPRESENTATIVE_COUNT]]


def density_partition(
    papers: list[ExpPaper],
    *,
    requested_clusters: int,
) -> FocusedPartition | None:
    """Cluster SPECTER papers with UMAP/HDBSCAN and select central+DPP evidence."""
    if len(papers) < 2 * REPRESENTATIVE_COUNT or requested_clusters < 2:
        return None
    clusterable = [paper for paper in papers if paper.specter_v2]
    missing_embeddings = [paper for paper in papers if not paper.specter_v2]
    if len(clusterable) < 2 * REPRESENTATIVE_COUNT:
        return None
    try:
        matrix = _normalize_rows(
            np.asarray(
                [paper.specter_v2 for paper in clusterable],
                dtype=np.float64,
            )
        )
    except ValueError:
        return None
    if not np.isfinite(matrix).all():
        return None

    from agora.research.cluster import fit_partition

    minimum_clusters = min(3, requested_clusters)
    candidates: list[tuple[tuple[int, float, float], np.ndarray]] = []
    for min_cluster_size in _candidate_min_cluster_sizes(
        len(clusterable), requested_clusters
    ):
        try:
            partition = fit_partition(
                matrix,
                min_cluster_size=min_cluster_size,
                min_samples=1,
                cluster_selection_method="leaf",
                n_neighbors=min(15, len(clusterable) - 1),
                n_components=min(10, len(clusterable) - 2),
                min_dist=0.0,
                random_state=42,
            )
        except (ImportError, ValueError):
            continue
        labels = np.asarray(partition.labels, dtype=np.int64)
        assigned = [label for label in np.unique(labels) if label != NOISE_LABEL]
        if len(assigned) < minimum_clusters:
            continue
        coverage = float(np.mean(labels != NOISE_LABEL))
        score = (
            -abs(len(assigned) - requested_clusters),
            coverage,
            float(partition.relative_validity),
        )
        candidates.append((score, labels))
        if len(assigned) == requested_clusters and coverage >= 0.7:
            break
    if not candidates:
        return None

    labels = max(candidates, key=lambda item: item[0])[1]
    labels = _merge_extra_clusters(matrix, labels, requested=requested_clusters)
    assigned_labels = [
        int(label) for label in np.unique(labels) if label != NOISE_LABEL
    ]
    assigned_labels.sort(key=lambda label: (-int(np.sum(labels == label)), label))
    if len(assigned_labels) < minimum_clusters:
        return None

    try:
        from agora.research.selection import select_representatives

        selected = select_representatives(
            matrix,
            labels,
            n_central=CENTRAL_REPRESENTATIVES,
            n_diverse=DIVERSE_REPRESENTATIVES,
            noise_label=NOISE_LABEL,
        )
        representative_indices = {
            label: [item.index for item in selected[label]] for label in assigned_labels
        }
    except (ImportError, ValueError):
        representative_indices = {
            label: _fallback_representatives(matrix, labels, label)
            for label in assigned_labels
        }

    return FocusedPartition(
        groups=[
            [clusterable[index] for index in np.flatnonzero(labels == label)]
            for label in assigned_labels
        ],
        representatives=[
            [clusterable[index] for index in representative_indices[label]]
            for label in assigned_labels
        ],
        unassigned=[
            *missing_embeddings,
            *[clusterable[index] for index in np.flatnonzero(labels == NOISE_LABEL)],
        ],
    )
