import { useEffect, useMemo, useState } from "react";
import { api, fmtDate, localToUnix, unixToLocal, shortHash } from "../api.js";

const MODES = [
  ["all", "All commits"],
  ["since", "Since date"],
  ["range", "Date range"],
  ["list", "Manual selection"],
];

function CommitPicker({ repoId, hashes, onChange }) {
  const [q, setQ] = useState("");
  const [rows, setRows] = useState([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);

  useEffect(() => {
    setOffset(0);
  }, [q, repoId]);

  useEffect(() => {
    const params = new URLSearchParams({ limit: 50, offset: String(offset) });
    if (q) params.set("q", q);
    api(`/api/repos/${repoId}/commits?${params}`)
      .then((res) => {
        setTotal(res.total);
        setRows((prev) => (offset === 0 ? res.commits : [...prev, ...res.commits]));
      })
      .catch(() => {});
  }, [repoId, q, offset]);

  const toggle = (h) => {
    const set = new Set(hashes);
    if (set.has(h)) set.delete(h);
    else set.add(h);
    onChange([...set]);
  };

  return (
    <div className="fieldset" style={{ flexBasis: "100%" }}>
      <div className="legend">
        Selected {hashes.length} commit(s) · matching {total}
      </div>
      <input placeholder="search subject or hash…" value={q} onChange={(e) => setQ(e.target.value)} style={{ width: "100%" }} />
      <div className="picker">
        {rows.map((c) => (
          <label key={c.hash} className="row small">
            <input type="checkbox" checked={hashes.includes(c.hash)} onChange={() => toggle(c.hash)} />
            <span className="mono">{shortHash(c.hash)}</span>
            <span className="muted">{fmtDate(c.committer_date)}</span>
            <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis" }}>{c.subject}</span>
            <span className="muted">{c.author_name}</span>
          </label>
        ))}
        {rows.length < total && (
          <div style={{ padding: 6, textAlign: "center" }}>
            <button onClick={() => setOffset((o) => o + 50)}>Load more</button>
          </div>
        )}
      </div>
    </div>
  );
}

export default function FilterBar({
  repoId,
  meta,
  authors,
  commitSet,
  setCommitSet,
  selectedAuthors,
  setSelectedAuthors,
}) {
  const mode = commitSet.mode || "all";
  const [showAllAuthors, setShowAllAuthors] = useState(false);

  const groups = useMemo(() => {
    const byEff = new Map();
    for (const a of authors) {
      const key = a.effective_id;
      if (!byEff.has(key)) byEff.set(key, []);
      byEff.get(key).push(a);
    }
    return [...byEff.entries()]
      .map(([eff, members]) => {
        const root = members.find((m) => m.id === eff) || members[0];
        const commits = members.reduce((s, m) => s + (m.commit_count || 0), 0);
        return { eff, label: root.name, members, commits };
      })
      .sort((a, b) => b.commits - a.commits);
  }, [authors]);

  const visibleGroups = showAllAuthors ? groups : groups.slice(0, 24);
  const hidden = groups.length - visibleGroups.length;

  const toggleAuthor = (eff) => {
    const set = new Set(selectedAuthors);
    if (set.has(eff)) set.delete(eff);
    else set.add(eff);
    setSelectedAuthors([...set]);
  };

  const setMode = (m) => {
    if (m === "all") setCommitSet({ mode: "all" });
    else if (m === "since") setCommitSet({ mode: "since", since: commitSet.since ?? meta.first_commit });
    else if (m === "range")
      setCommitSet({
        mode: "range",
        start: commitSet.start ?? meta.first_commit,
        end: commitSet.end ?? (meta.last_commit + 1),
      });
    else setCommitSet({ mode: "list", hashes: commitSet.hashes || [] });
  };

  return (
    <div className="card">
      <h2>Commit set</h2>
      <div className="filter-grid">
        <label>
          Set
          <select value={mode} onChange={(e) => setMode(e.target.value)}>
            {MODES.map(([v, l]) => (
              <option key={v} value={v}>
                {l}
              </option>
            ))}
          </select>
        </label>
        {mode === "since" && (
          <label>
            On or after
            <input
              type="datetime-local"
              value={unixToLocal(commitSet.since)}
              onChange={(e) => setCommitSet({ ...commitSet, since: localToUnix(e.target.value) })}
            />
          </label>
        )}
        {mode === "range" && (
          <>
            <label>
              From (inclusive)
              <input
                type="datetime-local"
                value={unixToLocal(commitSet.start)}
                onChange={(e) => setCommitSet({ ...commitSet, start: localToUnix(e.target.value) })}
              />
            </label>
            <label>
              To (exclusive)
              <input
                type="datetime-local"
                value={unixToLocal(commitSet.end)}
                onChange={(e) => setCommitSet({ ...commitSet, end: localToUnix(e.target.value) })}
              />
            </label>
          </>
        )}
        {mode === "list" && (
          <CommitPicker repoId={repoId} hashes={commitSet.hashes || []} onChange={(h) => setCommitSet({ ...commitSet, hashes: h })} />
        )}
      </div>
      <div className="legend" style={{ marginTop: 10 }}>
        {mode === "all"
          ? `H̄ — all ${meta.commit_count} non-merge commits reachable from ${meta.ref}`
          : mode === "since"
            ? "H_t — commits with committer date ≥ t"
            : mode === "range"
              ? "H_i,j — commits with i ≤ committer date < j"
              : "Manual commit list"}
      </div>

      <h2 style={{ marginTop: 12 }}>Authors</h2>
      {groups.length === 0 && <div className="muted small">No authors.</div>}
      <div className="chips">
        {visibleGroups.map((g) => (
          <span
            key={g.eff}
            className={"chip" + (selectedAuthors.includes(g.eff) ? " on" : "")}
            title={g.members.map((m) => `${m.name} <${m.email}>`).join(", ")}
            onClick={() => toggleAuthor(g.eff)}
          >
            {g.label}
            {g.members.length > 1 ? ` (+${g.members.length - 1})` : ""}
          </span>
        ))}
        {hidden > 0 && (
          <span className="chip" onClick={() => setShowAllAuthors(true)}>
            +{hidden} more…
          </span>
        )}
        {showAllAuthors && groups.length > 24 && (
          <span className="chip" onClick={() => setShowAllAuthors(false)}>
            show fewer
          </span>
        )}
      </div>
      <div className="actions">
        <button
          onClick={() => {
            setCommitSet({ mode: "all" });
            setSelectedAuthors([]);
          }}
        >
          Clear filters
        </button>
        <span className="muted small">
          {selectedAuthors.length ? `${selectedAuthors.length} author(s) selected` : "all authors"}
        </span>
      </div>
    </div>
  );
}
