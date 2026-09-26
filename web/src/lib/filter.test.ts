import { describe, expect, it } from "vitest";
import { matches, shownOf } from "./filter";

describe("matches", () => {
  it("keeps everything for an empty query", () => expect(matches({ mode: "MFSK" }, "  ")).toBe(true));
  it("is case-insensitive", () => expect(matches({ mode: "MFSK" }, "mfsk")).toBe(true));
  it("searches inside lists, so a submode finds its mode", () =>
    expect(matches({ mode: "MFSK", submodes: ["FT4", "JS8"] }, "ft4")).toBe(true));
  it("ignores nulls", () => expect(matches({ description: null }, "x")).toBe(false));
});

describe("shownOf", () => {
  it("says what was discarded", () => expect(shownOf(12, 403)).toBe("12 of 403 shown"));
  it("is plain when nothing was", () => expect(shownOf(403, 403)).toBe("403 shown"));
});
