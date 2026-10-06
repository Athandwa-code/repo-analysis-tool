# Repo Analysis Tool (RAT)

A web dashboard that ingests git repositories — either as a **zip upload containing `.git`** or by
**cloning from a URL** — and computes line-based contribution metrics for files, directories, whole
repositories, arbitrary commit sets and authors.

![dashboard](docs/dashboard.png)

## Highlights

- **Ingestion** — upload a zip archive that contains `.git`, or clone any (public) repository URL;
  multiple repositories are managed side by side, imports run in the background with live progress.
- **Filters everywhere** — repository selector, author multi-select, file/directory browser and a
  commit-set builder: *all commits* (`H̄`), *since date* (`H_t`), *date range* (`H_i,j`) or a
  *hand-picked commit list*.
- **The full metric family** — for every file, directory, repository, commit set and author:
  lines added `l+`, lines removed `l−`, growth `δ = l+ − l−`, churn `λ = l+ + l−`,
  modifications `n`, modification frequency `η = n / |H|`, churn rate `ρ = λ / |H|`, and author
  ownership `ω = λ_{H,o,a} / λ_{H,o}`, plus a churn-over-time chart per object.
- **Author identity handling** — `.mailmap` is applied automatically and remaining duplicate
  identities can be merged (and unmerged) directly in the UI.
- **Any ref** — re-analyze an existing clone at any branch, tag or commit hash; `H̄` is always
  “all non-merge commits reachable from the selected ref”.

## Requirement coverage at a glance

| Requirement | Where it is delivered |
| --- | --- |
| Correct for **all** metric categories: repo, file, directory, commit set, author | every metric is a sum over stored deltas — see *Git correctness rules*; verified by 48 exact-value engine checks + real-repo validation |
| **Both** ingestion paths: zip file **and** remote URL | `POST /api/repos` accepts a `.zip` upload (must contain `.git`) or a clone `url` |
| **All** of: filtering, author merge, multi-repo | repo switcher; author multi-select, file/dir browser, commit-set builder (`H̄`, `H_t`, `H_i,j`, manual list); `.mailmap` + manual merge/unmerge; any number of repositories side by side |
| Efficient algorithms & architecture | one streaming `git log` pass per repo → SQLite; filters are `WHERE` clauses — query time is O(result), no re-parsing (61 k-commit history imports in ~90 s, queries instant) |
| Inspired visualisation | metric cards per object, churn-over-time chart (day/week/month), sortable directory/file tables, ownership bars, live import progress |
| Navigation, error handling, quality-of-life | breadcrumb browser, status/progress/error surfacing per repo, commit picker with search, sortable columns, “set ref”, collapsible author lists |
| Performance on large (~100 k commit) repos | `git/git` with 61 101 commits imports in ~90 s; the UI stays responsive throughout (background import + polling) |
| Sample metrics **from a specific commit hash** | `POST /api/repos/{id}/reimport {ref: <hash>}`, or “set ref” in the UI: `H̄` becomes all non-merge commits reachable from that hash — validated at historical hashes (see below) |

## Git correctness rules (exactly as specified)

| Rule | Implementation |
| --- | --- |
| Only non-merge commits reachable from the ref | `git log --no-merges <ref>` |
| Root commit diffed against the empty tree | `--root` |
| Rename detection at 50 % similarity; changes attributed to the **new** path | `-M50%`, rename entries parsed from `--numstat -z` |
| Binary files excluded from all metrics | `-`/`-` numstat rows skipped (git's own detection) |
| Deletions recorded as removals on the deleted path | `--numstat` counts stored on the path |
| `.mailmap` merging | `%aN`/`%aE` format placeholders (git applies the mailmap) |
| Manual author merging | `authors.canonical_id`, resolved transitively at query time |
| Directory metrics = recursive sum over children | each file delta is rolled up into every ancestor directory (and the root) during import |

## Quick start

### 0. Prerequisites

Only three tools are required — check them first:

| Tool | Minimum version | Verify with |
| --- | --- | --- |
| Python | 3.10 | `python3 --version` |
| Node.js + npm | 18 | `node --version && npm --version` |
| git | 2.30 | `git --version` |

On Ubuntu/Debian these are `sudo apt install python3 python3-venv nodejs npm git`.

### 1. Start the app (one command)

From the repository root:

```bash
./start.sh
```

`start.sh` performs every setup step in order:

1. creates a Python virtualenv in `.venv/` (first run only),
2. installs the backend dependencies from `backend/requirements.txt`,
3. installs the dashboard's npm dependencies and builds it (`frontend/`),
4. starts the server on <http://127.0.0.1:8000>.

It is idempotent — re-running is safe and fast (the venv and `node_modules` are reused). It
honours environment variables, e.g. `PORT=9000 ./start.sh`. Stop the server with `Ctrl+C`.

### 2. Use the app

1. Open <http://127.0.0.1:8000> in any browser.
2. In the left panel, add a repository — either
   - paste a **clone URL** (e.g. `https://github.com/DaveGamble/cJSON.git`) into the *URL* tab, or
   - upload a **`.zip`** containing a `.git` directory via the *zip* tab.
   Any git repository works — these are just examples.
3. The import runs in the background with a live progress bar: small repos (~1,000 commits) finish
   in seconds; the full `git/git` history (~61,000 commits) takes ~90 seconds.
4. Select the repository, then use the dashboard: browse directories and files via breadcrumbs,
   build commit sets (*all* / *since* / *date range* / *hand-picked hashes*), filter by author, and
   merge duplicate author identities in the *Authors* tab. Every filter updates all metrics
   instantly.
5. To analyse a **specific commit hash** (e.g. supplied by a marker): click *set ref* on the
   repository card, paste the hash, and it re-imports the state reachable from that commit.

### 3. Run the tests (optional)

```bash
python3 tests/make_fixture.py && python3 tests/test_engine.py   # 48/48 exact-value checks
```

To cross-validate the engine against independent `git` pipelines on a real repository:

```bash
git clone https://github.com/DaveGamble/cJSON.git /tmp/cJSON
python3 tests/validate_repos.py /tmp/cJSON          # add --ref <hash> for a specific commit
```

See *Tests & validation* below for the full results on cJSON, Redis and git.

### Manual setup (equivalent to `start.sh`)

```bash
# 1. backend dependencies
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt

# 2. build the dashboard
cd frontend && npm install && npm run build && cd ..

# 3. run (serves API + dashboard on one port)
cd backend && ../.venv/bin/uvicorn app.api:app --port 8000
```

### Troubleshooting

| Symptom | Fix |
| --- | --- |
| `ERROR: 'node' is required ...` (or python3/git) | install the missing tool from step 0 |
| `[Errno 98] address already in use` | another process uses port 8000 — run `PORT=9000 ./start.sh` |
| Root URL shows a JSON status object instead of the dashboard | the frontend was not built — run `cd frontend && npm install && npm run build`, then restart |
| Zip upload rejected | the archive must contain a `.git` directory at some level |
| Import failed with a git error | the URL must be clonable from this machine (`git clone <url>` must work) |

For frontend development, run `npm run dev` inside `frontend/` (it proxies `/api` to port 8000)
while the backend runs with `--reload`.

## Architecture

```
backend/app/
  analyzer.py   git ingest engine: one streaming `git log --numstat -z` pass per repo,
                stores per-commit / per-object deltas (plus directory rollups) in SQLite
  metrics.py    all metrics as SQL sums over selectable commit sets and author filters
  api.py        FastAPI endpoints (repos, authors, tree, metrics, commits, re-import)
  ingest.py     zip extraction (zip-slip safe) and full clones
  db.py         SQLite schema
frontend/src/   React + Vite + Recharts dashboard
tests/          engine tests and real-repo validation
data/           runtime data: SQLite database + repository clones (git-ignored)
```

Because every metric is a pure sum over stored deltas, changing filters never re-reads the
repository — it just changes the `WHERE` clause.

## API overview

| Endpoint | Purpose |
| --- | --- |
| `POST /api/repos` | add a repository (multipart: `file` zip, or `url` + optional `ref`/`name`) |
| `GET /api/repos`, `GET /api/repos/{id}`, `DELETE /api/repos/{id}` | manage repositories |
| `POST /api/repos/{id}/reimport` | re-analyze the clone at another ref (branch/tag/hash) |
| `GET /api/repos/{id}/authors` · `POST .../authors/merge` · `POST .../authors/unmerge` | identity management |
| `POST /api/tree` | directory listing with per-child metrics (`repo_id`, `path`, `is_dir`, `commit_set`, `author_ids`) |
| `POST /api/metrics/authors` | per-author modifications, churn, ownership |
| `POST /api/metrics/timeseries` | `added`/`removed`/`churn` per day/week/month |
| `GET /api/repos/{id}/commits` | commit list (search) for the manual commit-set picker |

`commit_set` is `{mode: all}` or `{mode: since, since}` or `{mode: range, start, end}` or
`{mode: list, hashes:[...]}`; `author_ids` selects effective (merged) authors.

## Tests & validation

**Engine tests (exact values)** — a synthetic repository with hand-computed metrics covering
renames (rename+edit and pure rename), deletions, binary files, empty commits, `.mailmap` merging,
space/unicode paths, every commit-set mode, author filters and manual merges:

```bash
python3 tests/make_fixture.py && python3 tests/test_engine.py   # 48/48 checks
```

**Real-repo validation** — cross-checks the engine against independent `git` pipelines (the same
kind of check the brief’s sample values use):

```bash
git clone --quiet https://github.com/DaveGamble/cJSON.git && python3 tests/validate_repos.py cJSON
```

For each repository it verifies:
1. repository-level totals against an independent `git log --numstat` sum,
2. author commit counts against `git shortlog -s -e` (both mailmap-aware),
3. per-commit `(added, removed)` values at individually sampled **commit hashes** against `git show --numstat`.

Pass `--ref <hash>` to run all three checks for the state reachable from a specific commit hash —
the exact scenario of the brief’s sample values:

```bash
python3 tests/validate_repos.py --ref 924122904e6ed15735f0439c82b7d09ea87b822f cJSON
```

Results on the reference repositories (HEAD, and historical commit hashes via `--ref`):

| Repository | Commits analyzed | Repository totals (engine = git) | Author identities | Per-commit samples |
| --- | --- | --- | --- | --- |
| cJSON | 955 | 46 377 added / 11 211 removed ✓ | 101 ✓ | 25/25 hashes ✓ |
| Redis | 11 875 | 1 110 390 added / 500 315 removed ✓ | 976 ✓ | 25/25 hashes ✓ |
| git | 61 101 | 4 070 371 added / 2 375 604 removed ✓ | 2 485 ✓ | 25/25 hashes ✓ |
| cJSON @ `9241229` | 397 | 29 251 / 4 728 ✓ | 27 ✓ | 25/25 ✓ |
| Redis @ `23a4d70` | 4 992 | 361 858 / 170 407 ✓ | 215 ✓ | 25/25 ✓ |
| git @ `3ebda3e` | 29 794 | 1 256 299 / 535 205 ✓ | 1 301 ✓ | 25/25 ✓ |

The full `git/git` history (61 101 non-merge commits) imports in about a minute and a half — under
the Python engine, one streaming pass, no temporary files.

## Notes

- Tested with git 2.43, Python 3.12, Node 18.
- Imports are idempotent: re-importing or changing the ref replaces the stored data for that repository.
- Zip uploads are validated against path traversal and must contain a `.git` directory.
