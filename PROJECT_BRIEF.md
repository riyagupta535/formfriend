# Build FormFriend — AI-Powered Accessible Form Assistant

We are building **FormFriend**, a web application for LA Hacks 2026 that helps people with cognitive disabilities, limited literacy, language barriers, or difficulty understanding complex forms.

The application transforms complicated forms into simple, interactive conversations. Users upload a document, the AI breaks down its questions into understandable language, users answer through voice or text, and the application generates a completed form or structured answer sheet.

## Tech Stack

- **Frontend:** Next.js, React, TypeScript, Tailwind CSS
- **Backend:** Python FastAPI
- **LLM:** StepFun Step 5 Preview (`step-5-preview`)
- **Text-to-speech:** ElevenLabs
- **Speech-to-text:** Browser Web Speech API for MVP
- **PDF processing:** PyMuPDF and pypdf
- **DOCX processing:** python-docx
- **OCR:** Use a suitable OCR library for screenshots and scanned documents
- **Storage:** Temporary session storage for MVP

Keep API keys server-side and configure external services through environment variables.

## Core User Flow

### 1. Upload Form

Create a landing page where users can upload:

- PDF files
- DOCX files
- Screenshots/images (PNG, JPG)

Extract the questions, instructions, field types, and locations from the uploaded document.

For screenshots, use OCR and layout analysis to identify questions and associated answer fields.

Preserve references to the original document, including page numbers and field locations where possible.

### 2. Accessibility Preferences

Before starting, let users select:

- Listen and read (text displayed and read aloud)
- Read only
- Listen first (audio with optional visible text)

Default to "Listen and read" after the user selects their preference.

Include a persistent mute/unmute button.

### 3. AI-Guided Question Flow

Use Step 5 Preview to simplify complicated form questions.

Requirements:

- Display only one question at a time.
- Use plain, accessible language.
- Keep spoken questions around 20 words or fewer when possible.
- Break complicated questions into smaller subquestions.
- Generate subquestions dynamically rather than using a fixed number.
- Preserve the meaning of the original question.
- Never invent missing information.
- Ask clarifying questions when user answers are ambiguous.

For each question, show:

- Simplified question
- Text input and microphone button
- A friendly animated assistant/avatar that speaks
- Replay audio button
- "Explain more" button
- Information icon showing the original question and relevant section of the uploaded form
- Back, Skip, and "I don't know" buttons
- Progress indicator

Use ElevenLabs for speech synthesis and browser speech recognition for spoken answers.

### 4. Answer Interpretation

Use Step 5 Preview to interpret conversational answers and convert them into structured form values.

Support:

- Text
- Numbers and currency
- Dates
- Yes/no
- Multiple choice
- Addresses
- Conditional questions
- Repeated fields, such as household members

Every simplified question and subquestion must map back to its original form field.

If the answer is unclear, ask a follow-up question.

Before saving an interpreted answer, allow the user to confirm or edit it.

Maintain structured session state containing original questions, simplified questions, subquestions, user responses, interpreted values, confirmation status, and source references.

### 5. Review Page

After completing the conversation, display a review page containing:

- Original field/question
- User's interpreted answer
- Edit button for each answer
- Missing or skipped fields clearly marked
- Warnings for ambiguous or potentially inconsistent answers

Users must explicitly confirm their answers before exporting.

### 6. Export

Support different outputs depending on input type:

**Fillable PDF:** Populate the original PDF fields and return a downloadable completed PDF.

**DOCX:** Fill the original document when its structure can be safely preserved.

**Non-fillable PDF:** Attempt supported text placement only when reliable; otherwise provide an answer sheet.

**Screenshot/image:** Generate a structured, field-by-field answer sheet that users can copy. Prompt them to upload the original fillable document if available.

Never silently claim that an unsupported document has been filled.

## AI Architecture

Separate the application into three major components:

1. **Form Parser:** Extracts questions, fields, instructions, and source locations.
2. **Conversation Engine:** Uses Step 5 Preview to simplify questions, generate follow-ups, interpret answers, and track completion.
3. **Document Generator:** Maps confirmed answers to original fields and generates the completed document or answer sheet.

Use structured JSON responses from the LLM, validated with Pydantic schemas.

Example field representation:

```json
{
  "field_id": "annual_income",
  "original_question": "What is your annual gross household income?",
  "simplified_question": "How much money does everyone in your household make in a year before taxes?",
  "answer_type": "currency",
  "subquestions": [],
  "source_page": 2,
  "user_response": null,
  "interpreted_value": null,
  "confirmed": false,
  "status": "unanswered"
}
```

## UI/UX Design

Build a polished, friendly, accessible interface suitable for a hackathon demo.

Design principles:

- Clean, modern visual design
- Warm, approachable colors
- Large readable typography
- Large buttons and touch targets
- Minimal visual clutter
- One question per screen
- Clear progress indicators
- Friendly animated assistant character
- Responsive desktop and mobile layouts
- Keyboard accessibility
- Strong color contrast

The experience should feel supportive and conversational, not like another complicated government form.

## Error Handling and Privacy

- Validate uploaded file types and sizes.
- Handle OCR errors and unsupported document structures.
- Flag low-confidence field extraction for user review.
- Never hallucinate form answers.
- Preserve original form instructions.
- Do not provide unsupported legal, medical, or eligibility determinations.
- Never submit applications without explicit user approval.
- Keep sensitive information out of logs.
- Use synthetic user data for demo/testing.
- Allow users to clear their session.

## Development Priorities

**Phase 1 — Working foundation**
- Set up frontend and backend.
- Build upload interface.
- Implement PDF extraction.
- Create normalized field schema.
- Integrate Step 5 Preview.
- Display simplified questions.

**Phase 2 — Conversational experience**
- Implement one-question-at-a-time flow.
- Add dynamic subquestions and clarification.
- Add text answers, confirmation, and progress tracking.
- Integrate ElevenLabs and speech recognition.
- Add original question/source view.

**Phase 3 — Review and export**
- Implement editable review page.
- Add answer validation.
- Populate fillable PDFs.
- Generate answer sheets for screenshots and unsupported formats.

**Phase 4 — Polish and testing**
- Improve accessibility and avatar animation.
- Handle errors and edge cases.
- Test against several example forms.
- Add DOCX support and screenshot OCR.
- Prepare end-to-end hackathon demo.

## Important Implementation Instructions

Start by inspecting the existing repository and its structure.

If the repository is empty, scaffold the project.

Build incrementally with clear modular components and maintainable code.

Prioritize a fully working end-to-end flow for one representative fillable PDF before expanding to arbitrary documents.

Create a `.env.example` documenting required API keys.

If Step 5 Preview or ElevenLabs credentials are unavailable, implement clearly labeled mock adapters so the app can run locally. Keep the real integrations implemented and configurable.

Do not silently substitute another LLM for Step 5 Preview.

Write tests for field extraction, answer mapping, clarification logic, and PDF generation.

After implementation, provide setup instructions, commands to run the application, and a summary of completed features versus remaining work.

**Begin with Phase 1. Implement the project foundation, PDF upload, field extraction, Step 5 integration, and a basic question-by-question interface. Then run the available tests and report what works.**