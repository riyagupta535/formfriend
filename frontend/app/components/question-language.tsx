"use client";
import { createContext, useContext } from "react";

import { QUESTION_LANGUAGES, type QuestionLanguage } from "../../lib/question-languages";
export type { QuestionLanguage } from "../../lib/question-languages";
export const QuestionLabels = createContext<Record<string, string>>({});
export function useQuestionLabel() {
  const labels = useContext(QuestionLabels);
  return (value: string) => labels[value] ?? value;
}

export default function QuestionLanguageSelect({ value, onChange, disabled = false }: {
  value: QuestionLanguage; onChange: (language: QuestionLanguage) => void; disabled?: boolean;
}) {
  return <div className="question-language-select">
    <label className="sr-only" htmlFor="question-language">Question language</label>
    <select id="question-language" value={value} disabled={disabled}
      onChange={event => onChange(event.target.value as QuestionLanguage)}>
      {Object.entries(QUESTION_LANGUAGES).map(([code, language]) =>
        <option key={code} value={code} lang={language.htmlLang} dir="auto">{language.label}</option>)}
    </select>
  </div>;
}
