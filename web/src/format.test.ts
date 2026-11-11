import { describe, expect, it } from "vitest";

import { formatDuration, formatEvidence, formatMinutes, formatNumber, humanizeKey, splitList } from "./format";

describe("formatNumber", () => {
  it("keeps one decimal under 100 and none above", () => {
    expect(formatNumber(59.94)).toBe("59.9");
    expect(formatNumber(142.4)).toBe("142");
    expect(formatNumber(60)).toBe("60");
    expect(formatNumber(71.5, "°C")).toBe("71.5 °C");
  });
  it("shows a dash for missing values", () => {
    expect(formatNumber(null)).toBe("-");
    expect(formatNumber(undefined)).toBe("-");
    expect(formatNumber(Number.NaN)).toBe("-");
  });
});

describe("durations", () => {
  it("formats seconds and minutes", () => {
    expect(formatDuration(45)).toBe("45 s");
    expect(formatDuration(300)).toBe("5 min");
    expect(formatDuration(150.4)).toBe("2 min 30 s");
    expect(formatMinutes(45)).toBe("45 min");
    expect(formatMinutes(120)).toBe("2 h");
    expect(formatMinutes(95)).toBe("1 h 35 min");
    expect(formatMinutes(null)).toBe("");
  });
});

describe("splitList", () => {
  it("splits on commas, semicolons and new lines, trims and removes repeats", () => {
    expect(splitList("RTX 3070,  B550 ; rtx 3070\n0x124,,")).toEqual(["RTX 3070", "B550", "0x124"]);
    expect(splitList("   ")).toEqual([]);
  });
});

describe("evidence", () => {
  it("turns keys into readable labels", () => {
    expect(humanizeKey("cpu_temp_max_c")).toBe("Cpu temp max °C");
    expect(humanizeKey("free_share")).toBe("Free share");
    expect(humanizeKey("wear_pct")).toBe("Wear %");
  });
  it("formats nested values", () => {
    expect(formatEvidence({ "0x1A": 2, "0x50": 1 })).toBe("0x1A: 2, 0x50: 1");
    expect(formatEvidence(["a", "b"])).toBe("a, b");
    expect(formatEvidence(true)).toBe("yes");
    expect(formatEvidence(null)).toBe("-");
  });
});
