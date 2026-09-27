import { describe, expect, it } from "vitest";
import { ok, totalCount, Unavailable } from "./client";

const answer = (status: number, data?: unknown, headers: Record<string, string> = {}) =>
  Promise.resolve({ data, error: status >= 400 ? { detail: "x" } : undefined, response: new Response(null, { status, headers }) });

describe("ok", () => {
  it("passes an answer through", async () => expect((await ok(answer(200, [1, 2]))).data).toEqual([1, 2]));
  it("an HTTP error is a failure, not an empty answer", async () =>
    expect(ok(answer(500))).rejects.toBeInstanceOf(Unavailable));
  it("a 503 with a body is still a failure", async () =>
    expect(ok(answer(503, { detail: "No current ADIF version" }))).rejects.toBeInstanceOf(Unavailable));
});

describe("totalCount", () => {
  it("reads X-Total-Count", () => expect(totalCount(new Response(null, { headers: { "X-Total-Count": "37" } }))).toBe(37));
  it("zero is a count", () => expect(totalCount(new Response(null, { headers: { "X-Total-Count": "0" } }))).toBe(0));
  it("a missing header is a failure, not zero", () => expect(() => totalCount(new Response(null))).toThrow(Unavailable));
});
