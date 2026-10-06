import { useMemo, useState } from "react";
import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { fmtDate, fmtInt, fmtRate } from "../api.js";

const SORTS = [
  ["churn", "Churn λ"],
  ["growth", "Growth δ"],
  ["added", "Lines added"],
  ["removed", "Lines removed"],
  ["modifications", "Modifications n"],
  ["name", "Name"],
];

function Metric({ k, v, s, cls }) {
  return (
    <div className="metric">
      <div className="k">{k}</div>
      <div className={"v " + (cls || "")}>{v}</div>
      {s && <div className="s">{s}</div>}
    </div>
  );
}

function bucketLabel(b) {
  return typeof b === "number" ? fmtDate(b) : String(b);
}

export default function ObjectView({ tree, view, setView, series, bucket, setBucket }) {
  const [sortKey, setSortKey] = useState("churn");

  const children = useMemo(() => {
    if (!tree || !tree.children) return [];
    const arr = [...tree.children];
    if (sortKey === "name") arr.sort((a, b) => a.name.localeCompare(b.name));
    else arr.sort((a, b) => (b[sortKey] ?? 0) - (a[sortKey] ?? 0));
    return arr;
  }, [tree, sortKey]);

  if (!tree) return <div className="card">Loading metrics…</div>;
  const o = tree.object;
  const crumbs = view.path ? view.path.split("/") : [];

  return (
    <div>
      <div className="crumbs">
        <a onClick={() => setView({ path: "", is_dir: true })}>repository root</a>
        {crumbs.map((seg, i) => {
          const path = crumbs.slice(0, i + 1).join("/");
          const last = i === crumbs.length - 1;
          return (
            <span key={path} style={{ display: "flex", gap: 4 }}>
              <span className="sep">/</span>
              {last ? (
                <span className="cur">
                  {seg} {view.is_dir ? "/" : "(file)"}
                </span>
              ) : (
                <a onClick={() => setView({ path, is_dir: true })}>{seg}</a>
              )}
            </span>
          );
        })}
      </div>

      <div className="cards">
        <Metric k="Lines added" v={fmtInt(o.added)} cls="green" />
        <Metric k="Lines removed" v={fmtInt(o.removed)} cls="red" />
        <Metric k="Growth δ" v={fmtInt(o.growth)} s="added − removed" />
        <Metric k="Churn λ" v={fmtInt(o.churn)} s="added + removed" />
        <Metric k="Modifications n" v={fmtInt(o.modifications)} s="commits touching object" />
        <Metric k="|H| commits" v={fmtInt(o.commit_count)} s="in selected commit set" />
        <Metric k="Frequency η" v={fmtRate(o.modification_frequency)} s="n / |H|" />
        <Metric k="Churn rate ρ" v={fmtRate(o.churn_rate)} s="λ / |H|" />
      </div>

      <div className="card">
        <div className="actions" style={{ marginBottom: 6 }}>
          <h2 style={{ margin: 0 }}>Churn over time</h2>
          <span style={{ flex: 1 }} />
          <select value={bucket} onChange={(e) => setBucket(e.target.value)}>
            <option value="day">per day</option>
            <option value="week">per week</option>
            <option value="month">per month</option>
          </select>
        </div>
        {series.length === 0 ? (
          <div className="muted small">No changes in this commit set.</div>
        ) : (
          <ResponsiveContainer width="100%" height={240}>
            <ComposedChart data={series} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
              <CartesianGrid stroke="#334155" strokeDasharray="3 3" />
              <XAxis dataKey="bucket" tickFormatter={bucketLabel} stroke="#94a3b8" tick={{ fontSize: 11 }} />
              <YAxis stroke="#94a3b8" tick={{ fontSize: 11 }} />
              <Tooltip
                labelFormatter={bucketLabel}
                contentStyle={{ background: "#1e293b", border: "1px solid #334155", borderRadius: 8 }}
              />
              <Legend />
              <Bar dataKey="added" name="added" stackId="l" fill="#4ade80" />
              <Bar dataKey="removed" name="removed" stackId="l" fill="#f87171" />
              <Line dataKey="churn" name="churn λ" stroke="#38bdf8" dot={false} strokeWidth={2} />
            </ComposedChart>
          </ResponsiveContainer>
        )}
      </div>

      {view.is_dir && (
        <div className="card">
          <div className="actions" style={{ marginBottom: 6 }}>
            <h2 style={{ margin: 0 }}>Contents — {view.path || "root"}</h2>
            <span style={{ flex: 1 }} />
            <label className="small muted">
              sort by{" "}
              <select value={sortKey} onChange={(e) => setSortKey(e.target.value)}>
                {SORTS.map(([v, l]) => (
                  <option key={v} value={v}>
                    {l}
                  </option>
                ))}
              </select>
            </label>
          </div>
          {children.length === 0 ? (
            <div className="muted small">Empty in this commit set.</div>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>Name</th>
                  <th className="num">Added</th>
                  <th className="num">Removed</th>
                  <th className="num">Growth δ</th>
                  <th className="num">Churn λ</th>
                  <th className="num">Mods n</th>
                  <th className="num">η</th>
                  <th className="num">ρ</th>
                </tr>
              </thead>
              <tbody>
                {children.map((c) => (
                  <tr
                    key={c.path}
                    className="clickable"
                    onClick={() => setView({ path: c.path, is_dir: c.is_dir })}
                  >
                    <td>
                      <span className="muted small">{c.is_dir ? "dir " : "file "}</span>
                      {c.name}
                    </td>
                    <td className="num" style={{ color: "#4ade80" }}>
                      {fmtInt(c.added)}
                    </td>
                    <td className="num" style={{ color: "#f87171" }}>
                      {fmtInt(c.removed)}
                    </td>
                    <td className="num">{fmtInt(c.growth)}</td>
                    <td className="num">{fmtInt(c.churn)}</td>
                    <td className="num">{fmtInt(c.modifications)}</td>
                    <td className="num">{fmtRate(c.modification_frequency)}</td>
                    <td className="num">{fmtRate(c.churn_rate)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  );
}
