#!/usr/bin/env python3
"""Exact-value tests for the engine against the hand-computed 'alpha' fixture."""
import datetime as dt
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app import analyzer, db, metrics  # noqa: E402

FIX = ROOT / "_scratch" / "fixtures" / "alpha"
DBP = ROOT / "_scratch" / "test_engine.sqlite3"

FAILURES = []
CHECKS = 0


def check(desc, got, want):
    global CHECKS
    CHECKS += 1
    if got != want:
        FAILURES.append(f"{desc}: got {got!r} want {want!r}")
        print(f"FAIL {desc}: got {got!r} want {want!r}")
    else:
        print(f"ok   {desc}")


def ts(k):
    return int(dt.datetime(2023, 1, k, 12, tzinfo=dt.timezone.utc).timestamp())


def main():
    assert FIX.exists(), "fixture missing - run tests/make_fixture.py first"
    if DBP.exists():
        DBP.unlink()
    conn = db.connect(DBP)
    conn.execute(
        "INSERT INTO repositories (name, source_type, source, path) "
        "VALUES ('alpha', 'zip', 'fixture', ?)",
        (str(FIX),),
    )
    repo_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    stats = analyzer.import_repo(conn, repo_id, str(FIX))
    print(f"imported: {stats}")

    n = conn.execute(
        "SELECT COUNT(*) FROM commits WHERE repo_id=?", (repo_id,)
    ).fetchone()[0]
    check("commit count is 10", n, 10)

    def obj(path, is_dir, spec=None, authors=None):
        return metrics.object_metrics(conn, repo_id, path, is_dir, spec, authors)

    # ---- all-commits per-object values (added, removed, modifications) ----
    expected = {
        ("README.md", 0): (2, 0, 1),
        (".mailmap", 0): (2, 0, 1),
        ("src/a.txt", 0): (5, 1, 2),
        ("src/b.txt", 0): (1, 0, 1),
        ("src/c.txt", 0): (0, 5, 1),
        ("src/deep/d.txt", 0): (1, 0, 1),
        ("space name.txt", 0): (2, 0, 1),
        ("\u00fcn\u00efcode.txt", 0): (1, 0, 1),
        ("", 1): (14, 6, 7),
        ("src", 1): (7, 6, 5),
        ("src/deep", 1): (1, 0, 1),
    }
    for (path, is_dir), (a, r, m) in expected.items():
        got = obj(path, is_dir)
        check(
            f"object {path!r} is_dir={is_dir}",
            (got["added"], got["removed"], got["modifications"]),
            (a, r, m),
        )

    root = obj("", 1)
    check("root growth", root["growth"], 8)
    check("root churn", root["churn"], 20)
    check("root modification frequency", round(root["modification_frequency"], 6), round(0.7, 6))
    check("root churn rate", round(root["churn_rate"], 6), 2.0)

    paths = [
        row["path"]
        for row in conn.execute(
            "SELECT DISTINCT path FROM changes WHERE repo_id=?", (repo_id,)
        ).fetchall()
    ]
    check("no binary path recorded", any(p == "bin" or p.startswith("bin/") for p in paths), False)

    c4 = conn.execute(
        "SELECT hash FROM commits WHERE repo_id=? AND subject='c4'", (repo_id,)
    ).fetchone()[0]
    c4rows = conn.execute(
        "SELECT COUNT(*) FROM changes WHERE repo_id=? AND commit_hash=?", (repo_id, c4)
    ).fetchone()[0]
    check("pure rename has no change rows", c4rows, 0)

    # ---- directory listings (regression: rollup rows must not be double counted) ----
    root_kids = {
        c["path"]: (c["added"], c["removed"], c["modifications"])
        for c in metrics.list_children(conn, repo_id, "")
    }
    check("children of root: src = rollup once", root_kids.get("src"), (7, 6, 5))
    check("children of root: README.md", root_kids.get("README.md"), (2, 0, 1))
    check("children of root count", len(root_kids), 5)
    src_kids = {
        c["path"]: (c["added"], c["removed"], c["modifications"])
        for c in metrics.list_children(conn, repo_id, "src")
    }
    check("children of src: a.txt", src_kids.get("src/a.txt"), (5, 1, 2))
    check("children of src: deep (dir)", src_kids.get("src/deep"), (1, 0, 1))
    check("children of src count", len(src_kids), 4)

    # ---- authors (mailmap applied at import) ----
    am = {(a["name"], a["email"]): a for a in metrics.author_metrics(conn, repo_id, "", 1)}
    expected_authors = {
        ("Alice", "alice@x"): (2, 9),
        ("Bob", "b@x"): (3, 5),
        ("Canonical A", "a@x"): (1, 1),
        ("Canonical B", "b@x"): (1, 5),
    }
    check("author count", len(am), 4)
    for key, (m, lam) in expected_authors.items():
        entry = am.get(key)
        check(f"author {key} present", entry is not None, True)
        if entry:
            check(f"author {key} (mods, churn)", (entry["modifications"], entry["churn"]), (m, lam))
            check(f"author {key} ownership", round(entry["ownership"], 6), round(lam / 20, 6))

    # ---- commit sets ----
    since = obj("", 1, {"mode": "since", "since": ts(4)})
    check("since c4 (added,removed,mods)", (since["added"], since["removed"], since["modifications"]), (4, 5, 4))
    check("since c4 |H|", since["commit_count"], 7)

    rng = obj("", 1, {"mode": "range", "start": ts(3), "end": ts(6)})
    check("range [c3,c6) (added,removed,mods)", (rng["added"], rng["removed"], rng["modifications"]), (1, 5, 2))
    check("range [c3,c6) |H|", rng["commit_count"], 3)

    h1 = conn.execute("SELECT hash FROM commits WHERE repo_id=? AND subject='c1'", (repo_id,)).fetchone()[0]
    h7 = conn.execute("SELECT hash FROM commits WHERE repo_id=? AND subject='c7'", (repo_id,)).fetchone()[0]
    lst = obj("", 1, {"mode": "list", "hashes": [h1, h7]})
    check("manual list (added,removed,mods)", (lst["added"], lst["removed"], lst["modifications"]), (8, 0, 2))
    check("manual list |H|", lst["commit_count"], 2)

    # ---- author filter ----
    bob = conn.execute("SELECT id FROM authors WHERE repo_id=? AND name='Bob'", (repo_id,)).fetchone()[0]
    bobs = obj("", 1, {"mode": "since", "since": ts(4)}, [bob])
    check("bob since c4 (added,removed,mods)", (bobs["added"], bobs["removed"], bobs["modifications"]), (2, 0, 2))
    check("bob since c4 |H|", bobs["commit_count"], 2)

    # ---- manual author merge ----
    alice = conn.execute("SELECT id FROM authors WHERE repo_id=? AND name='Alice'", (repo_id,)).fetchone()[0]
    canon_a = conn.execute("SELECT id FROM authors WHERE repo_id=? AND name='Canonical A'", (repo_id,)).fetchone()[0]
    metrics.merge_authors(conn, repo_id, [canon_a], alice)
    merged = {(a["name"], a["email"]): a for a in metrics.author_metrics(conn, repo_id, "", 1)}
    check("merged author count", len(merged), 3)
    alice_rec = merged[("Alice", "alice@x")]
    check("merged alice churn", alice_rec["churn"], 10)
    check("merged alice modifications", alice_rec["modifications"], 3)

    print(f"\n{CHECKS - len(FAILURES)}/{CHECKS} checks passed")
    if FAILURES:
        print("FAILURES:")
        for f in FAILURES:
            print(" -", f)
        sys.exit(1)
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
