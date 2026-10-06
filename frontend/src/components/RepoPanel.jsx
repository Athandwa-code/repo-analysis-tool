import { useState } from "react";
import { api } from "../api.js";

export default function RepoPanel({ repos, repoId, onSelect, onRefresh, onError }) {
  const [kind, setKind] = useState("url");
  const [url, setUrl] = useState("");
  const [ref, setRef] = useState("");
  const [name, setName] = useState("");
  const [file, setFile] = useState(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    if (kind === "url" && !url.trim()) return;
    if (kind === "zip" && !file) return;
    setBusy(true);
    try {
      const fd = new FormData();
      fd.append("ref", ref || "HEAD");
      fd.append("name", name);
      if (kind === "url") fd.append("url", url.trim());
      else fd.append("file", file);
      const row = await api("/api/repos", { method: "POST", form: fd });
      setUrl("");
      setName("");
      setRef("");
      setFile(null);
      e.target.reset();
      await onRefresh();
      onSelect(row.id);
    } catch (err) {
      onError(String(err.message || err));
    } finally {
      setBusy(false);
    }
  };

  const remove = async (e, id, rname) => {
    e.stopPropagation();
    if (!window.confirm(`Delete repository “${rname}” and all its analysis data?`)) return;
    try {
      await api(`/api/repos/${id}`, { method: "DELETE" });
    } catch (err) {
      onError(String(err.message || err));
    }
    await onRefresh();
  };

  return (
    <div>
      <div className="card">
        <h2>Add repository</h2>
        <div className="chips" style={{ marginBottom: 8 }}>
          <span className={"chip" + (kind === "url" ? " on" : "")} onClick={() => setKind("url")}>
            Clone from URL
          </span>
          <span className={"chip" + (kind === "zip" ? " on" : "")} onClick={() => setKind("zip")}>
            Upload zip (.git inside)
          </span>
        </div>
        <form onSubmit={submit} style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {kind === "url" ? (
            <input
              placeholder="https://github.com/user/repo.git (or local path)"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
            />
          ) : (
            <input type="file" accept=".zip" onChange={(e) => setFile(e.target.files[0] || null)} />
          )}
          <div style={{ display: "flex", gap: 8 }}>
            <input placeholder="ref (default HEAD)" value={ref} onChange={(e) => setRef(e.target.value)} style={{ width: 130 }} />
            <input placeholder="name (optional)" value={name} onChange={(e) => setName(e.target.value)} style={{ flex: 1 }} />
          </div>
          <button className="primary" disabled={busy} type="submit">
            {busy ? "Adding…" : "Add & analyze"}
          </button>
        </form>
      </div>

      <div className="card">
        <h2>Repositories ({repos.length})</h2>
        {repos.length === 0 && <div className="muted small">None yet.</div>}
        {repos.map((r) => (
          <div
            key={r.id}
            className={"repo-item" + (r.id === repoId ? " active" : "")}
            onClick={() => onSelect(r.id)}
          >
            <div className="row">
              <strong>{r.name}</strong>
              <span className={"badge " + r.status}>{r.status}</span>
            </div>
            <div className="row small muted" style={{ marginTop: 2 }}>
              <span>
                {r.source_type === "zip" ? "zip" : "clone"} · {r.commit_total || 0} commits
              </span>
              <button className="danger small" onClick={(e) => remove(e, r.id, r.name)}>
                delete
              </button>
            </div>
            {["pending", "cloning", "importing"].includes(r.status) && (
              <div className="progress">
                <div style={{ width: `${r.progress || (r.status === "cloning" ? 5 : 0)}%` }} />
              </div>
            )}
            {r.status === "error" && <div className="small error">{r.error}</div>}
          </div>
        ))}
      </div>
    </div>
  );
}
