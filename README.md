# FormFriend

Local multipage prototype: Next.js/React/TypeScript/Tailwind frontend and
FastAPI backend.

## Run

From this project directory:

```sh
cp .env.example .env
python3 -m venv backend/.venv
backend/.venv/bin/pip install -r backend/requirements.txt
cd backend
.venv/bin/uvicorn app.main:app --reload --port 8000
```

In another terminal:

```sh
cd frontend
npm install
npm run dev
```

Open http://localhost:3000. Keep port 8000 local; this prototype has no
production authentication. Set NEXT_PUBLIC_API_URL in frontend/.env.local
if your backend address differs.

To inspect the deterministic extraction result without starting the API or
calling an LLM:

```sh
backend/.venv/bin/python backend/scripts/extract_questions.py path/to/form.pdf
```

The JSON includes a stable field ID, explicit printed question number and section
title when available, the inferred original label, answer type, PDF field names,
page/rectangle source reference, nearby source text, extraction confidence, OCR
confidence when applicable, and whether the source was a fillable widget, regular
PDF text layer, or scanned page. Related
checkbox options are returned as one choice question.

Without `GEMINI_API_KEY` the UI explicitly labels its mock mode. Set the key
in the root `.env` to use Gemini. `GEMINI_BASE_URL`, `GEMINI_MODEL`, and
`GEMINI_THINKING_LEVEL` are configurable. The default is
`gemini-3.5-flash-lite` with minimal thinking. Real-provider calls require
credentials. Each question is sent in its own JSON-mode request, with up to
three requests running concurrently. Returned JSON is validated locally.
The model receives the stable field ID, label,
answer type, choices, section, and bounded nearby text—not the original file or
user answers. Upload returns as soon as extraction finishes; Gemini runs in
tracked background batches while the questions page polls for completed results.
Invalid or unavailable batches are attempted up to three times with exponential
backoff, honoring a provider `Retry-After` delay when supplied. A batch that still
fails is split into individual question requests so one bad result does not discard
the other questions. Pending fields display a loading state while each completed
batch becomes usable. Clearing or expiring a session cancels its unfinished task.
If Gemini ends with `finishReason: MAX_TOKENS`, the retry budget increases from 4,096
to 8,192 and then 16,384 tokens so complex decision trees can finish their JSON.

For complex choice fields, Gemini may return a short conditional decision tree
instead of a generic “Select your…” prompt. Each path is limited to three
questions, every branch must resolve to an exact original form option, and the
backend rejects changed, missing, duplicated, or unreachable choices. The UI
skips irrelevant follow-ups and saves only the resolved original option.

## Tests

```sh
cd backend
.venv/bin/python -m pytest -q
cd ../frontend
npm run typecheck
npm run build
```

## Multipage workflow

- `/`: introduction with an animated teal mascot and a link to get started.
- `/upload`: drag and drop a PDF, DOCX, PNG, or JPG (up to 10 MB).
- `/questions`: simpler questions, typed or spoken answers, read-aloud with
  mute, progress, and original field details. PDF details include a page preview
  with the current field outlined.
- `/review`: edit answers and download the resulting document.

Fillable PDFs retain the original PDF and populate its text fields. Regular
PDFs with text layers and scanned PDFs use conservative question extraction;
scanned PDF fields include OCR confidence and source bounding boxes. The OCR
prototype stops after the first detected form page to avoid processing long
instruction appendices.
DOCX extraction recognizes paragraphs with question marks, colons, or blank
answer lines; export appends answers to those paragraphs while retaining the
other document files. It does not map Word content controls or reproduce page
numbers. Screenshots and scanned PDFs use the bundled RapidOCR runtime to find
numbered prompts, common identity/address fields, and question-like labels.
Screenshot answers export as a text answer sheet. OCR is heuristic, so check
every extracted question against the source image. No separate Tesseract
installation is required.

Upload up to 10 PNG/JPG screenshots together, in page order, for one form.
Each image may be up to 10 MB and the batch may be up to 30 MB. Questions in
overlapping regions are compared using normalized labels, printed question
numbers, section identity, and fuzzy text similarity. The higher-confidence OCR
copy is retained, along with its source screenshot number and rectangle.

Read-aloud uses ElevenLabs when both `ELEVENLABS_API_KEY` and
`ELEVENLABS_VOICE_ID` are set in the root `.env`, and otherwise falls back to
browser speech synthesis. Browser autoplay restrictions can require clicking
“Read this question.” Voice input uses the browser speech recognition API
where available; microphone permission is required. Browser voice recognition
may use the browser vendor's speech service. Mute preference is saved locally.

Gemini receives extracted field labels when configured; ElevenLabs receives
simplified questions when configured. Neither receives the original document
or answers through these integrations. Provider integration references:
[Gemini](https://ai.google.dev/gemini-api/docs) and
[ElevenLabs](https://elevenlabs.io/docs/api-reference/text-to-speech/convert).

Sessions and original uploads stay in temporary backend memory for one hour;
the browser stores only the session ID for navigation. Restarting the backend
clears all sessions. This local prototype has no production authentication.
Gemini can return up to three short explanatory subquestions per field; they are
stored as guidance while the original field retains one answer. Conditional
subquestions use the validated decision-tree flow described above.
Real-provider calls require credentials and are not covered by offline tests.

Try `examples/demo-form.pdf` for a synthetic three-question demonstration.
If Turbopack cannot start its CSS subprocess in a restricted environment,
verify the production build with `npm run build -- --webpack`.

## Team workflow

After cloning this repository, follow the setup above. Each teammate needs
their own local environment; do not commit API keys or real user forms.
Use Node.js 22 LTS (22.12 or newer within Node 22) and Python 3.11 or newer.
If using nvm, run `nvm install` and `nvm use` from the project root.

Create a feature branch for each task, push it, and open a pull request
against main. Run backend tests and the frontend build before requesting
review. Use the synthetic PDF in examples/ for demos.

## Independent voice controls and demo

The `/questions` workflow uses its own read-aloud controls and browser voice
fallback. The reusable controls and `/voice-demo` below use ElevenLabs only
for playback and report an error when it is unavailable.

Set ELEVENLABS_API_KEY and ELEVENLABS_VOICE_ID in the root .env, then
restart the backend. Select “Read question aloud” to play a supplied
question through ElevenLabs. Select “Answer with microphone” to dictate
in a browser supporting SpeechRecognition (typically Chrome; availability
varies). Grant microphone permission. Recognition may use the browser
vendor's remote service. Audio playback stops microphone capture and vice
versa. Stop, mute, navigation, and unmount cancel active voice work.

Edit the transcript in the answer box and explicitly confirm to save it
against the original field ID. Missing TTS credentials produce a labeled
unavailable message; no substitute voice provider is used. Typed answers
remain available. This milestone transcribes answers verbatim; semantic
interpretation and clarification remain the conversation backend's job.

The reusable frontend/components/VoiceControls.tsx accepts question,
fieldId, answer, and onAnswer props so teammates can supply simplified
questions independently of document extraction.

### Independent voice demo

With frontend and backend running, open http://localhost:3000/voice-demo.
No upload or Gemini credentials are needed for this route. It uses three
sample questions and shows confirmed answers with their field IDs, ready
for integration with the answer-processing service. Actual question audio
requires the ElevenLabs environment variables described above.

Run frontend voice interaction tests with `cd frontend && npm test`.
Tests mock speech recognition and audio playback; they do not verify a real
microphone or make billable ElevenLabs calls.
