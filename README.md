# forma

The friendly teal mascot is **Fomy**. The brand mark is a speech bubble with a lowercase **f**.

Local multipage prototype: Next.js/React/TypeScript/Tailwind frontend and
FastAPI backend.

For setup, architecture, integration status, known limits, and next steps, see
[the project handoff](docs/HANDOFF.md).

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
- `/questions`: a chat with the mascot on the right, typed or spoken replies,
  saved conversation history, editable previous answers, read-aloud with mute,
  progress, and original field details. PDF details include a page preview
  with the current field outlined.
- `/review`: edit answers and download the resulting document.

PDF uploads can contain text fields, checkboxes, radio groups, dropdowns,
single- or multiple-selection lists, printed questions, and scanned pages.
Native controls are completed in the original PDF; answers for printed or
scanned pages are appended as a PDF answer sheet with original page references.
Printed question detection uses labels and punctuation, so it can miss questions
or mistake headings for questions. Check the extracted questions and source
previews. Pages with native controls use their field labels to avoid duplicates;
additional printed questions on those same pages are not detected automatically.
Limits: 10 MB, 30 pages, and 100 questions
per PDF. Blank, unreadable, or password-locked PDFs produce clear errors.
Read-only fields, signature fields, and action buttons are skipped without
rejecting other controls. The app cannot sign PDFs or preserve the validity of
existing digital signatures after editing. Multi-select values are stored using
standard AcroForm arrays; viewers need to regenerate their appearances.
Scanned PDF fields include OCR confidence and source bounding boxes. The OCR
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

Read-aloud exclusively uses the ElevenLabs voice configured by
`ELEVENLABS_API_KEY` and `ELEVENLABS_VOICE_ID` in the root `.env`. Restart the
backend after changing these settings. StepFun is not required for voice.
If ElevenLabs is unavailable, the page reports an error instead of changing
to a browser voice. Browser autoplay restrictions can require clicking
“Read question aloud.” Voice input uses the browser speech recognition API
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

## Integrated voice controls and demo

The `/questions` workflow and `/voice-demo` share the reusable
`frontend/components/VoiceControls.tsx` and backend `/voice/speech` endpoint
from the voice-conversation branch. Questions automatically play when sound
is enabled; the mascot reacts while audio plays. Both routes use ElevenLabs
exclusively for playback and show an error if it is unavailable. Mute
preference is retained locally.

Set ELEVENLABS_API_KEY and ELEVENLABS_VOICE_ID in the root .env, then
restart the backend. Select “Read question aloud” to play a supplied
question through ElevenLabs. Select “Answer with microphone” to dictate
in a browser supporting SpeechRecognition (typically Chrome; availability
varies). Grant microphone permission. Recognition may use the browser
vendor's remote service. Audio playback stops microphone capture and vice
versa. Stop, mute, navigation, and unmount cancel active voice work.

Edit the transcript in the answer box and explicitly confirm to save it
against the original field ID using “Send answer” (or “Send & review” for the final question). Selecting another
question or saving cancels active audio and capture; late transcripts are
discarded. Checkbox and choice questions offer read-aloud and their original
answer options instead of free-form dictation. Typed answers remain available. This milestone transcribes answers verbatim; semantic
interpretation and clarification remain the conversation backend's job.

The reusable frontend/components/VoiceControls.tsx accepts question,
fieldId, answer, and onAnswer props, plus optional autoPlay, allowDictation,
disabled and onSpeakingChange props. Both the generic
`POST /voice/speech` endpoint and the existing session-scoped speech endpoint
use the same ElevenLabs provider code.

### Independent voice demo

With frontend and backend running, open http://localhost:3000/voice-demo.
No upload or Gemini credentials are needed for this route. It uses three
sample questions and shows confirmed answers with their field IDs, ready
for integration with the answer-processing service. Actual question audio
requires the ElevenLabs environment variables described above.

Run frontend voice interaction tests with `cd frontend && npm test`.
Tests mock speech recognition and audio playback; they do not verify a real
microphone or make billable ElevenLabs calls.

## Final review and PDF export

After the last answer, `/review` shows all original questions and editable
answers, with blank fields marked clearly. Edits stay on the review page until
export. Check **I’ve reviewed my answers** to enable **Download PDF**; changing
an answer resets that confirmation. Blank answers are allowed and remain blank.

`POST /sessions/{id}/review/export` validates the entire reviewed snapshot,
generates the PDF, and saves the answers together only if generation succeeds.
It rejects duplicate, missing, or unknown field IDs and invalid choice values.
Failures leave the review edits available for retry; no partial save is made.

For PDF uploads the original PDF is retained and fillable fields are populated;
printed/scanned questions use the existing appended answer sheet. For Word and
image uploads, this review action produces a clearly labeled PDF answer sheet,
not a claim that the original file has been filled. The older export endpoint
remains available for existing clients. Export does not submit an application.

Upload simplification runs at most three provider calls concurrently and stops
waiting after 20 seconds. Questions that could not be simplified retain their
original wording, with an explicit session warning. The browser also times out
uploads after two minutes rather than showing an endless loading state.

Scanned PDFs and screenshots require the OCR dependencies. Use Python 3.11 or
3.12 for the pinned `rapidocr-onnxruntime` package; it does not support Python
3.13. Create your backend virtual environment with Python 3.12, then install
`backend/requirements.txt` before starting the backend.

## ElevenLabs agent backend tools

The Step 5 question-schema adapter and deterministic agent tools are implemented.
See [the agent tool contract](docs/agent-tools.md) for routes, canonical answer
formats, conditional-question behavior, PDF mapping, and final review integration.
Try `examples/step5-questions.json` with `POST /agent/sessions`. These APIs do not
require an ElevenLabs agent or an LLM to test. Connecting the configured agent and
passing the session ID from the frontend remain integration tasks.

### Multilingual form conversations

Upload a file from **Upload your form**. The next page asks which language Fomi should use; choose your language and select **Continue to questions**. The site navigation and buttons stay in English. Document questions, answer-choice labels, helpful explanations, validation feedback, and Fomi’s conversation use your selected language. Choices are English, Spanish, Chinese, Tagalog, Vietnamese, Arabic, French, Korean, Portuguese, and Hindi. Chinese uses Simplified Chinese text and Mandarin speech; Tagalog uses `fil` in form sessions and text-to-speech, adapted to `tl` for the conversation SDK; Arabic uses Modern Standard Arabic with right-to-left question text; Portuguese uses Brazilian Portuguese. The preference belongs to the form session and survives a page refresh and voice-session restart.

Question translation uses the existing `GEMINI_API_KEY`. If translation is unavailable, the guide explicitly shows a notice with **Retry translation** and keeps the original question available. Translations are cached per question and refreshed if background simplification changes its wording.

The original form wording, field IDs, calculations, and saved choice values remain intact for export. Names, addresses, and free-text answers are saved as entered; this feature does not automatically translate a completed document or its answers into English. Spanish dates such as `2 de enero de 2000` are accepted; numeric date entry retains the displayed month/day/year convention.

For multilingual voice, the existing ElevenLabs agent must allow per-conversation language overrides. Enable just that setting, preserving its current voice, prompt, and tools:

```bash
cd backend
.venv/bin/python scripts/setup_elevenlabs_agent.py --enable-language-selection
```

The full agent setup/update command also enables the language override for future installations. The browser supplies the selected language code and a matching opening greeting, including when resuming a conversation. The same ElevenLabs key and agent serve all ten languages. Voice pronunciation still needs listening checks with fluent speakers.
