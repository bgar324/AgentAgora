from dataclasses import dataclass
from typing import Literal

import numpy as np
from numpy.typing import NDArray

from agora.research.semantics import centroid_relevance

RepresentativeRole = Literal[
    "central",
    "diverse",
]


@dataclass
class RepresentativeIndex:
    index: int
    role: RepresentativeRole
    rank: int


def _dpp_kernel(X: NDArray, quality: NDArray) -> NDArray[np.float64]:
    X = np.asarray(X, dtype=np.float64)
    quality = np.asarray(quality, dtype=np.float64)

    similarity = np.clip(X @ X.T, -1.0, 1.0)

    return quality[:, None] * similarity * quality[None, :]


def _greedy_dpp(L: NDArray, k: int) -> list[int]:
    L = np.asarray(L, dtype=np.float64)

    if L.ndim != 2 or L.shape[0] != L.shape[1]:
        raise ValueError("L must be a square matrix")

    n = len(L)
    k = min(k, n)

    diagonal = np.diag(L).copy()
    factors = np.zeros((k, n), dtype=np.float64)
    selected: list[int] = []

    for i in range(k):
        j = int(np.argmax(diagonal))
        value = diagonal[j]

        if not np.isfinite(value) or value <= np.finfo(float).eps:
            break

        selected.append(j)

        if i == k - 1:
            break

        if i == 0:
            correction = 0.0
        else:
            correction = factors[:i, j] @ factors[:i]

        row = (L[j] - correction) / np.sqrt(value)

        factors[i] = row
        diagonal = np.maximum(diagonal - row**2, 0.0)
        diagonal[selected] = -np.inf

    return selected


def select_representatives(
    X: NDArray,
    y: NDArray,
    *,
    n_central: int = 3,
    n_diverse: int = 2,
    noise_label: int = -1,
) -> dict[int, list[RepresentativeIndex]]:
    X = np.asarray(X, dtype=np.float64)
    y = np.asarray(y)

    if y.shape != (len(X),):
        raise ValueError("y must have shape (n,)")

    if n_central < 1:
        raise ValueError("n_central must be positive")

    if n_diverse < 1:
        raise ValueError("n_diverse must be positive")

    n_selected = n_central + n_diverse

    representatives: dict[int, list[RepresentativeIndex]] = {}

    for label in np.unique(y):
        if label == noise_label:
            continue

        indices = np.flatnonzero(y == label)
        X_cluster = X[indices]

        if len(indices) < n_selected:
            raise ValueError(
                f"Cluster {label} contains fewer than {n_selected} papers"
            )

        relevance = centroid_relevance(X_cluster)

        central = np.argsort(-relevance, kind="stable")[:n_central]

        quality = relevance - relevance.min()
        maximum = quality.max()

        if maximum > 0.0:
            quality = quality / maximum

        quality = np.clip(quality, np.finfo(float).eps, None)

        L = _dpp_kernel(X_cluster, quality)

        candidate_limit = min(len(X_cluster), 2 * n_selected)

        order = _greedy_dpp(L, candidate_limit)

        central_set = {int(i) for i in central}

        diverse = [i for i in order if i not in central_set][:n_diverse]

        if len(diverse) < n_diverse:
            order = _greedy_dpp(L, len(X_cluster))
            diverse = [i for i in order if i not in central_set][:n_diverse]

        if len(diverse) != n_diverse:
            raise ValueError(
                f"Cluster {label} does not provide "
                f"{n_diverse} distinct diverse papers"
            )

        representatives[int(label)] = [
            *[
                RepresentativeIndex(
                    index=int(indices[i]),
                    role="central",
                    rank=rank,
                )
                for rank, i in enumerate(central, start=1)
            ],
            *[
                RepresentativeIndex(
                    index=int(indices[i]),
                    role="diverse",
                    rank=rank,
                )
                for rank, i in enumerate(diverse, start=1)
            ],
        ]

    return representatives
