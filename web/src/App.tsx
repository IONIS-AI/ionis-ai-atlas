// The shell (SPEC "The shell"): primary navigation across the top, a contextual sidebar on the left,
// the content region in the middle. The frame persists; only the content region changes. Every
// view is addressable by URL, and its filter state lives in the URL (R11).
import { useEffect, useMemo, useState } from "react";
import { NavLink, Navigate, Route, Routes, useParams, useSearchParams } from "react-router-dom";
import { api, type Release } from "./api/client";
import { AdifView, ADIF_VIEWS } from "./adif/AdifView";

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
        <Route path="/" element={<Navigate to="/adif/bands" replace />} />
        <Route path="/adif" element={<Navigate to="/adif/bands" replace />} />
        <Route path="/adif/:view" element={<AdifSection />} />
        <Route path="*" element={<main className="content"><p className="state">No such page.</p></main>} />
      </Routes>
    </div>
  );
}

function AdifSection() {
  const { view = "bands" } = useParams();
  const [params, setParams] = useSearchParams();
  const [releases, setReleases] = useState<Release[] | null>(null);
  const [current, setCurrent] = useState<string | null>(null);

  useEffect(() => {
    api.GET("/api/v1/adif/releases").then(({ data }) => setReleases(data ?? []));
    api.GET("/api/v1/adif/current").then(({ data }) => setCurrent(data?.adif_version ?? null));
  }, []);

  const version = params.get("v") ?? current;
  const query = params.get("q") ?? "";
  const set = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next, { replace: true });
  };
  const known = useMemo(() => ADIF_VIEWS.map((v) => v.key), []);
  if (!known.includes(view)) return <Navigate to="/adif/bands" replace />;

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
        <nav className="views" aria-label="ADIF tables">
          {ADIF_VIEWS.map((v) => (
            <NavLink key={v.key} to={{ pathname: `/adif/${v.key}`, search: params.toString() }}
              className={({ isActive }) => (isActive ? "active" : "")}>
              {v.label}
            </NavLink>
          ))}
        </nav>
        <label className="control">
          <span>Filter</span>
          <input type="search" value={query} placeholder="e.g. FT4, 20m, Bouvet"
            onChange={(e) => set("q", e.target.value)} />
        </label>
        <p className="note">ADIF {version ?? "…"} as published by adif.org, loaded unmodified.</p>
      </aside>
      <main className="content">
        {version ? <AdifView view={view} version={version} query={query} /> : <p className="state">Loading…</p>}
      </main>
    </>
  );
}
