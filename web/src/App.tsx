// The shell (SPEC "The shell"): sections across the top; on the left, navigation only, named as the
// spec names things (R16), collapsible (#35) and collapsed by default on a phone (#42); the content
// region holds each view with its own search and paging (R15). The brand is the way Home (#36, #37),
// and each section opens on its own landing page (#44). The frame persists; only the content region
// changes. Every view is addressable by URL, and its search and page live in the URL (R11).
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { Link, NavLink, Navigate, Route, Routes, useLocation, useParams, useSearchParams } from "react-router-dom";
import { api, type EnumerationSummary, type Release } from "./api/client";
import { AdifLanding } from "./adif/AdifLanding";
import { AdifView, DEFINITIONS } from "./adif/AdifView";
import { Home } from "./Home";
import { readCollapsed, saveCollapsed } from "./lib/nav";
import { SECTIONS } from "./sections";

const storage = (): Storage | undefined => {
  try { return window.localStorage; } catch { return undefined; }
};

const Nav = createContext({ collapsed: false, toggle: () => {} });

export function App() {
  const [collapsed, setCollapsed] = useState(() => readCollapsed(storage(), window.innerWidth));
  const toggle = () => setCollapsed((c) => { saveCollapsed(storage(), !c); return !c; });

  return (
    <Nav.Provider value={{ collapsed, toggle }}>
      <div className={`shell${collapsed ? " nav-collapsed" : ""}`}>
        <header className="topbar">
          <Link to="/" className="brand" aria-label="IONIS-AI Atlas home">IONIS-AI <span>Atlas</span></Link>
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
          <Route path="/" element={<Home />} />
          <Route path="/adif" element={<AdifSection view="landing" />} />
          <Route path="/adif/enumerations" element={<Navigate to="/adif" replace />} />
          {/* Routes named as the spec names things (R16): the segment is ADIF's name in lower case. */}
          <Route path="/adif/fields" element={<AdifSection view="fields" />} />
          <Route path="/adif/datatypes" element={<AdifSection view="datatypes" />} />
          <Route path="/adif/enumerations/:table" element={<AdifSection />} />
          {/* Links from before R16 (/adif/<table>) keep working. */}
          <Route path="/adif/:legacy" element={<LegacyAdifLink />} />
          <Route path="*" element={<main className="content wide"><p className="state">No such page.</p></main>} />
        </Routes>
      </div>
    </Nav.Provider>
  );
}

function LegacyAdifLink() {
  const { legacy = "" } = useParams();
  const { search } = useLocation();
  return <Navigate to={`/adif/enumerations/${legacy}${search}`} replace />;
}

/** The left pane: a « / » control and, unless collapsed, the section's navigation. */
function Sidebar({ label, children }: { label: string; children: ReactNode }) {
  const { collapsed, toggle } = useContext(Nav);
  return (
    <aside className="sidebar" id="section-nav">
      <button type="button" className="navtoggle" onClick={toggle} aria-controls="section-nav" aria-expanded={!collapsed}
        aria-label={collapsed ? `Show ${label} navigation` : `Hide ${label} navigation`} title={collapsed ? "Show navigation" : "Hide navigation"}>
        <span aria-hidden="true">{collapsed ? "»" : "«"}</span>
        <span className="navtoggle-text">{collapsed ? `${label}: show navigation` : "Hide navigation"}</span>
      </button>
      {!collapsed && children}
    </aside>
  );
}

function AdifSection({ view: fixed }: { view?: string }) {
  const { table } = useParams();
  const view = fixed ?? table ?? "landing";
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
  const set = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next, { replace: true });
  };
  // Moving to another table keeps the chosen ADIF version and nothing else: a search, page or page
  // size belongs to the table it was set on.
  const search = params.get("v") ? `?v=${params.get("v")}` : "";
  const cls = ({ isActive }: { isActive: boolean }) => (isActive ? "active" : "");

  return (
    <>
      <Sidebar label="ADIF">
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
        <nav className="views" aria-label="ADIF section">
          <NavLink end to={{ pathname: "/adif", search }} className={cls}>Overview</NavLink>
        </nav>
        <nav className="views" aria-label="ADIF definitions">
          <span className="group">Definitions</span>
          {DEFINITIONS.map((v) => (
            <NavLink key={v.key} to={{ pathname: `/adif/${v.key}`, search }} className={cls}>{v.label}</NavLink>
          ))}
        </nav>
        <nav className="views" aria-label="ADIF enumerations">
          <span className="group">Enumerations ({enums.length})</span>
          {enums.map((e) => (
            <NavLink key={e.table} to={{ pathname: `/adif/enumerations/${e.table}`, search }} className={cls}>
              <span>{e.name.replace(/_/g, " ")}</span><span className="n">{e.records}</span>
            </NavLink>
          ))}
        </nav>
        <p className="note">ADIF {version ?? "…"} as published by adif.org, loaded unmodified.</p>
      </Sidebar>
      <main className="content">
        {!version ? <p className="state">Loading…</p>
          : view === "landing" ? <AdifLanding version={version} current={current} releases={releases ?? []} enums={enums} search={search} />
          : <AdifView view={view} version={version} />}
      </main>
    </>
  );
}
