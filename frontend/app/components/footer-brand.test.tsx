import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import FooterBrand from "./footer-brand";

afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

it("hides the logo when only the footer overflows and updates on resize", () => {
  vi.stubGlobal("ResizeObserver", class { observe() {} disconnect() {} });
  vi.spyOn(document.documentElement, "clientHeight", "get").mockReturnValue(800);
  vi.spyOn(document.documentElement, "scrollHeight", "get").mockReturnValue(850);
  let top = 700;
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(() => ({
    top, bottom: top + 150, left: 0, right: 1000, width: 1000, height: 150, x: 0, y: top, toJSON() {},
  }));
  render(<footer><FooterBrand /></footer>);
  const link = screen.getByLabelText("Forma home");
  expect(link.style.visibility).toBe("hidden");
  expect(link.tabIndex).toBe(-1);
  top = 1000;
  fireEvent(window, new Event("resize"));
  expect(link.style.visibility).toBe("visible");
  top = 700;
  fireEvent(window, new Event("resize"));
  expect(link.style.visibility).toBe("hidden");
});
