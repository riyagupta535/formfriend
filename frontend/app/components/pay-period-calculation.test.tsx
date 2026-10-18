import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import PayPeriodCalculation, { type PayPeriodCalculationSpec } from "./pay-period-calculation";

const calculation: PayPeriodCalculationSpec = {
  intro_question: "Calculate withholding.",
  intro_helper_text: "Uses earlier answers.",
  annual_amount_sources: [
    { label: "I have two jobs total", source_field_id: "two" },
    { label: "I have three jobs total", source_field_id: "three" },
  ],
  pay_period_field_id: "periods",
};

afterEach(cleanup);

it("divides the selected earlier amount by the saved pay periods", () => {
  const complete = vi.fn();
  render(<PayPeriodCalculation calculation={calculation} priorAnswers={{ two: "5200", three: "7800", periods: "26" }} busy={false} onComplete={complete} />);
  fireEvent.click(screen.getByRole("button", { name: /two jobs/ }));
  expect(screen.getByText("$200.00")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: /Use this amount/ }));
  expect(complete).toHaveBeenCalledWith("200");
});

it("does not calculate without the required earlier answer", () => {
  render(<PayPeriodCalculation calculation={calculation} priorAnswers={{ two: "", periods: "26" }} busy={false} onComplete={vi.fn()} />);
  fireEvent.click(screen.getByRole("button", { name: /two jobs/ }));
  expect(screen.getByRole("alert").textContent).toMatch(/wage-table calculation/);
});
