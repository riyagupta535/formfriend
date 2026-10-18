import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import EligibilityWorkflow, { type EligibilityWorkflowSpec } from "./eligibility-workflow";

const workflow: EligibilityWorkflowSpec = {
  workflow_id: "w4-exempt-2026",
  task_label: "TAX WITHHOLDING EXEMPTION",
  source_page: 2,
  source_section: "Exemption from withholding",
  intro_question: "Let’s check whether you qualify.",
  intro_helper_text: "Exemption means no federal income tax withholding.",
  conditions: [
    { condition_id: "prior", question: "Did you have zero liability in 2025?", helper_text: "This is not the same as receiving a refund.", yes_label: "Yes, zero", no_label: "No", unsure_label: "I'm not sure", unsure_help: "Compare the total tax and refundable-credit amounts on your Form 1040." },
    { condition_id: "current", question: "Do you expect zero liability in 2026?", helper_text: "Use your expected tax liability.", yes_label: "Yes, zero", no_label: "No", unsure_label: "I'm not sure", unsure_help: "Review your expected income and credits." },
  ],
  eligible_explanation: "No federal income tax will be withheld and an incorrect certification may result in tax and penalties.",
  ineligible_explanation: "Both conditions must be true, so the box will remain unchecked.",
  certification_text: "I certify that both conditions are true.",
  checked_value: "1",
};

afterEach(cleanup);

it("requires both conditions and explicit certification before checking the box", () => {
  const complete = vi.fn();
  render(<EligibilityWorkflow workflow={workflow} busy={false} onComplete={complete} />);
  fireEvent.click(screen.getByRole("button", { name: /^Yes, zero/ }));
  fireEvent.click(screen.getByRole("button", { name: /^Yes, zero/ }));
  const certify = screen.getByRole("button", { name: /Certify exemption/ });
  expect((certify as HTMLButtonElement).disabled).toBe(true);
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(certify);
  expect(complete).toHaveBeenCalledWith("1");
});

it("leaves the box unchecked when either condition is false", () => {
  const complete = vi.fn();
  render(<EligibilityWorkflow workflow={workflow} busy={false} onComplete={complete} />);
  fireEvent.click(screen.getByRole("button", { name: /^No/ }));
  expect(screen.getByText(/Both conditions must be true/)).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: /Leave unchecked/ }));
  expect(complete).toHaveBeenCalledWith("");
});

it("explains how to verify an uncertain answer without claiming exemption", () => {
  const complete = vi.fn();
  render(<EligibilityWorkflow workflow={workflow} busy={false} onComplete={complete} />);
  fireEvent.click(screen.getByRole("button", { name: /^I'm not sure/ }));
  expect(screen.getByText("Compare the total tax and refundable-credit amounts on your Form 1040.")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: /Leave unchecked/ }));
  expect(complete).toHaveBeenCalledWith("");
});
