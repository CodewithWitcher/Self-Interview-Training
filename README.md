# Self Interview Training

A private interview practice app that runs on your own Windows PC or Mac.
It reads your resume, builds a practice plan, asks questions, probes your answers with follow-ups, scores them against a fixed rubric and brings weak questions back on a schedule.
With a local model through Ollama, nothing you type leaves the computer. Claude can be used as an optional cloud model.

The full instructions, settings and troubleshooting are in the [setup guide](docs/05-setup-guide.md).

## Install

You need uv, Git and, for local mode, Ollama. Keep the folder path short, 100 characters or fewer on Windows.

Windows, in PowerShell:

```powershell
winget install --id astral-sh.uv -e
winget install --id Git.Git -e
```

Mac, in Terminal:

```zsh
curl -LsSf https://astral.sh/uv/install.sh | sh
xcode-select --install
```

Install Ollama from https://ollama.com/download on either system, then reopen the terminal.

Then, from the repository root, one command per line:

```text
uv sync
uv run python -m app.fetch_models
ollama pull llama3.1:8b
uv run python -m app.health
```

## Run

```text
uv run python -m app
```

Open http://127.0.0.1:8000. The app listens on this computer only.

To try the app with no model at all, set `SIT_DEV_FAKE=1` first: `$env:SIT_DEV_FAKE = "1"` in PowerShell, or `SIT_DEV_FAKE=1 uv run python -m app` on a Mac.
In fake mode, end an answer with `#strong`, `#weak`, `#wrong` or `#followup` to see the different results.

To use Claude, copy `.env.example` to `.env` and set `ANTHROPIC_API_KEY`. Cloud sessions show a badge that says your answers are sent to Anthropic.

## Develop

```text
uv run pytest
uv run ruff check .
uv run ruff format .
```

`uv run pytest -m models` needs the downloaded model files, and `uv run pytest -m live` needs a real language model.
The specifications in `docs/` are the source of truth, and `docs/06-task-breakdown.md` tracks progress.
