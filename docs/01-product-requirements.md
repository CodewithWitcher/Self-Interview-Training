# Product requirements

Status: draft 1, written 2026-10-08. Items marked **Assumed** are defaults chosen without the owner's confirmation. To overrule one, change it here first, then in the documents that depend on it.

Related documents: [architecture](02-architecture.md), [data model](03-data-model.md), [prompts and scoring](04-prompts-and-scoring.md), [setup guide](05-setup-guide.md), [task breakdown](06-task-breakdown.md).

## 1. What this is

Self Interview Training (working name) is a private interview practice app that runs on your own computer. You give it your resume. It builds a practice plan, asks interview questions, probes your answers with follow-ups, scores every answer against a fixed rubric, brings weak questions back on a schedule, and shows how ready you are. With a local model, nothing you type or say leaves the machine.

What sets it apart from existing tools: it is local first, grounded in your own resume, keeps separate profiles, and resumes a session exactly where you stopped.

## 2. Who uses it

One person at a time, on their own Windows PC or Mac. Several profiles can live on one machine, for example two career tracks or two people. There are no accounts and no login.

## 3. Product decisions (Assumed)

| # | Decision | Default used in these documents | Alternative |
|---|---|---|---|
| P1 | Which extras from the idea file are in v1 | Five: follow-up drilling, spaced repetition, job description mode, readiness score, resume probe | Swap one for another from section 7. Keep the total at five or fewer. |
| P2 | When voice is built | Last, as milestone M3, after the text product is complete | Build it earlier. It carries most of the cross-platform risk. |
| P3 | Job targets per profile | One resume and at most one job description per profile. A second job target is a second profile. | Several targets per profile. Needs two more tables and a target switcher. |
| P4 | Cloud model provider | Claude only | Add OpenAI as a third provider function. |
| P5 | Language | English only | None planned. |
| P6 | Distribution | Run from a clone of the repository. No installer. | Package later with a desktop wrapper. |

Technical decisions are recorded in the [architecture](02-architecture.md) document, section 2.

## 4. Milestones

Every milestone ends with an app that starts and works on both Windows and Mac.

| Milestone | Name | Contains | Result |
|---|---|---|---|
| M0 | Skeleton | Repository, tooling, database, empty web app, status page, CI on both systems | The app starts and its tests pass on both systems |
| M1 | Core loop, text | F1 to F10 | A usable practice tool |
| M2 | Retention and targeting | F11 to F13 | **v1 complete** |
| M3 | Voice | F14 to F16 | v1.1 |

## 5. Features and acceptance criteria

Each numbered line is a testable statement. Tasks in the [task breakdown](06-task-breakdown.md) refer to them as, for example, F5.6.

### F1. Profiles (M1)

A profile holds one person's resume, plan, questions and history.

1. A profile is created with a name of 1 to 60 characters. A name that already exists, ignoring case, is rejected with a message.
2. The home page lists every profile.
3. Deleting a profile requires typing the profile's name. It then removes the profile's resume, plan, questions, sessions and answers.
4. Nothing from one profile is ever shown or used in another.

### F2. Resume intake (M1)

1. The user uploads a PDF, TXT or MD file of at most 5 MB, or pastes text.
2. The extracted text appears in an editable box. Nothing is saved until the user presses Save.
3. Saved text must be 200 to 12,000 characters. Outside that range the app explains the limit and keeps what the user entered.
4. A wrong file type, an oversized file, a password-protected PDF, or a PDF with no extractable text is rejected with a message that suggests pasting the text.
5. Saving a new resume replaces the old one. Existing questions and history are kept.
6. The original file is not stored. Only the reviewed text is.

### F3. Prep plan (M1)

1. "Build plan" reads the resume and produces up to 10 topics. Each has a name, a kind, a weight from 1 to 5, a source, and a one-sentence reason.
2. The plan always contains at least one behavioral topic and the topic "Resume deep-dive".
3. The user can set a topic's weight from 0 to 5. Weight 0 switches the topic off without deleting its history.
4. The user can add a topic by name and kind.
5. Rebuilding the plan keeps topic history, keeps manually added topics, and switches off topics that the new plan no longer contains.
6. The plan is rebuilt only when the user asks.

### F4. Practice session (M1)

1. To start, the user picks one or more topics, 3, 5 or 10 questions, a difficulty (easy, medium or hard) and a model.
2. The session uses stored questions that were never attempted before it generates new ones.
3. A new question is never a near copy of a question the profile already has.
4. If fewer questions than requested can be produced, the session starts with what is available and says so. If none can be produced, no session is created and the reason is shown.
5. Each question shows its topic, difficulty and position, for example "2 of 5".
6. A profile has at most one active session.
7. The user can skip a question or end the session early. Ending discards anything not yet scored, after a confirmation that says so.
8. A finished session shows a summary: every question with its score, the session average, and the weakest rubric dimension.

### F5. Answer scoring and feedback (M1)

1. An answer is 1 to 5,000 characters. A character counter is shown.
2. After submitting, the user sees a score from 0 to 100, four rubric dimensions from 0 to 4 (correctness, depth, clarity, structure), up to three strengths, up to three gaps, and 2 to 4 sentences of feedback.
3. For the opening question the user also sees which key points the answer covered and which it missed.
4. The reference answer is shown only after the last follow-up for that question, or after a skip.
5. The score is computed by code from the four dimensions. The same dimension values always give the same score.
6. The answer is saved before the model is called. If scoring fails, the answer is still there, with a Retry button.
7. A skipped question scores 0.

### F6. Follow-up drilling (M1)

1. After scoring an answer, the interviewer may ask one follow-up that probes something in that answer.
2. A question has at most two follow-ups.
3. Each follow-up answer is scored like any other answer.
4. The question's score is the average of its answer scores.
5. No follow-up is asked after a skip.

### F7. Resume probe (M1)

1. Each question in the "Resume deep-dive" topic is built from one excerpt of the resume.
2. The excerpt is shown with the question, under "From your resume".
3. Feedback names any statement in the answer that contradicts the excerpt.

### F8. Session resume (M1)

1. Everything submitted is saved at once. Closing the browser or stopping the app loses nothing that was submitted.
2. The profile home shows "Continue session, question 3 of 5" while a session is active.
3. Continuing opens the exact pending step: an unanswered question, a pending follow-up, or an answer waiting for a scoring retry.

### F9. Model choice and privacy indicator (M1)

1. For each session the user picks Local (Ollama) or Cloud (Claude), and a model. The default is the last choice for that profile, and Local on first use.
2. Every session page shows a badge: "Local: nothing leaves this computer" or "Cloud: your answers and resume excerpts are sent to Anthropic".
3. An Ollama model that runs on a remote host is never offered as a local model.
4. The model can be changed during a session.
5. If no usable model exists, the start form explains what is missing and links to the status page.

### F10. Status page (basic version in M0, complete in M1)

1. The page shows pass or fail for: data folder writable, database version, embedding model present, Ollama reachable with its local models, Claude credentials present.
2. "Test model" sends a tiny prompt to the selected model and shows the elapsed time or the error.
3. The same checks run from the command line and return a non-zero exit code when a required check fails.

### F11. Job description mode (M2)

1. The user pastes a job title and a job description of at most 6,000 characters. Both are saved on the profile.
2. Rebuilding the plan with a job description labels each topic as coming from the resume, the job description, or both.
3. A topic that only the job description asks for is labelled "Gap" and gets a weight of at least 3.
4. Removing the job description and rebuilding returns to a resume-only plan. History is kept.

### F12. Spaced repetition (M2)

1. A question whose score is below 75 becomes due for review the next day.
2. A passed review moves the question along a ladder of 1, 3, 7 and 14 days. A review scoring 50 to 74 repeats the current step. A review below 50 restarts the ladder.
3. Passing the last step retires the question from review.
4. The profile home shows "Due today: N".
5. A session fills up to half of its questions with due reviews from the chosen topics. "Review only" fills the whole session with due reviews from all topics.

### F13. Readiness and progress (M2)

1. The progress page shows one readiness number from 0 to 100 for the profile.
2. It shows a bar per active topic with its score and its number of answered questions, and names the weakest rubric dimension.
3. It lists past sessions with date, model, number of questions and average score.
4. A topic that was never practised counts as zero.
5. With no history, the page shows an explanation instead of empty charts.

### F14. Spoken answers (M3)

1. A Record button starts and stops a recording of at most 5 minutes.
2. The recording is transcribed on this computer. The transcript is placed in the answer box, where the user can edit it before submitting.
3. Audio is never written to disk. It is discarded after transcription.
4. A denied microphone, a silent recording, and unreadable audio each produce a clear message. Typing always remains possible.

### F15. Read question aloud (M3)

1. A button reads the current question or follow-up with a voice installed on the computer.
2. A voice that needs a network service is never used.
3. The button is hidden when the browser has no suitable voice.

### F16. Delivery metrics (M3)

1. For a spoken answer, the feedback also shows speaking pace in words per minute, a filler word count, and the delay before the first word.
2. They are labelled as approximate and never change the score.

## 6. Screens

| Screen | Shows | Main actions |
|---|---|---|
| Home | All profiles | Create a profile, open a profile |
| Profile home | Readiness (M2), due count (M2), active session, start form | Start or continue a session, open resume, plan or progress, delete the profile |
| Resume | Current resume text | Upload or paste, review, save |
| Plan | Job description box (M2), topics with weight, source and reason | Build or rebuild, set a weight, add a topic |
| Question | The question, the thread of answers and feedback, the privacy badge | Submit, skip, retry scoring, next question, change model, end session. In M3: record, read aloud |
| Summary | Every question of the session with its score | Back to profile home |
| Progress (M2) | Readiness, topic bars, past sessions | None |
| Status | Environment checks | Test model |

## 7. Non-goals

Not in v1 or v1.1. An agent must not build these without a change to this document.

From the idea file's list of extras:

- Full mock interview with several rounds
- Interviewer personas
- Adaptive difficulty with a rating system. Difficulty is chosen by the user.
- Side-by-side replay of old and new answers
- A similarity score against the reference answer
- Video analysis
- Multi-agent evaluation
- A fine-tuned local evaluator
- A concept knowledge graph
- A separate hallucination detector

Product and platform:

- Accounts, login, sync, or any hosted service
- Mobile layouts and mobile apps
- An installer or desktop wrapper
- Linux and Intel Macs. They may work but are never verified.
- Languages other than English
- DOCX upload, export, import
- Running code written by the candidate
- OpenAI and other cloud providers
- Streaming model output token by token
- Hands-free voice: automatic end-of-speech detection and automatic reading of questions
- Storing audio
- GPU acceleration for speech recognition

## 8. Quality requirements

| Area | Requirement |
|---|---|
| Privacy | No telemetry. No assets from a CDN. The server listens on the loopback address only. Outbound traffic goes only to the chosen model provider and, during setup, to model downloads. |
| Offline | With a local model selected and setup complete, every feature works with networking switched off. |
| Platforms | Windows 10 or 11 on x64. macOS 14 or later on Apple Silicon. Current Chrome or Edge on Windows, current Chrome or Safari on Mac. |
| Hardware | 16 GB of RAM to run the default local model. 8 GB is enough with a small local model or with the cloud model. About 8 GB of free disk. Details are in the [setup guide](05-setup-guide.md). |
| Responsiveness | Every action that calls a model shows a busy state at once. A model call that exceeds the time limit (default 180 seconds) ends in an error the user can retry. |
| Data safety | A submitted answer is saved before any model call. No model failure loses user input. |
| Accessibility | Every control has a label and is reachable by keyboard. Focus is visible. Text meets WCAG AA contrast. No information is carried by colour alone. |
| Security | Rules are in the [architecture](02-architecture.md) document, section 9. |

## 9. Glossary

| Term | Meaning |
|---|---|
| Profile | One person's or one job target's workspace: resume, plan, questions, history |
| Topic | A subject to practise, with a kind: technical, behavioral, or resume probe |
| Question | A stored interview question with key points and a reference answer |
| Session | One sitting of 3, 5 or 10 questions |
| Attempt | One pass at one question inside a session, including its follow-ups |
| Turn | One prompt and its answer: the opening question (level 0) or a follow-up (level 1 or 2) |
| Answer score | 0 to 100 for one turn. The idea file calls this the confidence score. |
| Attempt score | The average of the answer scores in one attempt |
| Readiness | 0 to 100 for the whole profile |
| Due | A question scheduled for review today or earlier |
