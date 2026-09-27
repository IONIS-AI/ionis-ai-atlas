import { describe, expect, it } from "vitest";
import { DEFAULT_SIZE, pageCount, rangeOf, readPaging } from "./paging";

describe("rangeOf", () => {
  it("names the rows on this page and the total", () => expect(rangeOf(0, 100, 1965)).toBe("1–100 of 1,965"));
  it("handles the short last page", () => expect(rangeOf(1900, 65, 1965)).toBe("1,901–1,965 of 1,965"));
  it("says nothing matched", () => expect(rangeOf(0, 0, 0)).toBe("0 of 0"));
});

describe("pageCount", () => {
  it("rounds up", () => expect(pageCount(1965, 100)).toBe(20));
  it("is exact on a boundary", () => expect(pageCount(200, 100)).toBe(2));
  it("is at least one", () => expect(pageCount(0, 100)).toBe(1));
});

describe("readPaging", () => {
  const read = (s: string) => readPaging(new URLSearchParams(s));
  it("defaults", () => expect(read("")).toEqual({ page: 1, size: DEFAULT_SIZE }));
  it("reads both", () => expect(read("page=3&size=250")).toEqual({ page: 3, size: 250 }));
  it("refuses sizes it doesn't offer", () => expect(read("size=99999").size).toBe(DEFAULT_SIZE));
  it("refuses nonsense pages", () => {
    expect(read("page=0").page).toBe(1);
    expect(read("page=-2").page).toBe(1);
    expect(read("page=abc").page).toBe(1);
    expect(read("page=1.5").page).toBe(1);
  });
});
