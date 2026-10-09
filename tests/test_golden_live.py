"""The golden set of PS 11, scored by the configured model through the app's prompt path.

uv run pytest -m live -s
"""

import json

import pytest

from app import llm
from app.config import load_settings
from app.evaluation import normalise_evaluation
from app.prompts import Evaluation, evaluation_prompt
from app.scoring import MAX_FOLLOW_UPS, answer_score
from tests.helpers import FIXTURES


def score(settings, provider, model, question, answer):
    # PS 11 gives no reference answer for these questions, so the block says none.
    system, user = evaluation_prompt(
        question["kind"],
        MAX_FOLLOW_UPS,
        question["text"],
        question["key_points"],
        None,
        [],
        [],
        question["text"],
        answer,
    )
    e = llm.chat(
        provider,
        model,
        system,
        user,
        Evaluation,
        settings=settings,
        check=lambda r: normalise_evaluation(r, 0, len(question["key_points"])),
    )
    return answer_score(question["kind"], e.correctness, e.depth, e.clarity, e.structure), e


@pytest.mark.live
def test_golden_set():
    settings = load_settings()
    provider = settings.default_provider
    model = settings.ollama_model if provider == "ollama" else settings.anthropic_model
    data = json.loads((FIXTURES / "golden_answers.json").read_text(encoding="utf-8"))
    scores = {}
    failures = []
    for item in data["answers"]:
        question = data["questions"][item["question"]]
        try:
            scores[item["id"]], e = score(settings, provider, model, question, item["text"])
        except llm.LLMError as exc:  # Rule 4: no call may fail validation.
            failures.append(f"{item['id']}: {exc.title}")
            continue
        dims = (e.correctness, e.depth, e.clarity, e.structure)
        print(f"{item['id']}  {scores[item['id']]:>3}  dims={dims}")
    print(f"model {provider}:{model}")
    assert not failures, failures
    s = scores
    rules = {
        "A1 >= 70": s["A1"] >= 70,
        "A3 < A2 < A1": s["A3"] < s["A2"] < s["A1"],
        "A3 <= 45": s["A3"] <= 45,
        "B1 >= 70": s["B1"] >= 70,
        "B2 <= 45": s["B2"] <= 45,
        "B3 <= 45": s["B3"] <= 45,
        "A1 >= A2 + 15": s["A1"] >= s["A2"] + 15,
        "B1 >= B2 + 15 and B3 + 15": s["B1"] >= s["B2"] + 15 and s["B1"] >= s["B3"] + 15,
    }
    failed = [name for name, ok in rules.items() if not ok]
    assert not failed, f"failed rules: {failed}, scores: {scores}"
