"""FastAPI application for the Repo Analysis Tool.

Run from the `backend/` directory:  uvicorn app.api:app --port 8000
"""
from __future__ import annotations

import shutil
import threading
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import analyzer, db, ingest, metrics

ROOT = db.REPO_ROOT
DATA_DIR = ROOT / "data"
REPOS_DIR = DATA_DIR / "repos"
TMP_DIR = DATA_DIR / "tmp"

app = FastAPI(title="Repo Analysis Tool", version="1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------- schemas
class CommitSetSpec(BaseModel):
    mode: str = "all"  # all | since | range | list
    since: int | None = None
    start: int | None = None
    end: int | None = None
    hashes: list[str] | None = None


class ViewSpec(BaseModel):
    repo_id: int
    path: str = ""
    is_dir: bool = True
    commit_set: CommitSetSpec | None = None
    author_ids: list[int] | None = None


class MergeSpec(BaseModel):
    from_ids: list[int]
    into_id: int


class UnmergeSpec(BaseModel):
    author_ids: list[int]


class ReimportSpec(BaseModel):
    ref: str = "HEAD"


class TimeseriesSpec(ViewSpec):
    bucket: str = "week"  # day | week | month


# ---------------------------------------------------------------- helpers
def _repo_row(conn, repo_id: int):
    row = conn.execute(
        "SELECT * FROM repositories WHERE id=?", (repo_id,)
    ).fetchone()
    if not row:
        raise HTTPException(404, f"repository {repo_id} not found")
    return row


def _spec_dict(spec: CommitSetSpec | None):
    return spec.model_dump(exclude_none=True) if spec else {"mode": "all"}


def _run_import(repo_id: int, repo_path: Path, ref: str, zip_path: Path | None = None):
    """Background worker: extract (optional) / clone then analyze."""
    conn = db.connect()
    try:
        if zip_path is not None:
            repo_path = ingest.extract_zip(zip_path, repo_path)
            conn.execute(
                "UPDATE repositories SET path=? WHERE id=?", (str(repo_path), repo_id)
            )
            conn.commit()
            try:
                zip_path.unlink()
            except OSError:
                pass
        conn.execute(
            "UPDATE repositories SET status='importing', progress=0, error=NULL WHERE id=?",
            (repo_id,),
        )
        conn.commit()

        def progress(done: int, total: int):
            pct = int(done * 100 / total) if total else 0
            conn.execute(
                "UPDATE repositories SET progress=?, commit_total=? WHERE id=?",
                (pct, total, repo_id),
            )
            conn.commit()

        stats = analyzer.import_repo(conn, repo_id, str(repo_path), ref, progress)
        conn.execute(
            "UPDATE repositories SET status='ready', progress=100, commit_total=? WHERE id=?",
            (stats["commits"], repo_id),
        )
        conn.commit()
    except Exception as exc:  # noqa: BLE001 - surface any failure to the UI
        conn.execute(
            "UPDATE repositories SET status='error', error=? WHERE id=?",
            (str(exc)[:2000], repo_id),
        )
        conn.commit()
    finally:
        conn.close()


def _clone_then_import(repo_id: int, url: str, dest: Path, ref: str):
    """Background worker: clone then analyze."""
    try:
        ingest.clone(url, dest)
    except Exception as exc:  # noqa: BLE001
        conn = db.connect()
        conn.execute(
            "UPDATE repositories SET status='error', error=? WHERE id=?",
            (str(exc)[:2000], repo_id),
        )
        conn.commit()
        conn.close()
        return
    _run_import(repo_id, dest, ref)


# ---------------------------------------------------------------- repos
@app.post("/api/repos")
def create_repo(
    url: str = Form(""),
    ref: str = Form("HEAD"),
    name: str = Form(""),
    file: UploadFile | None = File(None),
):
    """Register a repository from a zip (must contain .git) or a clone URL."""
    if file is None and not url.strip():
        raise HTTPException(400, "provide either a zip file or a repository URL")

    conn = db.connect()
    try:
        if file is not None:
            src_name = name.strip() or Path(file.filename or "upload.zip").stem
            cur = conn.execute(
                "INSERT INTO repositories (name, source_type, source, path, ref, status)"
                " VALUES (?, 'zip', ?, '', ?, 'pending')",
                (src_name, file.filename or "upload.zip", ref or "HEAD"),
            )
            repo_id = cur.lastrowid
            TMP_DIR.mkdir(parents=True, exist_ok=True)
            zip_path = TMP_DIR / f"{uuid.uuid4().hex}.zip"
            with zip_path.open("wb") as fh:
                shutil.copyfileobj(file.file, fh)
            dest = REPOS_DIR / str(repo_id)
            conn.commit()
            threading.Thread(
                target=_run_import,
                args=(repo_id, dest, ref or "HEAD", zip_path),
                daemon=True,
            ).start()
        else:
            url = url.strip()
            src_name = name.strip() or url.rstrip("/").rsplit("/", 1)[-1].removesuffix(".git")
            cur = conn.execute(
                "INSERT INTO repositories (name, source_type, source, path, ref, status)"
                " VALUES (?, 'clone', ?, '', ?, 'pending')",
                (src_name, url, ref or "HEAD"),
            )
            repo_id = cur.lastrowid
            dest = REPOS_DIR / str(repo_id)
            REPOS_DIR.mkdir(parents=True, exist_ok=True)
            conn.execute(
                "UPDATE repositories SET path=? WHERE id=?", (str(dest), repo_id)
            )
            conn.commit()
            threading.Thread(
                target=_clone_then_import,
                args=(repo_id, url, dest, ref or "HEAD"),
                daemon=True,
            ).start()

        row = _repo_row(conn, repo_id)
        return dict(row)
    finally:
        conn.close()


@app.get("/api/repos")
def list_repos():
    conn = db.connect()
    try:
        rows = conn.execute(
            "SELECT * FROM repositories ORDER BY id DESC"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@app.get("/api/repos/{repo_id}")
def get_repo(repo_id: int):
    conn = db.connect()
    try:
        row = dict(_repo_row(conn, repo_id))
        info = conn.execute(
            "SELECT COUNT(*) AS n, MIN(committer_date) AS min_d, MAX(committer_date) AS max_d"
            " FROM commits WHERE repo_id=?",
            (repo_id,),
        ).fetchone()
        row["commit_count"] = info["n"]
        row["first_commit"] = info["min_d"]
        row["last_commit"] = info["max_d"]
        row["author_count"] = conn.execute(
            "SELECT COUNT(*) FROM authors WHERE repo_id=?", (repo_id,)
        ).fetchone()[0]
        return row
    finally:
        conn.close()


@app.delete("/api/repos/{repo_id}")
def delete_repo(repo_id: int):
    conn = db.connect()
    try:
        row = _repo_row(conn, repo_id)
        conn.execute("UPDATE authors SET canonical_id=NULL WHERE repo_id=?", (repo_id,))
        conn.execute("DELETE FROM changes WHERE repo_id=?", (repo_id,))
        conn.execute("DELETE FROM commits WHERE repo_id=?", (repo_id,))
        conn.execute("DELETE FROM authors WHERE repo_id=?", (repo_id,))
        conn.execute("DELETE FROM repositories WHERE id=?", (repo_id,))
        conn.commit()
        path = Path(row["path"]) if row["path"] else None
        if path and path.exists() and REPOS_DIR in path.parents:
            shutil.rmtree(path, ignore_errors=True)
        return {"deleted": repo_id}
    finally:
        conn.close()


@app.post("/api/repos/{repo_id}/reimport")
def reimport_repo(repo_id: int, spec: ReimportSpec):
    """Re-run the analysis at another ref (branch, tag or commit hash).

    The clone keeps full history, so metrics can be recomputed for any ref;
    commit set H-bar then means "commits reachable from that ref".
    """
    conn = db.connect()
    try:
        row = _repo_row(conn, repo_id)
        path = row["path"]
        if not path or not Path(path).exists():
            raise HTTPException(400, "repository files missing; re-add the repository")
        ref = (spec.ref or "HEAD").strip()
        conn.execute(
            "UPDATE repositories SET ref=?, status='importing', progress=0, error=NULL WHERE id=?",
            (ref, repo_id),
        )
        conn.commit()
        threading.Thread(
            target=_run_import, args=(repo_id, Path(path), ref), daemon=True
        ).start()
        return dict(_repo_row(conn, repo_id))
    finally:
        conn.close()


# ---------------------------------------------------------------- authors
@app.get("/api/repos/{repo_id}/authors")
def get_authors(repo_id: int):
    conn = db.connect()
    try:
        _repo_row(conn, repo_id)
        eff = metrics._resolve_authors(conn, repo_id)
        counts = {
            r["author_id"]: r["n"]
            for r in conn.execute(
                "SELECT author_id, COUNT(*) AS n FROM commits WHERE repo_id=? GROUP BY author_id",
                (repo_id,),
            ).fetchall()
        }
        out = []
        for r in conn.execute(
            "SELECT id, name, email, canonical_id FROM authors WHERE repo_id=? ORDER BY name, email",
            (repo_id,),
        ).fetchall():
            out.append(
                {
                    "id": r["id"],
                    "name": r["name"],
                    "email": r["email"],
                    "canonical_id": r["canonical_id"],
                    "effective_id": eff.get(r["id"], r["id"]),
                    "commit_count": counts.get(r["id"], 0),
                }
            )
        return out
    finally:
        conn.close()


@app.post("/api/repos/{repo_id}/authors/merge")
def merge_authors(repo_id: int, spec: MergeSpec):
    conn = db.connect()
    try:
        _repo_row(conn, repo_id)
        try:
            metrics.merge_authors(conn, repo_id, spec.from_ids, spec.into_id)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return {"ok": True}
    finally:
        conn.close()


@app.post("/api/repos/{repo_id}/authors/unmerge")
def unmerge_authors(repo_id: int, spec: UnmergeSpec):
    conn = db.connect()
    try:
        _repo_row(conn, repo_id)
        for aid in spec.author_ids:
            conn.execute(
                "UPDATE authors SET canonical_id=NULL WHERE id=? AND repo_id=?",
                (int(aid), repo_id),
            )
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


# ---------------------------------------------------------------- metrics
@app.post("/api/tree")
def tree(spec: ViewSpec):
    """Directory listing of the current view with per-child metrics."""
    conn = db.connect()
    try:
        _repo_row(conn, spec.repo_id)
        cs = _spec_dict(spec.commit_set)
        try:
            here = metrics.object_metrics(
                conn, spec.repo_id, spec.path, spec.is_dir, cs, spec.author_ids
            )
            children = metrics.list_children(
                conn, spec.repo_id, spec.path, cs, spec.author_ids
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return {"object": here, "children": children}
    finally:
        conn.close()


@app.post("/api/metrics/authors")
def authors_metrics(spec: ViewSpec):
    conn = db.connect()
    try:
        _repo_row(conn, spec.repo_id)
        try:
            return metrics.author_metrics(
                conn,
                spec.repo_id,
                spec.path,
                spec.is_dir,
                _spec_dict(spec.commit_set),
                spec.author_ids,
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc))
    finally:
        conn.close()


@app.post("/api/metrics/timeseries")
def timeseries(spec: TimeseriesSpec):
    conn = db.connect()
    try:
        _repo_row(conn, spec.repo_id)
        try:
            return metrics.timeseries(
                conn,
                spec.repo_id,
                spec.path,
                spec.is_dir,
                _spec_dict(spec.commit_set),
                spec.author_ids,
                spec.bucket,
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc))
    finally:
        conn.close()


@app.get("/api/repos/{repo_id}/commits")
def commits(repo_id: int, limit: int = 50, offset: int = 0, q: str = "", author_id: int | None = None):
    conn = db.connect()
    try:
        _repo_row(conn, repo_id)
        author_ids = [author_id] if author_id else None
        return metrics.list_commits(
            conn, repo_id, limit=min(max(limit, 1), 500), offset=max(offset, 0),
            author_ids=author_ids, q=q or None,
        )
    finally:
        conn.close()


# ---------------------------------------------------------------- static UI
DIST = ROOT / "frontend" / "dist"
if DIST.exists():
    app.mount("/", StaticFiles(directory=str(DIST), html=True), name="ui")
else:
    @app.get("/")
    def index():
        return {
            "name": "Repo Analysis Tool API",
            "docs": "/docs",
            "hint": "Build the frontend (cd frontend && npm install && npm run build) "
                    "to serve the dashboard from here, or run `npm run dev` for development.",
        }
