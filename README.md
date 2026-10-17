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

Without STEP_API_KEY the UI explicitly labels its mock mode. Set the key
in the root .env to use Step 5 Preview; no other model is substituted.
STEP_BASE_URL and STEP_MODEL are configurable. Real-provider calls require
credentials and are not covered by offline tests.

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

Fillable PDFs retain the original PDF and populate its text fields. PDFs
with other control types or no fillable text fields are rejected explicitly.
DOCX extraction recognizes paragraphs with question marks, colons, or blank
answer lines; export appends answers to those paragraphs while retaining the
other document files. It does not map Word content controls or reproduce page
numbers. Screenshots use local Tesseract OCR to identify question lines and
export a text answer sheet. OCR is heuristic: check extracted questions before
using the output. Screenshot users are prompted to upload a fillable version.

Install the `tesseract` executable on the backend host for screenshot uploads
(for example, `brew install tesseract` on macOS). Missing OCR is reported in
the upload UI. No extra Python packages are needed.

Read-aloud uses ElevenLabs when both `ELEVENLABS_API_KEY` and
`ELEVENLABS_VOICE_ID` are set in the root `.env`, and otherwise falls back to
browser speech synthesis. Browser autoplay restrictions can require clicking
“Read this question.” Voice input uses the browser speech recognition API
where available; microphone permission is required. Browser voice recognition
may use the browser vendor's speech service. Mute preference is saved locally.

StepFun receives extracted field labels when configured; ElevenLabs receives
simplified questions when configured. Neither receives the original document
or answers through these integrations. Provider integration references:
[StepFun](https://platform.stepfun.com/cookbook/step-5-vision-structured) and
[ElevenLabs](https://elevenlabs.io/docs/api-reference/text-to-speech/convert).

Sessions and original uploads stay in temporary backend memory for one hour;
the browser stores only the session ID for navigation. Restarting the backend
clears all sessions. This local prototype has no production authentication.
Dynamic follow-up subquestions and answer interpretation are not implemented.
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
No upload or Step 5 credentials are needed for this route. It uses three
sample questions and shows confirmed answers with their field IDs, ready
for integration with the answer-processing service. Actual question audio
requires the ElevenLabs environment variables described above.

Run frontend voice interaction tests with `cd frontend && npm test`.
Tests mock speech recognition and audio playback; they do not verify a real
microphone or make billable ElevenLabs calls.
