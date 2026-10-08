# Data model

Status: draft 1, written 2026-10-08. The SQL in this document was executed against SQLite 3.53 on 2026-10-08, see the [setup guide](05-setup-guide.md), section 9.

Related documents: [product requirements](01-product-requirements.md), [architecture](02-architecture.md), [prompts and scoring](04-prompts-and-scoring.md).

## 1. Overview

All user data lives in one SQLite file, `data/app.db`. There are seven tables.

```
profiles --< resume_chunks
profiles --< topics --< questions --< attempts --< turns
profiles --< sessions --< attempts
```

| Table | One row is |
|---|---|
| `profiles` | A profile, with its resume text and optional job description |
| `resume_chunks` | One excerpt of a resume, with its embedding |
| `topics` | One subject in a profile's plan |
| `questions` | One stored interview question |
| `sessions` | One practice sitting |
| `attempts` | One pass at one question inside a session |
| `turns` | One prompt and its answer: the opening question or a follow-up |

The only other files under `data/` are downloaded model files in `data/models/`. Uploaded resumes and recorded audio are never stored as files.

## 2. Schema

This is the content of `app/migrations/001_init.sql`. `STRICT` tables need SQLite 3.37 or later. The Python that uv installs on Windows bundles SQLite 3.53. The tests of task T03 prove the same on a Mac when they run in CI.

```sql
CREATE TABLE profiles (
  id            INTEGER PRIMARY KEY,
  name          TEXT NOT NULL COLLATE NOCASE UNIQUE CHECK (length(name) BETWEEN 1 AND 60),
  resume_text   TEXT,
  resume_name   TEXT,
  jd_title      TEXT,
  jd_text       TEXT,
  plan_summary  TEXT,
  created_at    TEXT NOT NULL
) STRICT;

CREATE TABLE resume_chunks (
  id          INTEGER PRIMARY KEY,
  profile_id  INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  ord         INTEGER NOT NULL,
  text        TEXT NOT NULL,
  embedding   BLOB,
  UNIQUE (profile_id, ord)
) STRICT;

CREATE TABLE topics (
  id          INTEGER PRIMARY KEY,
  profile_id  INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  name        TEXT NOT NULL COLLATE NOCASE CHECK (length(name) BETWEEN 1 AND 60),
  kind        TEXT NOT NULL CHECK (kind IN ('technical', 'behavioral', 'resume_probe')),
  weight      INTEGER NOT NULL DEFAULT 3 CHECK (weight BETWEEN 0 AND 5),
  source      TEXT NOT NULL CHECK (source IN ('resume', 'jd', 'both', 'manual')),
  rationale   TEXT NOT NULL DEFAULT '',
  UNIQUE (profile_id, name)
) STRICT;

CREATE TABLE questions (
  id                INTEGER PRIMARY KEY,
  topic_id          INTEGER NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
  difficulty        TEXT NOT NULL CHECK (difficulty IN ('easy', 'medium', 'hard')),
  text              TEXT NOT NULL,
  key_points        TEXT NOT NULL,
  reference_answer  TEXT NOT NULL,
  context           TEXT,
  embedding         BLOB,
  srs_step          INTEGER CHECK (srs_step BETWEEN 0 AND 3),
  srs_due           TEXT,
  created_at        TEXT NOT NULL,
  CHECK ((srs_step IS NULL) = (srs_due IS NULL))
) STRICT;

CREATE INDEX questions_topic ON questions(topic_id);
CREATE INDEX questions_due ON questions(srs_due) WHERE srs_due IS NOT NULL;

CREATE TABLE sessions (
  id            INTEGER PRIMARY KEY,
  profile_id    INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  provider      TEXT NOT NULL CHECK (provider IN ('ollama', 'anthropic', 'fake')),
  model         TEXT NOT NULL,
  difficulty    TEXT NOT NULL CHECK (difficulty IN ('easy', 'medium', 'hard')),
  status        TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'completed')),
  created_at    TEXT NOT NULL,
  completed_at  TEXT
) STRICT;

CREATE UNIQUE INDEX sessions_one_active ON sessions(profile_id) WHERE status = 'active';

CREATE TABLE attempts (
  id            INTEGER PRIMARY KEY,
  session_id    INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  question_id   INTEGER NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
  ord           INTEGER NOT NULL,
  is_review     INTEGER NOT NULL DEFAULT 0 CHECK (is_review IN (0, 1)),
  status        TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'active', 'done')),
  score         INTEGER CHECK (score BETWEEN 0 AND 100),
  completed_at  TEXT,
  UNIQUE (session_id, ord),
  CHECK ((status = 'done') = (score IS NOT NULL))
) STRICT;

CREATE INDEX attempts_question ON attempts(question_id);

CREATE TABLE turns (
  id             INTEGER PRIMARY KEY,
  attempt_id     INTEGER NOT NULL REFERENCES attempts(id) ON DELETE CASCADE,
  level          INTEGER NOT NULL CHECK (level BETWEEN 0 AND 2),
  prompt         TEXT NOT NULL,
  answer_text    TEXT,
  skipped        INTEGER NOT NULL DEFAULT 0 CHECK (skipped IN (0, 1)),
  answered_at    TEXT,
  score          INTEGER CHECK (score BETWEEN 0 AND 100),
  s_correctness  INTEGER CHECK (s_correctness BETWEEN 0 AND 4),
  s_depth        INTEGER CHECK (s_depth BETWEEN 0 AND 4),
  s_clarity      INTEGER CHECK (s_clarity BETWEEN 0 AND 4),
  s_structure    INTEGER CHECK (s_structure BETWEEN 0 AND 4),
  eval_json      TEXT,
  eval_model     TEXT,
  UNIQUE (attempt_id, level),
  CHECK (score IS NULL OR answer_text IS NOT NULL)
) STRICT;
```

Column notes:

| Column | Note |
|---|---|
| `profiles.resume_text` | The reviewed plain text. NULL until a resume is saved. |
| `profiles.resume_name` | The uploaded file name, for display only |
| `profiles.jd_text` | NULL means no job description |
| `profiles.plan_summary` | One or two sentences from the plan prompt |
| `resume_chunks.embedding`, `questions.embedding` | See section 6. NULL means "not embedded yet". |
| `topics.weight` | 0 switches the topic off. Topics are never deleted. |
| `topics.source` | `manual` marks a topic the user added |
| `questions.key_points` | A JSON array of 3 to 6 strings |
| `questions.context` | For resume probe questions, a copy of the resume excerpt the question was built from. A copy, not a reference, so replacing the resume cannot break old questions. |
| `questions.srs_step`, `questions.srs_due` | Review state, see section 3 |
| `attempts.ord` | Position in the session, starting at 1 |
| `turns.level` | 0 is the opening question, 1 and 2 are follow-ups |
| `turns.prompt` | The question text at level 0, the follow-up text otherwise |
| `turns.eval_json` | The validated `Evaluation` object as JSON |
| `turns.eval_model` | `provider:model` that produced the evaluation |

## 3. States and invariants

Turn:

| State | `answer_text` | `score` |
|---|---|---|
| Awaiting answer | NULL | NULL |
| Answered, not scored (scoring is running or failed) | text | NULL |
| Scored | text, or an empty string when skipped | 0 to 100 |

Attempt:

| Status | Meaning |
|---|---|
| `pending` | No turn has been answered |
| `active` | At least one turn has been answered |
| `done` | Finished. `score` and `completed_at` are set. |

Question review state:

| `srs_step` and `srs_due` | Meaning |
|---|---|
| Both NULL | Not in review: never failed, or retired from review |
| Both set | In review. `srs_step` is 0 to 3. Due when `srs_due` is today or earlier. |

Invariants. The database enforces the first six. Tests cover the rest.

1. A profile has at most one active session.
2. Positions are unique inside a session.
3. An attempt has at most one turn per level.
4. An attempt has a score exactly when it is `done`.
5. A turn can have a score only if it has an answer.
6. `srs_step` and `srs_due` are both NULL or both set.
7. An attempt's question belongs to the same profile as its session.
8. A turn's four dimension columns, `eval_json` and `eval_model` are set in the same statement as its `score`.
9. Turn levels of an attempt are contiguous from 0.
10. A session becomes `completed` in the same transaction that finishes its last attempt.

## 4. Profile isolation

- Every query that reads or writes profile data filters by `profile_id`, directly or through a join to `topics` or `sessions`.
- A route handler loads the profile named in the URL first and passes its id down. An object owned by another profile is a 404.
- Deleting a profile deletes every row that belongs to it, through the cascades above.

Two tests guard this: one creates two profiles with data and asserts that no page of one shows text from the other. One deletes a profile and asserts that no row in any table still refers to it.

## 5. Input limits

Each limit is a named constant. Input over a limit is rejected with a message. It is never cut silently.

| Input | Limit |
|---|---|
| Profile name, topic name | 1 to 60 characters |
| Resume file | At most 5 MB. Extensions `.pdf`, `.txt`, `.md`. |
| Resume text | 200 to 12,000 characters |
| Job title | At most 120 characters |
| Job description | At most 6,000 characters |
| Answer | 1 to 5,000 characters |
| Questions per session | 3, 5 or 10 |
| Resume chunk | At most 800 characters |
| Audio upload (M3) | At most 25 MB and 300 seconds |

## 6. Embeddings

- Embedded text: `resume_chunks.text` and `questions.text`.
- A vector is 384 little-endian 32-bit floats, 1,536 bytes, normalised to length 1.
- Write with `numpy.asarray(vec, dtype="<f4").tobytes()`. Read with `numpy.frombuffer(blob, dtype="<f4")`.
- Because vectors are normalised, cosine similarity is the dot product.
- `embeddings.backfill(conn)` runs at startup and embeds every row whose embedding is NULL.
- To change the embedding model, add a migration that sets every embedding to NULL. The next startup embeds everything again.

## 7. Connections, transactions and time

- Open with `sqlite3.connect(path, check_same_thread=False)`. Set `row_factory = sqlite3.Row`. Run `PRAGMA foreign_keys = ON` and `PRAGMA busy_timeout = 5000` on every new connection.
- `check_same_thread=False` is required. FastAPI can run a request's dependency and its handler on different worker threads. Each connection is still used by one request only.
- One connection per request, from the `get_db` dependency, closed in a `finally` block.
- Write inside `with conn:` blocks. Keep them short. No transaction is open during a model call.
- The journal mode stays at SQLite's default, so the database is exactly one file.
- Columns ending in `_at` hold UTC time as `YYYY-MM-DDTHH:MM:SSZ`, produced only by `db.utc_now()`.
- `srs_due` holds a local calendar date as `YYYY-MM-DD`. ISO dates compare correctly as text.

## 8. Migrations

- Files are named `app/migrations/NNN_name.sql`, numbered from 001.
- `PRAGMA user_version` holds the number of the last applied file.
- A merged migration file is never edited. A schema change is a new file.

Reference implementation. `executescript` commits first and then runs in autocommit mode, so the explicit `BEGIN` and `COMMIT` are what make a migration atomic.

```python
def migrate(conn: sqlite3.Connection) -> int:
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    for path in sorted(MIGRATIONS_DIR.glob("[0-9][0-9][0-9]_*.sql")):
        number = int(path.name[:3])
        if number <= current:
            continue
        sql = path.read_text(encoding="utf-8")
        try:
            conn.executescript(f"BEGIN;\n{sql}\nPRAGMA user_version = {number};\nCOMMIT;")
        except Exception:
            if conn.in_transaction:
                conn.rollback()
            raise
        current = number
    return current
```

## 9. Canonical queries

Questions due for review in a profile:

```sql
SELECT q.*
FROM questions q
JOIN topics t ON t.id = q.topic_id
WHERE t.profile_id = :profile_id
  AND q.srs_due IS NOT NULL
  AND q.srs_due <= :today
ORDER BY q.srs_due, q.id;
```

Stored questions of a topic that were never attempted:

```sql
SELECT q.*
FROM questions q
WHERE q.topic_id = :topic_id
  AND q.difficulty = :difficulty
  AND NOT EXISTS (SELECT 1 FROM attempts a WHERE a.question_id = q.id)
ORDER BY q.id;
```

The latest finished attempt of every question in the active topics of a profile. Readiness is computed from this.

```sql
SELECT q.id AS question_id, q.topic_id, a.score, a.completed_at
FROM questions q
JOIN topics t ON t.id = q.topic_id
JOIN attempts a ON a.id = (
  SELECT a2.id
  FROM attempts a2
  WHERE a2.question_id = q.id AND a2.status = 'done'
  ORDER BY a2.completed_at DESC, a2.id DESC
  LIMIT 1
)
WHERE t.profile_id = :profile_id AND t.weight > 0;
```

The current turn of an attempt:

```sql
SELECT * FROM turns WHERE attempt_id = :attempt_id ORDER BY level DESC LIMIT 1;
```

## 10. Voice columns (M3)

This is the content of `app/migrations/002_voice.sql`.

```sql
ALTER TABLE turns ADD COLUMN input_mode TEXT NOT NULL DEFAULT 'text' CHECK (input_mode IN ('text', 'voice'));
ALTER TABLE turns ADD COLUMN speech_ms INTEGER;
ALTER TABLE turns ADD COLUMN first_word_delay_ms INTEGER;
ALTER TABLE turns ADD COLUMN wpm INTEGER;
ALTER TABLE turns ADD COLUMN filler_count INTEGER;
```

The audio route writes these columns on the current turn when it transcribes a recording. A new recording for the same turn overwrites them.
