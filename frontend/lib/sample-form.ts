const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// A small demo set in the question-generation schema, for trying the guide without an upload.
export const SAMPLE_QUESTIONS = [
  { id: "full_name", original_text: "Name (first, middle initial, last)", simplified_question: "What is your full name?",
    help_text: "", input_type: "text", required: true, depends_on: [], show_if: null, options: [],
    validation: { pattern: "(?=.*[^\\W\\d_])[^\\d]+", message: "That doesn't look like a name. Names don't have numbers. Ask for their name again." },
    pdf_field_name: null, source_reference: { page: 1, section: "Step 1" }, key_terms: [] },
  { id: "filing_status", original_text: "Filing status: Single or Married filing separately; Married filing jointly; Head of household",
    simplified_question: "Which filing status fits you?", help_text: "Head of household is for unmarried people who pay more than half the costs of keeping up a home for a qualifying person.",
    input_type: "choice", required: true, depends_on: [], show_if: null,
    options: ["Single or married filing separately", "Married filing jointly", "Head of household"], validation: null,
    pdf_field_name: null, source_reference: { page: 1, section: "Step 1(c)" }, key_terms: ["filing status", "head of household"] },
  { id: "dependents_amount", original_text: "If your total income will be $200,000 or less, multiply the number of qualifying children under age 17 by $2,000",
    simplified_question: "How many children under 17 do you claim as dependents?", help_text: "", input_type: "number", required: false,
    depends_on: [], show_if: null, options: [], validation: { min: 0, max: 20 }, pdf_field_name: null,
    source_reference: { page: 1, section: "Step 3" }, key_terms: ["dependent", "qualifying children"] },
];

/** Creates a guided session for the sample form and returns its session ID. */
export async function startSampleSession(): Promise<string> {
  const response = await fetch(`${API}/agent/sessions`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ questions: SAMPLE_QUESTIONS }) });
  if (!response.ok) throw Error("The sample form could not start.");
  const { session_id } = await response.json();
  sessionStorage.setItem("formfriend-session", session_id);
  return session_id;
}
