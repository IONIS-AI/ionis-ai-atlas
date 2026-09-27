import { describe, expect, it } from "vitest";
import { NAV_KEY, readCollapsed, saveCollapsed } from "./nav";

const memory = () => {
  const m = new Map<string, string>();
  return { getItem: (k: string) => m.get(k) ?? null, setItem: (k: string, v: string) => void m.set(k, v) };
};
const refusing = {
  getItem: () => { throw new Error("SecurityError"); },
  setItem: () => { throw new Error("QuotaExceededError"); },
};

describe("readCollapsed", () => {
  it("defaults open on a desktop", () => expect(readCollapsed(memory(), 1440)).toBe(false));
  it("defaults collapsed on a phone", () => expect(readCollapsed(memory(), 390)).toBe(true));
  it("remembers a choice over the default", () => {
    const s = memory();
    saveCollapsed(s, true);
    expect(readCollapsed(s, 1440)).toBe(true);
    saveCollapsed(s, false);
    expect(readCollapsed(s, 390)).toBe(false);
  });
  it("ignores a value it did not write", () => {
    const s = memory();
    s.setItem(NAV_KEY, "yes");
    expect(readCollapsed(s, 1440)).toBe(false);
  });
  it("works with no storage at all", () => {
    expect(readCollapsed(undefined, 390)).toBe(true);
    expect(() => saveCollapsed(undefined, true)).not.toThrow();
  });
  it("works when storage refuses", () => {
    expect(readCollapsed(refusing, 1440)).toBe(false);
    expect(() => saveCollapsed(refusing, true)).not.toThrow();
  });
});
