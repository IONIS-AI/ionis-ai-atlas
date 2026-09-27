// The shell (SPEC "The shell"): sections across the top; on the left, navigation only, named as the
// spec names things (R16), collapsible (#35) and collapsed by default on a phone (#42); the content
// region holds each view with its own search and paging (R15). The brand is the way Home (#36, #37),
// and each section opens on its own landing page (#44). The frame persists; only the content region
// changes. Every view is addressable by URL, and its search and page live in the URL (R11).
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { Link, NavLink, Navigate, Route, Routes, useLocation, useParams, useSearchParams } from "react-router-dom";
import { api, ok, type EnumerationSummary, type Release } from "./api/client";
import { AdifLanding } from "./adif/AdifLanding";
import { AdifView, DEFINITIONS } from "./adif/AdifView";
import { Home } from "./Home";
import { PHONE_MAX, readSaved, saveCollapsed } from "./lib/nav";
import { SECTIONS } from "./sections";

const storage = (): Storage | undefined => {
  try { return window.localStorage; } catch { return undefined; }
};

const Nav = createContext({ collapsed: false, toggle: () => {} });

// Follows the same breakpoint as the @media rule in styles.css, live, so a resized window changes both.
const PHONE = `(max-width: ${PHONE_MAX}px)`;
function usePhone(): boolean {
  const [phone, setPhone] = useState(() => window.matchMedia(PHONE).matches);
  useEffect(() => {
    const m = window.matchMedia(PHONE);
    const on = () => setPhone(m.matches);
    m.addEventListener("change", on);
    return () => m.removeEventListener("change", on);
  }, []);
  return phone;
}

export function App() {
  // The reader's choice, once made, holds at every width; until then the pane follows the layout:
  // collapsed on a phone, open on a desktop, changing as the window does (#51).
  const phone = usePhone();
  const [saved, setSaved] = useState(() => readSaved(storage()));
  const collapsed = saved ?? phone;
  const toggle = () => { saveCollapsed(storage(), !collapsed); setSaved(!collapsed); };

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

/** The left pane: a « / » control and the region it shows or hides, which holds everything else in
 *  the pane (the version selector as well as the navigation, so the control's name says both). */
function Sidebar({ label, children }: { label: string; children: ReactNode }) {
  const { collapsed, toggle } = useContext(Nav);
  const what = `${label} version and navigation`;
  return (
    <aside className="sidebar">
      <button type="button" className="navtoggle" onClick={toggle} aria-controls="section-nav" aria-expanded={!collapsed}
        aria-label={collapsed ? `Show ${what}` : `Hide ${what}`} title={collapsed ? `Show ${what}` : `Hide ${what}`}>
        <span aria-hidden="true">{collapsed ? "»" : "«"}</span>
        <span className="navtoggle-text">{collapsed ? `${label}: show version and navigation` : "Hide"}</span>
      </button>
      <div className="navbody" id="section-nav" hidden={collapsed}>{children}</div>
    </aside>
  );
}

function AdifSection({ view: fixed }: { view?: string }) {
  const { table } = useParams();
  const view = fixed ?? table ?? "landing";
  const [params, setParams] = useSearchParams();
  const [releases, setReleases] = useState<Release[] | null>(null);
  const [current, setCurrent] = useState<string | null>(null);
  const [enums, setEnums] = useState<EnumerationSummary[] | null>(null);
  const [failed, setFailed] = useState(false);  // the section could not load what it is built on

  useEffect(() => {
    let live = true;
    Promise.all([ok(api.GET("/api/v1/adif/releases")), ok(api.GET("/api/v1/adif/current"))])
      .then(([r, c]) => { if (live) { setReleases(r.data); setCurrent(c.data.adif_version); } })
      .catch(() => live && setFailed(true));
    return () => { live = false; };
  }, []);

  const version = params.get("v") ?? current;
  useEffect(() => {
    if (!version) return;
    let live = true;
    setEnums(null);
    ok(api.GET("/api/v1/adif/enumerations", { params: { query: { adif_version: version } } }))
      .then(({ data }) => live && setEnums(data))
      .catch(() => live && setFailed(true));
    return () => { live = false; };
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
          <span className="group">Enumerations ({enums ? enums.length : failed ? "unavailable" : "…"})</span>
          {(enums ?? []).map((e) => (
            <NavLink key={e.table} to={{ pathname: `/adif/enumerations/${e.table}`, search }} className={cls}>
              <span>{e.name.replace(/_/g, " ")}</span><span className="n">{e.records}</span>
            </NavLink>
          ))}
        </nav>
        <p className="note">ADIF {version ?? "…"} as published by adif.org, loaded unmodified.</p>
      </Sidebar>
      <main className="content">
        {failed ? <p className="state error">Unavailable: the API did not answer, so the ADIF section cannot be shown.</p>
          : !version ? <p className="state">Loading…</p>
          : view === "landing" ? (enums ? <AdifLanding version={version} current={current} releases={releases ?? []} enums={enums} search={search} />
                                        : <p className="state">Loading ADIF {version}…</p>)
          : <AdifView view={view} version={version} />}
      </main>
    </>
  );
}
