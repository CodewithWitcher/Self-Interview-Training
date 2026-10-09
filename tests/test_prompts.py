import pytest
from pydantic import ValidationError

from app import prompts
from app.prompts import Evaluation, evaluation_prompt, plan_prompt, questions_prompt


def blocks(text):
    import re

    return dict(re.findall(r"<(\w+)>\n(.*?)\n</\1>", text, re.DOTALL))


def test_plan_prompt_blocks_and_none():
    system, user = plan_prompt("My resume", None, [])
    assert system.startswith("You are an interview preparation planner.")
    b = blocks(user)
    assert b == {"resume": "My resume", "job_description": "none"}
    assert user.rstrip().endswith("Existing topic names: none")


def test_plan_prompt_lists_at_most_30_names():
    names = [f"Topic {i}" for i in range(40)]
    _, user = plan_prompt("r", "jd text", names)
    assert "Topic 29" in user and "Topic 30" not in user
    assert blocks(user)["job_description"] == "jd text"


def test_questions_prompt_blocks_and_none():
    system, user = questions_prompt("Python", "technical", "easy", 3, "", [], [])
    assert system.startswith("You are an experienced interviewer writing questions")
    assert user.startswith(
        "Topic: Python\nKind: technical\nDifficulty: easy\nNumber of questions: 3\n"
    )
    assert blocks(user) == {"requirement": "none", "excerpts": "none", "already_asked": "none"}


def test_questions_prompt_numbers_excerpts():
    _, user = questions_prompt(
        "P", "resume_probe", "hard", 2, "why", ["one", "two"], ["Q1?", "Q2?"]
    )
    b = blocks(user)
    assert b["excerpts"] == "[1] one\n[2] two"
    assert b["already_asked"] == "- Q1?\n- Q2?"
    assert b["requirement"] == "why"


def test_already_asked_is_limited():
    many = [f"question {i:02d} " + "x" * 90 for i in range(30)]
    kept = prompts.limit_asked(many)
    assert len(kept) == 20
    long = ["y" * 1500] * 5
    assert len(prompts.limit_asked(long)) == 2


def test_evaluation_prompt_blocks_and_none():
    system, user = evaluation_prompt("technical", 0, "Q?", [], None, [], [], "Q?", "A")
    assert system.startswith("You are a fair, demanding interviewer")
    assert user.startswith("Kind: technical\nfollow_ups_left: 0\n")
    assert blocks(user) == {
        "question": "Q?",
        "key_points": "none",
        "reference_answer": "none",
        "resume_excerpt": "none",
        "earlier_turns": "none",
        "current_prompt": "Q?",
        "answer": "A",
    }


def test_evaluation_prompt_formats_lists():
    _, user = evaluation_prompt(
        "behavioral", 1, "Q?", ["a", "b"], "ref", ["ex1", "ex2"], [("Q?", "A1")], "F?", "A2"
    )
    b = blocks(user)
    assert b["key_points"] == "1. a\n2. b"
    assert b["earlier_turns"] == "Interviewer: Q?\nCandidate: A1"
    assert b["resume_excerpt"] == "ex1\nex2"


def test_evaluation_lists_evidence_before_scores():
    fields = list(Evaluation.model_fields)
    assert fields.index("strengths") < fields.index("correctness")
    assert fields.index("gaps") < fields.index("correctness")
    schema_order = list(Evaluation.model_json_schema()["properties"])
    assert schema_order.index("gaps") < schema_order.index("correctness")


def valid_eval(**over):
    data = {
        "strengths": [],
        "gaps": [],
        "key_points_hit": [],
        "correctness": 3,
        "depth": 3,
        "clarity": 3,
        "structure": 3,
        "feedback": "f",
        "follow_up": "",
    }
    data.update(over)
    return data


def test_score_of_5_fails_validation():
    Evaluation.model_validate(valid_eval())
    with pytest.raises(ValidationError):
        Evaluation.model_validate(valid_eval(depth=5))


def test_plan_prompt_fits_budget():
    names = [f"{i:02d}" + "n" * 58 for i in range(30)]
    _, user = plan_prompt("r" * 12_000, "j" * 6_000, names)
    assert len(prompts.PLAN_SYSTEM) + len(user) <= 22_000


def test_questions_prompt_fits_budget():
    asked = ["q" * 199] * 20
    _, user = questions_prompt(
        "t" * 60, "resume_probe", "medium", 5, "r" * 300, ["e" * 800] * 5, asked
    )
    assert len(prompts.QUESTIONS_SYSTEM) + len(user) <= 11_000


def test_evaluation_prompt_fits_budget():
    _, user = evaluation_prompt(
        "resume_probe",
        0,
        "q" * 600,
        [],
        None,
        ["e" * 800] * 2,
        [("q" * 600, "a" * 5000), ("f" * 400, "a" * 5000)],
        "f" * 400,
        "a" * 5000,
    )
    assert len(prompts.EVALUATION_SYSTEM) + len(user) <= 23_000
