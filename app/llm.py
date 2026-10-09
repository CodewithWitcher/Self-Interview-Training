"""The model layer: one function, two providers and a fake (AR 7)."""

import itertools
import json
import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass

import anthropic
import httpx
from pydantic import BaseModel, ValidationError

from app.config import Settings
from app.prompts import Evaluation, NewQuestion, Ping, Plan, PlanTopic, QuestionBatch

log = logging.getLogger(__name__)

CLAUDE_MODELS = ("claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5")
CLAUDE_MAX_TOKENS = 16000
CLAUDE_BETAS = ["server-side-fallback-2026-07-01"]
OLLAMA_NUM_PREDICT = 3000
OLLAMA_TAGS_TIMEOUT_S = 3.0

# Tests replace this with an httpx.MockTransport.
http_transport: httpx.BaseTransport | None = None


class LLMError(Exception):
    """A model call failed. str(error) is safe to show to the user."""

    title = "The model call failed"


class LLMUnavailable(LLMError):
    title = "The model could not be reached"


class LLMOutputError(LLMError):
    title = "The model returned an unusable reply"


class LLMRefused(LLMError):
    title = "The cloud model declined this request"


class InvalidReply(ValueError):
    """Raised by a check function when a reply cannot be used. Triggers the one retry."""


@dataclass(frozen=True)
class ModelOption:
    provider: str
    model: str
    label: str
    is_local: bool

    @property
    def value(self) -> str:
        return f"{self.provider}:{self.model}"


def _http() -> httpx.Client:
    return httpx.Client(transport=http_transport)


# Ollama


def _ollama_tags(settings: Settings) -> list[dict]:
    with _http() as client:
        r = client.get(f"{settings.ollama_url}/api/tags", timeout=OLLAMA_TAGS_TIMEOUT_S)
        r.raise_for_status()
        return r.json().get("models", [])


def _ollama_capabilities(settings: Settings, model: str) -> list[str]:
    try:
        for entry in _ollama_tags(settings):
            if model in (entry.get("name"), entry.get("model")):
                return entry.get("capabilities") or []
    except (httpx.HTTPError, ValueError):
        pass
    return []


def ollama_request_body(
    settings: Settings, model: str, system: str, user: str, schema: type[BaseModel], creative: bool
) -> dict:
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
        "format": schema.model_json_schema(),
        "options": {
            "num_ctx": settings.ollama_num_ctx,
            "temperature": 0.8 if creative else 0,
            "num_predict": OLLAMA_NUM_PREDICT,
        },
    }
    if "thinking" in _ollama_capabilities(settings, model):
        body["think"] = False
    return body


def _ollama(settings, model, system, user, schema, creative) -> str:
    body = ollama_request_body(settings, model, system, user, schema, creative)
    try:
        with _http() as client:
            r = client.post(
                f"{settings.ollama_url}/api/chat", json=body, timeout=settings.llm_timeout_s
            )
    except httpx.TimeoutException:
        raise LLMUnavailable(
            f"Ollama did not answer within {settings.llm_timeout_s:g} seconds."
        ) from None
    except httpx.HTTPError:
        raise LLMUnavailable(f"Ollama is not running at {settings.ollama_url}.") from None
    if r.status_code == 404:
        raise LLMUnavailable(
            f"Ollama has no model named {model}. Pull it with: ollama pull {model}"
        )
    if r.status_code >= 400:
        raise LLMUnavailable(f"Ollama answered with HTTP status {r.status_code}.")
    try:
        data = r.json()
    except ValueError:
        raise LLMUnavailable("Ollama sent a reply that is not JSON.") from None
    prompt_tokens = data.get("prompt_eval_count") or 0
    log.info(
        "ollama reply: model=%s prompt_tokens=%s reply_tokens=%s duration_ms=%s",
        model,
        prompt_tokens,
        data.get("eval_count"),
        (data.get("total_duration") or 0) // 1_000_000,
    )
    if prompt_tokens > 0.9 * settings.ollama_num_ctx:
        log.warning("prompt used %s of %s context tokens", prompt_tokens, settings.ollama_num_ctx)
    if data.get("done_reason") == "length":
        raise LLMOutputError("The reply was cut off before it was complete.")
    return (data.get("message") or {}).get("content") or ""


# Claude


def _claude(settings, model, system, user, schema):
    client = anthropic.Anthropic(timeout=settings.llm_timeout_s, max_retries=1)
    try:
        response = client.beta.messages.parse(
            model=model,
            max_tokens=CLAUDE_MAX_TOKENS,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_format=schema,
            output_config={"effort": settings.anthropic_effort},
            betas=CLAUDE_BETAS,
            fallbacks="default",
        )
    except anthropic.APITimeoutError:
        raise LLMUnavailable(
            f"Claude did not answer within {settings.llm_timeout_s:g} seconds."
        ) from None
    except anthropic.APIConnectionError:
        raise LLMUnavailable("The Claude API could not be reached. Check the network.") from None
    except anthropic.AuthenticationError:
        raise LLMUnavailable("Claude rejected the credentials. Check ANTHROPIC_API_KEY.") from None
    except anthropic.PermissionDeniedError:
        raise LLMUnavailable("This Claude account may not use this model.") from None
    except anthropic.NotFoundError:
        raise LLMUnavailable(f"Claude has no model named {model}.") from None
    except anthropic.RateLimitError:
        raise LLMUnavailable("Claude's rate limit was reached. Wait a minute and retry.") from None
    except anthropic.APIStatusError as exc:
        raise LLMUnavailable(f"Claude answered with HTTP status {exc.status_code}.") from None
    except anthropic.AnthropicError as exc:
        # For example no credentials at all.
        raise LLMUnavailable(f"Claude could not be called: {exc.__class__.__name__}.") from None
    except ValidationError as exc:
        raise InvalidReply("reply failed validation") from exc
    usage = getattr(response, "usage", None)
    log.info(
        "claude reply: model=%s stop=%s input_tokens=%s output_tokens=%s",
        model,
        response.stop_reason,
        getattr(usage, "input_tokens", None),
        getattr(usage, "output_tokens", None),
    )
    if response.stop_reason == "refusal":
        raise LLMRefused("The cloud model declined this request.")
    if response.stop_reason == "max_tokens":
        raise LLMOutputError("The reply was cut off before it was complete.")
    parsed = response.parsed_output
    if parsed is None:
        raise InvalidReply("no parsed output")
    return parsed


# Fake


_fake_counter = itertools.count(1)

FAKE_PLAN_TOPICS = [
    ("Python", "technical", 5),
    ("SQL", "technical", 4),
    ("System design", "technical", 3),
    ("Testing", "technical", 2),
    ("Teamwork", "behavioral", 3),
    ("Ownership", "behavioral", 2),
]


def _tag_block(user: str, tag: str) -> str:
    match = re.search(rf"<{tag}>\n(.*?)\n</{tag}>", user, re.DOTALL)
    return match.group(1) if match else "none"


def _line_value(user: str, label: str) -> str:
    match = re.search(rf"^{label}: (.*)$", user, re.MULTILINE)
    return match.group(1).strip() if match else ""


def _fake_plan(user: str) -> Plan:
    has_jd = _tag_block(user, "job_description") != "none"
    topics = []
    for name, kind, weight in FAKE_PLAN_TOPICS:
        source = "both" if has_jd and name == "Python" else "resume"
        topics.append(
            PlanTopic(name=name, kind=kind, weight=weight, source=source, rationale=f"Fake {name}.")
        )
    if has_jd:
        topics.append(
            PlanTopic(
                name="Kubernetes", kind="technical", weight=4, source="jd", rationale="Fake gap."
            )
        )
    return Plan(summary="Fake plan", topics=topics)


def _fake_questions(user: str) -> QuestionBatch:
    topic = _line_value(user, "Topic")
    kind = _line_value(user, "Kind")
    n = int(_line_value(user, "Number of questions") or 1)
    questions = []
    for position in range(1, n + 1):
        k = next(_fake_counter)
        words = " ".join(f"w{k}x{i}" for i in range(6))
        questions.append(
            NewQuestion(
                text=f"Fake {topic} question {k}: {words}",
                source=position if kind == "resume_probe" else 0,
                key_points=[f"Fake key point {i}" for i in (1, 2, 3)],
                reference_answer=f"Fake reference answer {k}.",
            )
        )
    return QuestionBatch(questions=questions)


def _fake_evaluation(user: str) -> Evaluation:
    answer = _tag_block(user, "answer")
    if "#invalid" in answer:
        raise LLMOutputError("The fake model was told to fail (#invalid).")
    if "#down" in answer:
        raise LLMUnavailable("The fake model was told to be unreachable (#down).")
    dims = [3, 3, 3, 3]
    if "#strong" in answer:
        dims = [4, 4, 4, 4]
    elif "#weak" in answer:
        dims = [1, 1, 1, 1]
    elif "#wrong" in answer:
        dims = [0, 3, 3, 3]
    left = int(_line_value(user, "follow_ups_left") or 0)
    follow_up = "Fake follow-up: tell me more." if "#followup" in answer and left > 0 else ""
    return Evaluation(
        strengths=["Fake strength."],
        gaps=["Fake gap."],
        key_points_hit=[1],
        correctness=dims[0],
        depth=dims[1],
        clarity=dims[2],
        structure=dims[3],
        feedback="Fake feedback. Add one concrete example.",
        follow_up=follow_up,
    )


def _fake[T: BaseModel](user: str, schema: type[T]) -> T:
    if schema is Ping:
        return Ping(ok=True)
    if schema is Plan:
        return _fake_plan(user)
    if schema is QuestionBatch:
        return _fake_questions(user)
    if schema is Evaluation:
        return _fake_evaluation(user)
    raise LLMOutputError(f"The fake model cannot produce {schema.__name__}.")


# Public


def chat[T: BaseModel](
    provider: str,
    model: str,
    system: str,
    user: str,
    schema: type[T],
    *,
    settings: Settings,
    creative: bool = False,
    check: Callable[[T], T] | None = None,
) -> T:
    """Return a validated instance of schema or raise an LLMError.

    check, when given, normalises the reply and raises InvalidReply when it cannot be used.
    An invalid reply is retried once (D6).
    """
    started = time.monotonic()
    for attempt in (1, 2):
        try:
            if provider == "fake":
                if not settings.dev_fake:
                    raise LLMUnavailable("The fake model is only available in fake mode.")
                reply = _fake(user, schema)
            elif provider == "ollama":
                text = _ollama(settings, model, system, user, schema, creative)
                try:
                    reply = schema.model_validate_json(text)
                except ValidationError as exc:
                    raise InvalidReply("reply failed validation") from exc
            elif provider == "anthropic":
                reply = _claude(settings, model, system, user, schema)
            else:
                raise LLMUnavailable(f"Unknown provider {provider}.")
            if check is not None:
                reply = check(reply)
        except InvalidReply:
            log.warning("invalid reply from %s:%s, attempt %s", provider, model, attempt)
            continue
        log.info(
            "model call ok: provider=%s schema=%s ms=%s",
            provider,
            schema.__name__,
            int((time.monotonic() - started) * 1000),
        )
        return reply
    raise LLMOutputError("The model's reply did not match the expected format twice.")


def list_models(settings: Settings) -> list[ModelOption]:
    if settings.dev_fake:
        return [ModelOption("fake", "fake", "Fake model: nothing is called", True)]
    options = []
    try:
        entries = _ollama_tags(settings)
    except (httpx.HTTPError, ValueError):
        entries = []
    for entry in entries:
        if "remote_host" in entry:
            continue  # F9.3: runs on a remote host, so it is not local
        name = entry.get("name") or entry.get("model")
        if name:
            options.append(ModelOption("ollama", name, f"Local: {name}", True))
    options.sort(key=lambda o: o.model)
    suffix = "" if settings.anthropic_api_key else " (no API key found)"
    options += [ModelOption("anthropic", m, f"Cloud: {m}{suffix}", False) for m in CLAUDE_MODELS]
    if settings.anthropic_model not in CLAUDE_MODELS:
        m = settings.anthropic_model
        options.append(ModelOption("anthropic", m, f"Cloud: {m}{suffix}", False))
    return options


def json_dump(model: BaseModel) -> str:
    return json.dumps(model.model_dump(), ensure_ascii=False)
