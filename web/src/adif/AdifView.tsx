// The ADIF Reference section: ADIF's own tables, as the lab loaded them from adif.org.
import { useEffect, useState, type ReactNode } from "react";
import { api } from "../api/client";
import { matches, shownOf } from "../lib/filter";

type Col<T> = { head: string; cell: (r: T) => ReactNode; num?: boolean };
type ViewDef = { key: string; label: string; lead: string };

export const ADIF_VIEWS: ViewDef[] = [
  { key: "bands", label: "Bands", lead: "ADIF's Band enumeration, lowest frequency first. Frequencies in MHz." },
  { key: "modes", label: "Modes", lead: "ADIF's Mode enumeration with its submodes: FT4, for example, is a submode of MFSK." },
  { key: "dxcc", label: "DXCC entities", lead: "ADIF's DXCC Entity Code enumeration. Deleted entities stay listed, marked deleted." },
  { key: "contests", label: "Contest IDs", lead: "ADIF's Contest_ID enumeration." },
  { key: "fields", label: "Fields", lead: "ADIF's fields: the definitions every IONIS column is built on." },
];

const importOnly = (v: boolean) => (v ? <span className="tag">import only</span> : null);

async function load(view: string, v: string): Promise<{ rows: Record<string, unknown>[]; cols: Col<any>[] }> {
  const q = { params: { query: { adif_version: v } } };
  switch (view) {
    case "bands": {
      const { data } = await api.GET("/api/v1/adif/bands", q);
      return { rows: data ?? [], cols: [
        { head: "Band", cell: (r) => <strong>{r.band}</strong> },
        { head: "Lower (MHz)", cell: (r) => r.lower_freq_mhz, num: true },
        { head: "Upper (MHz)", cell: (r) => r.upper_freq_mhz, num: true },
        { head: "", cell: (r) => importOnly(r.import_only) },
      ] };
    }
    case "modes": {
      const { data } = await api.GET("/api/v1/adif/modes", q);
      return { rows: data ?? [], cols: [
        { head: "Mode", cell: (r) => <strong>{r.mode}</strong> },
        { head: "Submodes", cell: (r) => r.submodes.join(", ") },
        { head: "Description", cell: (r) => r.description },
        { head: "", cell: (r) => importOnly(r.import_only) },
      ] };
    }
    case "dxcc": {
      const { data } = await api.GET("/api/v1/adif/dxcc", q);
      return { rows: data ?? [], cols: [
        { head: "Code", cell: (r) => r.entity_code, num: true },
        { head: "Entity", cell: (r) => <strong>{r.entity_name}</strong> },
        { head: "", cell: (r) => (r.deleted ? <span className="tag">deleted</span> : null) },
      ] };
    }
    case "contests": {
      const { data } = await api.GET("/api/v1/adif/contests", q);
      return { rows: data ?? [], cols: [
        { head: "Contest ID", cell: (r) => <code>{r.contest_id}</code> },
        { head: "Description", cell: (r) => r.description },
        { head: "", cell: (r) => importOnly(r.import_only) },
      ] };
    }
    default: {
      const { data } = await api.GET("/api/v1/adif/fields", q);
      return { rows: data ?? [], cols: [
        { head: "Field", cell: (r) => <code>{r.field_name}</code> },
        { head: "Data type", cell: (r) => r.data_type },
        { head: "Enumeration", cell: (r) => r.enumeration },
        { head: "Description", cell: (r) => r.description },
        { head: "", cell: (r) => importOnly(r.import_only) },
      ] };
    }
  }
}

export function AdifView({ view, version, query }: { view: string; version: string; query: string }) {
  const def = ADIF_VIEWS.find((d) => d.key === view)!;
  const [state, setState] = useState<{ rows: Record<string, unknown>[]; cols: Col<any>[] } | "loading" | "error">("loading");

  useEffect(() => {
    let live = true;
    setState("loading");
    load(view, version).then((r) => live && setState(r)).catch(() => live && setState("error"));
    return () => { live = false; };
  }, [view, version]);

  return (
    <section>
      <h1>{def.label}</h1>
      <p className="lead">{def.lead}</p>
      {state === "loading" && <p className="state">Loading ADIF {version}…</p>}
      {state === "error" && <p className="state error">The API did not answer. Is the database container running?</p>}
      {typeof state === "object" && (() => {
        const shown = state.rows.filter((r) => matches(r, query));
        return (
          <>
            <p className="count">{shownOf(shown.length, state.rows.length)} · ADIF {version}</p>
            {shown.length === 0 ? (
              <p className="state">Nothing in ADIF {version} matches “{query}”.</p>
            ) : (
              <div className="tablewrap">
                <table>
                  <thead><tr>{state.cols.map((c, i) => <th key={i} className={c.num ? "num" : ""}>{c.head}</th>)}</tr></thead>
                  <tbody>
                    {shown.map((r, i) => (
                      <tr key={i}>{state.cols.map((c, j) => <td key={j} className={c.num ? "num" : ""}>{c.cell(r)}</td>)}</tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </>
        );
      })()}
    </section>
  );
}
