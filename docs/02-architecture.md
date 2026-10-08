# Architecture and decisions

Status: draft 1, written 2026-10-08. Every decision in section 2 is **Assumed** until the owner confirms it. Facts marked "verified" were checked on the Windows reference machine on 2026-10-08. The evidence is in the [setup guide](05-setup-guide.md), section 9.

Related documents: [product requirements](01-product-requirements.md), [data model](03-data-model.md), [prompts and scoring](04-prompts-and-scoring.md), [setup guide](05-setup-guide.md), [task breakdown](06-task-breakdown.md).

## 1. Overview

One Python process serves a server-rendered web app on the loopback address. All user data lives in one SQLite file. Models are reached through one function with two providers.

```
Browser (Chrome, Edge, Safari)
   |  HTML forms and one small script        http://127.0.0.1:8000
   v
FastAPI app, one Python process
   |- routes/       pages and form handlers, rendered with Jinja2
   |- plan, questions, sessions, evaluation      the practice loop
   |- scoring       pure functions: scores, review schedule, readiness
   |- llm           one function, two providers --> Ollama, 127.0.0.1:11434 (local)
   |                                            \-> Claude API (cloud, optional)
   |- embeddings    MiniLM on ONNX Runtime, vectors stored in SQLite
   |- voice (M3)    faster-whisper on the CPU
   \- db            data/app.db, the only store of user data
```

Startup sequence:

1. Load `.env` and build the settings object.
2. Create the data folder if it is missing.
3. Apply pending database migrations.
4. Embed any stored text whose embedding is missing. Skip this step, without failing, when the embedding model is not downloaded.
5. Start serving.

## 2. Decision records

Each record gives the decision, the reason, and the point at which to revisit it.

### D1. Server-rendered HTML, no JavaScript framework

- **Decision:** FastAPI renders Jinja2 templates. Every action is an HTML form post followed by a redirect. One stylesheet and one small script for busy states. No Node, no build step.
- **Why:** One language, one process, one test runner. Every flow is testable with FastAPI's test client. The URL is the state, so session resume and browser refresh work by construction.
- **Differs from the idea file**, which suggested React or Next.js, or Tauri.
- **Revisit when** a screen must update without reloading. Hands-free voice is the first candidate.

### D2. One SQLite file, plain SQL

- **Decision:** The standard library `sqlite3` module, no ORM. Numbered `.sql` migration files applied with `PRAGMA user_version`.
- **Why:** Seven tables. One file to back up or delete.
- **Revisit when** queries are being assembled dynamically in many places.

### D3. Embeddings stored in SQLite and searched with NumPy

- **Decision:** Vectors are stored as BLOB columns. Search is a matrix product over the profile's vectors.
- **Why:** A profile has tens of resume chunks and hundreds of questions. Brute force over that is instant. One store means deleting a profile is one cascade and nothing can drift out of sync.
- **Differs from the idea file**, which suggested ChromaDB or FAISS.
- **Revisit when** a profile exceeds about 50,000 vectors.

### D4. Embedding model all-MiniLM-L6-v2, run with fastembed

- **Decision:** `sentence-transformers/all-MiniLM-L6-v2` through the `fastembed` library.
- **Why:** It is the model the idea file names. fastembed runs it on ONNX Runtime, so PyTorch is not installed.
- **Verified:** 384 dimensions, vectors arrive normalised, 87 MB on disk, loads offline in under a second. Input beyond 256 tokens is ignored by the model, so chunks stay at 800 characters or fewer.
- **Revisit when** retrieval quality is poor. Changing the model means re-embedding, see the [data model](03-data-model.md), section 6.

### D5. Two model providers: Ollama and Claude

- **Decision:** Ollama through its native HTTP API with `httpx`. Claude through the official `anthropic` SDK.
- **Why the native Ollama API:** It lets each request set the context window. Ollama's documentation gives a default window of 4,096 tokens on machines with less than 24 GB of video memory. The plan prompt can exceed that, and overflow is cut silently.
- **Why Claude as the only cloud provider:** One cloud path to verify on two systems. See product decision P4.
- **Revisit when** a third provider is wanted. It is one more function in `llm.py`.

### D6. Every model reply is schema-constrained JSON, validated, and retried once

- **Decision:** Each call passes a JSON schema to the provider's structured output feature. The reply is validated with Pydantic. One retry on invalid output, then an error the user can act on.
- **Why:** Small local models drift from a format that is only described in prose.

### D7. Configuration and secrets in `.env`

- **Decision:** `python-dotenv` loads `.env` into the process environment at startup. Real environment variables win. Nothing secret is stored in the database.
- **Ceiling:** A plain text file. Move to the operating system keychain if the app is ever packaged.

### D8. All user data in `./data`

- **Decision:** `data/app.db` and `data/models/`, inside the repository folder and ignored by git. `SIT_DATA_DIR` overrides the location.
- **Why:** The same on both systems, easy to find, easy to delete.

### D9. One resume and at most one job description per profile

- **Decision:** Both are columns on the `profiles` table. See product decision P3.

### D10. PDF text with pypdf, followed by human review

- **Decision:** `pypdf` extracts text. The user reviews and corrects it before saving (F2.2).
- **Why:** pypdf is pure Python, so it installs identically everywhere. Layout problems are solved by the review step, not by a heavier parser.
- **Revisit when** users report that review takes too long.

### D11. Voice: faster-whisper on the CPU, record then transcribe, browser speech synthesis

- **Decision:** The browser records with `MediaRecorder` and uploads the clip. The server transcribes it with `faster-whisper`, model `base.en`, on the CPU. Questions are read aloud with the browser's `speechSynthesis`.
- **Why:** CTranslate2, the engine under faster-whisper, has no GPU backend for Macs. Its README lists Apple Accelerate, a CPU library, and no Metal support. The CPU is fast enough, so both systems share one code path.
- **Verified on Windows:** a 12 second WebM/Opus clip transcribes in 1.3 seconds on a 4-core laptop CPU. Browser audio bytes are decoded without a system FFmpeg, because PyAV bundles its own. `av` must stay below version 19, see the [setup guide](05-setup-guide.md), section 7.
- **Differs from the idea file**, which suggested Piper and streaming voice activity detection.
- **Revisit when** hands-free conversation is wanted.

### D12. Python 3.13 managed by uv, two environments in one lockfile

- **Decision:** `uv` installs Python 3.13 and all dependencies. `pyproject.toml` restricts resolution to Windows x64 and macOS on Apple Silicon. The project is not packaged, it runs from the repository root.
- **Verified:** The dependency list resolves to prebuilt wheels on both systems for Python 3.13. On Python 3.14 it does not resolve for macOS 13. The locked ONNX Runtime wheel is tagged macOS 14, which sets the minimum macOS version.
- **Revisit when** Python 3.13 nears end of support.

### D13. Three test tiers

- **Decision:** Default tests use a fake model and a fake embedder and need no network. Tests marked `models` use the real embedding and speech models. Tests marked `live` use a real language model. Section 11 has the details.
- **Why:** The default tier runs in seconds on both systems in CI. The `models` tier proves the native libraries on a Mac without owning one.

### D14. Run from a clone, no installer

- **Decision:** The user installs uv and Ollama, clones the repository and runs one command. See product decision P6.

## 3. Folder layout

```
.
|- CLAUDE.md
|- README.md
|- pyproject.toml
|- uv.lock
|- .python-version              3.13
|- .env.example
|- .gitignore                   data/  .env  .venv/  __pycache__/
|- .gitattributes               * text=auto eol=lf
|- .github/workflows/ci.yml
|- docs/                        these documents
|- app/
|  |- __init__.py
|  |- __main__.py               python -m app
|  |- main.py                   create_app(), middleware, error pages, startup
|  |- config.py
|  |- db.py
|  |- migrations/               001_init.sql  (002_voice.sql in M3)
|  |- health.py                 python -m app.health
|  |- fetch_models.py           python -m app.fetch_models
|  |- llm.py
|  |- prompts.py
|  |- embeddings.py
|  |- resume.py
|  |- plan.py
|  |- questions.py
|  |- sessions.py
|  |- evaluation.py
|  |- scoring.py
|  |- voice.py                  M3
|  |- routes/                   profiles.py resume.py plan.py sessions.py progress.py status.py voice.py
|  |- templates/                base.html home.html profile.html resume.html plan.html
|  |                            attempt.html summary.html progress.html status.html error.html
|  \- static/                   app.css app.js voice.js
|- tests/
|  |- conftest.py
|  |- fixtures/                 sample_resume.txt sample_resume.pdf sample_jd.txt
|  |                            golden_answers.json speech_sample.webm
|  \- test_*.py                 one file per app module
\- data/                        created at run time, never committed
   |- app.db
   \- models/                   fastembed/  whisper/
```

## 4. Modules

Route handlers validate input and call these modules. SQL lives in these modules, never in templates or route handlers.

| Module | Responsibility | Public functions |
|---|---|---|
| `config.py` | Settings from the environment | `Settings`, `load_settings()` |
| `db.py` | Connections, migrations, timestamps | `connect(path)`, `migrate(conn)`, `get_db` (request dependency), `utc_now()` |
| `main.py` | App factory, security middleware, error pages, startup | `create_app(settings=None)` |
| `health.py` | Environment checks for the status page and the command line | `run_checks(settings)`, `main()` |
| `fetch_models.py` | Downloads model files into `data/models/` | `main()` |
| `llm.py` | The model layer, section 7 | `chat(...)`, `list_models(settings)`, `LLMError` and subclasses |
| `prompts.py` | Reply schemas and prompt builders | `Plan`, `QuestionBatch`, `Evaluation`, `plan_prompt(...)`, `questions_prompt(...)`, `evaluation_prompt(...)` |
| `embeddings.py` | Embedding and similarity | `embed(texts)`, `to_blob(vec)`, `from_blob(blob)`, `top_k(query, vectors, k)`, `backfill(conn)` |
| `resume.py` | Text extraction, chunking, saving | `extract_text(filename, data)`, `chunk_text(text)`, `save_resume(conn, profile_id, text, name)` |
| `plan.py` | Building and updating the plan | `build_plan(conn, profile_id, provider, model)`, `normalise_plan(plan, has_jd)` |
| `questions.py` | Generating and de-duplicating questions | `generate(conn, topic, n, difficulty, provider, model, rng)`, `drop_duplicates(candidates, existing)` |
| `sessions.py` | Session life cycle | `compose(...)`, `start(...)`, `current_attempt(conn, session_id)`, `finish_attempt(conn, attempt_id, today)`, `end(conn, session_id, today)` |
| `evaluation.py` | Scoring one turn | `evaluate_turn(conn, turn_id, settings)` |
| `scoring.py` | Constants and pure functions | `answer_score`, `attempt_score`, `srs_next`, `topic_score`, `readiness`, `weakest_dimension` |
| `voice.py` (M3) | Transcription and delivery metrics | `transcribe(data)`, `delivery_metrics(segments, text)` |

## 5. Routes

Every route returns a full HTML page or a redirect, except the audio route, which returns JSON. Form posts answer with `303 See Other`. Every route under `/profiles/{pid}` first loads the profile. A session, attempt or topic that belongs to another profile is a 404.

| Method | Path | Purpose |
|---|---|---|
| GET | `/` | Profile list and create form |
| POST | `/profiles` | Create a profile |
| GET | `/profiles/{pid}` | Profile home with the start form |
| POST | `/profiles/{pid}/delete` | Delete the profile. Form field `confirm` must equal the profile name. |
| GET | `/profiles/{pid}/resume` | Resume page |
| POST | `/profiles/{pid}/resume/extract` | Take a file or pasted text and show it for review. Saves nothing. |
| POST | `/profiles/{pid}/resume` | Save the reviewed text, chunk it, embed it |
| GET | `/profiles/{pid}/plan` | Plan page |
| POST | `/profiles/{pid}/plan/build` | Build or rebuild the plan |
| POST | `/profiles/{pid}/topics` | Add a topic by name and kind |
| POST | `/profiles/{pid}/topics/{tid}` | Set a topic's weight |
| POST | `/profiles/{pid}/jd` | Save or clear the job description (M2) |
| POST | `/profiles/{pid}/sessions` | Start a session |
| GET | `/profiles/{pid}/sessions/{sid}` | Redirect to the current attempt, or to the summary |
| GET | `/profiles/{pid}/sessions/{sid}/attempts/{aid}` | Question page: thread, answer form, feedback |
| POST | `/profiles/{pid}/sessions/{sid}/attempts/{aid}/answer` | Submit an answer |
| POST | `/profiles/{pid}/sessions/{sid}/attempts/{aid}/evaluate` | Retry scoring of a saved answer |
| POST | `/profiles/{pid}/sessions/{sid}/attempts/{aid}/skip` | Skip the current turn |
| POST | `/profiles/{pid}/sessions/{sid}/attempts/{aid}/audio` | Upload a recording, get a transcript as JSON (M3) |
| POST | `/profiles/{pid}/sessions/{sid}/model` | Change the session's provider and model |
| POST | `/profiles/{pid}/sessions/{sid}/end` | End the session early |
| GET | `/profiles/{pid}/sessions/{sid}/summary` | Session summary |
| GET | `/profiles/{pid}/progress` | Readiness and history (M2) |
| GET | `/status` | Environment checks |
| POST | `/status/test` | Run a tiny prompt against a chosen model |

GET requests never change data.

## 6. Key flows

### 6.1 Submit an answer

`POST /profiles/{pid}/sessions/{sid}/attempts/{aid}/answer`

1. Load the profile, session, attempt and current turn. The current turn is the attempt's turn that has no answer. If there is none, which happens on a double submit, redirect to the question page.
2. Validate the text: 1 to 5,000 characters after trimming. On failure render the question page again with status 422 and the text preserved.
3. Transaction 1: store the answer text and time, set the attempt to `active`, commit.
4. Call `evaluation.evaluate_turn`. It builds the prompt, calls `llm.chat`, and computes the answer score.
5. On `LLMError`, redirect to the question page with an error code in the query string. The turn stays answered and unscored. The page shows Retry and Change model.
6. Transaction 2: store the scores and the evaluation. Then either insert the follow-up turn at the next level, or finish the attempt. Finishing sets the attempt score, marks it `done`, updates the question's review schedule, and marks the session `completed` when no unfinished attempt remains. Commit.
7. Redirect to the question page.

`.../evaluate` repeats steps 4 to 7 for an answered, unscored turn. `.../skip` stores an empty answer with `skipped = 1`, a score of 0 and all dimensions 0, then finishes the attempt as in step 6 without a follow-up.

No database transaction is open while a model call runs.

### 6.2 Start a session

`POST /profiles/{pid}/sessions`

1. Validate the form. If the profile already has an active session, redirect to it.
2. Compose the question list by the rules in [prompts and scoring](04-prompts-and-scoring.md), section 6. Each batch of newly generated questions is saved to the question bank as soon as it validates, in its own transaction.
3. A topic whose generation fails is left out, with a notice. If no question is available at all, render the profile home with the reason and create nothing.
4. One transaction inserts the session, one attempt per question in order, and a level 0 turn for each attempt whose prompt is the question text.
5. Redirect to `/profiles/{pid}/sessions/{sid}`.

### 6.3 Open or resume a session

`GET /profiles/{pid}/sessions/{sid}` redirects to the summary when the session is completed. Otherwise it redirects to the first attempt, by position, that is not `done`.

The question page renders from stored state alone:

| Stored state of the attempt | Page shows |
|---|---|
| Latest turn has no answer | The thread so far and the answer form |
| Latest turn has an answer and no score | The saved answer, the error, Retry and Change model |
| Attempt is `done` | The whole thread, the reference answer, and Next |

Next links to the session route above. The profile home links to it too while a session is active. That is the whole resume feature.

### 6.4 End a session early

`POST /profiles/{pid}/sessions/{sid}/end`, in one transaction:

1. For every attempt that is not `done`, delete its turns that have no score.
2. If the attempt still has scored turns, finish it with their average. Otherwise delete the attempt. Its question returns to the bank.
3. If the session has no attempts left, delete the session and redirect to the profile home. Otherwise mark it `completed` and redirect to the summary.

## 7. Model layer

### 7.1 Contract

```python
def chat(provider: str, model: str, system: str, user: str,
         schema: type[T], *, creative: bool = False) -> T: ...

def list_models(settings: Settings) -> list[ModelOption]: ...
# ModelOption: provider, model, label, is_local
```

`chat` returns a validated instance of `schema` or raises a subclass of `LLMError`. `creative=True` is used only for question generation. Callers never see provider details.

### 7.2 Ollama

`GET {SIT_OLLAMA_URL}/api/tags` lists models. An entry with a `remote_host` field runs on a remote host and is excluded (F9.3). This was observed on Ollama 0.35.1, where cloud-hosted entries carry `remote_host` and `remote_model`. Each entry also lists its `capabilities`.

`POST {SIT_OLLAMA_URL}/api/chat` with this body:

```json
{
  "model": "llama3.1:8b",
  "messages": [
    {"role": "system", "content": "..."},
    {"role": "user", "content": "..."}
  ],
  "stream": false,
  "format": {"type": "object", "properties": {}, "required": []},
  "options": {"num_ctx": 8192, "temperature": 0, "num_predict": 3000}
}
```

- `format` is `schema.model_json_schema()`.
- `num_ctx` comes from `SIT_OLLAMA_NUM_CTX`.
- `temperature` is 0, or 0.8 when `creative=True`.
- Add `"think": false` only when the model's capabilities include `thinking`.
- The reply text is `message.content`. A `done_reason` of `length` means the reply was cut off and raises `LLMOutputError`.
- Log the token counts and the duration that Ollama reports. Log a warning when the prompt token count exceeds 90% of `num_ctx`.

The request shape follows Ollama's API reference. It has not been exercised yet, because the reference machine has no local model pulled. Task T10 is the first live check.

### 7.3 Claude

```python
client = anthropic.Anthropic(timeout=settings.llm_timeout_s, max_retries=1)

response = client.beta.messages.parse(
    model=model,                                   # default "claude-opus-5-5"
    max_tokens=16000,
    system=system,
    messages=[{"role": "user", "content": user}],
    output_format=schema,                          # the Pydantic class
    output_config={"effort": settings.anthropic_effort},   # default "medium"
    betas=["server-side-fallback-2026-07-01"],
    fallbacks="default",
)
if response.stop_reason == "refusal":
    raise LLMRefused(...)
if response.stop_reason == "max_tokens":
    raise LLMOutputError(...)
return response.parsed_output
```

- Never send `temperature`, `top_p` or `top_k`. Current Claude models reject them.
- Never send a `thinking` parameter. Thinking is adaptive by default and is steered with `effort`.
- `fallbacks="default"` opts into Anthropic's server-side refusal fallback: a request declined by a safety classifier is retried on another Claude model inside the same call.
- Always check `stop_reason` before reading the output.
- The SDK finds credentials by itself: `ANTHROPIC_API_KEY`, or a login profile created with Anthropic's `ant` command line tool.
- The models offered in the start form are `claude-opus-5-5` (default), `claude-sonnet-5-5` and `claude-haiku-5-5`. They are always listed. When `ANTHROPIC_API_KEY` is not set, their label says that no key was found, because a login profile may still work.
- Verified against the signatures of `anthropic` 1.12.1: `beta.messages.parse` accepts `output_format`, `output_config`, `betas` and `fallbacks` together and merges the first two. No live call has been made yet.

### 7.4 Errors

| Class | Raised when | What the user is told |
|---|---|---|
| `LLMUnavailable` | Connection refused, timeout, HTTP 5xx, bad credentials, unknown model | "The model could not be reached", with the specific cause |
| `LLMOutputError` | The reply fails validation twice, or was cut off | "The model returned an unusable reply" |
| `LLMRefused` | Claude's `stop_reason` is `refusal` | "The cloud model declined this request" |

All three extend `LLMError`. Invalid output is retried once. Nothing else is retried by the app.

### 7.5 Context budget

Local models work inside `SIT_OLLAMA_NUM_CTX`, default 8,192 tokens. The input limits in the [data model](03-data-model.md), section 5, and the caps in [prompts and scoring](04-prompts-and-scoring.md), sections 3 to 5, are sized so that every prompt fits. The count assumes 3.3 characters per token, which is conservative for English.

| Prompt | Largest case | Character budget | Tokens with the reply |
|---|---|---|---|
| Plan | A 12,000 character resume, a 6,000 character job description, 30 existing topic names | 22,000 | 6,667 + 1,000 = 7,667 |
| Questions | Five excerpts of 800 characters and 4,000 characters of already asked questions | 11,000 | 3,333 + 3,000 = 6,333 |
| Evaluation | The second follow-up: three answers of 5,000 characters, the question, two follow-up prompts and two excerpts | 23,000 | 6,970 + 1,000 = 7,970 |

The worst cases measured against the prompt texts on 2026-10-08 were 21,393, 10,300 and 21,862 characters.

Input from the user is never cut silently. Text over a limit is rejected at the form with a message. Task T11 tests the three budgets.

### 7.6 Fake provider

With `SIT_DEV_FAKE=1` the only provider offered is one named `fake`, and embeddings come from a hashing embedder. The app then runs with no model at all and makes no model request. Its exact behaviour is defined in [prompts and scoring](04-prompts-and-scoring.md), section 10.

## 8. Configuration

All settings come from environment variables, optionally through `.env`. The full list is in the [setup guide](05-setup-guide.md), section 5.

`create_app()` builds one `Settings` object and stores it on `app.state.settings`. It also stores `app.state.today` (a callable returning today's local date) and `app.state.rng` (a `random.Random`). Code reads the date and random numbers only through these, so tests can fix them.

## 9. Security and privacy rules

These rules are binding. A change that breaks one is a defect.

1. The server binds to `127.0.0.1`. The host is not configurable.
2. A request whose `Host` header is not `127.0.0.1` or `localhost` is rejected with Starlette's `TrustedHostMiddleware`. This blocks DNS rebinding.
3. A POST is rejected with 403 when its `Origin` header is present and is neither `http://127.0.0.1:PORT` nor `http://localhost:PORT`, or when its `Sec-Fetch-Site` header is present and is neither `same-origin` nor `none`. `PORT` is the configured port. This blocks cross-site form posts.
4. Only POST changes data.
5. Templates autoescape. Text from users and from models is rendered as plain text. The `safe` filter is never applied to it. Markdown is not rendered.
6. SQL always uses parameters. Values are never formatted into SQL strings.
7. An upload is at most 5 MB and is read into memory. A PDF must start with `%PDF-`. A text file must decode as UTF-8. The uploaded file name is shown to the user and is never used as a path.
8. Resume, job description and answer text is untrusted input to the model. Prompts wrap it in tags and tell the model to treat it as data. Model output is validated JSON. It is never executed and never used as a path.
9. Secrets come from the environment only. They are never stored in the database, never logged, and never sent to the browser.
10. Logs never contain resume text, job description text, answers, prompts or model replies. They contain event names, ids, durations and token counts.
11. At run time the app makes no outbound request except to the selected model provider. Model files are loaded with `local_files_only=True`, and `HF_HUB_OFFLINE=1` is set at startup.
12. No script, font or stylesheet is loaded from the network.
13. Audio is processed in memory and never written to disk.
14. A session on a cloud model always shows the cloud badge (F9.2).

## 10. Error handling

| Situation | Behaviour |
|---|---|
| Invalid form input | The same page again, status 422, a message next to the field, the input preserved |
| Unknown id, or an id owned by another profile | The 404 page |
| `LLMError` | Never a 500. The page says what failed and offers Retry or Change model. |
| Embedding model missing | The action that needs it fails with a message naming the fetch command |
| Any other exception | The 500 page with a short error id. The traceback goes to the log only. |

## 11. Testing

| Tier | Marker | Needs | Runs |
|---|---|---|---|
| Default | none | Nothing. Fake model and fake embedder. | Every push, on Windows and Mac, in CI |
| Models | `models` | The files from `python -m app.fetch_models` | In CI on both systems after a cached download |
| Live | `live` | A running Ollama with a local model, or Claude credentials | By hand, on each machine |

Rules:

- `tests/conftest.py` builds the app with `create_app(Settings(...))`, using `SIT_DEV_FAKE=1` and a data folder under pytest's `tmp_path`.
- The test client is created with `base_url="http://127.0.0.1:8000"`, otherwise rule 2 of section 9 rejects every request.
- Tests set `app.state.today` and `app.state.rng` to fix the date and the random choices.
- Every database connection is closed before a test ends. On Windows an open connection blocks deletion of the temporary folder.
- `pytest` runs the default tier only. `pytest -m models` and `pytest -m live` select the others.
- Each task in the [task breakdown](06-task-breakdown.md) names the check that proves it.
