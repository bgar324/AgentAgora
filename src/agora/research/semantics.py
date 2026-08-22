import numpy as np
from numpy.typing import NDArray


def l2_normalize(X: NDArray) -> NDArray[np.float64]:
    X = np.asarray(X, dtype=np.float64)

    if X.ndim != 2:
        raise ValueError("X must have shape (n, d)")

    if not np.isfinite(X).all():
        raise ValueError("X must contain only finite values")

    norms = np.linalg.norm(X, axis=1, keepdims=True)

    if np.any(norms == 0.0):
        raise ValueError("X must not contain zero vectors")

    return X / norms


def centroid_relevance(X: NDArray) -> NDArray[np.float64]:
    X = np.asarray(X, dtype=np.float64)

    if X.ndim != 2 or len(X) == 0:
        raise ValueError("X must have shape (n, d) with n > 0")

    center = X.mean(axis=0)
    norm = np.linalg.norm(center)

    if norm == 0.0:
        raise ValueError("The cluster centroid has zero norm")

    return X @ (center / norm)
