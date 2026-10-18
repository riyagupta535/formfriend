"use client";

import { useState } from "react";

export type EligibilityCondition = {
  condition_id: string;
  question: string;
  helper_text: string;
  yes_label: string;
  no_label: string;
  unsure_label: string;
  unsure_help: string;
};

export type EligibilityWorkflowSpec = {
  workflow_id: string;
  task_label: string;
  source_page: number;
  source_section: string;
  intro_question: string;
  intro_helper_text: string;
  conditions: EligibilityCondition[];
  eligible_explanation: string;
  ineligible_explanation: string;
  certification_text: string;
  checked_value: string;
};

type Outcome = "eligible" | "ineligible" | "unsure" | null;

export default function EligibilityWorkflow({
  workflow,
  busy,
  sourceImageUrl,
  onRead,
  onComplete,
}: {
  workflow: EligibilityWorkflowSpec;
  busy: boolean;
  sourceImageUrl?: string;
  onRead?: (step: string, text: string) => void;
  onComplete: (value: string) => void;
}) {
  const [step, setStep] = useState(0);
  const [outcome, setOutcome] = useState<Outcome>(null);
  const [certified, setCertified] = useState(false);
  const condition = workflow.conditions[step];

  function answer(value: "yes" | "no" | "unsure") {
    if (value === "no") { setOutcome("ineligible"); return; }
    if (value === "unsure") { setOutcome("unsure"); return; }
    if (step < workflow.conditions.length - 1) { setStep(step + 1); return; }
    setOutcome("eligible");
  }

  function startOver() {
    setStep(0);
    setOutcome(null);
    setCertified(false);
  }

  if (outcome === "ineligible") {
    return <div className="decision-resolved">
      <span>Exemption requirements not met</span>
      <strong>{workflow.ineligible_explanation}</strong>
      <button type="button" className="text-button" onClick={() => onRead?.("ineligible", workflow.ineligible_explanation)}>♫ Read this explanation</button>
      <button type="button" className="button primary" disabled={busy} onClick={() => onComplete("")}>Leave unchecked & continue →</button>
      <button type="button" className="text-button" onClick={startOver}>Start over</button>
    </div>;
  }

  if (outcome === "unsure") {
    return <div className="decision-resolved">
      <span>How to verify this condition</span>
      <strong>{condition.unsure_help}</strong>
      <button type="button" className="text-button" onClick={() => onRead?.(condition.condition_id, `${condition.question} ${condition.unsure_help}`)}>♫ Read this explanation</button>
      <button type="button" className="button primary" disabled={busy} onClick={() => onComplete("")}>Leave unchecked & continue →</button>
      <button type="button" className="text-button" onClick={() => setOutcome(null)}>I checked—answer this question</button>
    </div>;
  }

  if (outcome === "eligible") {
    return <fieldset className="decision-card eligibility-certification">
      <legend>Review before claiming exemption</legend>
      <p>{workflow.eligible_explanation}</p>
      <button type="button" className="text-button" onClick={() => onRead?.("eligible", `${workflow.eligible_explanation} ${workflow.certification_text}`)}>♫ Read the consequences</button>
      <label className="certification-check">
        <input type="checkbox" checked={certified} onChange={event => setCertified(event.target.checked)} />
        <span>{workflow.certification_text}</span>
      </label>
      <button type="button" className="button primary" disabled={busy || !certified} onClick={() => onComplete(workflow.checked_value)}>Certify exemption & continue →</button>
      <button type="button" className="text-button" onClick={startOver}>← Review my answers</button>
    </fieldset>;
  }

  if (!condition) return null;
  return <fieldset className="decision-card eligibility-question">
    <legend>{condition.question}</legend>
    <p>Step {step + 1} of {workflow.conditions.length + 1} · Tax withholding</p>
    <p className="helper-text">{condition.helper_text}</p>
    <button type="button" className="text-button" onClick={() => onRead?.(condition.condition_id, `${condition.question} ${condition.helper_text}`)}>♫ Read this explanation</button>
    <div className="decision-options">
      <button type="button" className="decision-option" disabled={busy} onClick={() => answer("yes")}>{condition.yes_label}<span aria-hidden="true">→</span></button>
      <button type="button" className="decision-option" disabled={busy} onClick={() => answer("no")}>{condition.no_label}<span aria-hidden="true">→</span></button>
      <button type="button" className="decision-option" disabled={busy} onClick={() => answer("unsure")}>{condition.unsure_label}<span aria-hidden="true">→</span></button>
    </div>
    {sourceImageUrl && <details className="term-help"><summary>View the original IRS instructions</summary><img className="source-preview" src={sourceImageUrl} alt={`${workflow.source_section} instructions on page ${workflow.source_page}`} loading="lazy" /></details>}
    {step > 0 && <button type="button" className="text-button" onClick={() => setStep(step - 1)}>← Previous condition</button>}
  </fieldset>;
}
