// The only way the front end reaches the API. Types come from schema.d.ts, which is generated from
// the API's published OpenAPI description (npm run gen:api), so a path or field that does not
// exist in the contract is a compile error, not a runtime surprise.
import createClient from "openapi-fetch";
import type { components, paths } from "./schema";

export const api = createClient<paths>({ baseUrl: "" });

/** The API did not give what was asked: an HTTP error, or no body. */
export class Unavailable extends Error {}

/**
 * openapi-fetch does not throw on an HTTP error: it returns `{ error, response }` with no data. A
 * caller that falls back to a default (`data ?? []`) would then show "0 enumerations" as though it
 * were a count. Every call whose answer is shown goes through ok(), so a failure is a failure.
 */
export async function ok<D>(call: Promise<{ data?: D; error?: unknown; response: Response }>): Promise<{ data: D; response: Response }> {
  const { data, response } = await call;
  if (!response.ok || data === undefined) throw new Unavailable(`${response.url || "API"}: HTTP ${response.status}`);
  return { data, response };
}

/** The X-Total-Count of a paged answer (R15). Missing is a failure, not zero. */
export function totalCount(response: Response): number {
  const n = Number(response.headers.get("X-Total-Count"));
  if (response.headers.get("X-Total-Count") === null || !Number.isFinite(n)) throw new Unavailable(`${response.url}: no X-Total-Count`);
  return n;
}

export type Band = components["schemas"]["Band"];
export type Mode = components["schemas"]["Mode"];
export type DxccEntity = components["schemas"]["DxccEntity"];
export type Contest = components["schemas"]["Contest"];
export type Field = components["schemas"]["Field"];
export type Release = components["schemas"]["Release"];
export type DataType = components["schemas"]["DataType"];
export type EnumerationSummary = components["schemas"]["EnumerationSummary"];
export type Enumeration = components["schemas"]["Enumeration"];
