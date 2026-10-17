# FormFriend

Separate Phase 1 prototype: Next.js/React/TypeScript/Tailwind frontend and
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

## Phase 1 scope

Implemented: PDF size/signature checks, fillable text field extraction with
page/bounding-box references, validated StepFun simplification responses,
question-by-question UI, answer confirmation, editable review, memory-only
sessions with a one-hour expiry, session clearing, and labeled mock mode.
Server restart clears sessions. Never use real sensitive data for this demo.

Not yet implemented: OCR, arbitrary non-fillable PDFs, DOCX, voice input,
ElevenLabs audio, dynamic subquestions, answer interpretation/clarification,
PDF generation, answer-sheet downloads, production session authentication,
or deployment. Unsupported PDFs are rejected explicitly. Phase 1 does not
claim to fill or export original documents.

StepFun reference: https://platform.stepfun.com/cookbook/step-5-vision-structured

Try examples/demo-form.pdf for a synthetic three-question demonstration.

## Team workflow

After cloning this repository, follow the setup above. Each teammate needs
their own local environment; do not commit API keys or real user forms.
Use Node.js 22 LTS or newer and Python 3.11 or newer.

Create a feature branch for each task, push it, and open a pull request
against main. Run backend tests and the frontend build before requesting
review. Use the synthetic PDF in examples/ for demos.
