"use client";

import { useState } from "react";

export type TableLookupSpec = {
  lookup_id: string;
  source_page: number;
  intro_question: string;
  intro_helper_text: string;
  higher_wage_label: string;
  lower_wage_label: string;
  tables: { filing_status: string }[];
};

export default function TableLookupWorkflow({
  lookup,
  busy,
  sourceImageUrl,
  onLookup,
  onComplete,
}: {
  lookup: TableLookupSpec;
  busy: boolean;
  sourceImageUrl?: string;
  onLookup: (input: { filing_status: string; higher_wage: number; lower_wage: number }) => Promise<string>;
  onComplete: (value: string) => void;
}) {
  const [step, setStep] = useState(0);
  const [filingStatus, setFilingStatus] = useState("");
  const [higherWage, setHigherWage] = useState("");
  const [lowerWage, setLowerWage] = useState("");
  const [result, setResult] = useState<string | null>(null);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState("");

  async function calculate() {
    setWorking(true);
    setError("");
    try {
      setResult(await onLookup({
        filing_status: filingStatus,
        higher_wage: Number(higherWage),
        lower_wage: Number(lowerWage),
      }));
    } catch (caught) {
      setError((caught as Error).message);
    } finally {
      setWorking(false);
    }
  }

  if (result !== null) {
    return <div className="decision-resolved">
      <span>Amount found in the wage table</span>
      <strong>${Number(result).toLocaleString("en-US", { maximumFractionDigits: 2 })}</strong>
      <p>Form Friend matched your filing status and wages to the table in your form.</p>
      <button type="button" className="button primary" disabled={busy} onClick={() => onComplete(result)}>Use this amount & continue →</button>
      <button type="button" className="text-button" onClick={() => setResult(null)}>Change my answers</button>
    </div>;
  }

  return <fieldset className="decision-card table-lookup-question">
    {step === 0 && <>
      <legend>What filing status will you use?</legend>
      <p>This selects the correct wage table.</p>
      <div className="decision-options">
        {lookup.tables.map(table => <button
          key={table.filing_status}
          type="button"
          className="decision-option"
          disabled={busy}
          onClick={() => { setFilingStatus(table.filing_status); setStep(1); }}
        >{table.filing_status}<span aria-hidden="true">→</span></button>)}
      </div>
    </>}
    {step === 1 && <>
      <legend>{lookup.higher_wage_label}</legend>
      <p>Use the expected taxable wages for the full year.</p>
      <div className="guided-number">
        <label htmlFor="table-higher-wage">Annual wages</label>
        <input id="table-higher-wage" type="number" min="0" step="1" value={higherWage} onChange={event => setHigherWage(event.target.value)} />
        <button type="button" className="button primary" disabled={busy || higherWage === "" || Number(higherWage) < 0} onClick={() => setStep(2)}>Continue →</button>
      </div>
      <button type="button" className="text-button" onClick={() => setStep(0)}>← Back</button>
    </>}
    {step === 2 && <>
      <legend>{lookup.lower_wage_label}</legend>
      <p>Use the expected taxable wages for the full year.</p>
      <div className="guided-number">
        <label htmlFor="table-lower-wage">Annual wages</label>
        <input id="table-lower-wage" type="number" min="0" step="1" value={lowerWage} onChange={event => setLowerWage(event.target.value)} />
        <button type="button" className="button primary" disabled={busy || working || lowerWage === "" || Number(lowerWage) < 0} onClick={() => void calculate()}>{working ? "Checking the table…" : "Find my amount →"}</button>
      </div>
      <button type="button" className="text-button" onClick={() => setStep(1)}>← Back</button>
    </>}
    {error && <p className="error-message" role="alert">{error}</p>}
    {sourceImageUrl && <details className="term-help"><summary>View the original wage table</summary><img className="source-preview" src={sourceImageUrl} alt="The wage tables included with your form" loading="lazy" /></details>}
  </fieldset>;
}
