import pytest

from app.scoring import answer_score, attempt_score, weakest_dimension


@pytest.mark.parametrize(
    ("kind", "dims", "score"),
    [
        ("technical", (3, 2, 4, 3), 71),
        ("technical", (0, 4, 4, 4), 20),
        ("technical", (1, 3, 3, 3), 45),
        ("behavioral", (4, 3, 3, 4), 88),
        ("resume_probe", (2, 2, 3, 3), 59),
        ("technical", (4, 4, 4, 4), 100),
        ("behavioral", (4, 4, 4, 4), 100),
        ("resume_probe", (4, 4, 4, 4), 100),
    ],
)
def test_answer_score_table(kind, dims, score):
    assert answer_score(kind, *dims) == score


def test_fake_tag_scores_for_every_kind():
    for kind in ("technical", "behavioral", "resume_probe"):
        assert answer_score(kind, 3, 3, 3, 3) == 75
        assert answer_score(kind, 4, 4, 4, 4) == 100
        assert answer_score(kind, 1, 1, 1, 1) == 25
        assert answer_score(kind, 0, 3, 3, 3) == 20


def test_answer_score_rounds_half_up():
    # raw 2 gives 0.5, which rounds up to 1. round() would give 0.
    assert answer_score("technical", 2, 0, 0, 0) == 20
    assert answer_score("behavioral", 0, 0, 0, 0) == 0


def test_answer_score_rejects_out_of_range():
    with pytest.raises(ValueError):
        answer_score("technical", 5, 0, 0, 0)


@pytest.mark.parametrize(
    ("scores", "mean"), [((71, 55, 80), 69), ((75, 74), 75), ((88,), 88), ((0, 1), 1)]
)
def test_attempt_score_table(scores, mean):
    assert attempt_score(scores) == mean


def turn(c, d, cl, s, skipped=0, score=50):
    return {
        "s_correctness": c,
        "s_depth": d,
        "s_clarity": cl,
        "s_structure": s,
        "skipped": skipped,
        "score": score,
    }


def test_weakest_dimension_lowest_average():
    assert weakest_dimension([turn(3, 1, 3, 3), turn(3, 2, 3, 3)]) == "depth"


def test_weakest_dimension_tie_goes_to_first():
    assert weakest_dimension([turn(3, 2, 3, 2)]) == "depth"
    assert weakest_dimension([turn(2, 2, 2, 2)]) == "correctness"


def test_weakest_dimension_ignores_skipped_and_unscored():
    turns = [turn(0, 0, 0, 0, skipped=1, score=0), turn(1, 1, 1, 1, score=None), turn(4, 4, 3, 4)]
    assert weakest_dimension(turns) == "clarity"


def test_weakest_dimension_empty():
    assert weakest_dimension([]) is None
    assert weakest_dimension([turn(0, 0, 0, 0, skipped=1, score=0)]) is None
