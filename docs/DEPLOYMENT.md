# Deploy Forma: Vercel frontend + Render backend

The repository contains two services. Deploy `frontend/` on Vercel and the
FastAPI service on Render. Uploads go directly from the browser to the backend;
do not proxy them through Vercel Functions. The backend stores uploads and
sessions in process memory and runs background tasks, so use one persistent
process, one worker, and one service instance.

## 1. Sync the repository

Pull remote `main`, run the checks, commit deployment configuration, and push
before creating the hosted services. Both providers must deploy the same latest
commit of `main`.

## 2. Create the Vercel project

Import `riyagupta535/formfriend` from GitHub. Set **Root Directory** to
`frontend`, framework **Next.js**, and **Node.js 22.x**. Use `npm ci`,
the checked-in build command `npm run build -- --webpack`, and the default
Next.js output directory.

Reserve/note the production domain, for example `https://forma.vercel.app`.
The actual domain may differ. A first deployment without a backend URL can
show the pages but cannot complete the form workflow.

## 3. Deploy the backend

In Render, create a **Blueprint** from this repository; it reads `render.yaml`.
Alternatively, create a Python web service with these exact settings:

| Setting | Value |
| --- | --- |
| Root directory | `backend` |
| Python version | `3.12.8` (OCR needs Python 3.11/3.12) |
| Build command | `pip install -r requirements.txt` |
| Start command | `uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 1` |
| Health check | `/health` |

Set these server-side environment variables in Render, copying secret values
from your existing local `.env` into Render's environment settings:

- `CORS_ORIGINS`: exact Vercel origin, such as `https://forma.vercel.app`.
  Additional approved origins can be comma-separated. No paths or wildcards.
- `GEMINI_API_KEY`: question simplification, translation, and answer assistance.
- `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID`, `ELEVENLABS_AGENT_ID`: voice guide.

Optional Gemini model/base URL settings use the existing defaults unless set.
Leave `AGENT_TOOL_SECRET` unset for the existing browser integration: it does
not send a bearer token. Do not put a shared secret in a `NEXT_PUBLIC_` variable.

Wait for Render to report healthy. Visit its actual HTTPS URL plus `/health`.

The Blueprint uses the free plan to avoid an automatic paid service. Free
instances can sleep, restart, or hit memory limits during OCR; sessions disappear
on any restart or deploy, and otherwise expire after one hour. Use synthetic demo
forms. This prototype has no user authentication; a public URL is not a
production-ready service for sensitive documents. Durable sessions, private
storage, and authentication require a separate production-hardening change.

## 4. Connect Vercel to the backend

In Vercel's project environment settings, set `NEXT_PUBLIC_API_URL` to the actual
Render HTTPS origin (no trailing slash), for Production. Add it to Preview only
when the preview origin is also approved in `CORS_ORIGINS`. Redeploy Vercel:
this variable is embedded at build time. Never place Gemini or ElevenLabs keys
in the frontend environment.

If the final Vercel production domain changed, update Render's `CORS_ORIGINS`
and restart/redeploy the backend. Do not allow all `*.vercel.app` domains.

## 5. Verify the hosted flow

Open the Vercel site, upload `examples/demo-form.pdf`, choose a language, answer
the questions, review, and download the PDF. Test voice with browser microphone
permission, and confirm no network request targets `localhost:8000`. Confirm
the ElevenLabs agent allows language and first-message overrides if using them;
see the multilingual setup instructions in README.md.

## References

- https://vercel.com/docs/monorepos
- https://vercel.com/docs/environment-variables
- https://vercel.com/docs/functions/limitations
- https://render.com/docs/deploy-fastapi
