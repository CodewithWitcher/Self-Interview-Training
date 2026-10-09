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
