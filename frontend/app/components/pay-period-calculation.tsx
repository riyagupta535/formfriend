"use client";

import { useState } from "react";

export type PayPeriodCalculationSpec = {
  intro_question: string;
  intro_helper_text: string;
  annual_amount_sources: { label: string; source_field_id: string }[];
  pay_period_field_id: string;
};

export default function PayPeriodCalculation({
  calculation,
  priorAnswers,
  busy,
  onComplete,
}: {
  calculation: PayPeriodCalculationSpec;
  priorAnswers: Record<string, string>;
  busy: boolean;
  onComplete: (value: string) => void;
}) {
  const [result, setResult] = useState<string | null>(null);
  const [error, setError] = useState("");

  function calculate(sourceFieldId: string) {
    const annualAnswer = priorAnswers[sourceFieldId];
    const payPeriodAnswer = priorAnswers[calculation.pay_period_field_id];
    const annualAmount = Number(annualAnswer);
    const payPeriods = Number(payPeriodAnswer);
    if (!annualAnswer?.trim() || !Number.isFinite(annualAmount) || annualAmount < 0) {
      setError("Complete the matching wage-table calculation first.");
      return;
    }
    if (!payPeriodAnswer?.trim() || !Number.isFinite(payPeriods) || payPeriods <= 0) {
      setError("Enter the number of paychecks per year in the previous question first.");
      return;
    }
    setError("");
    setResult(String(Math.round((annualAmount / payPeriods) * 100) / 100));
  }

  if (result !== null) {
    return <div className="decision-resolved">
      <span>Extra withholding for each paycheck</span>
      <strong>${Number(result).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</strong>
      <p>Form Friend divided your annual wage-table amount by your number of paychecks.</p>
      <button type="button" className="button primary" disabled={busy} onClick={() => onComplete(result)}>Use this amount & continue →</button>
      <button type="button" className="text-button" onClick={() => setResult(null)}>Change job count</button>
    </div>;
  }

  return <fieldset className="decision-card">
    <legend>Which job situation did you calculate?</legend>
    <p>We’ll use the matching result from the earlier questions.</p>
    <div className="decision-options">
      {calculation.annual_amount_sources.map(source => <button
        key={source.source_field_id}
        type="button"
        className="decision-option"
        disabled={busy}
        onClick={() => calculate(source.source_field_id)}
      >{source.label}<span aria-hidden="true">→</span></button>)}
    </div>
    {error && <p className="error-message" role="alert">{error}</p>}
  </fieldset>;
}
