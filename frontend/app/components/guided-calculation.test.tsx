import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import GuidedCalculation, { type CalculationSpec, type GuidedQuestion } from "./guided-calculation";

const questions: GuidedQuestion[] = [
  {
    text: "Do you expect to claim tax credits besides credits for children or dependents?",
    helper_text: "A tax credit is an amount that can lower the tax you owe.",
    answer_type: "choice",
    options: ["Yes", "No", "I'm not sure"],
  },
  {
    text: "What is the total amount of those other tax credits?",
    helper_text: "Enter the total from your tax records or tax-preparation estimate.",
    answer_type: "currency",
    options: [],
  },
];

const calculation: CalculationSpec = {
  operation: "add",
  input_question_indices: [1],
  source_question_numbers: ["3(a)", "3(b)"],
  source_field_ids: ["children", "dependents"],
  condition_question_index: 0,
  condition_answer: "Yes",
  condition_zero_answers: ["No"],
  condition_skip_answers: ["I'm not sure"],
  condition_failure_message: "Leave this blank and review it when you have your tax records.",
};

afterEach(cleanup);

describe("GuidedCalculation optional amounts", () => {
  it("automatically adds referenced answers when no new input is needed", async () => {
    const onComplete = vi.fn();
    render(<GuidedCalculation
      questions={[]}
      calculation={{
        operation: "add",
        input_question_indices: [],
        source_question_numbers: [],
        source_field_ids: ["first-lookup", "second-lookup"],
      }}
      priorAnswers={{ "first-lookup": "5590", "second-lookup": "2200" }}
      busy={false}
      onComplete={onComplete}
    />);

    await waitFor(() => expect(screen.getByText("$7,790")).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: /Save & continue/ }));
    expect(onComplete).toHaveBeenCalledWith("7790");
  });

  it("defines the unfamiliar term and treats the optional input as zero", () => {
    const onComplete = vi.fn();
    render(<GuidedCalculation questions={questions} calculation={calculation} priorAnswers={{ children: "4400", dependents: "500" }} busy={false} onComplete={onComplete} />);

    expect(screen.getByText("A tax credit is an amount that can lower the tax you owe.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /No/ }));
    expect(screen.getByText("$4,900")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Save & continue/ }));
    expect(onComplete).toHaveBeenCalledWith("4900");
  });

  it("asks for the amount after Yes", () => {
    render(<GuidedCalculation questions={questions} calculation={calculation} priorAnswers={{ children: "4400", dependents: "500" }} busy={false} onComplete={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: /Yes/ }));
    expect(screen.getByText("What is the total amount of those other tax credits?")).toBeTruthy();
    expect(screen.getByText("Enter the total from your tax records or tax-preparation estimate.")).toBeTruthy();
  });

  it("lets an unsure user skip for later review", () => {
    const onComplete = vi.fn();
    render(<GuidedCalculation questions={questions} calculation={calculation} priorAnswers={{ children: "4400", dependents: "500" }} busy={false} onComplete={onComplete} />);

    fireEvent.click(screen.getByRole("button", { name: /I'm not sure/ }));
    expect(screen.getByText("It’s okay not to know this yet")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Skip for now/ }));
    expect(onComplete).toHaveBeenCalledWith("");
  });
});
