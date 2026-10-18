"use client";
export type AnswerField = {
  answer_type?: "text" | "number" | "currency" | "date" | "checkbox" | "choice" | "multichoice";
  options?: string[];
};

export function selectedOptions(value: string): string[] {
  try { const parsed = JSON.parse(value); return Array.isArray(parsed) ? parsed : []; }
  catch { return []; }
}

export default function AnswerInput({ field, id, value, onChange, onBlur, disabled = false }: {
  field: AnswerField;
  id: string;
  value: string;
  onChange: (value: string) => void;
  onBlur?: (value: string) => void;
  disabled?: boolean;
}) {
  if (field.answer_type === "multichoice") {
    const selected = selectedOptions(value);
    return <div className="answer-options" role="group" aria-labelledby={`${id}-label`}>
      {(field.options || []).map(option => <label key={option} className="answer-option">
        <input type="checkbox" disabled={disabled} checked={selected.includes(option)} onChange={e => {
          const next = e.target.checked ? [...selected, option] : selected.filter(item => item !== option);
          const encoded = next.length ? JSON.stringify(next) : "";
          onChange(encoded); onBlur?.(encoded);
        }}/>{option}
      </label>)}
    </div>;
  }
  if (field.answer_type === "checkbox" || field.answer_type === "choice") {
    return <select id={id} value={value} disabled={disabled} onChange={e => onChange(e.target.value)} onBlur={e => onBlur?.(e.target.value)}>
      <option value="">Choose an answer (or skip)</option>
      {(field.options || []).map(option => <option key={option} value={option}>{option}</option>)}
    </select>;
  }
  return <textarea id={id} rows={3} maxLength={5000} disabled={disabled} value={value} onChange={e => onChange(e.target.value)} onBlur={e => onBlur?.(e.target.value)} placeholder="Type your answer here…"/>;
}
