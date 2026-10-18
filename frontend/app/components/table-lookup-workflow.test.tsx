import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import TableLookupWorkflow, { type TableLookupSpec } from "./table-lookup-workflow";

const lookup: TableLookupSpec = {
  lookup_id: "w4-test",
  source_page: 5,
  intro_question: "Let’s calculate the amount from the wage table for you.",
  intro_helper_text: "Answer three questions.",
  higher_wage_label: "What are the annual wages from the higher-paying job?",
  lower_wage_label: "What are the annual wages from the lower-paying job?",
  tables: [{ filing_status: "Single or Married Filing Separately" }],
};

afterEach(cleanup);

it("collects filing status and two wages, then uses the returned table amount", async () => {
  const calculate = vi.fn().mockResolvedValue("5590");
  const complete = vi.fn();
  render(<TableLookupWorkflow lookup={lookup} busy={false} onLookup={calculate} onComplete={complete} />);
  fireEvent.click(screen.getByRole("button", { name: /Single or Married/ }));
  fireEvent.change(screen.getByLabelText("Annual wages"), { target: { value: "110000" } });
  fireEvent.click(screen.getByRole("button", { name: /Continue/ }));
  fireEvent.change(screen.getByLabelText("Annual wages"), { target: { value: "25000" } });
  fireEvent.click(screen.getByRole("button", { name: /Find my amount/ }));
  await waitFor(() => expect(calculate).toHaveBeenCalledWith({ filing_status: "Single or Married Filing Separately", higher_wage: 110000, lower_wage: 25000 }));
  expect(screen.getByText("$5,590")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: /Use this amount/ }));
  expect(complete).toHaveBeenCalledWith("5590");
});
