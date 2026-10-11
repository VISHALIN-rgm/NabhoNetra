import { describe, it, expect, beforeAll, afterEach, vi } from "vitest";
import { render, cleanup, waitFor } from "@testing-library/react";
import App from "./App.jsx";
import data from "./test-data.json";
import alerts from "./test-alerts.json";

beforeAll(() => {
  window.matchMedia ||= () => ({ matches: false, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} });
  globalThis.ResizeObserver ||= class { observe() {} unobserve() {} disconnect() {} };
  global.fetch = vi.fn(async (url) => ({ ok: true, status: 200, json: async () => (String(url).startsWith("/api/data") ? data : String(url).startsWith("/api/alerts") ? alerts : {}) }));
});
afterEach(cleanup);

describe("every page renders with server-shaped data and no runtime errors", () => {
  for (const page of ["home", "map", "ai", "interventions", "resources", "impact"]) {
    it(page, async () => {
      window.location.hash = `#/${page}`;
      const errors = [];
      const spy = vi.spyOn(console, "error").mockImplementation((...a) => errors.push(a.join(" ")));
      const { container } = render(<App />);
      await waitFor(() => expect(container.querySelector(".page, .mapgrid")).toBeTruthy(), { timeout: 4000 });
      spy.mockRestore();
      expect(errors.filter((e) => !/not wrapped in act|act\(/.test(e))).toEqual([]);
    });
  }
});
