// The ADIF section's landing page (#44): shown at /adif, before anything in the left pane is chosen.
// What ADIF is, which versions are here, and everything the section holds with its count, its API
// route and a link. It shows ADIF as published and adds nothing to it.
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, ok, totalCount, type EnumerationSummary, type Release } from "../api/client";

const n = (x: number) => x.toLocaleString("en-US");
const API = "/api/v1/adif";

type Props = { version: string; current: string | null; releases: Release[]; enums: EnumerationSummary[]; search: string };

export function AdifLanding({ version, current, releases, enums, search }: Props) {
  const [defs, setDefs] = useState<{ fields: number; datatypes: number } | "error" | null>(null);

  useEffect(() => {
    let live = true;
    setDefs(null);  // another version's counts are never shown under this one's heading
    const q = { params: { query: { adif_version: version, limit: 1 } } };
    Promise.all([ok(api.GET("/api/v1/adif/fields", q)), ok(api.GET("/api/v1/adif/datatypes", q))]).then(([f, d]) => {
      if (live) setDefs({ fields: totalCount(f.response), datatypes: totalCount(d.response) });
    }).catch(() => live && setDefs("error"));
    return () => { live = false; };
  }, [version]);

  const values = enums.reduce((t, e) => t + e.records, 0);
  const row = (to: string, label: string, adif: string, file: string, route: string, count?: number | "error") => (
    <tr key={to}>
      <td><Link to={to + search}><strong>{label}</strong></Link></td>
      <td><code>{adif}</code></td>
      <td className="num">{count === undefined ? "…" : count === "error" ? "unavailable" : n(count)}</td>
      <td><code>{file}</code></td>
      <td><a href={`${route}?adif_version=${version}&limit=100`}><code>{route}</code></a></td>
    </tr>
  );

  return (
    <section>
      <h1>ADIF Reference</h1>
      <p className="lead">
        ADIF, the Amateur Data Interchange Format, defines how amateur radio contacts are recorded and
        exchanged. Its data types, fields and enumerations are published by adif.org; Atlas loads them
        exactly as published, one version beside another, and every IONIS-AI field is defined against them.
      </p>
      <p className="count">
        Showing ADIF <strong>{version}</strong>{version === current ? " (current)" : ""}.
        Loaded: {releases.map((r) => r.adif_version + (r.adif_version === current ? " (current)" : "")).join(", ")}.
        {" "}{n(enums.length)} enumerations holding {n(values)} values.
      </p>
      <div className="tablewrap">
        <table>
          <thead><tr><th>In this section</th><th>ADIF name</th><th className="num">Records</th><th>File</th><th>API</th></tr></thead>
          <tbody>
            {row("/adif/datatypes", "Data Types", "DataTypes", "datatypes.json", `${API}/datatypes`, defs === "error" ? defs : defs?.datatypes)}
            {row("/adif/fields", "Fields", "Fields", "fields.json", `${API}/fields`, defs === "error" ? defs : defs?.fields)}
            {enums.map((e) => row(`/adif/enumerations/${e.table}`, e.name.replace(/_/g, " "), e.name, e.file,
                                  `${API}/enumerations/${e.table}`, e.records))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
