"use client";
import {useState} from "react";

export default function DateEntry({busy, onSubmit}: {busy: boolean; onSubmit: (value: string) => void}) {
  const [value,setValue]=useState("");
  return <fieldset className="date-entry" disabled={busy}>
    <legend>Enter or choose a date</legend>
    <p>Say the date aloud or enter it here.</p>
    <label htmlFor="calendar-answer">Date (month/day/year)</label>
    <input id="calendar-answer" type="date" value={value} onChange={event=>setValue(event.target.value)} />
    <button type="button" className="button secondary" disabled={!/^\d{4}-\d{2}-\d{2}$/.test(value)} onClick={()=>onSubmit(value)}>Use this date</button>
  </fieldset>;
}
