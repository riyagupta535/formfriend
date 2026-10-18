"use client";
import { useQuestionLabel } from "./question-language";

import { useState } from "react";

export type WorksheetInput = {
  input_id: string;
  question: string;
  helper_text?: string | null;
  answer_type: "currency" | "choice";
  options: string[];
};

export type WorksheetSpec = {
  worksheet_id: string;
  task_label: string;
  title: string;
  source_page: number;
  result_line: string;
  intro_question: string;
  intro_helper_text: string;
  inputs: WorksheetInput[];
};

type Route = "already" | "help" | "skip";

export default function WorksheetWorkflow({
  worksheet,
  busy,
  sourceImageUrl,
  onCalculate,
  onComplete,
}: {
  worksheet: WorksheetSpec;
  busy: boolean;
  sourceImageUrl?: string;
  onCalculate: (answers: Record<string, string>) => Promise<string>;
  onComplete: (value: string) => void;
}) {
  const optionLabel = useQuestionLabel();
  const [route, setRoute] = useState<Route | null>(null);
  const [started, setStarted] = useState(false);
  const [step, setStep] = useState(0);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [draft, setDraft] = useState("");
  const [result, setResult] = useState<string | null>(null);
  const [calculating, setCalculating] = useState(false);
  const [error, setError] = useState("");
  const question = worksheet.inputs[step];

  function chooseRoute() {
    if (!route) return;
    if (route === "skip") {
      onComplete("");
      return;
    }
    setStarted(true);
  }

  async function record(answer: string) {
    if (!question) return;
    const next = { ...answers, [question.input_id]: answer };
    setAnswers(next);
    setError("");
    if (step < worksheet.inputs.length - 1) {
      setStep(step + 1);
      setDraft(next[worksheet.inputs[step + 1].input_id] || "");
      return;
    }
    setCalculating(true);
    try {
      setResult(await onCalculate(next));
    } catch (caught) {
      setError((caught as Error).message);
    } finally {
      setCalculating(false);
    }
  }

  if (result !== null) {
    return <div className="decision-resolved">
      <span>Your deductions worksheet result</span>
      <strong>${Number(result).toLocaleString("en-US", { maximumFractionDigits: 2 })}</strong>
      <p>Please confirm this result before Form Friend adds it to your form.</p>
      <button type="button" className="button primary" disabled={busy} onClick={() => onComplete(result)}>Confirm & continue →</button>
      <button type="button" className="text-button" onClick={() => { setResult(null); setStep(0); setStarted(false); setRoute(null); }}>Change answer</button>
    </div>;
  }

  if (!started) {
    return <fieldset className="decision-card worksheet-choice">
      <legend>Choose what you’d like to do</legend>
      <div className="decision-options">
        {[
          ["already", "I already completed the worksheet"],
          ["help", "Help me work through the worksheet"],
          ["skip", "I’d like to leave this blank"],
        ].map(([value, label]) => <button
          key={value}
          type="button"
          className={`decision-option ${route === value ? "selected" : ""}`}
          aria-pressed={route === value}
          onClick={() => setRoute(value as Route)}
        >{label}<span>{route === value ? "✓" : "→"}</span></button>)}
      </div>
      <button type="button" className="button primary" disabled={!route || busy} onClick={chooseRoute}>Continue →</button>
    </fieldset>;
  }

  if (route === "already") {
    return <fieldset className="decision-card">
      <legend>What was the result of your deductions worksheet?</legend>
      <p>Enter the final amount from your completed deductions worksheet.</p>
      <div className="guided-number">
        <label htmlFor="worksheet-known-result">Worksheet result</label>
        <input id="worksheet-known-result" type="number" min="0" step="0.01" value={draft} onChange={event => setDraft(event.target.value)} />
        <button type="button" className="button primary" disabled={busy || draft === "" || Number(draft) < 0} onClick={() => setResult(draft)}>Review amount →</button>
      </div>
      <button type="button" className="text-button" onClick={() => setStarted(false)}>← Back</button>
    </fieldset>;
  }

  if (!question) return null;
  return <fieldset className="decision-card worksheet-question">
    <legend>{question.question}</legend>
    <p>Worksheet question {step + 1} of {worksheet.inputs.length}</p>
    {question.helper_text && <details className="term-help"><summary>What does this mean?</summary><p>{question.helper_text}</p></details>}
    {sourceImageUrl && <details className="term-help"><summary>View the original worksheet</summary><img className="source-preview" src={sourceImageUrl} alt={`${worksheet.title} on page ${worksheet.source_page}`} loading="lazy" /></details>}
    {question.answer_type === "choice" ? <div className="decision-options">
      {question.options.map(option => <button key={option} type="button" className="decision-option" disabled={busy || calculating} onClick={() => void record(option)}>{optionLabel(option)}<span>→</span></button>)}
    </div> : <div className="guided-number">
      <label htmlFor={`worksheet-${question.input_id}`}>Amount</label>
      <input id={`worksheet-${question.input_id}`} type="number" min="0" step="0.01" value={draft} onChange={event => setDraft(event.target.value)} />
      <button type="button" className="button primary" disabled={busy || calculating || draft === "" || Number(draft) < 0} onClick={() => void record(draft)}>{calculating ? "Calculating…" : step === worksheet.inputs.length - 1 ? "Calculate result →" : "Continue →"}</button>
    </div>}
    {error && <p className="error-message" role="alert">{error}</p>}
    <button type="button" className="text-button" onClick={() => {
      if (step === 0) { setStarted(false); return; }
      const previous = worksheet.inputs[step - 1];
      setStep(step - 1);
      setDraft(answers[previous.input_id] || "");
    }}>← Back</button>
  </fieldset>;
}
