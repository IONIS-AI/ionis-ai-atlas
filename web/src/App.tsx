// The shell (SPEC "The shell"): primary navigation across the top, a contextual sidebar on the left,
// the content region in the middle. The frame persists; only the content region changes. Every
// view is addressable by URL, and its filter state lives in the URL (R11).
import { useEffect, useState } from "react";
import { NavLink, Navigate, Route, Routes, useParams, useSearchParams } from "react-router-dom";
import { api, type EnumerationSummary, type Release } from "./api/client";
import { AdifView, DEFINITIONS } from "./adif/AdifView";

// Sections appear here as they are built. A section that does not exist yet is absent, not disabled.
const SECTIONS = [{ path: "/adif", label: "ADIF Reference" }];

export function App() {
  return (
    <div className="shell">
      <header className="topbar">
        <div className="brand">IONIS <span>Atlas</span></div>
        <nav className="sections" aria-label="Sections">
          {SECTIONS.map((s) => (
            <NavLink key={s.path} to={s.path} className={({ isActive }) => (isActive ? "active" : "")}>
              {s.label}
            </NavLink>
          ))}
        </nav>
        <a className="apidocs" href="/api/docs">API</a>
      </header>
      <Routes>
        <Route path="/" element={<Navigate to="/adif/band" replace />} />
        <Route path="/adif" element={<Navigate to="/adif/band" replace />} />
        <Route path="/adif/:view" element={<AdifSection />} />
        <Route path="*" element={<main className="content"><p className="state">No such page.</p></main>} />
      </Routes>
    </div>
  );
}

function AdifSection() {
  const { view = "band" } = useParams();
  const [params, setParams] = useSearchParams();
  const [releases, setReleases] = useState<Release[] | null>(null);
  const [current, setCurrent] = useState<string | null>(null);
  const [enums, setEnums] = useState<EnumerationSummary[]>([]);

  useEffect(() => {
    api.GET("/api/v1/adif/releases").then(({ data }) => setReleases(data ?? []));
    api.GET("/api/v1/adif/current").then(({ data }) => setCurrent(data?.adif_version ?? null));
  }, []);

  const version = params.get("v") ?? current;
  useEffect(() => {
    if (!version) return;
    api.GET("/api/v1/adif/enumerations", { params: { query: { adif_version: version } } }).then(({ data }) => setEnums(data ?? []));
  }, [version]);
  const query = params.get("q") ?? "";
  const set = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next, { replace: true });
  };
  const search = params.toString();

  return (
    <>
      <aside className="sidebar">
        <label className="control">
          <span>ADIF version</span>
          <select value={version ?? ""} onChange={(e) => set("v", e.target.value === current ? "" : e.target.value)}>
            {(releases ?? []).map((r) => (
              <option key={r.adif_version} value={r.adif_version}>
                {r.adif_version}{r.adif_version === current ? " (current)" : ""}
              </option>
            ))}
          </select>
        </label>
        <label className="control">
          <span>Filter</span>
          <input type="search" value={query} placeholder="e.g. FT4, 20m, Bouvet"
            onChange={(e) => set("q", e.target.value)} />
        </label>
        <nav className="views" aria-label="ADIF definitions">
          <span className="group">Definitions</span>
          {DEFINITIONS.map((v) => (
            <NavLink key={v.key} to={{ pathname: `/adif/${v.key}`, search }} className={({ isActive }) => (isActive ? "active" : "")}>
              {v.label}
            </NavLink>
          ))}
        </nav>
        <nav className="views" aria-label="ADIF enumerations">
          <span className="group">Enumerations ({enums.length})</span>
          {enums.map((e) => (
            <NavLink key={e.table} to={{ pathname: `/adif/${e.table}`, search }} className={({ isActive }) => (isActive ? "active" : "")}>
              <span>{e.name.replace(/_/g, " ")}</span><span className="n">{e.records}</span>
            </NavLink>
          ))}
        </nav>
        <p className="note">ADIF {version ?? "…"} as published by adif.org, loaded unmodified.</p>
      </aside>
      <main className="content">
        {version ? <AdifView view={view} version={version} query={query} /> : <p className="state">Loading…</p>}
      </main>
    </>
  );
}
