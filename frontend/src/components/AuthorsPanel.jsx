import { useMemo, useState } from "react";
import { api, fmtInt, fmtRate } from "../api.js";

export default function AuthorsPanel({
  authors,
  authorMetrics,
  repoId,
  selectedAuthors,
  setSelectedAuthors,
  onChanged,
  onError,
}) {
  const [picked, setPicked] = useState([]);
  const [target, setTarget] = useState("");

  const effName = useMemo(() => {
    const m = new Map();
    for (const a of authors) if (a.id === a.effective_id) m.set(a.id, `${a.name} <${a.email}>`);
    return m;
  }, [authors]);

  const togglePick = (id) => {
    setPicked((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id]));
  };

  const doMerge = async () => {
    if (!picked.length || !target) return;
    const into = Number(target);
    const from = picked.filter((id) => id !== into);
    if (!from.length) return;
    try {
      await api(`/api/repos/${repoId}/authors/merge`, {
        method: "POST",
        body: { from_ids: from, into_id: into },
      });
      setPicked([]);
      setTarget("");
      onChanged();
    } catch (e) {
      onError(String(e.message || e));
    }
  };

  const doUnmerge = async (id) => {
    try {
      await api(`/api/repos/${repoId}/authors/unmerge`, {
        method: "POST",
        body: { author_ids: [id] },
      });
      onChanged();
    } catch (e) {
      onError(String(e.message || e));
    }
  };

  const toggleFilter = (effId) => {
    const set = new Set(selectedAuthors);
    if (set.has(effId)) set.delete(effId);
    else set.add(effId);
    setSelectedAuthors([...set]);
  };

  return (
    <div className="card">
      <h2>Authors — metrics & merging</h2>
      <div className="two-col">
        <div>
          <h3>
            Effective authors <span className="muted small">(click a row to filter this view)</span>
          </h3>
          <table>
            <thead>
              <tr>
                <th>Author</th>
                <th className="num">Mods n</th>
                <th className="num">Churn λ</th>
                <th className="num">Ownership ω</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {authorMetrics.map((a) => (
                <tr
                  key={a.author_id}
                  className={"clickable" + (selectedAuthors.includes(a.author_id) ? " selected" : "")}
                  onClick={() => toggleFilter(a.author_id)}
                >
                  <td>
                    {a.name} <span className="muted small">{a.email}</span>
                  </td>
                  <td className="num">{fmtInt(a.modifications)}</td>
                  <td className="num">{fmtInt(a.churn)}</td>
                  <td className="num">
                    <div style={{ display: "flex", gap: 6, alignItems: "center", justifyContent: "flex-end" }}>
                      <span>{fmtRate(a.ownership * 100)}%</span>
                      <div className="bar" style={{ width: 70 }}>
                        <div style={{ width: `${Math.min(100, a.ownership * 100)}%` }} />
                      </div>
                    </div>
                  </td>
                  <td />
                </tr>
              ))}
              {authorMetrics.length === 0 && (
                <tr>
                  <td colSpan={5} className="muted small">
                    No authors in this commit set.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        <div>
          <h3>
            Identity merging <span className="muted small">(.mailmap is applied automatically; merge the rest here)</span>
          </h3>
          <table>
            <thead>
              <tr>
                <th></th>
                <th>Raw identity</th>
                <th className="num">Commits</th>
                <th>Resolves to</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {authors.map((a) => (
                <tr key={a.id} className="clickable" onClick={() => togglePick(a.id)}>
                  <td>
                    <input type="checkbox" checked={picked.includes(a.id)} readOnly />
                  </td>
                  <td>
                    {a.name} <span className="muted small">{a.email}</span>
                  </td>
                  <td className="num">{fmtInt(a.commit_count)}</td>
                  <td className="small">{a.canonical_id ? effName.get(a.effective_id) || "merged" : "—"}</td>
                  <td>
                    {a.canonical_id != null && (
                      <button
                        className="danger"
                        onClick={(e) => {
                          e.stopPropagation();
                          doUnmerge(a.id);
                        }}
                      >
                        unmerge
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="actions">
            <span className="muted small">{picked.length} selected →</span>
            <select value={target} onChange={(e) => setTarget(e.target.value)}>
              <option value="">merge into…</option>
              {authors.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name} &lt;{a.email}&gt;
                </option>
              ))}
            </select>
            <button className="primary" disabled={!picked.length || !target} onClick={doMerge}>
              Merge
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
