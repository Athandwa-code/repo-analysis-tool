"""Metric computations for the RAT.

Every metric in the brief is a sum over the per-commit, per-object deltas
stored by the analyzer. Commit sets (all / since / [i, j) / manual list) and
author filters are pure query predicates.
"""
from __future__ import annotations

import sqlite3


def _resolve_authors(conn: sqlite3.Connection, repo_id: int) -> dict[int, int]:
    """Map every author id to its effective (manually merged) author id."""
    rows = conn.execute(
        "SELECT id, canonical_id FROM authors WHERE repo_id=?", (repo_id,)
    ).fetchall()
    canon = {r["id"]: r["canonical_id"] for r in rows}
    eff: dict[int, int] = {}
    for aid in canon:
        seen = set()
        cur = aid
        while canon.get(cur) is not None and cur not in seen:
            seen.add(cur)
            cur = canon[cur]
        eff[aid] = cur
    return eff


def _commit_filter(spec, author_eff=None, author_ids=None, alias="c"):
    """Build a WHERE fragment (over commits `alias`) for a commit-set spec."""
    spec = spec or {"mode": "all"}
    mode = spec.get("mode", "all")
    conds, params = [], []
    if mode == "since":
        if spec.get("since") is None:
            raise ValueError("commit set 'since' requires the 'since' timestamp")
        conds.append(f"{alias}.committer_date >= ?")
        params.append(int(spec["since"]))
    elif mode == "range":
        if spec.get("start") is None or spec.get("end") is None:
            raise ValueError("commit set 'range' requires 'start' and 'end'")
        conds.append(f"{alias}.committer_date >= ? AND {alias}.committer_date < ?")
        params += [int(spec["start"]), int(spec["end"])]
    elif mode == "list":
        hashes = list(spec.get("hashes") or [])
        if hashes:
            conds.append(f"{alias}.hash IN ({','.join('?' * len(hashes))})")
            params += hashes
        else:
            conds.append("0")
    elif mode != "all":
        raise ValueError(f"unknown commit set mode: {mode!r}")
    if author_ids:
        selected = set(author_ids)
        raw = [aid for aid, eid in (author_eff or {}).items() if eid in selected]
        if raw:
            conds.append(f"{alias}.author_id IN ({','.join('?' * len(raw))})")
            params += raw
        else:
            conds.append("0")
    return (" AND ".join(conds) if conds else "1=1"), params


def _count_commits(conn, repo_id, where, params) -> int:
    return conn.execute(
        f"SELECT COUNT(*) FROM commits c WHERE c.repo_id=? AND {where}",
        (repo_id, *params),
    ).fetchone()[0]


def _object_sum(conn, repo_id, path, is_dir, where, params):
    row = conn.execute(
        f"""
        SELECT COALESCE(SUM(ch.added), 0) AS a,
               COALESCE(SUM(ch.removed), 0) AS r,
               COUNT(*) AS n
        FROM changes ch
        JOIN commits c ON c.repo_id = ch.repo_id AND c.hash = ch.commit_hash
        WHERE ch.repo_id=? AND ch.path=? AND ch.is_dir=? AND {where}
        """,
        (repo_id, path, int(bool(is_dir)), *params),
    ).fetchone()
    return row["a"], row["r"], row["n"]


def object_metrics(conn, repo_id, path, is_dir, commit_set=None, author_ids=None):
    """File / directory / repository metrics over a commit set."""
    eff = _resolve_authors(conn, repo_id)
    where, params = _commit_filter(commit_set, eff, author_ids)
    added, removed, mods = _object_sum(conn, repo_id, path, is_dir, where, params)
    h = _count_commits(conn, repo_id, where, params)
    return {
        "path": path,
        "is_dir": bool(is_dir),
        "added": added,
        "removed": removed,
        "growth": added - removed,
        "churn": added + removed,
        "modifications": mods,
        "commit_count": h,
        "modification_frequency": mods / h if h else 0.0,
        "churn_rate": (added + removed) / h if h else 0.0,
    }


def author_metrics(conn, repo_id, path, is_dir, commit_set=None, author_ids=None):
    """Per-author metrics incl. ownership.

    Ownership denominators use the full commit set (all authors), per the
    brief: omega = lambda_{H,o,a} / lambda_{H,o}.
    """
    eff = _resolve_authors(conn, repo_id)
    base_where, base_params = _commit_filter(commit_set)
    added, removed, _ = _object_sum(conn, repo_id, path, is_dir, base_where, base_params)
    total_churn = added + removed

    where, params = _commit_filter(commit_set, eff, author_ids)
    rows = conn.execute(
        f"""
        SELECT c.author_id AS aid,
               COUNT(*) AS n,
               COALESCE(SUM(ch.added + ch.removed), 0) AS lam
        FROM changes ch
        JOIN commits c ON c.repo_id = ch.repo_id AND c.hash = ch.commit_hash
        WHERE ch.repo_id=? AND ch.path=? AND ch.is_dir=? AND {where}
        GROUP BY c.author_id
        """,
        (repo_id, path, int(bool(is_dir)), *params),
    ).fetchall()

    agg: dict[int, dict] = {}
    for r in rows:
        e = eff.get(r["aid"], r["aid"])
        cur = agg.setdefault(e, {"churn": 0, "modifications": 0})
        cur["churn"] += r["lam"]
        cur["modifications"] += r["n"]

    out = []
    for e, v in agg.items():
        meta = conn.execute(
            "SELECT name, email FROM authors WHERE id=?", (e,)
        ).fetchone()
        out.append(
            {
                "author_id": e,
                "name": meta["name"],
                "email": meta["email"],
                "modifications": v["modifications"],
                "churn": v["churn"],
                "ownership": v["churn"] / total_churn if total_churn else 0.0,
            }
        )
    out.sort(key=lambda a: a["churn"], reverse=True)
    return out


def merge_authors(conn, repo_id, from_ids, into_id):
    """Manually merge authors: every id in from_ids resolves to into_id."""
    eff = _resolve_authors(conn, repo_id)
    into_id = int(into_id)
    roots = {eff.get(int(i), int(i)) for i in from_ids}
    if eff.get(into_id, into_id) in roots:
        raise ValueError("cannot merge an author into itself")
    for i in from_ids:
        conn.execute(
            "UPDATE authors SET canonical_id=? WHERE id=? AND repo_id=?",
            (into_id, int(i), repo_id),
        )
    conn.commit()


def _like_prefix(prefix: str) -> str:
    esc = prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return esc + "%"


def list_children(conn, repo_id, path, commit_set=None, author_ids=None):
    """Immediate children of a directory (or of the root when path=''), with
    metrics. Directory children carry rollup rows, so one grouped query gives
    every child's recursive totals."""
    eff = _resolve_authors(conn, repo_id)
    where, params = _commit_filter(commit_set, eff, author_ids)
    prefix = (path + "/") if path else ""
    rows = conn.execute(
        f"""
        SELECT ch.path AS p, ch.is_dir AS d,
               COALESCE(SUM(ch.added), 0) AS a,
               COALESCE(SUM(ch.removed), 0) AS r,
               COUNT(*) AS n
        FROM changes ch
        JOIN commits c ON c.repo_id = ch.repo_id AND c.hash = ch.commit_hash
        WHERE ch.repo_id=? AND ch.path LIKE ? ESCAPE '\\' AND {where}
        GROUP BY ch.path, ch.is_dir
        """,
        (repo_id, _like_prefix(prefix), *params),
    ).fetchall()

    children: dict[tuple[str, int], list[int]] = {}
    for r in rows:
        if r["p"] == path or not r["p"].startswith(prefix):
            continue
        rest = r["p"][len(prefix):]
        if not rest:
            continue
        if "/" in rest:
            # deeper object: its contribution is already included in the
            # ancestor directory's own rollup row, so skip it here
            continue
        child, cdir = r["p"], r["d"]
        cur = children.setdefault((child, cdir), [0, 0, 0])
        cur[0] += r["a"]
        cur[1] += r["r"]
        cur[2] += r["n"]

    out = []
    h = _count_commits(conn, repo_id, where, params)
    for (child, cdir), (a, r, n) in children.items():
        out.append(
            {
                "path": child,
                "is_dir": bool(cdir),
                "name": child.rsplit("/", 1)[-1],
                "added": a,
                "removed": r,
                "growth": a - r,
                "churn": a + r,
                "modifications": n,
                "commit_count": h,
                "modification_frequency": n / h if h else 0.0,
                "churn_rate": (a + r) / h if h else 0.0,
            }
        )
    out.sort(key=lambda c: c["churn"], reverse=True)
    return out


def timeseries(conn, repo_id, path, is_dir, commit_set=None, author_ids=None, bucket="week"):
    """added/removed/churn/modifications per time bucket for one object."""
    eff = _resolve_authors(conn, repo_id)
    where, params = _commit_filter(commit_set, eff, author_ids)
    if bucket == "month":
        keyexpr, scale = "strftime('%Y-%m', c.committer_date, 'unixepoch')", None
    elif bucket == "day":
        keyexpr, scale = "c.committer_date / 86400", 86400
    else:
        keyexpr, scale = "c.committer_date / 604800", 604800
    rows = conn.execute(
        f"""
        SELECT {keyexpr} AS b,
               COALESCE(SUM(ch.added), 0) AS a,
               COALESCE(SUM(ch.removed), 0) AS r,
               COUNT(*) AS n
        FROM changes ch
        JOIN commits c ON c.repo_id = ch.repo_id AND c.hash = ch.commit_hash
        WHERE ch.repo_id=? AND ch.path=? AND ch.is_dir=? AND {where}
        GROUP BY b ORDER BY b
        """,
        (repo_id, path, int(bool(is_dir)), *params),
    ).fetchall()
    return [
        {
            "bucket": r["b"] if scale is None else r["b"] * scale,
            "added": r["a"],
            "removed": r["r"],
            "churn": r["a"] + r["r"],
            "modifications": r["n"],
        }
        for r in rows
    ]


def list_commits(conn, repo_id, limit=50, offset=0, author_ids=None, q=None):
    """Newest-first commit list for the manual commit-set picker."""
    eff = _resolve_authors(conn, repo_id)
    conds, params = ["c.repo_id=?"], [repo_id]
    if author_ids:
        raw = [aid for aid, eid in eff.items() if eid in set(author_ids)]
        conds.append(f"c.author_id IN ({','.join('?' * len(raw))})" if raw else "0")
        params += raw
    if q:
        conds.append("(c.subject LIKE ? OR c.hash LIKE ?)")
        params += [f"%{q}%", f"{q}%"]
    w = " AND ".join(conds)
    total = conn.execute(
        f"SELECT COUNT(*) FROM commits c WHERE {w}", params
    ).fetchone()[0]
    rows = conn.execute(
        f"""
        SELECT c.hash, c.committer_date, c.subject, c.author_id
        FROM commits c WHERE {w}
        ORDER BY c.committer_date DESC, c.hash LIMIT ? OFFSET ?
        """,
        (*params, limit, offset),
    ).fetchall()
    meta = {
        r["id"]: (r["name"], r["email"])
        for r in conn.execute(
            "SELECT id, name, email FROM authors WHERE repo_id=?", (repo_id,)
        ).fetchall()
    }
    out = []
    for r in rows:
        e = eff.get(r["author_id"], r["author_id"])
        name, email = meta.get(e, ("?", "?"))
        out.append(
            {
                "hash": r["hash"],
                "committer_date": r["committer_date"],
                "subject": r["subject"],
                "author_name": name,
                "author_email": email,
            }
        )
    return {"total": total, "commits": out}
