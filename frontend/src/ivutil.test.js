import { describe, it, expect } from "vitest";
import { stageOf, buildItems, split, where } from "./ivutil.js";

const iv = (status, matches = {}) => ({ id: "a", status, matches, cluster: { id: "C1", lat: 30, lon: 75, priority: "high", fires: 5, last_detected: "2026-10-08T10:00:00Z" } });

describe("stageOf", () => {
  it("ticks only what the record shows", () => {
    expect(stageOf(null).done).toBe(1);
    expect(stageOf(iv("open")).done).toBe(2);
    expect(stageOf(iv("open", { suggested: 2 })).done).toBe(3);
    expect(stageOf(iv("coordinating", { asked: 2 })).done).toBe(3);
    expect(stageOf(iv("accepted", { accepted: 1 })).done).toBe(4);
  });
  it("only a verified outcome completes the last step", () => {
    expect(stageOf(iv("completed")).done).toBe(4);
    expect(stageOf(iv("rejected")).done).toBe(4);
    expect(stageOf(iv("verified")).done).toBe(5);
  });
});

describe("buildItems", () => {
  const clusters = [
    { id: "C1", lat: 30.01, lon: 75.01, priority: "high", fires: 5, wind_speed: 7, wind_from: 45, last_detected: "2026-10-08T10:00:00Z" },
    { id: "C2", lat: 31, lon: 76, priority: "low", fires: 2, last_detected: "2026-10-09T10:00:00Z" },
  ];
  it("adds live wind data to an intervention and keeps unmatched detections", () => {
    const out = buildItems([iv("open")], clusters);
    expect(out.map((x) => x.key)).toEqual(["a", "d-C2"]);
    expect(out[0].c.wind_speed).toBe(7);
    expect(out[1].iv).toBeNull();
  });
  it("sorts high priority first and works with no data", () => {
    expect(buildItems([], [clusters[1], clusters[0]])[0].c.priority).toBe("high");
    expect(buildItems(null, undefined)).toEqual([]);
  });
});

describe("split", () => {
  it("separates the place from its district", () => {
    expect(split("Sehjra, Kasur District, Punjab")).toEqual({ title: "Sehjra", sub: "Kasur District, Punjab" });
    expect(split("").title).toBe("Unnamed place");
  });
});

describe("where", () => {
  it("never splits coordinates when there is no place name", () => {
    expect(where({ id: "C3", lat: 29.11, lon: 75.3 })).toEqual({ title: "Fire cluster C3", sub: "29.11°N, 75.30°E" });
    expect(where({ place: "Sehjra, Kasur District", lat: 1, lon: 1 }).title).toBe("Sehjra");
  });
});
