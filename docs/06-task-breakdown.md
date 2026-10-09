# Task breakdown

Status: draft 1, written 2026-10-08. 31 tasks in four milestones. No task has been started.

Specifications: [product requirements](01-product-requirements.md) (PR), [architecture](02-architecture.md) (AR), [data model](03-data-model.md) (DM), [prompts and scoring](04-prompts-and-scoring.md) (PS), [setup guide](05-setup-guide.md) (SG). A reference such as "PS 7.3" means section 7.3 of that document. "F5.6" means line 6 of feature F5 in the product requirements.

## 1. Rules for working through the tasks

1. Work top to bottom. Start a task only when every task it depends on is ticked.
2. One task is one commit. The commit message starts with the task id.
3. For a task with logic, write the test named in its check first and watch it fail. Then implement.
4. A task is done when the conditions in section 9 hold.
5. Use the specification as written. If it is wrong or unclear, correct the document in the same commit and say so in the commit message. Never deviate silently.
6. Build nothing from the non-goals in PR 7.
7. If a task is blocked on the owner, write the reason on its progress line and continue with the next task that does not depend on it.
8. Run every command from the repository root, one command per line.

## 2. Progress

Tick a line in the commit that completes the task.

M0, skeleton:

- [x] T01 Repository scaffold
- [x] T02 Settings
- [x] T03 Database
- [x] T04 Web shell and security
- [x] T05 Status page and health command
- [ ] T06 CI on Windows and Mac

M1, core loop:

- [x] T07 Profiles
- [x] T08 Embeddings
- [ ] T09 Resume intake
- [ ] T10 Model layer
- [ ] T11 Prompts and schemas
- [ ] T12 Scoring core
- [ ] T13 Fake provider
- [ ] T14 Prep plan
- [ ] T15 Question generation
- [ ] T16 Start a session
- [ ] T17 Answer, score, follow up
- [ ] T18 Finish, resume, end, summary
- [ ] T19 Status page, complete
- [ ] T20 Golden set
- [ ] T21 M1 smoke and README

M2, retention and targeting:

- [ ] T22 Job description mode
- [ ] T23 Spaced repetition
- [ ] T24 Readiness and progress
- [ ] T25 v1 hardening

M3, voice:

- [ ] T26 Voice dependencies and model
- [ ] T27 Transcription
- [ ] T28 Recorder in the browser
- [ ] T29 Delivery metrics on the page
- [ ] T30 Read aloud
- [ ] T31 M3 smoke

## 3. Needs the owner

An agent must not do these on its own.

| # | Item | Blocks |
|---|---|---|
| 1 | Confirm or change the Assumed decisions: P1 to P6 in PR 3 and D1 to D14 in AR 2 | Best settled before T01 |
| 2 | Create a GitHub repository and allow pushes to it | T06 |
| 3 | Allow `ollama pull llama3.1:8b`, a 4.9 GB download, on each machine | The live part of T10, T20, T21 |
| 4 | Provide a Claude API key, if cloud mode is to be verified | The cloud part of T10 and T20 |
| 5 | Provide a Mac session, or run the Mac checks yourself | The Mac half of T21, T25, T31 |
| 6 | Grant microphone permission in the browser | T28, T31 |

## 4. M0: skeleton

### T01 Repository scaffold

- **Depends on:** nothing
- **Spec:** AR 3, SG 4
- **Files:** `pyproject.toml`, `uv.lock`, `.python-version`, `.gitignore`, `.gitattributes`, `.env.example`, `README.md`, `app/__init__.py`
- **Build:** Run `git init` if the folder is not a repository. Use the project file from SG 4 unchanged. `.python-version` contains `3.13`. `.gitignore` covers `data/`, `.env`, `.venv/`, `__pycache__/`, `.pytest_cache/` and `.ruff_cache/`. `.gitattributes` contains `* text=auto eol=lf`. `.env.example` lists every variable of SG 5, commented out. The README says what the app is in three lines and links to the setup guide. Leave `Project Idea.md` and `document.md` untouched.
- **Check:** `uv sync` succeeds. `uv run python -c "import app"` exits with 0. `uv run ruff check .` passes. `git check-ignore data .env` prints both names.

### T02 Settings

- **Depends on:** T01
- **Spec:** SG 5, AR 8
- **Files:** `app/config.py`, `tests/test_config.py`
- **Build:** A frozen dataclass `Settings` with one field per variable in SG 5, plus `repo_root`. `load_settings()` loads `.env` from the repository root with `load_dotenv` and then reads the environment. Tests build `Settings` directly and never read the developer's `.env`. A relative `SIT_DATA_DIR` resolves against the repository root. An unknown provider or a non-numeric number raises an error that names the variable.
- **Check:** Tests: every default equals the table in SG 5. An environment variable beats `.env`. A data folder path that contains spaces resolves. `SIT_DEFAULT_PROVIDER=other` raises.

### T03 Database

- **Depends on:** T02
- **Spec:** DM 2, 3, 7, 8
- **Files:** `app/db.py`, `app/migrations/001_init.sql`, `tests/test_db.py`
- **Build:** Copy the schema block of DM 2 verbatim. Implement `connect`, `migrate` as in DM 8, `get_db` and `utc_now`.
- **Check:** Tests: a new database reaches version 1 with seven tables. A second `migrate` changes nothing. A failing migration leaves no trace. Each of invariants 1 to 6 in DM 3 raises `IntegrityError`. Deleting a profile leaves no row that refers to it. The temporary folder can be deleted when the test ends.

### T04 Web shell and security

- **Depends on:** T03
- **Spec:** AR 1, AR 5, AR 9 rules 1 to 5, AR 10, AR 11, the accessibility line of PR 8
- **Files:** `app/main.py`, `app/__main__.py`, `app/routes/profiles.py`, `app/templates/base.html`, `app/templates/home.html`, `app/templates/error.html`, `app/static/app.css`, `app/static/app.js`, `tests/conftest.py`, `tests/test_main.py`
- **Build:** `create_app(settings=None)` with the host check, the origin check, the startup sequence and the 404 and 500 pages. A base layout with a skip link, labelled navigation and visible focus. `app.js` does three things only: it disables the submit button and shows "Working..." on forms marked `data-busy`, it counts characters, and it asks for confirmation on forms marked `data-confirm`. Every page works without JavaScript. The `client` fixture follows AR 11.
- **Check:** Tests: `GET /` returns 200 and the empty state. A request with `Host: evil.example` returns 400. A POST with `Origin: http://evil.example` returns 403. A POST with `Sec-Fetch-Site: cross-site` returns 403. An unknown path returns the 404 page. An exception in a route returns the 500 page with no traceback in the body. By hand: `uv run python -m app` prints the address and the page loads.

### T05 Status page and health command

- **Depends on:** T04
- **Spec:** F10.1, F10.3, AR 4
- **Files:** `app/health.py`, `app/routes/status.py`, `app/templates/status.html`, `tests/test_health.py`
- **Build:** `run_checks(settings)` returns a list of `Check(name, required, ok, detail)`. Checks: Python version and platform, data folder writable, database version, `import anthropic` succeeds, embedding model present, Ollama reachable with its local models, Claude key present. The first four are required. The failure detail of the import check points to trap 1 in SG 7. `python -m app.health` prints one line per check in ASCII only and exits with 1 when a required check fails. In fake mode the model checks are reported as skipped.
- **Check:** Tests: the page lists every check. The command exits with 0 in a healthy fake setup. It exits with 1 when a file occupies the data folder path. Its output is ASCII only.

### T06 CI on Windows and Mac

- **Depends on:** T05, owner item 2
- **Spec:** AR 11, SG 9.1
- **Files:** `.github/workflows/ci.yml`
- **Build:** One job with a matrix of `windows-latest` and `macos-latest` and `fail-fast: false`. Steps: check out, install uv with the official `astral-sh/setup-uv` action, `uv sync --locked`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run pytest`. Look up the current major version of each action. Do not guess it. Print `uname -m` on the Mac runner and confirm it says `arm64`. From T08 on, add a cached `uv run python -m app.fetch_models` step and `uv run pytest -m models`.
- **Check:** Both jobs are green on the default branch. Add a row to the log in SG 9.3.

## 5. M1: core loop

### T07 Profiles

- **Depends on:** T04
- **Spec:** F1, DM 4, AR 5
- **Files:** `app/routes/profiles.py`, `app/templates/home.html`, `app/templates/profile.html`, `tests/test_profiles.py`
- **Build:** Create, list, the profile home with links to resume and plan, and delete with typed confirmation.
- **Check:** Tests: a created profile is listed. The same name in another letter case is rejected with a message and status 422. Delete with a wrong confirmation changes nothing. Delete with the right one removes the profile. An unknown profile id returns 404.

### T08 Embeddings

- **Depends on:** T03
- **Spec:** DM 6, PS 8.2, PS 10, decision D4, AR 9 rule 11
- **Files:** `app/embeddings.py`, `app/fetch_models.py`, `tests/test_embeddings.py`
- **Build:** `embed(texts)` returns an array of shape (n, 384). In fake mode it is the fake embedder. Otherwise it is fastembed with `cache_dir` set to `data/models/fastembed` and `local_files_only=True`, loaded once on first use. A missing model raises an error that names the fetch command. Also `to_blob`, `from_blob`, `top_k` and `backfill`. `fetch_models` downloads the embedding model. It runs outside `create_app`, so the offline setting of AR 9 rule 11 does not apply to it.
- **Check:** Default tests: fake vectors are deterministic and have length 1. A blob round trip is 1,536 bytes. `top_k` orders by similarity. `backfill` fills only NULL rows. `models` test: real vectors have shape (n, 384) and length 1, the query "Kafka and event streaming" ranks a Kafka sentence first, and loading works with `HF_HUB_OFFLINE=1`.

### T09 Resume intake

- **Depends on:** T07, T08
- **Spec:** F2, PS 8.1, DM 5, AR 9 rule 7
- **Files:** `app/resume.py`, `app/routes/resume.py`, `app/templates/resume.html`, `tests/fixtures/sample_resume.txt`, `tests/fixtures/sample_resume.pdf`, `tests/test_resume.py`
- **Build:** `extract_text` for PDF with pypdf, catching `pypdf.errors.PyPdfError` and treating `is_encrypted` as unreadable, and for text files in UTF-8 with or without a byte order mark. `chunk_text` exactly as PS 8.1. `save_resume` replaces text, chunks and embeddings in one transaction. The text fixture is a resume of more than 200 characters that mentions Python, SQL and Kafka. Create the PDF fixture once from the same lines with `uv run --with reportlab python`. Commit the PDF, not the script.
- **Check:** Tests: the PDF fixture yields its lines in order. A blank PDF and a locked PDF, both built in the test with pypdf, a `.docx` file name, a 6 MB upload, and text of 199 and of 12,001 characters are each rejected with a message, and typed text is preserved. No chunk exceeds 800 characters and no line is lost. Saving twice leaves one set of chunks. Nothing but the database is written under the data folder.

### T10 Model layer

- **Depends on:** T02
- **Spec:** AR 7, the `Ping` schema in PS 2
- **Files:** `app/llm.py`, `tests/test_llm.py`
- **Build:** `chat`, `list_models`, the three error classes, the Ollama function, the Claude function, and the single retry on invalid output. In this task the fake provider answers `Ping` only.
- **Check:** Default tests with `httpx.MockTransport` for Ollama: the request body matches AR 7.2, including `num_ctx` and the schema. `think` is sent only for a model with the `thinking` capability. A `done_reason` of `length` raises `LLMOutputError`. Invalid JSON twice raises `LLMOutputError` after exactly two calls. A refused connection raises `LLMUnavailable`. `list_models` leaves out entries with `remote_host`. Default tests with a stub in place of `anthropic.Anthropic`: the call has no sampling parameter, it has `betas` and `fallbacks`, and a `refusal` stop reason raises `LLMRefused`. `live` test: `Ping` returns `ok` on the configured provider. The live test needs owner item 3 or 4.

### T11 Prompts and schemas

- **Depends on:** T10
- **Spec:** PS 1 to 5, AR 7.5
- **Files:** `app/prompts.py`, `tests/test_prompts.py`
- **Build:** The schema classes of PS 2 verbatim. `plan_prompt`, `questions_prompt` and `evaluation_prompt`, each returning `(system, user)` with the texts of PS 3 to 5.
- **Check:** Tests: every tag block is present, and an empty input renders the word `none`. `Evaluation` lists strengths and gaps before the scores. A score of 5 fails validation. With every input at its largest case from AR 7.5, the plan prompt is at most 22,000 characters, the question prompt at most 11,000 and the evaluation prompt at most 23,000.

### T12 Scoring core

- **Depends on:** T01
- **Spec:** PS 7.1, 7.2, 7.5, 12
- **Files:** `app/scoring.py`, `tests/test_scoring.py`
- **Build:** The constants of PS 12. `answer_score(kind, correctness, depth, clarity, structure)`, `attempt_score(scores)` and `weakest_dimension(turns)`.
- **Check:** Tests reproduce every row of the tables in PS 7.1 and 7.2, and the tie rule and the empty case of PS 7.5.

### T13 Fake provider

- **Depends on:** T10, T11, T12
- **Spec:** PS 10
- **Files:** `app/llm.py`, `tests/test_llm_fake.py`
- **Build:** The fake replies for `Plan`, `QuestionBatch` and `Evaluation`, read from the user prompt. In fake mode `list_models` returns the `fake` provider and nothing else. Outside fake mode it never returns it.
- **Check:** Tests: each tag gives the documented dimension values and, through `answer_score`, 75, 100, 25 and 20. `#followup` yields a follow-up only while follow-ups are left. `#invalid` and `#down` raise the documented errors. 200 fake questions of one topic contain no pair at or above the near copy threshold. The plan gains Kubernetes when a job description is present.

### T14 Prep plan

- **Depends on:** T09, T13
- **Spec:** F3, PS 3
- **Files:** `app/plan.py`, `app/routes/plan.py`, `app/templates/plan.html`, `tests/test_plan.py`
- **Build:** `normalise_plan`, `build_plan`, the plan page, set weight, add topic. Building without a saved resume shows a message and calls no model. The build form carries a model picker, preselected as F9.1 says. Write that picker as one template include, because T16 and T18 reuse it.
- **Check:** Unit tests for each of the seven normalisation rules. Flow tests: a built plan lists topics with weight, source and reason. "Resume deep-dive" and a behavioral topic are present. A topic set to weight 0 stays listed as off. A manually added topic survives a rebuild. A rebuild keeps topic ids.

### T15 Question generation

- **Depends on:** T14
- **Spec:** F4.3, F7.1, PS 4, PS 8.2, PS 8.3
- **Files:** `app/questions.py`, `tests/test_questions.py`
- **Build:** `generate`: choose inputs, call the model, normalise, drop near copies, store each question with its embedding and `context`. `drop_duplicates` as a pure function.
- **Check:** Tests: each normalisation rule. `drop_duplicates` with hand-made vectors drops at 0.82 and keeps at 0.81, against stored questions and inside the batch. A resume probe batch stores a different `context` per question, each taken from the profile's chunks. With a seeded random generator the chosen excerpts are reproducible. An excerpt under the 0.25 floor is not sent, checked on the prompt text. Questions of another profile are never used for the near copy check or the already asked list.

### T16 Start a session

- **Depends on:** T15
- **Spec:** F4.1 to F4.6, F9.1 to F9.3, F9.5, PS 6 steps 3 to 6, AR 6.2, AR 6.3
- **Files:** `app/sessions.py`, `app/routes/sessions.py`, `app/templates/profile.html`, `tests/test_sessions_start.py`
- **Build:** `compose` without reviews, `start`, the session router route, and the start form with topic checkboxes, count, difficulty and the model picker. A helper returns the profile's last used provider and model, or the configured default.
- **Check:** Flow tests: a 5 question session over two topics creates 5 attempts in alternating topic order, each with a level 0 turn. Stored unattempted questions are used before anything is generated, proven by counting the fake's calls. A second start while a session is active redirects to it. A topic with weight 0 is not offered. When generation fails for every topic, nothing is created and the reason is shown. When it fails for one topic, the session starts shorter with a notice. The form preselects the last used model.

### T17 Answer, score, follow up

- **Depends on:** T16
- **Spec:** F5, F6, F7.2, F7.3, F9.2, PS 5, AR 6.1
- **Files:** `app/evaluation.py`, `app/routes/sessions.py`, `app/templates/attempt.html`, `tests/test_answer_flow.py`
- **Build:** `evaluate_turn` with input selection and normalisation. The question page in its three states. The answer, evaluate and skip routes. The privacy badge.
- **Check:** Flow tests: a plain answer shows 75 and four dimensions. `#followup` twice produces levels 1 and 2 and never a level 3. The attempt score is the mean of its turns. `#down` keeps the answer and shows Retry, and Retry then succeeds. `#invalid` behaves the same. Skip scores 0, shows the reference answer and asks no follow-up. The reference answer is absent from the page until the attempt is done. An empty answer and one of 5,001 characters return 422 with the text preserved. A double submit creates no second turn. A resume probe question shows its excerpt. A session on the `fake` provider shows the Local badge, and a session row with the provider `anthropic` shows the Cloud badge. Unit test: no transaction is open while `llm.chat` runs.

### T18 Finish, resume, end, summary

- **Depends on:** T17
- **Spec:** F4.7, F4.8, F8, F9.4, AR 6.3, AR 6.4, DM 3 invariant 10
- **Files:** `app/sessions.py`, `app/routes/sessions.py`, `app/templates/summary.html`, `app/templates/profile.html`, `tests/test_session_lifecycle.py`
- **Build:** `finish_attempt`, `end`, the summary page, "Continue session, question k of n" on the profile home, and the change model route.
- **Check:** Flow tests: after two of five questions, a new test client built on the same data folder lands on question 3. This stands in for an app restart. Each of the three stored states of AR 6.3 renders its page. Finishing the last attempt completes the session in the same transaction. Ending early follows the three rules of AR 6.4, including deletion of a session with nothing scored. The summary shows every attempt, the average and the weakest dimension. After a model change, the next evaluation records the new `eval_model`.

### T19 Status page, complete

- **Depends on:** T05, T10
- **Spec:** F10
- **Files:** `app/health.py`, `app/routes/status.py`, `app/templates/status.html`, `tests/test_health.py`
- **Build:** The model list with local and cloud labels. The Test model form, which calls `chat` with `Ping` and shows the elapsed time or the error.
- **Check:** Tests: Test model with the fake provider shows a time. With a stubbed unreachable Ollama it shows the "could not be reached" message and no traceback.

### T20 Golden set

- **Depends on:** T17, owner item 3 or 4
- **Spec:** PS 11
- **Files:** `tests/fixtures/golden_answers.json`, `tests/test_golden_live.py`
- **Build:** The six answers of PS 11 verbatim, with their key points and expected ranges. A `live` test scores them through the same prompt path the app uses, asserts the four pass rules and prints a table of scores.
- **Check:** `uv run pytest -m live` passes on the configured model. Add the model name, the six scores and the result to the log in SG 9.3. If the default local model fails, record that and tell the owner. Do not widen the ranges.

### T21 M1 smoke and README

- **Depends on:** T18, T19, T20, owner items 3 and 5
- **Spec:** SG 9.2 steps 1 to 12
- **Files:** `README.md`, `CLAUDE.md`, `docs/05-setup-guide.md`
- **Build:** A README with install and run steps for both systems, taken from the setup guide. Bring the first paragraph and the environment facts of `CLAUDE.md` up to date. Run the checklist on Windows. Run it on a Mac, or record that it is still open.
- **Check:** Steps 1 to 12 pass on each system that was available. One log row per system.

## 6. M2: retention and targeting

### T22 Job description mode

- **Depends on:** T14
- **Spec:** F11, PS 3
- **Files:** `app/routes/plan.py`, `app/templates/plan.html`, `tests/fixtures/sample_jd.txt`, `tests/test_jd.py`
- **Build:** The job description form with save and clear. Source labels, and the Gap label for `jd` topics.
- **Check:** Flow tests: with a job description the rebuilt plan shows Kubernetes labelled Gap with a weight of 3 or more. Clearing it and rebuilding sets that topic's weight to 0 and keeps its row. A job description of 6,001 characters is rejected with the text preserved.

### T23 Spaced repetition

- **Depends on:** T18
- **Spec:** F12, PS 6 steps 1 and 2, PS 7.3
- **Files:** `app/scoring.py`, `app/sessions.py`, `app/templates/profile.html`, `tests/test_srs.py`
- **Build:** `srs_next`. The schedule update inside `finish_attempt`. "Due today: N" on the profile home. Reviews and the review-only option in `compose`.
- **Check:** Unit tests reproduce every row of the table in PS 7.3, and the full ladder: retired after four passes, 25 days after the first failure. Flow tests with `app.state.today` moved forward: a `#weak` answer makes the question due the next day and not before. A 5 question session takes at most 2 due questions and marks them `is_review`. Review-only with nothing due creates no session and says so.

### T24 Readiness and progress

- **Depends on:** T23
- **Spec:** F13, PS 7.4, PS 7.5, DM 9
- **Files:** `app/scoring.py`, `app/routes/progress.py`, `app/templates/progress.html`, `app/templates/profile.html`, `tests/test_readiness.py`
- **Build:** `topic_score` and `readiness`. The progress page with one `<meter>` per topic, each with its number as text, and the session list. Readiness on the profile home.
- **Check:** Unit tests reproduce the worked example of PS 7.4: 75.00, 30.67 and 0 give 47. They also cover the 20 row window, an age below zero treated as zero, and no active topic giving no value. Flow tests: the empty state. A profile with history shows the number, the bars and the sessions. A topic with weight 0 is left out.

### T25 v1 hardening

- **Depends on:** T22, T24, owner item 5
- **Spec:** PR 8, DM 4, AR 9, AR 10, SG 9.2 steps 13 and 14
- **Files:** tests and templates as needed, `README.md`, `docs/05-setup-guide.md`
- **Build:** An empty state on every page. Every form error preserves input. The two isolation tests of DM 4. A test that scans every template and fails on the `safe` filter or on an asset loaded over `http://` or `https://`. A test that the log output of a full fake session contains no resume, answer or prompt text. A keyboard pass through every page.
- **Check:** All of those tests pass. Steps 13 and 14 pass on each available system. Log rows are added. This completes v1.

## 7. M3: voice

### T26 Voice dependencies and model

- **Depends on:** T25
- **Spec:** decision D11, DM 10, trap 2 in SG 7
- **Files:** `pyproject.toml`, `uv.lock`, `app/fetch_models.py`, `app/migrations/002_voice.sql`, `app/health.py`, `tests/test_db.py`
- **Build:** Enable the two M3 lines in the project file. `fetch_models --voice` downloads `base.en` into `data/models/whisper`. Copy the migration of DM 10 verbatim. Add a status check for the speech model.
- **Check:** `uv lock` succeeds and the lock still holds packages for both environments. The migration test reaches version 2 from a version 1 database that contains data. `models` test: the speech model loads with `local_files_only=True`.

### T27 Transcription

- **Depends on:** T26
- **Spec:** F14.2 to F14.4, PS 9, DM 5, DM 10, AR 9 rule 13
- **Files:** `app/voice.py`, `app/routes/voice.py`, `tests/fixtures/speech_sample.webm`, `tests/test_voice.py`
- **Build:** `transcribe`, `delivery_metrics`, and the audio route. The route answers with JSON, either a `text` field or an `error` field, and stores the metrics on the current turn. Fixture recipe, used on Windows on 2026-10-08: speak the sentence of PS 9.2 with the system speech engine into a WAV file, then use FFmpeg to put 1.5 seconds of silence in front and encode it as Opus in WebM. On a Mac, `say -o` produces the speech. FFmpeg is needed for this one step only.
- **Check:** Default tests with a stub recogniser: the two guards drop a late segment and a punctuation-only segment. No segment gives the "No speech was detected" error. A decoding error gives the "could not be read" error. A 26 MB body is rejected. The measured example reproduces: 27 words, 147 words per minute, 3 fillers. `models` tests: the fixture's transcript contains "tuple is immutable" and "dictionary key", with a first word delay between 0.8 and 1.8 seconds. Two seconds of silence built in the test give the no speech error. No new file appears under the data folder after a request.

### T28 Recorder in the browser

- **Depends on:** T27
- **Spec:** F14.1, F14.4
- **Files:** `app/static/voice.js`, `app/templates/attempt.html`
- **Build:** A Record button that toggles. `MediaRecorder` with `audio/webm;codecs=opus` when `isTypeSupported` accepts it, otherwise `audio/mp4`. A stop at 5 minutes. Upload to the audio route and put the transcript in the answer box. The states "Recording" and "Transcribing" and every error are announced in an `aria-live` region. A denied permission is explained in words. The page works unchanged without JavaScript.
- **Check:** By hand, smoke steps 15 and 16 of SG 9.2, in Chrome and Edge on Windows and in Chrome and Safari on a Mac. One log row per browser.

### T29 Delivery metrics on the page

- **Depends on:** T27
- **Spec:** F16
- **Files:** `app/templates/attempt.html`, `tests/test_voice.py`
- **Build:** Pace, filler count and first word delay beside the feedback of a voice turn, with a note that they are approximate.
- **Check:** Flow test: a turn with voice columns shows the three values and the note. A text turn shows none. The answer score is the same with and without voice columns.

### T30 Read aloud

- **Depends on:** T17
- **Spec:** F15
- **Files:** `app/static/voice.js`, `app/templates/attempt.html`
- **Build:** A button that speaks the current prompt with `speechSynthesis`, using a voice whose `localService` is true and whose language starts with `en`. The button stays hidden when no such voice exists. Speech starts only from a click.
- **Check:** By hand, smoke step 17 of SG 9.2 on each system and browser. Log it.

### T31 M3 smoke

- **Depends on:** T28, T29, T30, owner items 5 and 6
- **Spec:** SG 9.2 steps 15 to 17
- **Files:** `docs/05-setup-guide.md`
- **Build:** Run the steps on each available system.
- **Check:** The steps pass. Log rows are added. This completes v1.1.

## 8. Dependency overview

```
T01 -> T02 -> T03 -> T04 -> T05 -> T06
                |      |
                |      \-> T07 --\
                \-> T08 ---------+-> T09 --\
T02 -> T10 -> T11 --\                      |
T01 -> T12 ---------+-> T13 ---------------+-> T14 -> T15 -> T16 -> T17 -> T18
T05 + T10 -> T19          T17 -> T20          T18 + T19 + T20 -> T21
T14 -> T22    T18 -> T23 -> T24    T22 + T24 -> T25
T25 -> T26 -> T27 -> T28    T27 -> T29    T17 -> T30    T28 + T29 + T30 -> T31
```

## 9. Definition of done

A task is done when all of these hold:

1. Its check passes.
2. `uv run ruff check .`, `uv run ruff format --check .` and `uv run pytest` pass.
3. No rule in AR 9 is broken.
4. Any document that the change contradicts was updated in the same commit.
5. Its progress line in section 2 is ticked.
