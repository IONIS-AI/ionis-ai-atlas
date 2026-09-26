// The only way the front end reaches the API. Types come from schema.d.ts, which is generated from
// the API's published OpenAPI description (npm run gen:api), so a path or field that does not
// exist in the contract is a compile error, not a runtime surprise.
import createClient from "openapi-fetch";
import type { components, paths } from "./schema";

export const api = createClient<paths>({ baseUrl: "" });

export type Band = components["schemas"]["Band"];
export type Mode = components["schemas"]["Mode"];
export type DxccEntity = components["schemas"]["DxccEntity"];
export type Contest = components["schemas"]["Contest"];
export type Field = components["schemas"]["Field"];
export type Release = components["schemas"]["Release"];
export type DataType = components["schemas"]["DataType"];
export type EnumerationSummary = components["schemas"]["EnumerationSummary"];
export type Enumeration = components["schemas"]["Enumeration"];
