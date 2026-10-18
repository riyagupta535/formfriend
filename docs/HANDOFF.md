# Form Friend — project handoff

Prepared October 17, 2026. Source reviewed at commit `9db053a`
(`Add schema-driven backend tools for ElevenLabs agent`).

## Project and current status

Form Friend helps people complete forms through a friendly, mascot-led
conversation. Users upload a document, answer one question at a time by typing
or speaking, review their answers, and download a PDF.

The main application works as a local prototype. Its chat interface is driven
by extracted form questions; it is not yet a freely conversational AI agent.
ElevenLabs supplies read-aloud audio. Browser speech recognition supplies typed
transcripts. StepFun question simplification is optional and separate from voice.
A schema-driven backend for a future ElevenLabs conversational agent exists,
but connecting that agent to the frontend remains unfinished.

### What is implemented

| Area | Current behavior |
| --- | --- |
| Website | Landing, explanation, upload, chat, review, and voice-demo pages |
| Mascot | Transparent teal character on the right of the chat; floating motion, speaking glow, and audio-driven mouth overlay |
| Upload | One PDF or DOCX, or up to 10 PNG/JPG screenshots selected in page order |
| PDF extraction | Native controls, nearby question labels, printed questions, and scanned-form OCR |
| Screenshots | OCR, source references, confidence metadata, and overlapping-question deduplication |
| Questions | One question at a time, history, editing previous answers, skip, and in-page draft preservation |
| Voice output | ElevenLabs only; no browser-generated replacement voice |
| Voice input | Browser speech recognition for free-text answers; transcript remains editable |
| Review | Editable fields, explicit review confirmation, and atomic PDF export |
| Agent backend | Schema validation, canonical answer validation, conditional questions, revision checks, and review integration |

## Run locally

Use **Node 22.12+ within Node 22** and **Python 3.11 or 3.12**. Python 3.12 is
the suggested choice because the pinned RapidOCR package does not support 3.13.

From the repository root, on a new checkout:

```sh
nvm install
nvm use
python3.12 -m venv backend/.venv
backend/.venv/bin/pip install -r backend/requirements.txt
```

Copy `.env.example` to `.env` **only if `.env` does not already exist**.
Keep existing keys when updating a checkout.

Start the backend:

```sh
cd backend
.venv/bin/uvicorn app.main:app --reload --port 8000
```

In another terminal, from the repository root:

```sh
nvm use
cd frontend
npm ci
npm run dev
```

- Application: http://localhost:3000
- Backend health: http://localhost:8000/health
- Interactive API documentation: http://localhost:8000/docs
- Independent voice playground: http://localhost:3000/voice-demo

The backend permits frontend origins `http://localhost:3000` and
`http://localhost:3001`. Other origins need an explicit CORS update.
`NEXT_PUBLIC_API_URL` belongs in `frontend/.env.local` if the browser needs
an API address other than the default `http://localhost:8000`. Putting it only
in the root backend `.env` does not configure the Next.js browser bundle.

### Configuration

| Variable | Location | Purpose |
| --- | --- | --- |
| `ELEVENLABS_API_KEY` | Root `.env` | Server-side read-aloud credential |
| `ELEVENLABS_VOICE_ID` | Root `.env` | Selects the voice used for questions |
| `STEP_API_KEY` | Root `.env` | Optional question simplification; can remain empty |
| `STEP_BASE_URL` | Root `.env` | StepFun endpoint; defaults are in `.env.example` |
| `STEP_MODEL` | Root `.env` | Currently defaults to `step-5-preview` |
| `AGENT_TOOL_SECRET` | Root `.env` | Optional bearer secret protecting `/agent/*` routes |
| `NEXT_PUBLIC_API_URL` | `frontend/.env.local` | Browser-facing backend URL; contains no secrets |

Restart the backend after changing the root `.env`. It is loaded at process
startup. Restart Next.js after changing its environment configuration.
Changing credentials does not reprocess already-created sessions; upload again
if you want questions simplified using newly enabled StepFun credentials.

Do not commit `.env`, real user forms, or credentials. `.env.example` contains
variable names without secrets.

## Pages and frontend ownership

| Route | Purpose | Main implementation |
| --- | --- | --- |
| `/` | Product introduction and mascot | `frontend/app/page.tsx` |
| `/how-it-works` | Explanation and upload entry point | `frontend/app/how-it-works/page.tsx` |
| `/upload` | Document selection and extraction | `frontend/app/components/workflow.tsx` |
| `/questions` | Mascot-led conversation | `frontend/app/components/question-chat.tsx` |
| `/review` | Review, confirmation, and PDF download | `frontend/app/components/review-answers.tsx` |
| `/voice-demo` | Sample voice questions without upload | `frontend/app/voice-demo/page.tsx` |

Shared implementation:

- `workflow.tsx`: session retrieval, upload, navigation, draft answers, and
  saving ordinary question answers. The small route files select its stage.
- `answer-input.tsx`: text, checkbox/choice, and multi-choice answer controls.
- `frontend/components/VoiceControls.tsx`: ElevenLabs requests, audio lifecycle,
  microphone capture, mute, cancellation, and stale-result protection.
- `frontend/lib/useSpeechMouth.ts`: measures **question playback**, not the
  microphone, to drive the mascot mouth.
- `mascot.tsx`: image and mouth overlay. The mascot is horizontally mirrored.
- `frontend/public/images/formfriend-mascot-top-hat.png`: shared mascot asset, wearing a navy top hat with no antennae, orb, or tie (previous versions are retained).
- `frontend/app/globals.css`: shared visual styles, responsive chat layout,
  and motion rules. Tailwind tooling is also installed in the project.
- `shell.tsx`: navigation, workflow steps, and footer.

The browser stores the current session ID under `formfriend-session` in
`sessionStorage` and the mute preference under `formfriend-muted` in
`localStorage`. Unsent question drafts live in React memory; they do not
survive a refresh. Review edits stay local until successful export.

## Main document flow

1. `POST /sessions` accepts multipart `file`, or repeated `files` for screenshots.
2. `parser.py`, `ocr.py`, and `documents.py` extract questions and source metadata.
3. The backend attempts optional simplification. It runs at most three calls
   concurrently and waits at most 20 seconds overall. Unavailable or slow
   simplification leaves original wording and adds a session warning.
4. The frontend saves the session ID and opens `/questions`.
5. `VoiceControls` posts the current question to `/voice/speech`. Dictation
   edits the draft; it does not automatically save an answer.
6. Sending an answer posts it against its original field ID. The next question
   appears, while previous exchanges remain available for editing.
7. `/review` collects the complete edited answer snapshot. The user checks
   the review confirmation before downloading.
8. `POST /sessions/{id}/review/export` validates and generates the PDF before
   committing the reviewed answers. Export failure leaves stored answers
   unchanged and keeps the local edits available for retry.

### Backend file map

| File | Responsibility |
| --- | --- |
| `backend/app/main.py` | Upload, in-memory sessions, ordinary answers, source previews, route registration |
| `backend/app/models.py` | Extracted fields and ordinary sessions |
| `backend/app/parser.py` | Deterministic PDF controls, labels, grouping, and text-layer extraction |
| `backend/app/ocr.py` | RapidOCR processing, confidence, source geometry, screenshot deduplication |
| `backend/app/documents.py` | DOCX extraction and legacy/original-document export |
| `backend/app/conversation.py` | Optional StepFun simplification and explicit mock mode |
| `backend/app/voice.py` | ElevenLabs status and MP3 generation |
| `backend/app/review.py` | Validated, atomic final review and PDF generation |
| `backend/app/agent_models.py` | Step 5 schema, dependencies, and typed agent payloads |
| `backend/app/agent_tools.py` | Deterministic agent session and answer tools |
| `backend/scripts/extract_questions.py` | Inspect extraction without starting the API or calling an LLM |

### Key ordinary-session endpoints

| Method and path | Purpose |
| --- | --- |
| `GET /health` | Backend availability and simplification mode |
| `POST /sessions` | Upload and extract a form |
| `GET /sessions/{id}` | Retrieve session fields |
| `POST /sessions/{id}/fields/{field_id}` | Save one ordinary-session answer |
| `GET /sessions/{id}/fields/{field_id}/source` | Highlighted PDF page preview |
| `POST /sessions/{id}/review/export` | Validate reviewed snapshot and download PDF |
| `DELETE /sessions/{id}` | Clear session and original upload |
| `GET /voice/status` | Whether both ElevenLabs settings are present; does not verify the credential with the provider |
| `POST /voice/speech` | Generate question audio with ElevenLabs |

The older `GET /sessions/{id}/export` and session-scoped speech route remain
for compatibility. New frontend download work should use final review export.
Use `/docs` for exact request and response schemas.

## Voice behavior and integration boundary

Read-aloud uses the configured ElevenLabs voice and `eleven_flash_v2_5`.
It works without StepFun. If credentials are missing or the provider fails,
the page displays an error rather than substituting browser speech.
Autoplay can be blocked until the user clicks **Read question aloud**.

Voice input uses `SpeechRecognition` / `webkitSpeechRecognition` when available.
Microphone permission and browser support are required; audio may be processed
by the browser vendor. Typed answers remain available. Choice questions use
explicit options instead of free-form dictation.

Stop, mute, saving, field navigation, and unmount cancel active voice work.
Generation checks discard old audio responses and transcripts. Preserve this
behavior when modifying the chat; a late answer must never land on a new field.

**The current voice interface is TTS plus transcription, not an ElevenLabs
conversational-agent connection.** Free-form clarification and semantic answer
interpretation still need the agent integration below.

## Agent backend: implemented versus still to connect

Read [agent-tools.md](agent-tools.md) before integrating. It is the detailed
contract, including canonical values, authentication, conditions, and PDF mapping.
Use `examples/step5-questions.json` for a runnable schema.

Implemented endpoints:

- `POST /agent/sessions`: create a session from a supplied question schema;
  optionally link an original upload with `document_session_id`.
- `GET /agent/sessions/{id}/next-question`: choose the next applicable question.
- `POST /agent/sessions/{id}/answers`: validate and save a canonical answer.
- `POST /agent/sessions/{id}/skip`: skip an optional question.
- `GET /agent/sessions/{id}/questions/{question_id}/context`: retrieve context.

These tools do not call StepFun or ElevenLabs themselves. They support typed
answers, `equals` conditions, dependency validation, stale revision rejection,
and invalidation of dependent answers after a parent changes. Tool saves are
immediate; the final review is the confirmation point.

Remaining integration work:

1. Produce the supported schema from StepFun output and create the agent session.
   The current ordinary simplifier only rewrites individual labels; it is not
   the complete schema-generation pipeline.
2. Configure the actual ElevenLabs conversational agent and its backend tools.
3. Pass the backend-created session ID into the agent conversation. Never let
   the model invent session IDs. Pass revisions on writes.
4. Drive the UI from agent next-question states (`question`, `complete`,
   `blocked`) and route complete conversations to review.
5. Set `formfriend-session` to the agent session ID before opening `/review`.

Do not simply substitute an agent session ID into the current ordinary chat's
save endpoint: legacy answer/export routes reject agent sessions. Integrate the
agent tools explicitly. The review API already understands agent sessions.

A hosted agent cannot call the developer machine's `localhost`. Reachable hosting
and appropriate session authentication are needed before a shared deployment.
`AGENT_TOOL_SECRET` protects `/agent/*` only; it is not full application auth.

## Export behavior

| Uploaded source | Final review download |
| --- | --- |
| Fillable PDF | Original PDF with supported controls populated |
| Printed/scanned PDF | Original pages plus an appended answer sheet |
| DOCX | Clearly labeled PDF answer sheet alongside the original Word document |
| Screenshot(s) | Clearly labeled PDF answer sheet |

The legacy export route can return DOCX or text outputs; that is separate from
the current review screen's PDF-only flow. Exporting never submits a form.
Read-only controls, action buttons, and signatures are not filled. Editing a
signed PDF does not preserve the validity of an existing digital signature.

## Limits, state, and known gaps

- Local prototype: no production user authentication, database, or durable file
  storage. Sessions and original uploads live in backend memory for one hour;
  restarting the backend clears them. The upload path caps ordinary sessions
  at 50. Treat this as a local demo and use synthetic data.
- Uploads: 10 MB per file; up to 10 screenshots and 30 MB combined. PDFs are
  limited to 30 pages. The browser aborts uploads after two minutes.
- The 100-question restriction exists in multiple places: PDF extraction,
  agent schema validation, and final-review request validation. Some OCR paths
  return only the first 100 fields. Raising one limit is not sufficient.
- Scanned-PDF OCR currently returns the first page where usable questions are
  found. Do not assume a multi-page scanned form was fully extracted.
- OCR and printed-form grouping are heuristic. Confidence and source metadata
  help inspection but do not guarantee completeness. Multi-screenshot deduplication
  can confuse similar questions; compare against the original form.
- Native-control extraction does not imply every printed question on the same
  PDF page was detected. DOCX extraction uses paragraph punctuation; it does
  not map Word content controls or accurate page layout.
- Password-locked PDFs must be unlocked before upload. Handwriting, arbitrary
  layouts, XFA forms, and every possible PDF control are not guaranteed.
- Multi-select PDF controls use standard AcroForm value arrays and may depend
  on the PDF viewer regenerating appearances.
- Review edits are not saved just by typing. They save together on successful
  export; leaving the page can lose unsaved edits.
- StepFun receives question labels; ElevenLabs TTS receives question text.
  Browser recognition may send microphone audio to its vendor. A future
  conversational agent will introduce its own data flow and must be documented.

## Verification and demo checklist

From the repository root, inspect extraction without API/provider calls:

```sh
backend/.venv/bin/python backend/scripts/extract_questions.py examples/demo-form.pdf
```

Run the existing checks:

```sh
cd backend
.venv/bin/python -m pytest -q
cd ../frontend
npm test
npm run typecheck
npm run build
```

If Turbopack cannot launch its CSS subprocess in a restricted environment:

```sh
npm run build -- --webpack
```

Frontend tests cover voice cancellation, transcripts, question navigation,
chat history/drafts, mouth animation, and final review. Backend tests cover
extraction, PDF controls/export, voice requests, bounded simplification,
review validation, and agent tools. Provider calls and browser APIs are mocked
where appropriate; passing tests do not verify a real microphone, voice account,
or every uploaded form.

Before a demo:

1. Start both servers with the correct runtime versions.
2. Upload `examples/demo-form.pdf` and inspect question/source alignment.
3. Confirm the configured ElevenLabs voice plays; test mute and stop.
4. Dictate an answer, edit the transcript, and send it.
5. Confirm history, previous-answer editing, and draft preservation.
6. Review all answers, check the confirmation, and download the PDF.
7. Open the PDF and compare actual fields/answer sheet with the source.
8. Test screenshots, DOCX, and agent tools separately when demonstrating them.

This handoff is a documentation change. Source and configuration contracts were
inspected; the test suites and live integrations were not rerun for this document.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Push rejected with “fetch first” | Fetch, inspect, and merge the remote changes; resolve/test before pushing. Avoid force-pushing shared `main`. |
| UI says simplification is off | `STEP_API_KEY` controls simplification; it does not indicate whether ElevenLabs works. |
| Voice unavailable after editing `.env` | Restart backend; check both ElevenLabs settings. Status only checks presence, not key validity. |
| No audio on initial question | Unmute and click **Read question aloud** to satisfy browser autoplay rules. |
| Microphone button disabled | Browser may lack speech recognition; use supported browser/permission settings or type. |
| Upload cannot reach API | Backend must run on port 8000; check browser API URL and CORS. |
| Session missing after restart | Expected for memory-only sessions; upload again. |
| OCR install fails on Python 3.13 | Recreate the virtual environment with Python 3.12 and reinstall requirements. |
| Form exceeds 100 questions | Inspect extraction/grouping; coordinate any limit changes across parser, OCR, agent schema, and review. |
| Extraction misses later scanned pages | Current first-detected-page OCR limitation; split pages or use ordered screenshots. |

## Suggested next work

1. Connect the schema-driven agent backend to the configured ElevenLabs agent
   and frontend, retaining field identity, revision checks, and final review.
2. Evaluate extraction against a small set of synthetic representative forms;
   improve multi-page OCR coverage and grouping before increasing field limits.
3. Add browser QA for actual playback, microphone permissions, mobile layout,
   and the appearance of exported controls in more than one PDF viewer.
4. Add user-owned durable sessions, authenticated endpoints, and hosting before
   real-user deployment.

See also [README](../README.md), [agent tool contract](agent-tools.md), and
[mascot generation notes](mascot-generation.md).
