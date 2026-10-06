#!/usr/bin/env python3
"""Validate the engine against independent `git` ground truth on real repos.

For each repository directory given on the command line this script:

1. imports it with the engine (in-process, temp database);
2. cross-checks repository-level (added, removed) totals against an
   independent awk pipeline over `git log --numstat`;
3. cross-checks author commit counts against `git shortlog -s -e`
   (both apply .mailmap);
4. spot-checks per-commit metrics at specific commit hashes against
   `git show --numstat` — this mirrors the brief's sample-value checks.

Usage: python3 tests/validate_repos.py <repo-dir> [<repo-dir> ...]
"""
import random
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app import analyzer, db, metrics  # noqa: E402

FAIL = []


def check(desc, ok, detail=""):
    print(("ok   " if ok else "FAIL ") + desc + (f"  [{detail}]" if detail else ""))
    if not ok:
        FAIL.append(desc)


def git(repo, *args):
    return subprocess.run(
        ["git", "-C", repo, *args], capture_output=True, check=True
    ).stdout


def awk_numstat(data: bytes, z=False):
    """Sum (added, removed) from `git log/show --numstat` output, skipping binary."""
    added = removed = 0
    for line in data.decode("utf-8", "replace").splitlines():
        parts = line.split("\t")
        if len(parts) < 3 or parts[0] in ("-", "") or parts[1] in ("-", ""):
            continue
        try:
            added += int(parts[0])
            removed += int(parts[1])
        except ValueError:
            continue
    return added, removed


def git_totals(repo):
    """Independent repository-level totals via git + a plain-text sum."""
    out = git(
        repo, "log", "--no-merges", "--root", "-M50%", "--numstat", "--format="
    )
    return awk_numstat(out)


def shortlog_by_email(repo):
    want = {}
    for line in git(repo, "shortlog", "--no-merges", "-s", "-e", "HEAD").decode(
        "utf-8", "replace"
    ).splitlines():
        line = line.strip()
        if not line:
            continue
        n, ident = line.split("\t", 1)
        email = ident[ident.rfind("<") + 1 : ident.rfind(">")]
        want[email] = want.get(email, 0) + int(n)
    return want


def commit_hashes(repo):
    return git(repo, "rev-list", "--no-merges", "HEAD").decode().split()


def per_commit_check(name, repo, conn, repo_id, n_sample=25):
    hashes = commit_hashes(repo)
    rng = random.Random(42)
    sample = (
        hashes if len(hashes) <= n_sample else rng.sample(hashes, n_sample)
    )
    # keep it fast on huge repos: at most 3 git show calls if the repo is big
    bad = 0
    for h in sample:
        row = conn.execute(
            "SELECT added, removed FROM changes WHERE repo_id=? AND commit_hash=? AND path='' AND is_dir=1",
            (repo_id, h),
        ).fetchone()
        got = (row["added"], row["removed"]) if row else (0, 0)
        out = git(repo, "show", "-M50%", "--numstat", "--format=", h)
        want = awk_numstat(out)
        if got != want:
            bad += 1
            if bad <= 5:
                print(f"     mismatch at {h[:10]}: engine {got} vs git {want}")
    check(f"{name}: per-commit values match git show ({len(sample)} sampled hashes)", bad == 0)


def validate(repo_dir):
    repo = str(Path(repo_dir).resolve())
    name = Path(repo).name
    print(f"\n=== {name} ===")
    dbp = Path(tempfile.mkdtemp()) / "validate.sqlite3"
    conn = db.connect(dbp)
    conn.execute(
        "INSERT INTO repositories (name, source_type, source, path) VALUES (?, 'clone', ?, ?)",
        (name, repo, repo),
    )
    repo_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    t0 = time.time()
    stats = analyzer.import_repo(conn, repo_id, repo)
    dt = time.time() - t0

    got = metrics.object_metrics(conn, repo_id, "", True)
    want_a, want_r = git_totals(repo)
    check(
        f"{name}: repository totals match git awk ({want_a} added / {want_r} removed)",
        (got["added"], got["removed"]) == (want_a, want_r),
        f"engine {got['added']}/{got['removed']} in {dt:.1f}s, {stats['commits']} commits",
    )

    want = shortlog_by_email(repo)
    ours = {
        r["email"]: r["n"]
        for r in conn.execute(
            "SELECT a.email AS email, COUNT(*) AS n FROM commits c JOIN authors a ON a.id=c.author_id"
            " WHERE c.repo_id=? GROUP BY a.email",
            (repo_id,),
        ).fetchall()
    }
    mism = {k: (ours.get(k), v) for k, v in want.items() if ours.get(k) != v}
    mism.update({k: (v, None) for k, v in ours.items() if k not in want})
    check(
        f"{name}: author commit counts match git shortlog ({len(want)} identities)",
        not mism,
        "" if not mism else f"{len(mism)} differing: {list(mism.items())[:3]}",
    )

    per_commit_check(name, repo, conn, repo_id)
    conn.close()


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(2)
    for repo in sys.argv[1:]:
        validate(repo)
    print()
    if FAIL:
        print(f"{len(FAIL)} FAILURES")
        for f in FAIL:
            print(" -", f)
        raise SystemExit(1)
    print("ALL REAL-REPO VALIDATIONS PASSED")


if __name__ == "__main__":
    main()
