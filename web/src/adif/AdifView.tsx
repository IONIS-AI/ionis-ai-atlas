// The ADIF Reference section: ADIF's own tables, as the lab loaded them from adif.org.
// Every list is paged, searched and filtered by the API (SPEC R15): the browser asks for one page and
// never holds a whole table. Names follow the spec (R16): the route segment is the table name, and
// each view's heading shows ADIF's own name, the file ADIF publishes it as, and its API route.
// A handful of enumerations have tailored layouts; every other one renders from the columns ADIF
// defines for it, so all 25 are reachable without 25 hand views.
import { useEffect, useState, type ReactNode } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import { DEFAULT_SIZE, PAGE_SIZES, pageCount, rangeOf, readPaging } from "../lib/paging";

type Col = { head: string; cell: (r: any) => ReactNode; num?: boolean };
type Loaded = {
  label: string;     // ADIF's name with spaces for underscores (R16)
  adifName: string;  // ADIF's exact name
  file: string;      // the file ADIF publishes it as
  route: string;     // the canonical API route
  lead: string;
  cols: Col[];
  rows: Record<string, unknown>[];
  total: number;     // rows matching the search, across all pages
};

// The two definition lists; everything else in the section is an enumeration.
export const DEFINITIONS = [
  { key: "datatypes", label: "Data Types" },
  { key: "fields", label: "Fields" },
];

const API = "/api/v1/adif";
const tag = (on: unknown, text: string) => (on ? <span className="tag">{text}</span> : null);
const human = (col: string) => col.replace(/_/g, " ").replace(/\bmhz\b/i, "(MHz)").replace(/^\w/, (c) => c.toUpperCase());
const counted = (r: Response, fallback: number) => Number(r.headers.get("X-Total-Count") ?? fallback);
const enumMeta = (table: string, adifName: string) => ({
  label: adifName.replace(/_/g, " "), adifName, file: `enumerations_${table}.json`, route: `${API}/enumerations/${table}`,
});

async function load(view: string, v: string, limit: number, offset: number, q?: string): Promise<Loaded> {
  const query = { adif_version: v, limit, offset, ...(q ? { q } : {}) };
  switch (view) {
    case "datatypes": {
      const { data, response } = await api.GET("/api/v1/adif/datatypes", { params: { query } });
      if (!data) throw new Error("no data");
      return { label: "Data Types", adifName: "DataTypes", file: "datatypes.json", route: `${API}/datatypes`,
        lead: "ADIF's data types: what a field's value may look like.", rows: data, total: counted(response, data.length), cols: [
          { head: "Data type", cell: (r) => <code>{r.data_type_name}</code> },
          { head: "Indicator", cell: (r) => r.data_type_indicator },
          { head: "Description", cell: (r) => r.description },
          { head: "", cell: (r) => tag(r.import_only, "import only") },
        ] };
    }
    case "fields": {
      const { data, response } = await api.GET("/api/v1/adif/fields", { params: { query } });
      if (!data) throw new Error("no data");
      return { label: "Fields", adifName: "Fields", file: "fields.json", route: `${API}/fields`,
        lead: "ADIF's fields: the definitions every IONIS-AI column is built on.", rows: data, total: counted(response, data.length), cols: [
          { head: "Field", cell: (r) => <code>{r.field_name}</code> },
          { head: "Data type", cell: (r) => r.data_type },
          { head: "Enumeration", cell: (r) => r.enumeration },
          { head: "Description", cell: (r) => r.description },
          { head: "", cell: (r) => tag(r.import_only, "import only") },
        ] };
    }
    case "band": {
      const { data, response } = await api.GET("/api/v1/adif/bands", { params: { query } });
      if (!data) throw new Error("no data");
      return { ...enumMeta("band", "Band"), lead: "ADIF's Band enumeration, lowest frequency first. Frequencies in MHz.",
        rows: data, total: counted(response, data.length), cols: [
          { head: "Band", cell: (r) => <strong>{r.band}</strong> },
          { head: "Lower (MHz)", cell: (r) => r.lower_freq_mhz, num: true },
          { head: "Upper (MHz)", cell: (r) => r.upper_freq_mhz, num: true },
          { head: "", cell: (r) => tag(r.import_only, "import only") },
        ] };
    }
    case "mode": {
      const { data, response } = await api.GET("/api/v1/adif/modes", { params: { query } });
      if (!data) throw new Error("no data");
      return { ...enumMeta("mode", "Mode"), lead: "ADIF's Mode enumeration with its submodes: FT4, for example, is a submode of MFSK. A search matches submodes too.",
        rows: data, total: counted(response, data.length), cols: [
          { head: "Mode", cell: (r) => <strong>{r.mode}</strong> },
          { head: "Submodes", cell: (r) => r.submodes.join(", ") },
          { head: "Description", cell: (r) => r.description },
          { head: "", cell: (r) => tag(r.import_only, "import only") },
        ] };
    }
    default: {
      const { data, error } = await api.GET("/api/v1/adif/enumerations/{name}", { params: { path: { name: view }, query } });
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
      return { ...enumMeta(data.table, data.name), lead: `ADIF's ${data.name} enumeration.`, rows: data.rows, total: data.total, cols };
    }
  }
}

export function AdifView({ view, version }: { view: string; version: string }) {
  const [params, setParams] = useSearchParams();
  const { page, size } = readPaging(params);
  const q = params.get("q") ?? "";
  const [state, setState] = useState<Loaded | "error" | null>(null);
  const [loading, setLoading] = useState(true);
  const [all, setAll] = useState<number | null>(null);  // rows before the search, to say what it left out
  const [draft, setDraft] = useState(q);

  // Everything a view shows is in the URL (R11): a filtered page can be linked to and restored.
  const update = (changes: Record<string, string | null>) => {
    const next = new URLSearchParams(params);
    for (const [k, v] of Object.entries(changes)) (v === null ? next.delete(k) : next.set(k, v));
    setParams(next, { replace: true });
  };
  const go = (p: number) => {
    update({ page: p <= 1 ? null : String(p) });
    // The content region scrolls on a desktop; on a phone the document does (#42). Reset both.
    document.querySelector(".content")?.scrollTo(0, 0);
    window.scrollTo(0, 0);
  };

  useEffect(() => setDraft(q), [q]);
  // Search as you type, a moment after typing stops; a new search starts at page 1.
  useEffect(() => {
    if (draft.trim() === q) return;
    const t = setTimeout(() => update({ q: draft.trim() || null, page: null }), 300);
    return () => clearTimeout(t);
  }, [draft]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    let live = true;
    setLoading(true);
    load(view, version, size, (page - 1) * size, q || undefined)
      .then((r) => { if (!live) return; setState(r); setLoading(false); if (!q) setAll(r.total); })
      .catch(() => { if (live) { setState("error"); setLoading(false); } });
    return () => { live = false; };
  }, [view, version, page, size, q]);

  // With a search on, one row asked for without it gives the unfiltered total.
  useEffect(() => {
    if (!q) return;
    let live = true;
    load(view, version, 1, 0).then((r) => live && setAll(r.total)).catch(() => undefined);
    return () => { live = false; };
  }, [view, version, q]);

  // A search can leave the page number past the end; bring it back to the last page.
  const last = state && state !== "error" ? pageCount(state.total, size) : 1;
  useEffect(() => {
    if (!loading && page > last) go(last);
  }, [loading, page, last]); // eslint-disable-line react-hooks/exhaustive-deps

  if (state === "error") return <p className="state error">Nothing to show: ADIF {version} has no table “{view}”, or the API did not answer.</p>;
  if (state === null) return <p className="state">Loading ADIF {version}…</p>;

  const pages = last;
  const offset = (page - 1) * size;

  return (
    <section>
      <h1>{state.label}</h1>
      <p className="source">
        <code>{state.adifName}</code> · <span>{state.file}</span> ·{" "}
        <a href={`${state.route}?adif_version=${version}&limit=${size}`}>GET {state.route}</a>
      </p>
      <p className="lead">{state.lead}</p>
      <div className="controls">
        <input type="search" value={draft} placeholder={`Search ${state.label}`} aria-label={`Search ${state.label}`}
          onChange={(e) => setDraft(e.target.value)} />
        <span className="count">
          {rangeOf(offset, state.rows.length, state.total)}
          {q ? <> matching “{q}”{all !== null ? ` · ${all.toLocaleString("en-US")} in all` : ""}</> : null} · ADIF {version}
        </span>
        <label className="size">Rows
          <select value={size} onChange={(e) => update({ size: Number(e.target.value) === DEFAULT_SIZE ? null : e.target.value, page: null })}>
            {PAGE_SIZES.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </label>
      </div>
      {state.rows.length === 0 ? (
        <p className="state">Nothing in {state.label} (ADIF {version}) matches “{q}”.</p>
      ) : (
        <div className={`tablewrap${loading ? " loading" : ""}`} aria-busy={loading}>
          <table>
            <thead><tr>{state.cols.map((c, i) => <th key={i} className={c.num ? "num" : ""}>{c.head}</th>)}</tr></thead>
            <tbody>
              {state.rows.map((r, i) => (
                <tr key={i}>{state.cols.map((c, j) => <td key={j} className={c.num ? "num" : ""}>{c.cell(r)}</td>)}</tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {pages > 1 && (
        <nav className="pager" aria-label="Pages">
          <button type="button" onClick={() => go(1)} disabled={page <= 1} aria-label="First page">«</button>
          <button type="button" onClick={() => go(page - 1)} disabled={page <= 1} aria-label="Previous page">‹</button>
          <span>Page {page} of {pages}</span>
          <button type="button" onClick={() => go(page + 1)} disabled={page >= pages} aria-label="Next page">›</button>
          <button type="button" onClick={() => go(pages)} disabled={page >= pages} aria-label="Last page">»</button>
        </nav>
      )}
    </section>
  );
}
