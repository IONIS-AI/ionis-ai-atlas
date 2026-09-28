import { describe, expect, it } from "vitest";
import { CURATED_FILTERS, invalidFilter } from "./filters";

describe("invalidFilter (#62)", () => {
  it("accepts each curated view's own filters", () => {
    expect(invalidFilter("band", { freq_mhz: "14.074" })).toBeNull();
    expect(invalidFilter("fields", { data_type: "Enumeration" })).toBeNull();
    expect(invalidFilter("mode", {})).toBeNull();
  });
  it("refuses a filter the curated view does not support (Hopper's repro)", () => {
    expect(invalidFilter("band", { no_such: "x" })).toMatch(/not by “no_such”/);
    expect(invalidFilter("mode", { data_type: "String" })).toMatch(/no filters/);
    expect(invalidFilter("datatypes", { freq_mhz: "1" })).toMatch(/no filters/);
  });
  it("refuses a frequency that is not one", () => {
    for (const bad of ["abc", "-1", " ", "1e999"]) expect(invalidFilter("band", { freq_mhz: bad })).toMatch(/not a frequency/);
  });
  it("leaves the generic enumeration views to the API, which refuses unknown columns", () => {
    expect(invalidFilter("primary_administrative_subdivision", { no_such: "x" })).toBeNull();
  });
  it("covers every curated view", () => {
    expect(Object.keys(CURATED_FILTERS).sort()).toEqual(["band", "datatypes", "fields", "mode"]);
  });
});
