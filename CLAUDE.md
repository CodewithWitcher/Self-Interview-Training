# Self Interview Training

A private interview practice app that runs locally on Windows and Mac. FastAPI with server-rendered HTML, one SQLite file, local models through Ollama, Claude as an optional cloud model. The code covers every task in `docs/06-task-breakdown.md`; the unticked ones wait only on the owner's machines, a model or CI. The specifications in `docs/` are the source of truth.

## Read first

| Document | Read it when |
|---|---|
| `docs/06-task-breakdown.md` | Always. It says what to do next and how to prove it. |
| `docs/01-product-requirements.md` | You need to know what a feature must do, or whether something is in scope |
| `docs/02-architecture.md` | You touch structure, routes, the model layer, security or tests |
| `docs/03-data-model.md` | You touch the database |
| `docs/04-prompts-and-scoring.md` | You touch prompts, scores, the review schedule, readiness or voice metrics |
| `docs/05-setup-guide.md` | You install, configure or run anything, or hit an environment error |

`Project Idea.md` and `document.md` are background from the owner, not specifications. Where they disagree with `docs/`, `docs/` wins. Do not edit them.

## Commands

Run from the repository root, one command per line. Never join commands with `&&`.

```text
uv sync                               install Python 3.13 and all packages
uv run python -m app                  start the app at http://127.0.0.1:8000
uv run pytest                         default tests: fake model, no network
uv run pytest -m models               tests that need the downloaded model files
uv run pytest -m live                 tests that need a real language model
uv run ruff check .                   lint
uv run ruff format .                  format
uv run python -m app.health           environment checks
uv run python -m app.fetch_models     download model files
```

Set `SIT_DEV_FAKE=1` to run the app with no model at all.

## Workflow

- Take the first unticked task in `docs/06-task-breakdown.md` whose dependencies are ticked. One task, one commit, and the message starts with the task id.
- For anything with logic, write the test from the task's check first and watch it fail.
- A task is done when its check, the lint, the format check and the default tests all pass, and its progress line is ticked.
- If code has to differ from a document, change the document in the same commit and say so.
- The items under "Needs the owner" in the task breakdown are not yours. Never push, create a remote, pull a multi-gigabyte model or call a paid API without being told.

## Rules that are easy to break

Both systems:

- Use `pathlib.Path` for every path. The repository path contains spaces on the owner's machine.
- Pass `encoding="utf-8"` to every `open`, `read_text` and `write_text`.
- No shell scripts and no Makefile. Anything runnable is a Python module started with `uv run`.
- Command line output is ASCII only.
- Close every SQLite connection. An open one breaks the tests on Windows.
- Use `uv run python`, never `python`. Windows has no `python` on the path.
- Add no dependency without a decision record in `docs/02-architecture.md` and a successful `uv lock`. Keep the `av<19` pin.

Privacy and security, from section 9 of the architecture document:

- Bind to `127.0.0.1` only. Never weaken the host and origin checks.
- At run time, no network request except to the selected model provider. No CDN links.
- Never log or print resume text, job description text, answers, prompts, model replies or keys.
- Never apply the `safe` filter to text from a user or a model.
- SQL with parameters only. Every query is scoped to one profile.
- Never commit `data/` or `.env`.

Design:

- Plain HTML forms, POST then redirect. No JavaScript framework and no build step.
- No model call inside a database transaction.
- Scores come from `app/scoring.py`, never from the model. Round half up. Never use `round()`.
- Read the date and random numbers only through `app.state.today` and `app.state.rng`.
- Never edit a migration file that has been merged.
- Build nothing from the non-goals list in the product requirements.
- Keep it small: no abstraction with a single user, no setting nobody asked for. Mark a deliberate shortcut with a comment that starts with `ponytail:` and names its limit and the upgrade path.

## Environment facts

- Python 3.13 through uv. Supported: Windows 10 or 11 on x64, and macOS 14 or later on Apple Silicon.
- The owner's Windows machine runs Windows PowerShell 5.1.
- Section 9 of the setup guide lists what has been verified. Nothing has run on a Mac yet, and no real model has been called yet.
- Ruff also formats Python blocks inside Markdown, so `pyproject.toml` excludes `*.md`. Keep that line.
- `uv sync` refuses Linux, which the lock does not cover. In a Linux development container, install the locked versions with `uv export` and `uv pip install`, then run commands with `UV_NO_SYNC=1`.
