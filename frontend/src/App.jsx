import { useCallback, useEffect, useState } from "react";
import { api } from "./api.js";
import RepoPanel from "./components/RepoPanel.jsx";
import FilterBar from "./components/FilterBar.jsx";
import ObjectView from "./components/ObjectView.jsx";
import AuthorsPanel from "./components/AuthorsPanel.jsx";

const BUSY = ["pending", "cloning", "importing"];

export default function App() {
  const [repos, setRepos] = useState([]);
  const [repoId, setRepoId] = useState(null);
  const [meta, setMeta] = useState(null);
  const [view, setView] = useState({ path: "", is_dir: true });
  const [commitSet, setCommitSet] = useState({ mode: "all" });
  const [selectedAuthors, setSelectedAuthors] = useState([]);
  const [tree, setTree] = useState(null);
  const [authors, setAuthors] = useState([]);
  const [authorMetrics, setAuthorMetrics] = useState([]);
  const [series, setSeries] = useState([]);
  const [bucket, setBucket] = useState("month");
  const [rev, setRev] = useState(0);
  const [error, setError] = useState("");

  const busy = repos.some((r) => BUSY.includes(r.status));

  const refreshRepos = useCallback(async () => {
    try {
      setRepos(await api("/api/repos"));
    } catch (e) {
      setError(String(e.message || e));
    }
  }, []);

  useEffect(() => {
    refreshRepos();
  }, [refreshRepos]);

  useEffect(() => {
    if (!busy) return undefined;
    const t = setInterval(refreshRepos, 1200);
    return () => clearInterval(t);
  }, [busy, refreshRepos]);

  // auto-select the newest ready repo
  useEffect(() => {
    if (repoId == null) {
      const ready = repos.find((r) => r.status === "ready");
      if (ready) setRepoId(ready.id);
    } else if (meta && !repos.some((r) => r.id === repoId)) {
      setRepoId(null);
      setMeta(null);
    }
  }, [repos, repoId, meta]);

  const loadMeta = useCallback(async (id) => {
    try {
      setMeta(await api(`/api/repos/${id}`));
    } catch (e) {
      setError(String(e.message || e));
    }
  }, []);

  const loadAuthors = useCallback(async (id) => {
    try {
      setAuthors(await api(`/api/repos/${id}/authors`));
    } catch {
      /* non-fatal */
    }
  }, []);

  useEffect(() => {
    if (!repoId) return;
    setView({ path: "", is_dir: true });
    setCommitSet({ mode: "all" });
    setSelectedAuthors([]);
    setTree(null);
    loadMeta(repoId);
    loadAuthors(repoId);
  }, [repoId, loadMeta, loadAuthors]);

  // refresh meta while the selected repo is still ingesting
  useEffect(() => {
    if (!repoId || !meta || !BUSY.includes(meta.status)) return undefined;
    const t = setInterval(() => loadMeta(repoId), 1200);
    return () => clearInterval(t);
  }, [repoId, meta, loadMeta]);

  const ready = repoId && meta && meta.status === "ready";

  useEffect(() => {
    if (!ready) return;
    const body = {
      repo_id: repoId,
      path: view.path,
      is_dir: view.is_dir,
      commit_set: commitSet,
      author_ids: selectedAuthors.length ? selectedAuthors : null,
    };
    api("/api/tree", { method: "POST", body }).then(setTree).catch((e) => setError(String(e.message)));
    api("/api/metrics/authors", { method: "POST", body })
      .then(setAuthorMetrics)
      .catch(() => {});
  }, [ready, repoId, view, commitSet, selectedAuthors, rev]);

  useEffect(() => {
    if (!ready) return;
    api("/api/metrics/timeseries", {
      method: "POST",
      body: {
        repo_id: repoId,
        path: view.path,
        is_dir: view.is_dir,
        commit_set: commitSet,
        author_ids: selectedAuthors.length ? selectedAuthors : null,
        bucket,
      },
    })
      .then(setSeries)
      .catch(() => {});
  }, [ready, repoId, view, commitSet, selectedAuthors, bucket, rev]);

  const onAuthorsChanged = useCallback(() => {
    setRev((r) => r + 1);
    if (repoId) loadAuthors(repoId);
  }, [repoId, loadAuthors]);

  return (
    <div className="app">
      <header className="topbar">
        <h1>Repo Analysis Tool</h1>
        {meta && (
          <span className="muted small">
            {meta.name}
            {meta.status === "ready" && (
              <>
                {" "}· {meta.commit_count} commits · {meta.author_count} authors ·{" "}
                {meta.first_commit ? new Date(meta.first_commit * 1000).toISOString().slice(0, 10) : "?"} →{" "}
                {meta.last_commit ? new Date(meta.last_commit * 1000).toISOString().slice(0, 10) : "?"}
              </>
            )}
          </span>
        )}
        <span style={{ flex: 1 }} />
        {error && (
          <span className="error small" onClick={() => setError("")} title="click to dismiss">
            {error} ✕
          </span>
        )}
      </header>
      <div className="layout">
        <aside className="sidebar">
          <RepoPanel
            repos={repos}
            repoId={repoId}
            onSelect={setRepoId}
            onRefresh={refreshRepos}
            onError={setError}
          />
        </aside>
        <main className="main">
          {!repoId && <div className="empty">Add a repository (a zip that contains .git, or a clone URL) to begin.</div>}
          {repoId && meta && !ready && (
            <div className="empty">
              Repository “{meta.name}” is {meta.status}
              {meta.error ? ` — ${meta.error}` : "…"}
            </div>
          )}
          {ready && (
            <>
              <FilterBar
                repoId={repoId}
                meta={meta}
                authors={authors}
                commitSet={commitSet}
                setCommitSet={setCommitSet}
                selectedAuthors={selectedAuthors}
                setSelectedAuthors={setSelectedAuthors}
              />
              <ObjectView
                tree={tree}
                view={view}
                setView={setView}
                series={series}
                bucket={bucket}
                setBucket={setBucket}
              />
              <AuthorsPanel
                authors={authors}
                authorMetrics={authorMetrics}
                repoId={repoId}
                selectedAuthors={selectedAuthors}
                setSelectedAuthors={setSelectedAuthors}
                onChanged={onAuthorsChanged}
                onError={setError}
              />
            </>
          )}
        </main>
      </div>
    </div>
  );
}
