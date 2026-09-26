// The ADIF Reference section: ADIF's own tables, as the lab loaded them from adif.org.
// Views are keyed by table name. A handful have tailored layouts; every other enumeration renders
// generically from the columns ADIF defines for it, so all 25 are reachable without 25 hand views.
import { useEffect, useState, type ReactNode } from "react";
import { api } from "../api/client";
import { matches, shownOf } from "../lib/filter";

type Col = { head: string; cell: (r: any) => ReactNode; num?: boolean };
type Loaded = { title: string; lead: string; rows: Record<string, unknown>[]; cols: Col[] };

export const DEFINITIONS = [
  { key: "datatypes", label: "Data types" },
  { key: "fields", label: "Fields" },
];

const tag = (on: unknown, text: string) => (on ? <span className="tag">{text}</span> : null);
const human = (col: string) => col.replace(/_/g, " ").replace(/\bmhz\b/i, "(MHz)").replace(/^\w/, (c) => c.toUpperCase());

async function load(view: string, v: string): Promise<Loaded> {
  const q = { params: { query: { adif_version: v } } };
  switch (view) {
    case "datatypes": {
      const { data } = await api.GET("/api/v1/adif/datatypes", q);
      return { title: "Data types", lead: "ADIF's data types: what a field's value may look like.", rows: data ?? [], cols: [
        { head: "Data type", cell: (r) => <code>{r.data_type_name}</code> },
        { head: "Indicator", cell: (r) => r.data_type_indicator },
        { head: "Description", cell: (r) => r.description },
        { head: "", cell: (r) => tag(r.import_only, "import only") },
      ] };
    }
    case "fields": {
      const { data } = await api.GET("/api/v1/adif/fields", q);
      return { title: "Fields", lead: "ADIF's fields: the definitions every IONIS column is built on.", rows: data ?? [], cols: [
        { head: "Field", cell: (r) => <code>{r.field_name}</code> },
        { head: "Data type", cell: (r) => r.data_type },
        { head: "Enumeration", cell: (r) => r.enumeration },
        { head: "Description", cell: (r) => r.description },
        { head: "", cell: (r) => tag(r.import_only, "import only") },
      ] };
    }
    case "band": {
      const { data } = await api.GET("/api/v1/adif/bands", q);
      return { title: "Band", lead: "ADIF's Band enumeration, lowest frequency first. Frequencies in MHz.", rows: data ?? [], cols: [
        { head: "Band", cell: (r) => <strong>{r.band}</strong> },
        { head: "Lower (MHz)", cell: (r) => r.lower_freq_mhz, num: true },
        { head: "Upper (MHz)", cell: (r) => r.upper_freq_mhz, num: true },
        { head: "", cell: (r) => tag(r.import_only, "import only") },
      ] };
    }
    case "mode": {
      const { data } = await api.GET("/api/v1/adif/modes", q);
      return { title: "Mode", lead: "ADIF's Mode enumeration with its submodes: FT4, for example, is a submode of MFSK.", rows: data ?? [], cols: [
        { head: "Mode", cell: (r) => <strong>{r.mode}</strong> },
        { head: "Submodes", cell: (r) => r.submodes.join(", ") },
        { head: "Description", cell: (r) => r.description },
        { head: "", cell: (r) => tag(r.import_only, "import only") },
      ] };
    }
    default: {
      const { data, error } = await api.GET("/api/v1/adif/enumerations/{name}", { params: { path: { name: view }, query: { adif_version: v } } });
      if (error || !data) throw new Error("not found");
      const flags = new Set(["import_only", "deleted"]);
      const cols: Col[] = data.columns
        .filter((c) => !flags.has(c.name) && c.name !== "record_key")
        .map((c, i) => ({
          head: human(c.name),
          num: ["integer", "numeric"].includes(c.type),
          cell: (r) => (i === 0 ? <strong>{String(r[c.name] ?? "")}</strong> : (r[c.name] as ReactNode)),
        }));
      cols.push({ head: "", cell: (r) => <>{tag(r.deleted, "deleted")} {tag(r.import_only, "import only")}</> });
      return { title: data.name.replace(/_/g, " "), lead: `ADIF's ${data.name} enumeration.`, rows: data.rows, cols };
    }
  }
}

export function AdifView({ view, version, query }: { view: string; version: string; query: string }) {
  const [state, setState] = useState<Loaded | "loading" | "error">("loading");

  useEffect(() => {
    let live = true;
    setState("loading");
    load(view, version).then((r) => live && setState(r)).catch(() => live && setState("error"));
    return () => { live = false; };
  }, [view, version]);

  if (state === "loading") return <p className="state">Loading ADIF {version}…</p>;
  if (state === "error") return <p className="state error">Nothing to show: ADIF {version} has no table “{view}”, or the API did not answer.</p>;
  const shown = state.rows.filter((r) => matches(r, query));
  return (
    <section>
      <h1>{state.title}</h1>
      <p className="lead">{state.lead}</p>
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
    </section>
  );
}
