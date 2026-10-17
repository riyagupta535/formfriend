# FormFriend agent tool contract

The backend accepts the Step 5 question schema directly. ElevenLabs handles
conversation wording, explanations, and follow-ups. The backend chooses applicable
questions, validates canonical answers, and keeps document/review state. These
endpoints do not call an LLM or ElevenLabs and can be tested independently.

## Create a session from Step 5 output

`POST /agent/sessions`

```json
{
  "questions": [
    {
      "id": "spouse_employment",
      "original_text": "Complete this step if ... married filing jointly and your spouse also works.",
      "simplified_question": "Does your spouse also work?",
      "input_type": "boolean",
      "depends_on": ["filing_status"],
      "show_if": {"field": "filing_status", "operator": "equals", "value": "married_filing_jointly"},
      "required": false,
      "pdf_field_name": null
    }
  ],
  "document_session_id": "optional original upload session ID"
}
```

This excerpt needs the referenced `filing_status` question in the same list.
Use `examples/step5-questions.json` for a complete, runnable example. `options` is
required for choice/multichoice questions; it is not needed for the supplied
boolean schema. Supported input types are text, address (text), boolean, number,
currency, date, choice, and multichoice. Only the supplied `equals` operator is
implemented. Unknown IDs, duplicate IDs, dependency cycles, and unsupported
operators are rejected rather than guessed.

With `document_session_id`, the tool creates a new session retaining the uploaded
document. Exact `pdf_field_name` matches preserve native PDF widget references;
ambiguous, duplicate, or incompatible mappings are rejected. A null mapping goes
to the answer sheet. Without an uploaded document, the session exports a PDF
answer sheet. No PDF locations or source page numbers are invented.

The response contains the new `session_id`, revision, progress, and next question.
The app must bind that ID to the agent conversation. Do not ask the model to invent
or choose session IDs. To use the existing review page, the browser must set
`sessionStorage.setItem("formfriend-session", session_id)` before navigating to
`/review`. This handoff is an integration step for the upcoming agent UI, not a
change to the current upload/question UI.

## Tools for the configured agent

| Tool name | HTTP endpoint | Payload |
| --- | --- | --- |
| `get_next_question` | `GET /agent/sessions/{session_id}/next-question` | None |
| `save_answer` | `POST /agent/sessions/{session_id}/answers` | `question_id`, `value`, `raw_response`, optional `revision` |
| `skip_question` | `POST /agent/sessions/{session_id}/skip` | `question_id`, optional `revision` |
| `get_question_context` | `GET /agent/sessions/{session_id}/questions/{question_id}/context` | None |

Save example:

```json
{
  "question_id": "spouse_employment",
  "value": false,
  "raw_response": "No, my spouse doesn't work.",
  "revision": 1
}
```

Use JSON true/false for boolean answers (not "yes", "no", or "maybe"), JSON numbers
for number/currency, YYYY-MM-DD strings for dates, exact option strings for choice,
and arrays of exact option strings for multichoice. Text/address values must be
nonempty strings. The agent must clarify uncertainty or missing detail before
calling save; backend type validation cannot determine whether a person's answer
is truthful or semantically complete. Store the original words in `raw_response`.

`save_answer` returns `saved`, the canonical typed value, invalidated dependent
question IDs, and `next`. It saves immediately, with no per-answer confirmation.
Final review handles edits and confirmation. `skip_question` allows optional
questions only. Required questions stay unresolved when users cannot answer;
explain, clarify, or pause the conversation instead of inventing information.

## Next-question states and conditions

- `question`: ask `question.simplified_question` and respect its input type/options.
- `complete`: applicable fields are answered or optionally skipped; offer review.
- `blocked`: no eligible question remains, but dependencies are unanswered/skipped.
  Inspect `blocked_question_ids` with the context tool, revisit the unresolved
  dependency, or let the user pause. Do not claim the form is complete.

Missing dependency answers are unknown, never false. Conditions are evaluated
against canonical saved answers. Input order is preserved among eligible
questions; dependencies are asked first even if the input list is out of order.
Changing a parent's answer invalidates all transitive dependent answers and
returns their IDs. Old dependent answers are not restored if the condition becomes
true again. Questions whose conditions are false are omitted from review/export.
Repeated reads of next-question do not consume or skip a question.

Pass the latest returned revision on writes to reject late/stale tool calls.
A 409 means fetch the next question again; a 422 means a validation/follow-up is
needed; a 404 means the session/question is missing or the one-hour session expired.
Validation failures leave the stored answer unchanged. No responses are logged by
these tools. Sessions disappear on backend restart or clearing.

## Review and PDF export

Agent sessions share `/sessions/{id}` and `/sessions/{id}/review/export` with the
existing review UI. Review exposes currently applicable fields. Required answers
cannot be blank. Edits affecting dependent questions must be made through the
agent tools before returning to review, so newly applicable questions are not
silently skipped or answered under an obsolete condition. Direct legacy answer
and export endpoints reject agent sessions to prevent bypassing these rules.

## Local test

From the repo root, with the backend running:

```sh
curl -X POST http://localhost:8000/agent/sessions \
  -H 'Content-Type: application/json' \
  --data-binary @examples/step5-questions.json
```

Use the returned session ID in the four tools above. The OpenAPI schemas are
available at `http://localhost:8000/docs`.

Set `AGENT_TOOL_SECRET` in the backend `.env` to require
`Authorization: Bearer <secret>` on `/agent/*`. Configure the same secret as a
server-side tool header in the agent settings. Never put it in frontend code or
question text. With no secret, these endpoints are intended for local testing,
matching the rest of this prototype. Cloud-hosted agents cannot reach your
computer's localhost; connecting them requires a reachable backend and appropriate
session authentication before shared/production use. Hosting/tunneling and the
agent's actual tool configuration have not been performed here.

## Suggested agent instructions

Ask one supplied question at a time. Explain using original_text and supplied
context; never invent form instructions or eligibility advice. If the answer is
vague, off topic, incomplete, or inconsistent, ask one focused follow-up or
rephrase the question. Do not save until the answer is clear. Do not assume a
missing dependency is false. After saving, use the returned next state. Offer
skipping only when optional. Do not ask "is that right?" after every clear answer;
offer the final review at completion. Never submit an application.
