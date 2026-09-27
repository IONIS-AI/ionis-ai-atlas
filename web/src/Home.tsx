// Home (SPEC R1; #37): what Atlas is, which release is running, what's loaded, where to go next.
// Every number here comes from the API, never from this file: which release (/api/v1/version), which
// ADIF versions and which is current, and the counts for the current one.
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type EnumerationSummary, type Release } from "./api/client";
import { SECTIONS } from "./sections";

const n = (x: number) => x.toLocaleString("en-US");
const counted = (r: Response) => Number(r.headers.get("X-Total-Count") ?? 0);

type Loaded = {
  release: { version: string; revision: string } | null;
  releases: Release[];
  current: string | null;
  enums: EnumerationSummary[];
  fields: number;
  datatypes: number;
};

export function Home() {
  const [s, setS] = useState<Loaded | "error" | null>(null);

  useEffect(() => {
    let live = true;
    (async () => {
      const [version, releases, current] = await Promise.all([
        api.GET("/api/v1/version"), api.GET("/api/v1/adif/releases"), api.GET("/api/v1/adif/current"),
      ]);
      const v = current.data?.adif_version ?? null;
      const q = { params: { query: { adif_version: v ?? undefined, limit: 1 } } };
      const [enums, fields, datatypes] = await Promise.all([
        api.GET("/api/v1/adif/enumerations", { params: { query: { adif_version: v ?? undefined } } }),
        api.GET("/api/v1/adif/fields", q), api.GET("/api/v1/adif/datatypes", q),
      ]);
      if (live) setS({
        release: version.data ?? null, releases: releases.data ?? [], current: v, enums: enums.data ?? [],
        fields: counted(fields.response), datatypes: counted(datatypes.response),
      });
    })().catch(() => live && setS("error"));
    return () => { live = false; };
  }, []);

  const records = s && s !== "error" ? s.enums.reduce((t, e) => t + e.records, 0) : 0;
  const rel = s && s !== "error" ? s.release : null;

  return (
    <main className="content wide">
      <section className="home">
        <h1>IONIS-AI Atlas</h1>
        <p className="lead">
          Atlas is how you explore the IONIS-AI propagation collection: which HF paths were open, on
          which band, when, and how well, drawn from billions of spots. It reads a database you run
          yourself and never writes to it. The collection arrives here section by section; the first is
          ADIF, the Amateur Data Interchange Format that every field and value is defined against.
        </p>

        {s === "error" && <p className="state error">The API did not answer.</p>}
        {s === null && <p className="state">Loading…</p>}

        {s && s !== "error" && (
          <div className="cards">
            <div className="card">
              <h2>Running</h2>
              <p className="big">{rel?.version === "dev" ? "a development build" : `release ${rel?.version ?? "?"}`}</p>
              <p className="muted">
                {rel && rel.revision !== "unknown"
                  ? <>built from <code title={rel.revision}>{rel.revision.slice(0, 7)}</code></>
                  : "not built by the release process"}
              </p>
            </div>
            <div className="card">
              <h2>ADIF loaded</h2>
              <p className="big">{s.releases.map((r) => r.adif_version).join(" · ") || "none"}</p>
              <p className="muted">current: <strong>{s.current ?? "none set"}</strong>, as published by adif.org, unmodified</p>
            </div>
            <div className="card">
              <h2>In ADIF {s.current}</h2>
              <p className="big">{n(s.enums.length)} enumerations · {n(records)} values</p>
              <p className="muted">{n(s.fields)} fields · {n(s.datatypes)} data types</p>
            </div>
          </div>
        )}

        <h2>Sections</h2>
        <ul className="links">
          {SECTIONS.map((sec) => (
            <li key={sec.path}><Link to={sec.path}>{sec.label}</Link>: {sec.about}</li>
          ))}
        </ul>

        <h2>For developers</h2>
        <ul className="links">
          <li><a href="/api/docs">API documentation</a>: every endpoint, tried in the browser. Read-only.</li>
          <li><a href="/api/v1/openapi.json">OpenAPI description</a>: the <code>/api/v1</code> contract; changes are additive only.</li>
          <li>
            <a href="https://github.com/IONIS-AI/ionis-ai-atlas/blob/main/SIGNING.md" rel="noopener noreferrer">Verifying the images</a>:
            every release is signed; <code>cosign verify</code> with the published public key proves an image is ours.
          </li>
        </ul>
      </section>
    </main>
  );
}
