"use client";
import { useQuestionLabel } from "./question-language";

import { useEffect, useState } from "react";

export type GuidedQuestion = {
  text: string;
  helper_text?: string | null;
  answer_type: string;
  options: string[];
};

export type CalculationSpec = {
  operation: "multiply" | "add";
  input_question_indices: number[];
  factor?: number | null;
  source_question_numbers: string[];
  source_field_ids: string[];
  condition_question_index?: number | null;
  condition_answer?: string | null;
  condition_zero_answers?: string[];
  condition_skip_answers?: string[];
  condition_failure_message?: string | null;
};

export default function GuidedCalculation({
  questions,
  calculation,
  priorAnswers,
  busy,
  onComplete,
}: {
  questions: GuidedQuestion[];
  calculation: CalculationSpec;
  priorAnswers: Record<string, string>;
  busy: boolean;
  onComplete: (value: string) => void;
}) {
  const optionLabel = useQuestionLabel();
  const [step, setStep] = useState(0);
  const [answers, setAnswers] = useState<string[]>([]);
  const [draft, setDraft] = useState("");
  const [result, setResult] = useState<string | null>(null);
  const [ineligible, setIneligible] = useState(false);
  const [uncertain, setUncertain] = useState(false);
  const [missingPriorAnswer, setMissingPriorAnswer] = useState(false);
  const question = questions[step];

  function calculate(next: string[]) {
    const priorValues = calculation.source_field_ids.map(id => priorAnswers[id]);
    if (priorValues.some(answer => !answer?.trim())) {
      setMissingPriorAnswer(true);
      return;
    }
    const enteredValues = calculation.input_question_indices.map(index => next[index]);
    const numbers = [...priorValues, ...enteredValues].map(value => Number(value));
    if (numbers.some(number => !Number.isFinite(number) || number < 0)) return;
    const total = calculation.operation === "multiply"
      ? numbers[0] * (calculation.factor || 0)
      : numbers.reduce((sum, number) => sum + number, 0);
    setResult(String(total));
  }

  function record(answer: string) {
    const next = [...answers];
    next[step] = answer;
    setAnswers(next);
    if (
      calculation.condition_question_index === step &&
      answer !== calculation.condition_answer
    ) {
      if (calculation.condition_zero_answers?.includes(answer)) {
        const zeroed = [...next];
        calculation.input_question_indices.forEach(index => { zeroed[index] = "0"; });
        setAnswers(zeroed);
        calculate(zeroed);
        return;
      }
      if (calculation.condition_skip_answers?.includes(answer)) {
        setUncertain(true);
        return;
      }
      setIneligible(true);
      return;
    }
    if (step < questions.length - 1) {
      setStep(step + 1);
      setDraft(next[step + 1] || "");
      return;
    }
    calculate(next);
  }

  useEffect(() => {
    if (
      questions.length === 0
      && calculation.source_field_ids.length > 0
      && result === null
      && !missingPriorAnswer
    ) {
      calculate([]);
    }
  }, [calculation.source_field_ids.length, missingPriorAnswer, questions.length, result]);

  if (ineligible) {
    return <div className="decision-resolved">
      <span>This calculation needs another method</span>
      <strong>{calculation.condition_failure_message}</strong>
      <button type="button" className="button primary" disabled={busy} onClick={() => onComplete("")}>Skip this field →</button>
      <button type="button" className="text-button" onClick={() => { setIneligible(false); setStep(0); setAnswers([]); }}>Start over</button>
    </div>;
  }

  if (uncertain) {
    return <div className="decision-resolved">
      <span>It’s okay not to know this yet</span>
      <strong>{calculation.condition_failure_message || "You can leave this blank and review it when you have your tax records or tax-preparation estimate."}</strong>
      <button type="button" className="button primary" disabled={busy} onClick={() => onComplete("")}>Skip for now →</button>
      <button type="button" className="text-button" onClick={() => { setUncertain(false); setStep(0); setAnswers([]); }}>Start over</button>
    </div>;
  }

  if (missingPriorAnswer) {
    return <div className="decision-resolved">
      <span>Earlier answers are needed</span>
      <strong>Complete the two earlier amount questions before calculating this total.</strong>
      <button type="button" className="button primary" disabled={busy} onClick={() => onComplete("")}>Skip this field →</button>
      <button type="button" className="text-button" onClick={() => setMissingPriorAnswer(false)}>Try again</button>
    </div>;
  }

  if (result !== null) {
    return <div className="decision-resolved">
      <span>Calculated amount for this field</span>
      <strong>${Number(result).toLocaleString("en-US")}</strong>
      <button type="button" className="button primary" disabled={busy} onClick={() => onComplete(result)}>Save & continue →</button>
      {questions.length > 0 && <button type="button" className="text-button" onClick={() => { setResult(null); setStep(calculation.input_question_indices[0] || 0); }}>Change answer</button>}
    </div>;
  }

  if (!question) return null;
  return <fieldset className="decision-card">
    <legend>{question.text}</legend>
    <p>Step {step + 1} of {questions.length}</p>
    {question.helper_text && <p className="helper-text">{question.helper_text}</p>}
    {question.answer_type === "choice" ? <div className="decision-options">
      {question.options.map(option => <button key={option} type="button" className="decision-option" disabled={busy} onClick={() => record(option)}>{optionLabel(option)}<span>→</span></button>)}
    </div> : <div className="guided-number">
      <label htmlFor="guided-number-answer">Your answer</label>
      <input id="guided-number-answer" type="number" min="0" step="1" value={draft} onChange={event => setDraft(event.target.value)} />
      <button type="button" className="button primary" disabled={busy || draft === "" || Number(draft) < 0} onClick={() => record(draft)}>Calculate →</button>
    </div>}
    {step > 0 && <button type="button" className="text-button" onClick={() => { setStep(step - 1); setDraft(answers[step - 1] || ""); }}>← Previous step</button>}
  </fieldset>;
}
