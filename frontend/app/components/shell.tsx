import Link from "next/link";
import Logo from "./logo";
export function Header({ compact = false }: { compact?: boolean }) { return <header className={`site-header${compact ? " compact" : ""}`}><Link href="/" className="brand" aria-label="Forma home"><Logo navigation /></Link><nav><Link href="/how-it-works">How it works</Link><Link className="nav-start" href="/upload">Let’s get started <span>↗</span></Link></nav></header>; }
export function Steps({ active }: { active: number }) { return <div className="steps" aria-label="Form workflow">{["Upload your form", "Let’s work through it", "Review & download"].map((label, i) => <div key={label} className={i === active ? "active" : i < active ? "complete" : ""}><span>{i < active ? "✓" : `${i + 1}`}</span>{label}</div>)}</div>; }
export function Footer() {return <footer><Link href="/" className="footer-brand" aria-label="Forma home"><Logo /></Link><span>A little help. A lot more confidence.</span><span>Made for your pace ♡</span></footer>;}
