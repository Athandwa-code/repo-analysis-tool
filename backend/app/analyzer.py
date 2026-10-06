"""Git ingest engine.

Runs a single streaming `git log` pass over the target repository and stores
per-commit, per-object deltas into SQLite. All brief rules are enforced here:

* only non-merge commits reachable from the ref (default HEAD);
* root commit diffed against the empty tree (`--root`);
* rename detection at 50% similarity (`-M50%`), changes attributed to the
  NEW path;
* binary files are excluded from metrics;
* deletions are recorded as removals on the deleted path;
* `.mailmap` is applied automatically via `%aN`/`%aE`;
* directories are rolled up recursively (each file delta is added to every
  ancestor directory and to the repository root `("", 1)`).

Output format (verified empirically, see probes): tokens are NUL-separated.
Per commit: `\\x01<sha>`, parents, committer-ts, author-name, author-email,
subject; then numstat entries. First entry of a commit may carry one leading
`\\n`. A rename entry ends with a tab and is followed by two extra tokens:
OLD path, then NEW path. Binary entries have `-` counts.
"""
from __future__ import annotations

import subprocess
from collections.abc import Callable, Iterator
from typing import BinaryIO

_LOG_FORMAT = "%x01%H%x00%P%x00%ct%x00%aN%x00%aE%x00%s"
_CHUNK = 1 << 20
_COMMIT_BATCH = 500


def _dec(raw: bytes) -> str:
    return raw.decode("utf-8", "replace")


def ancestors(path: str) -> Iterator[str]:
    """Yield every ancestor directory of a file path, ending with the root ''."""
    parts = path.split("/")
    for i in range(len(parts) - 1, 0, -1):
        yield "/".join(parts[:i])
    yield ""


def count_commits(repo_path: str, ref: str = "HEAD") -> int:
    out = subprocess.run(
        ["git", "-C", repo_path, "rev-list", "--no-merges", "--count", ref],
        capture_output=True,
        check=True,
    )
    return int(out.stdout.strip())


def _tokens(stream: BinaryIO, chunk_size: int = _CHUNK) -> Iterator[bytes]:
    """Split a binary stream on NUL bytes without loading it fully."""
    buf = b""
    while True:
        chunk = stream.read(chunk_size)
        if not chunk:
            break
        buf += chunk
        parts = buf.split(b"\x00")
        buf = parts.pop()
        yield from parts
    if buf:
        yield buf


def iter_log(repo_path: str, ref: str = "HEAD"):
    """Yield (commit_dict, {path: (added, removed)}) for each non-merge commit."""
    cmd = [
        "git", "-C", repo_path, "log",
        "--no-merges", "--root", "-M50%", "--numstat", "-z",
        f"--format={_LOG_FORMAT}", ref,
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert proc.stdout is not None
    it = _tokens(proc.stdout)
    commit = None
    entries: dict[str, list[int]] = {}

    for tok in it:
        if tok.startswith(b"\x01"):
            if commit is not None:
                yield commit, {p: (a, r) for p, (a, r) in entries.items()}
            sha = _dec(tok[1:])
            parents = _dec(next(it, b"")).strip()
            ct = int(next(it, b"0") or b"0")
            name = _dec(next(it, b""))
            email = _dec(next(it, b""))
            subject = _dec(next(it, b"")).rstrip("\n")
            commit = {
                "hash": sha,
                "parents": parents,
                "committer_date": ct,
                "author_name": name,
                "author_email": email,
                "subject": subject,
            }
            entries = {}
            continue

        # numstat entry
        tok = tok.lstrip(b"\n")
        if not tok:
            continue
        parts = tok.split(b"\t", 2)
        if len(parts) < 2:
            continue
        added_s, removed_s = parts[0], parts[1]
        binary = added_s == b"-" or removed_s == b"-"
        if len(parts) == 3 and parts[2] == b"":
            # rename: OLD path token, then NEW path token
            next(it, None)  # old path (not needed; attribution goes to new path)
            new_path = _dec(next(it, b""))
            path = new_path
        else:
            path = _dec(parts[2]) if len(parts) == 3 else ""
        if binary or not path:
            continue
        added = int(added_s)
        removed = int(removed_s)
        if added + removed == 0:
            continue
        cur = entries.get(path)
        if cur is None:
            entries[path] = [added, removed]
        else:
            cur[0] += added
            cur[1] += removed

    if commit is not None:
        yield commit, {p: (a, r) for p, (a, r) in entries.items()}

    stderr = proc.stderr.read().decode("utf-8", "replace") if proc.stderr else ""
    if proc.wait() != 0:
        raise RuntimeError(f"git log failed for {repo_path!r} ref {ref!r}: {stderr.strip()}")


def import_repo(
    conn,
    repo_id: int,
    repo_path: str,
    ref: str = "HEAD",
    progress: Callable[[int, int], None] | None = None,
) -> dict:
    """Ingest one repository into `conn`. Returns summary stats.

    Any previously stored data for `repo_id` is cleared first, so re-imports
    are idempotent.
    """
    conn.execute("UPDATE authors SET canonical_id=NULL WHERE repo_id=?", (repo_id,))
    conn.execute("DELETE FROM changes WHERE repo_id=?", (repo_id,))
    conn.execute("DELETE FROM commits WHERE repo_id=?", (repo_id,))
    conn.execute("DELETE FROM authors WHERE repo_id=?", (repo_id,))
    conn.commit()

    total = count_commits(repo_path, ref)
    author_ids: dict[tuple[str, str], int] = {}
    n_commits = 0
    n_rows = 0

    for commit, files in iter_log(repo_path, ref):
        key = (commit["author_name"], commit["author_email"])
        aid = author_ids.get(key)
        if aid is None:
            row = conn.execute(
                "SELECT id FROM authors WHERE repo_id=? AND name=? AND email=?",
                (repo_id, key[0], key[1]),
            ).fetchone()
            if row:
                aid = row["id"]
            else:
                cur = conn.execute(
                    "INSERT INTO authors (repo_id, name, email) VALUES (?,?,?)",
                    (repo_id, key[0], key[1]),
                )
                aid = cur.lastrowid
            author_ids[key] = aid

        conn.execute(
            "INSERT INTO commits (repo_id, hash, author_id, committer_date, parent_hash, subject)"
            " VALUES (?,?,?,?,?,?)",
            (
                repo_id,
                commit["hash"],
                aid,
                commit["committer_date"],
                commit["parents"].split(" ")[0] if commit["parents"] else None,
                commit["subject"],
            ),
        )

        # roll file deltas up into ancestor directories (incl. root "")
        rollup: dict[tuple[str, int], list[int]] = {}
        for path, (added, removed) in files.items():
            rollup[(path, 0)] = [added, removed]
            for anc in ancestors(path):
                cur = rollup.get((anc, 1))
                if cur is None:
                    rollup[(anc, 1)] = [added, removed]
                else:
                    cur[0] += added
                    cur[1] += removed

        rows = [
            (repo_id, commit["hash"], path, is_dir, d[0], d[1])
            for (path, is_dir), d in rollup.items()
            if d[0] + d[1] > 0
        ]
        if rows:
            conn.executemany(
                "INSERT INTO changes (repo_id, commit_hash, path, is_dir, added, removed)"
                " VALUES (?,?,?,?,?,?)",
                rows,
            )
            n_rows += len(rows)

        n_commits += 1
        if n_commits % _COMMIT_BATCH == 0:
            conn.commit()
            if progress:
                progress(n_commits, total)

    conn.commit()
    if progress:
        progress(n_commits, total)
    return {"commits": n_commits, "change_rows": n_rows, "authors": len(author_ids)}
