import type { Metadata } from "next";
import Link from "next/link";
import { Footer, Header } from "../components/shell";

export const metadata: Metadata = {
  title: "How it works | Forma",
  description: "Upload your form, answer simpler questions, and review your document with forma.",
};

const steps = [
  {
    number: "1",
    icon: "↥",
    title: "Bring your form",
    description: "Choose a PDF, Word document, or a clear screenshot. Drag it onto the upload page or choose a file from your device.",
    detail: "PDF, DOCX, PNG, and JPG files up to 10 MB. PDFs can contain text fields, checkboxes, radio buttons, dropdowns, printed questions, or scanned pages. Scanned pages use OCR. Word questions are identified from question marks, colons, and blank answer lines.",
  },
  {
    number: "2",
    icon: "☏",
    title: "Take it one question at a time",
    description: "We’ll guide you through the questions in simpler language. Type an answer, or use your microphone in a supported browser.",
    detail: "Listen to questions or mute the audio. Open “See more details” to check the original wording and, for PDFs, see the field highlighted on the page. You can skip a question and come back later.",
  },
  {
    number: "3",
    icon: "✓",
    title: "Check, edit, and download",
    description: "Review all your answers together and change anything you need. When you’re ready, download your document.",
    detail: "Fillable PDF controls are completed directly. Printed or scanned PDF questions get an answer sheet appended to the original pages. Word answers are added beside matching question paragraphs. Screenshots produce a text answer sheet; upload a fillable version to complete the original form.",
  },
];

export default function HowItWorks() {
  return (
    <>
      <Header />
      <main className="how-page">
        <div className="page-intro">
          <p className="eyebrow">YOUR FORM. YOUR PACE.</p>
          <h1>A little guidance.<br /><span>Every step of the way.</span></h1>
          <p>Here’s how we’ll turn your paperwork into smaller, friendlier steps.</p>
          <Link href="/upload" className="button primary">Let’s fill out a form <span>↗</span></Link>
        </div>
        <section className="how-grid" aria-label="How forma works">
          {steps.map((step) => (
            <article key={step.number}>
              <div className="card-top"><span className="feature-icon" aria-hidden="true">{step.icon}</span><span>STEP {step.number}</span></div>
              <h2>{step.title}</h2>
              <p>{step.description}</p>
              <p className="how-detail">{step.detail}</p>
            </article>
          ))}
        </section>
        <section className="how-reassurance">
          <h2>There’s no need to rush.</h2>
          <p>You can go back, skip questions, and edit your answers before downloading. Sessions last up to an hour in temporary server memory. Use sample data while trying this prototype.</p>
          <Link href="/upload" className="button primary">Take the first step <span>→</span></Link>
        </section>
      </main>
      <Footer />
    </>
  );
}
