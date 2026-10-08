# Setup guide for Windows and Mac

Status: draft 1, written 2026-10-08. Windows steps and facts were checked on the reference machine described in section 1. **Nothing in this guide has been run on a Mac yet.** Section 9 records exactly what was and was not verified.

Related documents: [product requirements](01-product-requirements.md), [architecture](02-architecture.md), [task breakdown](06-task-breakdown.md).

## 1. Supported machines

| | Windows | Mac |
|---|---|---|
| System | Windows 10 or 11, x64 | macOS 14 or later, Apple Silicon |
| Memory | 16 GB for the default local model. 8 GB with a small local model or with Claude. | The same |
| Disk | About 8 GB free | The same |
| Graphics | Optional. Ollama uses an NVIDIA card when it finds one. | Ollama uses the Apple GPU. |
| Browser | Current Chrome or Edge | Current Chrome or Safari |

Not supported: Intel Macs, Linux, Windows on ARM. They may work but are never verified.

Disk use:

| Item | Size |
|---|---|
| Python environment in `.venv` | 0.35 GB |
| Embedding model | 0.09 GB |
| Speech model, from M3 | 0.14 GB |
| Default local model `llama3.1:8b`, stored by Ollama outside the project | 4.9 GB |

Reference machine, Windows: Windows 11 Home, Intel Core i5-10300H with 4 cores, 32 GB of RAM, NVIDIA GTX 1650 with 4 GB of video memory, uv 0.11.21, Ollama 0.35.1, Git 2.56. Ollama on this machine has only cloud-hosted models, so a local model must be pulled before local mode works. The default local model is larger than the card's video memory, so expect Ollama to run part of it on the CPU. Its speed on this machine has not been measured.

Reference machine, Mac: not yet assigned.

## 2. What you install

| Tool | Why | Needed for |
|---|---|---|
| uv | Installs Python 3.13 and every package | Everything |
| Git | Fetches the code | Everything |
| Ollama | Runs local models | Local mode |
| A Claude API key | Access to Claude | Cloud mode, optional |

Not needed: a system Python, Node, FFmpeg, a C compiler. Every dependency installs as a prebuilt package.

## 3. Install the tools

### Windows, in PowerShell

```powershell
winget install --id astral-sh.uv -e
winget install --id Git.Git -e
```

Install Ollama with the installer from https://ollama.com/download. Then close and reopen PowerShell.

### Mac, in Terminal

```zsh
curl -LsSf https://astral.sh/uv/install.sh | sh
xcode-select --install
```

The second command installs Git. Skip it when `git --version` already works. Install Ollama with the app from https://ollama.com/download. Then close and reopen Terminal.

### Check, on both

```text
uv --version
git --version
ollama --version
```

## 4. Set up the project

Keep the repository in a short folder path, 100 characters or fewer on Windows. Section 7 explains why. Run every command from the repository root, one command per line.

```text
git clone <repository URL>
cd <repository folder>
uv sync
uv run python -m app.fetch_models
ollama pull llama3.1:8b
uv run python -m app.health
uv run python -m app
```

| Command | What it does |
|---|---|
| `uv sync` | Installs Python 3.13 and the packages from `uv.lock` into `.venv` |
| `uv run python -m app.fetch_models` | Downloads the embedding model into `data/models/`. Add `--voice` from M3 on. |
| `ollama pull llama3.1:8b` | Downloads the default local model, 4.9 GB |
| `uv run python -m app.health` | Runs the status checks and prints pass or fail for each |
| `uv run python -m app` | Starts the app |

Then open http://127.0.0.1:8000 in the browser.

To change a setting or add a Claude key, create `.env` from the example and edit it.

```powershell
Copy-Item .env.example .env
```

```zsh
cp .env.example .env
```

### The project file

This `pyproject.toml` was locked and installed on the reference machine on 2026-10-08. Task T01 starts from it.

```toml
[project]
name = "self-interview-training"
version = "0.1.0"
requires-python = "==3.13.*"
dependencies = [
  "fastapi",
  "uvicorn",
  "jinja2",
  "python-multipart",
  "python-dotenv",
  "httpx",
  "anthropic",
  "pypdf",
  "numpy",
  "fastembed",
  # Added in M3 by task T26:
  # "faster-whisper",
  # "av<19",
]

[dependency-groups]
dev = ["pytest", "ruff"]

[tool.uv]
package = false
environments = [
  "sys_platform == 'win32' and platform_machine == 'AMD64'",
  "sys_platform == 'darwin' and platform_machine == 'arm64'",
]

[tool.pytest.ini_options]
pythonpath = ["."]
testpaths = ["tests"]
addopts = "-m 'not models and not live'"
markers = [
  "models: needs the downloaded embedding or speech model",
  "live: needs a real language model",
]

[tool.ruff]
line-length = 100
```

Versions that the full list, including the two M3 lines, resolved to on 2026-10-08: fastapi 0.143.0, starlette 1.7.0, uvicorn 0.54.0, jinja2 3.1.6, python-multipart 0.0.32, python-dotenv 1.2.4, httpx 0.28.1, anthropic 1.12.1, pydantic 2.14.0, pypdf 6.19.0, numpy 2.5.3, fastembed 0.9.0, onnxruntime 1.30.0, faster-whisper 1.2.1, ctranslate2 4.8.2, av 18.1.0, pytest 9.1.1, ruff 0.16.10. `uv.lock` is the source of truth once it exists. The file exactly as shown was also locked and installed, and its three test selections were run: `pytest`, `pytest -m models` and `pytest -m live` each pick only their own tests.

## 5. Configuration

Every setting is an environment variable. `.env` in the repository root is loaded at startup. A variable set in the real environment wins over `.env`.

| Variable | Default | Meaning |
|---|---|---|
| `SIT_PORT` | `8000` | Port of the web app. The address is always `127.0.0.1`. |
| `SIT_DATA_DIR` | `data` | Folder for the database and model files. Relative to the repository root unless absolute. |
| `SIT_DEFAULT_PROVIDER` | `ollama` | Provider preselected on first use: `ollama` or `anthropic` |
| `SIT_OLLAMA_URL` | `http://127.0.0.1:11434` | Where Ollama listens |
| `SIT_OLLAMA_MODEL` | `llama3.1:8b` | Local model preselected in the start form |
| `SIT_OLLAMA_NUM_CTX` | `8192` | Context window requested from Ollama, in tokens |
| `SIT_ANTHROPIC_MODEL` | `claude-opus-5-5` | Claude model preselected in the start form |
| `SIT_ANTHROPIC_EFFORT` | `medium` | Thinking effort for Claude: `low`, `medium`, `high`, `xhigh` or `max` |
| `ANTHROPIC_API_KEY` | not set | Read by the Anthropic SDK. Only for cloud mode. |
| `SIT_LLM_TIMEOUT_S` | `180` | Time limit for one model call, in seconds |
| `SIT_DEV_FAKE` | `0` | `1` replaces the model and the embedder with fakes. For tests and interface work. |
| `SIT_WHISPER_MODEL` | `base.en` | Speech model, M3 |
| `SIT_WHISPER_DEVICE` | `cpu` | Speech device, M3. `cuda` is possible on Windows with NVIDIA libraries but is untested. |
| `SIT_WHISPER_COMPUTE` | `int8` | Speech number format, M3 |
| `SIT_WHISPER_PROMPT` | empty | Optional hint text for the recogniser, M3 |

`.env.example` lists every variable with its default, commented out.

## 6. Choosing a model

### Local

- The default is `llama3.1:8b`. It was chosen because it is a long-standing model that is certain to exist, not because it is the best available.
- Any local Ollama chat model that supports structured output can be used. Pull it, then pick it in the start form or set `SIT_OLLAMA_MODEL`.
- On a machine with little memory, `llama3.2:3b` is a 2.0 GB alternative. Expect less reliable scoring from it.
- Decide with evidence: `uv run pytest -m live` runs the golden set from [prompts and scoring](04-prompts-and-scoring.md), section 11, against the configured model.
- An Ollama model that runs on Ollama's servers, with a name ending in `cloud`, is not a local model. The app does not list it.

### Claude

Put the key in `.env`:

```text
ANTHROPIC_API_KEY=your-key
```

A login made with Anthropic's `ant` command line tool also works, with no key in `.env`. API use is billed separately from a Claude chat subscription.

Prices per million tokens, from Anthropic's price list as cached on 2026-10-06:

| Model | Input | Output |
|---|---|---|
| `claude-opus-5-5`, the default | $4.00 | $20.00 |
| `claude-sonnet-5-5` | $2.00 | $10.00 |
| `claude-haiku-5-5` | $0.10 | $0.50 |

With a Claude model, your answers and resume excerpts are sent to Anthropic. The app shows a badge on every session page that says so.

## 7. Known traps

"Verified" means the failure was reproduced on the reference machine on 2026-10-08.

| # | Trap | System | What happens | What to do |
|---|---|---|---|---|
| 1 | Long folder path. **Verified.** | Windows | `import anthropic` fails with `ModuleNotFoundError` for a `beta_managed_agents_...` module. Windows limits a path to 260 characters and the SDK contains a file name of 87 characters. The repository root can be at most 126 characters, and at most 124 once model files are downloaded. | Keep the repository root at 100 characters or fewer. |
| 2 | `av` version 19. **Verified.** | Both | faster-whisper 1.2.1 fails with `TypeError: open() got an unexpected keyword argument 'metadata_errors'`. | Keep `"av<19"` in `pyproject.toml`. Remove the pin when a faster-whisper release fixes it. |
| 3 | No `python` command. **Verified.** | Windows | `python` opens the Microsoft Store. | Always use `uv run python`. |
| 4 | `&&` between commands | Windows | Windows PowerShell 5.1 rejects it. | One command per line, in documents and in scripts. |
| 5 | Spaces in the path | Both | The reference machine's project folder is `D:\Self Interview Training`. Unquoted paths break. | Quote paths in commands. Use `pathlib` in code. |
| 6 | Text encoding | Windows | Python 3.13 opens files in the system encoding, not UTF-8. | Pass `encoding="utf-8"` to every `open`, `read_text` and `write_text`. |
| 7 | Symlink warning from Hugging Face. **Verified.** | Windows | A warning about Developer Mode during model download. | Ignore it. Files are copied instead. |
| 8 | Ollama cloud models. **Verified.** | Both | `ollama list` shows models that run remotely. | The app filters them out, see the [architecture](02-architecture.md), section 7.2. |
| 9 | Ollama's small default context | Both | Prompts over 4,096 tokens are cut silently. | The app requests `SIT_OLLAMA_NUM_CTX` on every call. |
| 10 | `localhost` | Both | It can resolve to IPv6 first and miss a server that listens on IPv4. | Use `127.0.0.1` in every URL and setting. |
| 11 | Open database handles | Windows | Tests fail with `PermissionError: [WinError 32]` when deleting a temporary folder. | Close every connection. |
| 12 | Working folder | Both | `python -m app` finds the package relative to the current folder. | Run commands from the repository root. |
| 13 | Python 3.14 | Mac | The dependency list has no solution for macOS 13 on Python 3.14. | Stay on Python 3.13. |
| 14 | Microphone permission, M3 | Both | The browser cannot record until the system allows it. | Windows: Settings, Privacy and security, Microphone. Mac: System Settings, Privacy and Security, Microphone. |

## 8. Everyday commands

| Purpose | Command |
|---|---|
| Start the app | `uv run python -m app` |
| Start with reload while developing | `uv run uvicorn app.main:create_app --factory --reload --host 127.0.0.1 --port 8000` |
| Run the default tests | `uv run pytest` |
| Run the tests that need downloaded models | `uv run pytest -m models` |
| Run the tests that need a language model | `uv run pytest -m live` |
| Check code style | `uv run ruff check .` |
| Format code | `uv run ruff format .` |
| Run the status checks | `uv run python -m app.health` |
| Download model files | `uv run python -m app.fetch_models` |

To start the app with no model at all, set `SIT_DEV_FAKE` first.

```powershell
$env:SIT_DEV_FAKE = "1"
uv run python -m app
```

```zsh
SIT_DEV_FAKE=1 uv run python -m app
```

## 9. Verification

### 9.1 What proves what

| Evidence | Windows | Mac |
|---|---|---|
| Default tests in CI | Every push | Every push |
| `models` tests in CI: real embedding and speech models | Every push | Every push |
| `live` tests: golden set with a real model | By hand | By hand |
| Manual smoke checklist | By hand | By hand |

CI on a Mac runner proves the native libraries on Apple Silicon without owning a Mac. It does not prove Ollama, the browser, the microphone or speech output. Those need the manual checklist on a real Mac.

### 9.2 Manual smoke checklist

Run it on each system at the end of M1, M2 and M3. Record the result in section 9.3.

After M1:

1. `uv run python -m app.health` exits with code 0.
2. Start the app and open http://127.0.0.1:8000.
3. Create a profile named "Smoke".
4. Upload `tests/fixtures/sample_resume.pdf`. The text appears for review. Save it.
5. Build the plan. It shows at least four topics, including a behavioral topic and "Resume deep-dive".
6. Start a session of 3 questions on two topics with the local model. The badge says Local.
7. Answer the first question properly. A score, four dimensions and feedback appear, then a follow-up or the reference answer.
8. On the second question, stop the app with Ctrl+C and close the browser. Start the app again. The profile home shows "Continue session, question 2 of 3", and Continue opens question 2.
9. Skip question 2. It scores 0 and shows the reference answer.
10. Finish the session. The summary shows three rows and an average.
11. Quit Ollama. Start a new session with stored questions, or answer a pending question. The answer is kept and a Retry button appears. Start Ollama again. Retry works.
12. Switch networking off. Run a short session with the local model. Everything works.

After M2:

13. Paste `tests/fixtures/sample_jd.txt` as the job description and rebuild the plan. At least one topic is labelled Gap.
14. Open the progress page. It shows a readiness number, topic bars and the finished sessions.

After M3:

15. Record a spoken answer of about 10 seconds. The transcript appears in the answer box. After submitting, pace, filler count and first-word delay are shown.
16. Deny the microphone permission and press Record. A clear message appears and typing still works.
17. Press Read aloud. The question is spoken.

Optional, with a Claude key:

18. Start a session with Claude. The badge says Cloud. Scoring works.

### 9.3 Verification log

Append a row for every run. Never delete rows.

| Date | System | What was run | Result |
|---|---|---|---|
| 2026-10-08 | Windows 11, uv 0.11.21 | Resolution of the dependency list to prebuilt packages only, for Python 3.13 on Windows x64 and on macOS Apple Silicon | Pass on both. On Python 3.14 it fails for macOS 13. |
| 2026-10-08 | Windows 11 | `uv lock` and `uv sync` of the project file in section 4, with the two M3 lines enabled | Pass. Python 3.13.14. The lock holds Windows x64 and macOS 14 Apple Silicon packages. |
| 2026-10-08 | Windows 11 | The project file exactly as shown in section 4: lock, install, `import app` from the root, the three pytest selections, ruff | Pass |
| 2026-10-08 | Windows 11 | `import anthropic` from an environment in a deep folder | Fail, then pass in a shorter folder. Cause confirmed: one file path of 263 characters. Trap 1. |
| 2026-10-08 | Windows 11 | fastembed 0.9.0 with all-MiniLM-L6-v2: download, embed, reload with `local_files_only=True` and `HF_HUB_OFFLINE=1` | Pass. 384 values, 32-bit floats, length 1. 87 MB on disk. |
| 2026-10-08 | Windows 11 | faster-whisper 1.2.1 with av 19.0.1 | Fail. Trap 2. |
| 2026-10-08 | Windows 11 | faster-whisper 1.2.1 with av 18.1.0, `base.en`, `int8`, CPU, on WebM/Opus bytes, with FFmpeg removed from the path | Pass. A 12.3 second clip took 1.3 seconds. Silence gives no segments. Invalid bytes raise `av.error.InvalidDataError`. Offline reload passes. 141 MB on disk. |
| 2026-10-08 | Windows 11 | The same model on a WAV made by the Windows speech engine | Pass with a defect: invented segments after the end of the audio. Guard added in [prompts and scoring](04-prompts-and-scoring.md), section 9.1. |
| 2026-10-08 | Windows 11, SQLite 3.53.1 | The SQL, the `migrate` code and the queries of the [data model](03-data-model.md) | Pass: constraints, rollback of a failing migration, cascade on profile deletion, isolation in queries. |
| 2026-10-08 | Windows 11 | Every worked example in [prompts and scoring](04-prompts-and-scoring.md), sections 7 to 10, the chunking rule and the filler pattern | Pass |
| 2026-10-08 | Windows 11 | A text PDF written with reportlab and read with pypdf 6.19.0. A blank PDF, a locked PDF, a broken PDF. | Pass. Blank gives empty text. Locked raises `FileNotDecryptedError`. Broken raises `PdfStreamError`. Both extend `pypdf.errors.PyPdfError`. |
| 2026-10-08 | Windows 11 | anthropic 1.12.1: the parameters of `beta.messages.parse` used in the [architecture](02-architecture.md), section 7.3 | Pass by inspection of the installed SDK. No request was sent. |
| open | Mac | Anything at all | Not run |
| open | Both | A request to a local Ollama model | Not run. No local model is pulled on the reference machine. |
| open | Both | A request to Claude | Not run |
| open | Both | Browser recording, microphone permission, speech output | Not run |
| open | Both | The app itself | Not built yet |

## 10. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `ModuleNotFoundError: No module named 'anthropic.types.beta...'` on Windows | Trap 1, the folder path is too long | Move the repository to a shorter path. Enabling long paths in Windows also works but needs administrator rights. |
| `TypeError: open() got an unexpected keyword argument 'metadata_errors'` | Trap 2 | Restore `"av<19"` and run `uv sync` |
| "Python was not found; run without arguments to install from the Microsoft Store" | Trap 3 | Use `uv run python` |
| "The token '&&' is not a valid statement separator" | Trap 4 | Run the commands one per line |
| The browser shows "Invalid host header" | The app was opened by machine name or network address | Open http://127.0.0.1:8000 |
| Status page: Ollama is not reachable | Ollama is not running, or the URL is wrong | Start the Ollama app. Check `SIT_OLLAMA_URL`. |
| Status page: no local model | Nothing was pulled, or only cloud models are present | `ollama pull llama3.1:8b` |
| Status page: embedding model missing, or `Could not load model ... from any source` | The model files were not downloaded | `uv run python -m app.fetch_models` |
| Model calls time out | The model is too large for the machine | Pick a smaller model, or raise `SIT_LLM_TIMEOUT_S`. `ollama ps` shows how the model is split between processor and graphics card. |
| "The model returned an unusable reply", often | The model is too weak for structured scoring | Try another model and run `uv run pytest -m live` |
| The port is already in use | Another program uses port 8000 | Set `SIT_PORT` |
| Record does nothing, or permission is denied | Trap 14 | Allow the microphone for the browser |
| `PermissionError: [WinError 32]` in tests | Trap 11 | Close the database connection in the code under test |

## 11. Reset and removal

| Goal | Action |
|---|---|
| Delete one profile | Use Delete on the profile home |
| Delete all app data | Stop the app, then delete the `data` folder |
| Remove the local model | `ollama rm llama3.1:8b` |
| Remove the Python environment | Delete the `.venv` folder |
