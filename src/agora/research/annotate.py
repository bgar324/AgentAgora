import hashlib

import dspy


def observation_id(
    source_id: str,
    text: str,
    location: str | None = None,
) -> str:
    value = "\x1f".join(
        (
            source_id,
            location or "",
            " ".join(text.split()),
        )
    )
    digest = hashlib.sha256(value.encode()).hexdigest()[:16]
    return f"observation_{digest}"


class ExtractObservations(dspy.Signature):
    """
    You are reviewing one source passage from a paper for statements that
    are relevant to a research question.

    The research question determines which statements are relevant. The
    paper title and source passage determine what can be stated. Record each
    relevant proposition separately, preserving comparisons, conditions,
    populations, settings, negation, modality, and uncertainty.

    When one statement contains distinct claims that can stand separately,
    separate them. This task records what the source states; interpretation
    for a Perspective is done separately.
    """

    question: str = dspy.InputField()
    title: str = dspy.InputField()
    passage: str = dspy.InputField()

    observations: list[str] = dspy.OutputField()
