import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import WorksheetWorkflow, { type WorksheetSpec } from "./worksheet-workflow";

const worksheet: WorksheetSpec = {
  worksheet_id: "test",
  task_label: "DEDUCTIONS",
  title: "Deductions Worksheet",
  source_page: 4,
  result_line: "15",
  intro_question: "Would you like help calculating your deductions?",
  intro_helper_text: "You may leave this blank.",
  inputs: [
    { input_id: "tips", question: "What are your qualified tips?", helper_text: "Enter 0 if none apply.", answer_type: "currency", options: [] },
    { input_id: "status", question: "What is your filing status?", helper_text: null, answer_type: "choice", options: ["Single", "Married"] },
  ],
};

afterEach(cleanup);

it("offers completed, guided, and skip branches", () => {
  render(<WorksheetWorkflow worksheet={worksheet} busy={false} onCalculate={vi.fn()} onComplete={vi.fn()} />);
  expect(screen.getByText("I already completed the worksheet")).toBeTruthy();
  expect(screen.getByText("Help me work through the worksheet")).toBeTruthy();
  expect(screen.getByText("I’d like to leave this blank")).toBeTruthy();
});

it("walks through inputs and confirms the backend result", async () => {
  const calculate = vi.fn().mockResolvedValue("1250");
  const complete = vi.fn();
  render(<WorksheetWorkflow worksheet={worksheet} busy={false} onCalculate={calculate} onComplete={complete} />);
  fireEvent.click(screen.getByText("Help me work through the worksheet"));
  fireEvent.click(screen.getByRole("button", { name: /Continue/ }));
  expect(screen.getByText("What are your qualified tips?")).toBeTruthy();
  fireEvent.change(screen.getByLabelText("Amount"), { target: { value: "250" } });
  fireEvent.click(screen.getByRole("button", { name: /Continue/ }));
  fireEvent.click(screen.getByRole("button", { name: /Single/ }));
  await waitFor(() => expect(calculate).toHaveBeenCalledWith({ tips: "250", status: "Single" }));
  expect(screen.getByText("$1,250")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: /Confirm & continue/ }));
  expect(complete).toHaveBeenCalledWith("1250");
});

it("allows the worksheet field to remain blank", () => {
  const complete = vi.fn();
  render(<WorksheetWorkflow worksheet={worksheet} busy={false} onCalculate={vi.fn()} onComplete={complete} />);
  fireEvent.click(screen.getByText("I’d like to leave this blank"));
  fireEvent.click(screen.getByRole("button", { name: /Continue/ }));
  expect(complete).toHaveBeenCalledWith("");
});

it("does not expose worksheet line references in the completed-result flow", () => {
  render(<WorksheetWorkflow worksheet={worksheet} busy={false} onCalculate={vi.fn()} onComplete={vi.fn()} />);
  fireEvent.click(screen.getByText("I already completed the worksheet"));
  fireEvent.click(screen.getByRole("button", { name: /Continue/ }));
  expect(screen.getByText("What was the result of your deductions worksheet?")).toBeTruthy();
  expect(screen.queryByText(/line 15/i)).toBeNull();
  expect(screen.queryByText(/Step 4\(b\)/i)).toBeNull();
});
