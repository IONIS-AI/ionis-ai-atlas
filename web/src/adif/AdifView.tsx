// The ADIF Reference section: ADIF's own tables, as the lab loaded them from adif.org.
// Every list is paged, searched and filtered by the API (SPEC R15): the browser asks for one page and
// never holds a whole table. Names follow the spec (R16): the route segment is the table name, and
// each view's heading shows ADIF's own name, the file ADIF publishes it as, and its API route.
// A handful of enumerations have tailored layouts; every other one renders from the columns ADIF
// defines for it, so all 25 are reachable without 25 hand views.
// Filters are per view (#38) and derived from what the view holds, never from a list of names: a
// deleted / import-only filter where the table has that flag, an entity filter where it has a DXCC
// entity code (choices from the API's distinct values), a frequency on bands, a data type on fields.
// In the URL each is f.<API parameter>, and it goes to the API as that parameter.
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
  total: number;     // rows matching the search and filters, across all pages
  columns: string[]; // the table's columns, for a generic view's filters; empty for curated views
};
type Filters = Record<string, string>;   // API parameter -> value

const FLAGS: Record<string, [string, string]> = {  // column -> [label when true, label when false]
  deleted: ["deleted", "not deleted"],
  import_only: ["import-only", "not import-only"],
};
const ENTITY = "dxcc_entity_code";

function readFilters(params: URLSearchParams): Filters {
  const out: Filters = {};
  params.forEach((v, k) => { if (k.startsWith("f.") && v) out[k.slice(2)] = v; });
  return out;
}

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

async function load(view: string, v: string, limit: number, offset: number, q?: string, filters: Filters = {}): Promise<Loaded> {
  const query = { adif_version: v, limit, offset, ...(q ? { q } : {}) };
  switch (view) {
    case "datatypes": {
      const { data, response } = await api.GET("/api/v1/adif/datatypes", { params: { query } });
      if (!data) throw new Error("no data");
      return { label: "Data Types", adifName: "DataTypes", file: "datatypes.json", route: `${API}/datatypes`, columns: [],
        lead: "ADIF's data types: what a field's value may look like.", rows: data, total: counted(response, data.length), cols: [
          { head: "Data type", cell: (r) => <code>{r.data_type_name}</code> },
          { head: "Indicator", cell: (r) => r.data_type_indicator },
          { head: "Description", cell: (r) => r.description },
          { head: "", cell: (r) => tag(r.import_only, "import only") },
        ] };
    }
    case "fields": {
      const { data, response } = await api.GET("/api/v1/adif/fields", {
        params: { query: { ...query, ...(filters.data_type ? { data_type: filters.data_type } : {}) } } });
      if (!data) throw new Error("no data");
      return { label: "Fields", adifName: "Fields", file: "fields.json", route: `${API}/fields`, columns: [],
        lead: "ADIF's fields: the definitions every IONIS-AI column is built on.", rows: data, total: counted(response, data.length), cols: [
          { head: "Field", cell: (r) => <code>{r.field_name}</code> },
          { head: "Data type", cell: (r) => r.data_type },
          { head: "Enumeration", cell: (r) => r.enumeration },
          { head: "Description", cell: (r) => r.description },
          { head: "", cell: (r) => tag(r.import_only, "import only") },
        ] };
    }
    case "band": {
      const freq = Number(filters.freq_mhz);
      const { data, response } = await api.GET("/api/v1/adif/bands", {
        params: { query: { ...query, ...(filters.freq_mhz && Number.isFinite(freq) ? { freq_mhz: freq } : {}) } } });
      if (!data) throw new Error("no data");
      return { ...enumMeta("band", "Band"), columns: [], lead: "ADIF's Band enumeration, lowest frequency first. Frequencies in MHz.",
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
      return { ...enumMeta("mode", "Mode"), columns: [], lead: "ADIF's Mode enumeration with its submodes: FT4, for example, is a submode of MFSK. A search matches submodes too.",
        rows: data, total: counted(response, data.length), cols: [
          { head: "Mode", cell: (r) => <strong>{r.mode}</strong> },
          { head: "Submodes", cell: (r) => r.submodes.join(", ") },
          { head: "Description", cell: (r) => r.description },
          { head: "", cell: (r) => tag(r.import_only, "import only") },
        ] };
    }
    default: {
      // Column filters are any of the table's own column names (the API refuses one it lacks), so the
      // typed query is widened here, deliberately.
      const { data, error } = await api.GET("/api/v1/adif/enumerations/{name}", {
        params: { path: { name: view }, query: { ...query, ...filters } as typeof query } });
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
      return { ...enumMeta(data.table, data.name), lead: `ADIF's ${data.name} enumeration.`, rows: data.rows, total: data.total, cols,
        columns: data.columns.map((c) => c.name) };
    }
  }
}

export function AdifView({ view, version }: { view: string; version: string }) {
  const [params, setParams] = useSearchParams();
  const { page, size } = readPaging(params);
  const q = params.get("q") ?? "";
  const filters = readFilters(params);
  const filterKey = JSON.stringify(filters);
  const narrowed = Boolean(q) || Object.keys(filters).length > 0;
  const [state, setState] = useState<Loaded | "error" | null>(null);
  const [entities, setEntities] = useState<Record<string, string>>({});  // DXCC code -> name
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
    load(view, version, size, (page - 1) * size, q || undefined, filters)
      .then((r) => { if (!live) return; setState(r); setLoading(false); if (!narrowed) setAll(r.total); })
      .catch(() => { if (live) { setState("error"); setLoading(false); } });
    return () => { live = false; };
  }, [view, version, page, size, q, filterKey]); // eslint-disable-line react-hooks/exhaustive-deps

  // With a search or filter on, one row asked for without them gives the total they narrowed from.
  useEffect(() => {
    if (!narrowed) return;
    let live = true;
    load(view, version, 1, 0).then((r) => live && setAll(r.total)).catch(() => undefined);
    return () => { live = false; };
  }, [view, version, narrowed]); // eslint-disable-line react-hooks/exhaustive-deps

  // Entity names, for the entity filter and for saying what it narrowed to.
  const hasEntity = state !== null && state !== "error" && state.columns.includes(ENTITY);
  useEffect(() => {
    if (!hasEntity) return;
    let live = true;
    api.GET("/api/v1/adif/dxcc", { params: { query: { adif_version: version, limit: 1000 } } })
      .then(({ data }) => live && setEntities(Object.fromEntries((data ?? []).map((e) => [String(e.entity_code), e.entity_name]))));
    return () => { live = false; };
  }, [hasEntity, version]);

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
          {narrowed ? <> {describe(q, filters, entities)}{all !== null ? ` · ${all.toLocaleString("en-US")} in all` : ""}</> : null} · ADIF {version}
        </span>
        <label className="size">Rows
          <select value={size} onChange={(e) => update({ size: Number(e.target.value) === DEFAULT_SIZE ? null : e.target.value, page: null })}>
            {PAGE_SIZES.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </label>
      </div>
      <FilterControls view={view} version={version} columns={state.columns} filters={filters} entities={entities}
        set={(k, v) => update({ [`f.${k}`]: v, page: null })}
        clear={() => update({ ...Object.fromEntries(Object.keys(filters).map((k) => [`f.${k}`, null])), q: null, page: null })} />
      {state.rows.length === 0 ? (
        <p className="state">Nothing in {state.label} (ADIF {version}) {describe(q, filters, entities)}.</p>
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


/** What the search and filters narrowed to, in words: 'matching “oblast”, entity ASIATIC RUSSIA (15)'. */
function describe(q: string, filters: Filters, entities: Record<string, string>): string {
  const parts = Object.entries(filters).map(([k, v]) =>
    k in FLAGS ? FLAGS[k][v === "true" ? 0 : 1]
      : k === ENTITY ? `entity ${entities[v] ? `${entities[v]} (${v})` : v}`
      : k === "freq_mhz" ? `containing ${v} MHz`
      : k === "data_type" ? `of type ${v}`
      : `${k} = ${v}`);
  return [q ? `matching “${q}”` : "", ...parts].filter(Boolean).join(", ");
}

type FilterProps = {
  view: string; version: string; columns: string[]; filters: Filters; entities: Record<string, string>;
  set: (param: string, value: string | null) => void; clear: () => void;
};

/** The filters this view offers, derived from what it holds (#38). */
function FilterControls({ view, version, columns, filters, entities, set, clear }: FilterProps) {
  const [choices, setChoices] = useState<{ value: string; count: number }[]>([]);
  const [types, setTypes] = useState<string[]>([]);
  const [freq, setFreq] = useState(filters.freq_mhz ?? "");
  const hasEntity = columns.includes(ENTITY);

  useEffect(() => {  // which entities this table has, and how many records each
    if (!hasEntity) return;
    let live = true;
    api.GET("/api/v1/adif/enumerations/{name}/values/{column}", {
      params: { path: { name: view, column: ENTITY }, query: { adif_version: version, limit: 1000 } } })
      .then(({ data }) => live && setChoices((data ?? []).filter((c) => c.value !== null) as { value: string; count: number }[]));
    return () => { live = false; };
  }, [hasEntity, view, version]);
  useEffect(() => {  // ADIF's data types, for the fields view
    if (view !== "fields") return;
    let live = true;
    api.GET("/api/v1/adif/datatypes", { params: { query: { adif_version: version, limit: 1000 } } })
      .then(({ data }) => live && setTypes((data ?? []).map((d) => d.data_type_name)));
    return () => { live = false; };
  }, [view, version]);
  useEffect(() => setFreq(filters.freq_mhz ?? ""), [filters.freq_mhz]);
  useEffect(() => {  // a frequency applies a moment after typing stops, like the search
    if (view !== "band" || freq === (filters.freq_mhz ?? "")) return;
    const t = setTimeout(() => set("freq_mhz", freq.trim() || null), 300);
    return () => clearTimeout(t);
  }, [freq]); // eslint-disable-line react-hooks/exhaustive-deps

  const flags = Object.keys(FLAGS).filter((f) => columns.includes(f));
  const named = (code: string) => entities[code] ?? code;
  const sorted = [...choices].sort((a, b) => named(a.value).localeCompare(named(b.value)));
  if (!flags.length && !hasEntity && view !== "band" && view !== "fields") return null;

  return (
    <div className="filters" role="group" aria-label="Filters">
      {view === "band" && (
        <label>Contains
          <input type="number" inputMode="decimal" step="any" min="0" placeholder="MHz, e.g. 14.074" value={freq}
            aria-label="Band containing this frequency (MHz)" onChange={(e) => setFreq(e.target.value)} />
        </label>
      )}
      {view === "fields" && (
        <label>Data type
          <select aria-label="Data type" value={filters.data_type ?? ""} onChange={(e) => set("data_type", e.target.value || null)}>
            <option value="">any</option>
            {types.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
        </label>
      )}
      {hasEntity && (
        <label>Entity
          <select aria-label="DXCC entity" value={filters[ENTITY] ?? ""} onChange={(e) => set(ENTITY, e.target.value || null)}>
            <option value="">any ({choices.length})</option>
            {sorted.map((c) => (
              <option key={c.value} value={c.value}>{named(c.value)}{entities[c.value] ? ` (${c.value})` : ""} · {c.count}</option>
            ))}
          </select>
        </label>
      )}
      {flags.map((f) => (
        <label key={f}>{FLAGS[f][0].replace(/^\w/, (x) => x.toUpperCase())}
          <select aria-label={FLAGS[f][0]} value={filters[f] ?? ""} onChange={(e) => set(f, e.target.value || null)}>
            <option value="">any</option>
            <option value="true">yes</option>
            <option value="false">no</option>
          </select>
        </label>
      ))}
      {Object.keys(filters).length > 0 && <button type="button" className="clear" onClick={clear}>Clear filters</button>}
    </div>
  );
}
