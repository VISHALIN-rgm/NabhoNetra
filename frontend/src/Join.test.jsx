import { describe, it, expect, beforeAll, afterEach, vi } from "vitest";
import { render, cleanup, screen, fireEvent } from "@testing-library/react";
import Subscribe from "./Subscribe.jsx";
import data from "./test-data.json";

beforeAll(() => {
  window.matchMedia ||= () => ({ matches: false, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} });
  globalThis.ResizeObserver ||= class { observe() {} unobserve() {} disconnect() {} };
  global.fetch = vi.fn(async () => ({ ok: true, status: 200, json: async () => ({ channels: ["sms", "email", "whatsapp"] }) }));
});
afterEach(cleanup);

describe("Join NabhoNetra form", () => {
  it("shows fields for each role, consent, and WhatsApp when configured", async () => {
    render(<Subscribe data={data} />);
    expect(screen.getByText("Join NabhoNetra", { selector: "h2" })).toBeTruthy();
    expect(screen.getByText("Land area (acres)")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Machine provider" }));
    expect(screen.getByText("Machines you offer")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Biomass buyer" }));
    expect(screen.getByText("Residue you buy")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Officer" })).toBeNull();   // only a signed-in administrator can add officers
    expect(screen.getByText(/I agree to be contacted/)).toBeTruthy();
    expect(await screen.findByRole("button", { name: "WhatsApp" })).toBeTruthy();
  });

  it("offers the Officer role only to a signed-in administrator, and tells farmers how their details are shared", () => {
    render(<Subscribe data={data} me={{ role: "admin", name: "Admin" }} />);
    fireEvent.click(screen.getByRole("button", { name: "Officer" }));
    expect(screen.getByText("Designation")).toBeTruthy();
    cleanup(); render(<Subscribe data={data} />);
    expect(screen.getByText(/never shared automatically/)).toBeTruthy();
  });
});
