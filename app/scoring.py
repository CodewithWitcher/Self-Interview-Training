"""Constants and pure functions for scores, the review schedule and readiness (PS 7, PS 12).

Rounding is always half up. Python's round() rounds half to even and is never used here.
"""

from collections.abc import Iterable, Mapping

MAX_FOLLOW_UPS = 2
PASS_SCORE = 75
REPEAT_SCORE = 50
SRS_LADDER_DAYS = (1, 3, 7, 14)
DIMENSIONS = ("correctness", "depth", "clarity", "structure")
KIND_WEIGHTS = {
    "technical": (40, 30, 15, 15),
    "behavioral": (20, 30, 20, 30),
    "resume_probe": (30, 35, 20, 15),
}
CORRECTNESS_CAPS = {0: 20, 1: 45}
READINESS_WINDOW = 20
READINESS_HALF_LIFE_DAYS = 14
READINESS_FULL_COVERAGE = 5
RETRIEVE_K = 4
RETRIEVE_MIN_COSINE = 0.25
DEDUPE_COSINE = 0.82
QUESTIONS_PER_CALL = 5


def answer_score(kind: str, correctness: int, depth: int, clarity: int, structure: int) -> int:
    values = (correctness, depth, clarity, structure)
    if any(v not in (0, 1, 2, 3, 4) for v in values):
        raise ValueError("dimension values run from 0 to 4")
    raw = sum(w * v for w, v in zip(KIND_WEIGHTS[kind], values, strict=True))
    score = (raw + 2) // 4
    cap = CORRECTNESS_CAPS.get(correctness)
    if cap is not None:
        score = min(score, cap)
    return score


def mean_half_up(scores: Iterable[int]) -> int:
    values = list(scores)
    if not values:
        raise ValueError("no scores")
    n = len(values)
    return (2 * sum(values) + n) // (2 * n)


def attempt_score(scores: Iterable[int]) -> int:
    return mean_half_up(scores)


def weakest_dimension(turns: Iterable[Mapping]) -> str | None:
    """The dimension with the lowest average over scored, non-skipped turns.

    Each turn maps s_correctness, s_depth, s_clarity, s_structure, score and skipped.
    Ties go to the first in DIMENSIONS. None when no turn is in scope.
    """
    totals = [0, 0, 0, 0]
    count = 0
    for turn in turns:
        if turn["skipped"] or turn["score"] is None:
            continue
        for i, name in enumerate(DIMENSIONS):
            totals[i] += turn[f"s_{name}"]
        count += 1
    if count == 0:
        return None
    lowest = min(totals)
    return DIMENSIONS[totals.index(lowest)]
