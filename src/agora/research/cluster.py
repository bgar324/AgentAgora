from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray


@dataclass
class Partition:
    labels: NDArray[np.int64]
    Z: NDArray[np.float32]
    probabilities: NDArray[np.float64]
    persistence: NDArray[np.float64]
    relative_validity: float


def project(
    X: NDArray,
    *,
    n_neighbors: int = 15,
    n_components: int = 10,
    min_dist: float = 0.0,
    metric: str = "cosine",
    random_state: int = 42,
) -> NDArray[np.float32]:
    import umap

    X = np.asarray(X, dtype=np.float32)

    if X.ndim != 2:
        raise ValueError("X must have shape (n, d)")

    if not np.isfinite(X).all():
        raise ValueError("X must contain only finite values")

    n = len(X)

    if n < 5:
        raise ValueError("At least five papers are required")

    if n_neighbors < 2:
        raise ValueError("n_neighbors must be at least 2")

    if n_components < 2:
        raise ValueError("n_components must be at least 2")

    if min_dist < 0.0:
        raise ValueError("min_dist must be nonnegative")

    model = umap.UMAP(
        n_neighbors=min(n_neighbors, n - 1),
        n_components=min(n_components, n - 2),
        min_dist=min_dist,
        metric=metric,
        init="spectral",
        random_state=random_state,
    )

    return np.asarray(model.fit_transform(X), dtype=np.float32)


def fit_partition(
    X: NDArray,
    *,
    min_cluster_size: int = 30,
    min_samples: int = 1,
    cluster_selection_method: str = "leaf",
    n_neighbors: int = 15,
    n_components: int = 10,
    min_dist: float = 0.0,
    random_state: int = 42,
) -> Partition:
    import hdbscan

    X = np.asarray(X)
    n = len(X)

    if not 2 <= min_cluster_size <= n:
        raise ValueError(
            "min_cluster_size must satisfy 2 <= min_cluster_size <= n"
        )

    if min_samples < 1:
        raise ValueError("min_samples must be positive")

    if cluster_selection_method not in {"eom", "leaf"}:
        raise ValueError("cluster_selection_method must be 'eom' or 'leaf'")

    Z = project(
        X,
        n_neighbors=n_neighbors,
        n_components=n_components,
        min_dist=min_dist,
        random_state=random_state,
    )

    model = hdbscan.HDBSCAN(
        min_cluster_size=min_cluster_size,
        min_samples=min_samples,
        metric="euclidean",
        cluster_selection_method=cluster_selection_method,
        core_dist_n_jobs=-1,
        gen_min_span_tree=True,
    ).fit(Z)

    return Partition(
        labels=np.asarray(model.labels_, dtype=np.int64),
        Z=Z,
        probabilities=np.asarray(model.probabilities_, dtype=np.float64),
        persistence=np.asarray(model.cluster_persistence_, dtype=np.float64),
        relative_validity=float(model.relative_validity_),
    )
